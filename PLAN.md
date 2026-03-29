# ПЛАН: Парсинг → Neon PostgreSQL + GitHub Actions

## 1. Текущее состояние

### Что уже готово
- **5 парсеров** полностью реализованы: Kolesa.kz (~30K объявлений), mycar.kz (~2.4K), newauto.kz (~4.6K), avtorynok.kz (~480), OLX.kz (~500)
- **Общие утилиты** (`parsers/common/`): HTTP-клиент с curl_cffi (антибот), ротация прокси, async DB через asyncpg
- **Схема БД** (`database/init.sql`): таблицы listings, price_history, brands, models, lookup-таблицы — всё есть
- **Airflow DAG** (`airflow/dags/daily_parsers_dag.py`): ежедневный запуск в 03:00 UTC, параллельный запуск парсеров, деактивация старых объявлений
- **FastAPI бэкенд** + **Next.js фронтенд** с аналитикой
- **Docker Compose** для локального запуска всей инфраструктуры

### Чего нет
- GitHub Actions workflows — не существует каталога `.github/workflows/`
- Подключения к Neon PostgreSQL — сейчас всё рассчитано на локальный Docker Postgres
- Standalone-запуска парсеров без Docker (нужно проверить, работают ли `import`-пути вне контейнера)
- Обработки SSL для Neon (`sslmode=require` обязателен)

---

## 2. Пошаговый план

### Шаг 1: Создать БД в Neon и получить строку подключения

