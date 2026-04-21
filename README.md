# 🚗 Авто Аналитика KZ

> Платформа для мониторинга и анализа авторынка Казахстана — агрегирует объявления с 5 площадок, хранит историю цен и строит аналитику по маркам, моделям и городам.

---

## 🔍 Что это

**Авто Аналитика KZ** — serverless-система без VPS, которая:

- **Парсит** объявления с Kolesa.kz, OLX.kz, mycar.kz, avtorynok.kz, newauto.kz ежедневно по расписанию
- **Хранит** историю цен для анализа трендов и расчёта рентабельности перепродажи
- **Визуализирует** данные через дашборд с фильтрами по марке, модели, городу, году и источнику
- **Уведомляет** в Telegram об успехе/ошибке каждого парсера

---

## 🏗️ Архитектура

```
┌──────────────────────────────────────────────────────────┐
│              GitHub Actions (ежедневно 06:00 Астана)     │
│                                                          │
│  refresh_proxy → ┌─ parse_kolesa  (параллельно,         │
│                  ├─ parse_mycar    5 городов/батч)       │
│                  ├─ parse_newauto                        │
│                  ├─ parse_avtorynok                      │
│                  └─ parse_olx                            │
│                       └→ deactivate_old_listings         │
└─────────────────────────┬────────────────────────────────┘
                          │ asyncpg (SSL)
               ┌──────────▼──────────┐
               │   Neon PostgreSQL   │  listings, price_history,
               │   (serverless)      │  brands, models
               └──────────┬──────────┘
                          │
               ┌──────────▼──────────┐     ┌──────────────┐
               │    FastAPI API      │◄────│  Next.js 14  │
               │    /api/v1/         │     │  Dashboard   │
               └─────────────────────┘     └──────────────┘
```

| Компонент | Технологии |
|-----------|-----------|
| **Парсеры** | Python 3.11, curl_cffi (Chrome impersonation), BeautifulSoup, asyncio |
| **Планировщик** | GitHub Actions (cron `0 1 * * *` UTC = 06:00 Астана) |
| **База данных** | Neon PostgreSQL (serverless, free tier) |
| **Backend** | FastAPI, asyncpg, Uvicorn |
| **Frontend** | Next.js 14, TypeScript, SWR, Recharts, Framer Motion |
| **Уведомления** | Telegram Bot API |
| **Локальная разработка** | Docker Compose |

---

## 📊 Источники данных

| Площадка | Метод | Объявлений/запуск | Время парсинга |
|----------|-------|------------------|----------------|
| [Kolesa.kz](https://kolesa.kz) | Embedded JSON из HTML (15 городов × 5 параллельно) | ~30 000 | ~12 мин |
| [mycar.kz](https://mycar.kz) | REST JSON API | ~5 400 | ~37 мин |
| [newauto.kz](https://newauto.kz) | HTML парсинг (241 модель, slug-ID) | ~241 | ~1 мин |
| [avtorynok.kz](https://avtorynok.kz) | HTML парсинг (стоп по повтору ID) | ~16 | ~1 мин |
| [OLX.kz](https://olx.kz) | HTML парсинг (alphanumeric ID) | ~500 | ~15 мин |

---

## 🚀 Быстрый старт

### Продакшн (GitHub Actions + Neon)

1. **Создать БД в Neon:**
   - Зарегистрироваться на [neon.tech](https://neon.tech) → новый проект
   - В SQL Editor выполнить `database/init.sql`
   - Скопировать **Pooler connection string** (вид: `postgresql://user:pass@ep-xxx-pooler.region.aws.neon.tech/neondb?sslmode=require`)

2. **Добавить секреты в GitHub:**
   Settings → Secrets and variables → Actions:

   | Секрет | Значение |
   |--------|----------|
   | `DATABASE_URL` | Pooler URL от Neon |
   | `TELEGRAM_BOT_TOKEN` | Токен бота (опционально) |
   | `TELEGRAM_CHAT_ID` | ID чата для уведомлений (опционально) |

3. **Готово.** Парсеры запустятся автоматически в 06:00 по Астане. Ручной запуск:
   - GitHub → Actions → Daily Parsers → Run workflow → выбрать источник

---

### Локальная разработка (Docker Compose)

```bash
git clone https://github.com/RusBulgakov/avto-analytics.git
cd avto-analytics
cp .env.example .env
# Отредактируйте .env — укажите DATABASE_URL или POSTGRES_* переменные
docker compose up -d
```

| Сервис | URL |
|--------|-----|
| Дашборд | http://localhost |
| API | http://localhost/api/v1 |

Запуск парсеров локально:

```bash
# Установить зависимости
pip install -r parsers/requirements.txt

# Запустить один парсер
export DATABASE_URL="postgresql://..."
export PYTHONPATH=.
python -m parsers.kolesa.parser
```

---

## ⚙️ Конфигурация

### Продакшн (GitHub Secrets)

```
DATABASE_URL          — Neon Pooler URL (обязательно)
TELEGRAM_BOT_TOKEN    — токен Telegram бота (опционально)
TELEGRAM_CHAT_ID      — ID чата для уведомлений (опционально)
```

### Локально (.env)

```env
# Neon (если задан — POSTGRES_* ниже игнорируются)
DATABASE_URL=postgresql://user:pass@ep-xxx-pooler.region.aws.neon.tech/neondb?sslmode=require

# Или локальный PostgreSQL (Docker Compose)
POSTGRES_USER=automarket
POSTGRES_PASSWORD=your_secure_password
POSTGRES_DB=automarket_db
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

# Backend
SECRET_KEY=your_jwt_secret_here

# Telegram (опционально)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

---

## 📁 Структура проекта

```
.
├── .github/
│   └── workflows/
│       └── daily_parsers.yml      # Расписание и запуск парсеров
├── airflow/                       # Устаревший планировщик (не используется в prod)
│   └── dags/daily_parsers_dag.py
├── backend/
│   └── app/
│       ├── api/v1/endpoints/      # analytics, auth
│       └── core/                  # config, database, security
├── database/
│   └── init.sql                   # Схема БД + seed данные
├── frontend/
│   ├── components/                # FilterPanel, PriceChart, Header
│   ├── pages/                     # Dashboard, Login
│   └── lib/api.ts                 # API-клиент
├── parsers/
│   ├── requirements.txt           # Зависимости парсеров
│   ├── common/
│   │   ├── db.py                  # asyncpg пул, save_listing, statement_cache_size=0
│   │   ├── http_client.py         # curl_cffi fetch с retry и ротацией прокси
│   │   ├── proxy_manager.py       # Загрузка и проверка прокси (семафор 200)
│   │   ├── notifier.py            # Telegram уведомления об успехе/ошибке
│   │   ├── deactivate.py          # Деактивация старых объявлений
│   │   └── refresh_proxies.py     # Standalone обновление пула прокси
│   ├── kolesa/parser.py           # JSON-extraction, 15 городов × 5 параллельно
│   ├── mycar/parser.py            # REST API
│   ├── newauto/parser.py
│   ├── avtorynok/parser.py
│   ├── olx/parser.py
│   └── migrator.py                # Миграция данных между БД
├── docker-compose.yml
├── PLAN.md                        # План реализации (архивный)
└── .env.example
```

---

## ⚡ GitHub Actions Workflow

Файл: `.github/workflows/daily_parsers.yml`

```
Расписание: 0 1 * * * (UTC) = 06:00 Астана
Ручной запуск: workflow_dispatch с выбором источника (all / kolesa / mycar / ...)

Джобы:
  1. refresh-proxies     — обновить пул прокси (~1 мин)
  2. parse-{source} ×5   — параллельный запуск всех парсеров
     timeout: 330 мин (5.5ч) для kolesa, остальные быстрее
  3. deactivate-old       — деактивировать объявления без обновления >48ч
```

**Колеса запускается раньше других и завершается первым** (~12 мин) благодаря параллельному обходу 15 городов батчами по 5.

---

## 🗄️ Схема БД

```sql
sources       (id, name, display_name, base_url)
brands        (id, name, slug)
models        (id, brand_id, name, slug)
listings      (id UUID, source_id, brand_id, model_id, external_id,
               title, year, mileage_km, engine_volume_cc, engine_power_hp,
               body_type_id, fuel_type_id, transmission_id, drive_type_id,
               color, city, region, condition, listing_url,
               is_active, first_seen_at, last_seen_at, closed_at)
price_history (id, listing_id, price_kzt, price_usd, recorded_at)
body_types / fuel_types / transmission_types / drive_types  — справочники
users / subscription_plans / user_subscriptions             — пользователи
```

> **Neon free tier:** ~512 MB хранилища ≈ 3–4 месяца данных при ежедневном парсинге.

---

## 🔌 API

### Аналитика

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/api/v1/analytics/summary` | Активные объявления, бренды, средняя цена, источники |
| `GET` | `/api/v1/analytics/price-history` | История средних цен по периодам |
| `GET` | `/api/v1/analytics/market-overview` | Топ марок, распределение по городам |
| `GET` | `/api/v1/analytics/profitability` | Рентабельность перепродажи по моделям |

Все эндпоинты поддерживают фильтры: `brand_id[]`, `model_id[]`, `city[]`, `source[]`, `year[]`

### Справочники

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/api/v1/filters/brands` | Список марок |
| `GET` | `/api/v1/filters/models?brand_id=1` | Модели по марке |
| `GET` | `/api/v1/filters/cities` | Города |
| `GET` | `/health` | Healthcheck |

---

## 🐛 Известные особенности

- **Kolesa атрибуты:** На страницах листинга kolesa.kz возвращает только `brand`, `model`, `avgPrice` в `attributes` — поля `mileage_km`, `engine_volume_cc`, `fuel_type` и т.д. будут `NULL`. Полные данные доступны только на странице конкретного объявления (парсинг детальных страниц не реализован).
- **Neon Pooler + asyncpg:** Используется `statement_cache_size=0` — обязательно при работе через PgBouncer в transaction-pooling режиме, иначе `InvalidSQLStatementNameError`.
- **Бесплатные прокси:** Включены для mycar/olx/avtorynok/newauto. Для kolesa отключены (`use_proxy=False`) — curl_cffi с Chrome impersonation проходит напрямую, прокси только добавляют задержки через retry-loop.
- **avtorynok.kz пагинация:** Сайт возвращает одни и те же ~16 объявлений на любом номере страницы. Парсер останавливается после первого повтора ID (стоп по `seen_ids`).
- **newauto.kz TLS fingerprinting:** Сайт блокирует curl/aiohttp — возвращает пустой ответ. Работает только через `curl_cffi` с Chrome impersonation. Каталог (/catalog) содержит 241 модель без числовых ID; используем slug-ID вида `bmw-x5`.
- **OLX.kz ID формат:** OLX сменил числовые ID (`ID12345`) на буквенно-цифровые (`IDqMNaw`). Парсер использует `r"ID([A-Za-z0-9]+)"` для поддержки обоих форматов.

---

## 📄 Лицензия

MIT