**Задачи:**
1. Зарегистрироваться на [neon.tech](https://neon.tech) → создать проект `kolesa-analytics`
2. В Neon Console: Settings → Connection String → скопировать строку вида:
   ```
   postgresql://user:password@ep-xxx.eu-central-1.aws.neon.tech/neondb?sslmode=require
   ```
3. Запустить `database/init.sql` через Neon SQL Editor или `psql` для создания схемы и seed-данных

**Проверить free tier лимиты:**
- Хранилище: 512 MB (≈ 3-5M строк в listings + price_history — хватит на старт)
- Compute: 190 часов/месяц (≈ 6 часов/день — впритык для Kolesa)
- Соединения: через встроенный PgBouncer (connection pooler URL), не через прямой хост

---

### Шаг 2: Адаптировать `parsers/common/db.py` для Neon

**Файл:** `parsers/common/db.py`

**Что менять:**
1. Добавить поддержку `DATABASE_URL` как единой переменной окружения (Neon даёт одну строку)
2. Добавить `ssl='require'` в asyncpg при наличии `sslmode=require` в URL (Neon требует SSL):
   ```python
   import os, asyncpg, ssl
   from contextlib import asynccontextmanager

   DATABASE_URL = os.environ["DATABASE_URL"]  # полный URL от Neon

   # asyncpg не понимает ?sslmode=require в URL — нужно передать ssl отдельно
   ssl_ctx = ssl.create_default_context()

   @asynccontextmanager
   async def db_conn():
       conn = await asyncpg.connect(DATABASE_URL, ssl=ssl_ctx)
       try:
           yield conn
       finally:
           await conn.close()
   ```
3. Убрать / сделать опциональным пул соединений (asyncpg pool плохо работает с serverless Neon, у которого compute засыпает — лучше одиночные соединения или использовать pooler URL)

**Альтернатива без правок кода:** использовать **Neon Pooler URL** (вида `ep-xxx-pooler.neon.tech`) — он совместим со стандартным asyncpg pool без изменений.

---

### Шаг 3: Исправить пути импорта для запуска вне Docker

**Проблема:** Парсеры используют `from parsers.common.db import ...`, что работает только при запуске из корня проекта с `PYTHONPATH=.`

**Файл:** каждый `parsers/{site}/parser.py`

**Что делать:** в GitHub Actions добавить:
```bash
export PYTHONPATH=$GITHUB_WORKSPACE
```
Либо добавить в начало каждого `parser.py`:
```python
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../..'))
```

Это **не требует изменений в коде** — достаточно правильного `PYTHONPATH` в workflow.

---

### Шаг 4: Создать GitHub Actions workflow

**Файл:** `.github/workflows/daily_parsers.yml`

**Структура:**

```yaml
name: Daily Parsers

on:
  schedule:
    - cron: '0 3 * * *'   # ежедневно в 03:00 UTC
  workflow_dispatch:        # ручной запуск для отладки

jobs:
  refresh-proxies:
    name: Refresh Proxy Pool
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r parsers/requirements.txt
      - run: python parsers/common/proxy_manager.py
        env:
          PYTHONPATH: ${{ github.workspace }}

  parse-all:
    name: Parse ${{ matrix.source }}
    needs: refresh-proxies
    runs-on: ubuntu-latest
    timeout-minutes: 330   # 5.5 часов — Kolesa может занять до 5 часов
    strategy:
      fail-fast: false      # если один парсер упал — остальные продолжают
      matrix:
        source: [kolesa, mycar, newauto, avtorynok, olx]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r parsers/requirements.txt
      - name: Run ${{ matrix.source }} parser
        run: python parsers/${{ matrix.source }}/parser.py
        env:
          PYTHONPATH: ${{ github.workspace }}
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
          PARSER_REQUEST_DELAY_MIN: 3
          PARSER_REQUEST_DELAY_MAX: 6
          PARSER_MAX_RETRIES: 3

  deactivate-old:
    name: Deactivate Old Listings
    needs: parse-all
    runs-on: ubuntu-latest
    if: always()  # запускать даже если парсеры упали частично
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -r parsers/requirements.txt
      - run: python parsers/common/deactivate.py
        env:
          PYTHONPATH: ${{ github.workspace }}
          DATABASE_URL: ${{ secrets.DATABASE_URL }}
```

**Почему matrix strategy:** каждый парсер запускается в отдельном job — параллельно и с независимым таймаутом. Kolesa получает свои 5.5 часов, маленькие парсеры завершатся за 5-15 минут.

---

### Шаг 5: Настроить секреты в GitHub

В репозитории: Settings → Secrets and variables → Actions → New repository secret

| Секрет | Значение |
|--------|----------|
| `DATABASE_URL` | `postgresql://user:pass@ep-xxx-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require` |

Использовать **pooler URL** от Neon (не direct connection) — он лучше справляется с множеством коротких соединений из GitHub Actions.

---

### Шаг 6: Создать `parsers/requirements.txt` (если не существует)

Проверить и убедиться, что файл `parsers/requirements.txt` содержит все зависимости для GitHub Actions:
```
curl_cffi>=0.7
beautifulsoup4>=4.12
asyncpg>=0.29
aiohttp>=3.9
lxml>=5.0
```

(Отдельно от `backend/requirements.txt` — бэкенду нужен FastAPI, парсерам нет)

---

### Шаг 7: Добавить мониторинг запусков (опционально)

**Вариант A — только GitHub Actions:**
Уведомления об ошибках через GitHub встроенные (email при failed run).

**Вариант B — Telegram уведомления:**
Добавить в конце workflow step:
```yaml
- name: Notify on failure
  if: failure()
  run: |
    curl -s -X POST "https://api.telegram.org/bot${{ secrets.TG_BOT_TOKEN }}/sendMessage" \
      -d "chat_id=${{ secrets.TG_CHAT_ID }}&text=❌ Parser ${{ matrix.source }} failed"
```

---

## 3. Технические детали

### Схема БД (уже есть в `database/init.sql`)

```
sources (5 строк: kolesa, olx, mycar, avtorynok, newauto)
  └── listings (UUID PK, source_id FK, brand_id, model_id, year, mileage_km,
                engine_volume_cc, city, price в price_history, is_active)
        └── price_history (listing_id FK, price_kzt, recorded_at)
brands (auto-populated)
models (brand_id FK, auto-populated)
body_types, fuel_types, transmission_types, drive_types (pre-seeded)
```

**Индексы** (уже определены): brand_id, model_id, year, city, is_active, first_seen_at, recorded_at

### Оценка объёма данных на Neon Free Tier (512 MB)

| Таблица | Строк/день | Размер строки | Итог за 30 дней |
|---------|-----------|---------------|-----------------|
| listings | ~38K новых (первый запуск) | ~500 байт | ~20 MB |
| price_history | ~38K новых / день | ~100 байт | ~114 MB за 30 дней |
| **Итого** | | | **~140 MB / месяц** |

Вывод: **3-4 месяца данных влезет в free tier**. Дальше нужна очистка старого price_history или апгрейд до $19/месяц.

### Оценка compute часов Neon (190 ч/месяц)

Neon compute автоматически засыпает при отсутствии соединений. Активен только во время парсинга.

| Парсер | Время работы | Часов/месяц |
|--------|-------------|-------------|
| Kolesa | ~2-3 часа | 60-90 ч |
| mycar | ~10 мин | 5 ч |
| newauto, avtorynok, olx | ~10-20 мин | 5-10 ч |
| **Итого** | | **~70-105 ч/месяц** |

Вывод: **влезаем в free tier** (190 ч/месяц).

### GitHub Actions минуты (Public repo: бесплатно без лимитов)

Если репозиторий **публичный** — GitHub Actions полностью бесплатны. Если **приватный** — 2,000 мин/месяц (~33 часа), чего не хватит (Kolesa один занимает ~150 мин). Решение: сделать репозиторий публичным.

### Структура workflow файлов

```
.github/
└── workflows/
    └── daily_parsers.yml   # основной workflow
```

---

## 4. Порядок выполнения (приоритет)

```
[ ] 1. Создать Neon проект, выполнить init.sql
[ ] 2. Добавить секрет DATABASE_URL в GitHub
[ ] 3. Создать .github/workflows/daily_parsers.yml
[ ] 4. Адаптировать parsers/common/db.py для Neon SSL
[ ] 5. Убедиться что parsers/requirements.txt существует и полный
[ ] 6. Протестировать один парсер вручную (workflow_dispatch → только mycar)
[ ] 7. Включить ежедневное расписание
[ ] 8. Проверить данные в Neon после первого прогона
```

Минимально рабочий результат достигается на шагах 1-5. Шаги 6-8 — валидация.
