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
┌────────────────────────────────────────────────────────────────┐
│   GitHub Actions — 2 независимых workflow                      │
│                                                                │
│  daily_parsers.yml  — каждые 6 часов                           │
│  refresh_proxy → ┌─ parse_kolesa  (191 фид: 15 городов         │
│                  │   + 80 брендов + 97 моделей, batch=3)       │
│                  ├─ parse_mycar   (REST API)                   │
│                  ├─ parse_newauto (241 модель)                 │
│                  ├─ parse_avtorynok                            │
│                  └─ parse_olx                                  │
│                       └→ deactivate_old_listings (>168h)       │
│                                                                │
│  alive_check.yml    — каждые 12 часов                          │
│  reviver (5000/run) GET'ит inactive → 200 ⇒ is_active=TRUE     │
└──────────────────────────────┬─────────────────────────────────┘
                               │ asyncpg + SSL + statement_cache=0
                    ┌──────────▼──────────┐
                    │   Neon PostgreSQL   │  listings, price_history,
                    │   (serverless)      │  brands, models
                    └──────────┬──────────┘
                               │
             ┌─────────────────┴───────────────┐
             │                                 │
   ┌─────────▼──────────┐            ┌─────────▼──────────┐
   │   FastAPI API      │◄───────────│   Next.js 14       │
   │   /api/v1/         │   CORS     │   Static Export    │
   │   на Render        │            │   на Render        │
   └────────────────────┘            └────────────────────┘
```

| Компонент | Технологии |
|-----------|-----------|
| **Парсеры** | Python 3.11, curl_cffi (Chrome impersonation), asyncio, asyncpg |
| **Планировщик** | GitHub Actions: `daily_parsers` (cron `0 */6 * * *`) + `alive_check` (cron `30 */12 * * *`) |
| **База данных** | Neon PostgreSQL (serverless, free tier, Pooler через PgBouncer) |
| **Backend** | FastAPI, asyncpg, Uvicorn — на Render (Web Service) |
| **Frontend** | Next.js 14 (static export), TypeScript, SWR, Recharts, Leaflet, zustand — на Render (Static Site) |
| **Уведомления** | Telegram Bot API |
| **Локальная разработка** | Docker Compose (только backend + frontend; БД = Neon) |

---

## 📊 Источники данных

| Площадка | Метод | Фидов | Время парсинга |
|----------|-------|:-----:|----------------|
| [Kolesa.kz](https://kolesa.kz) | Embedded JSON из HTML (15 городов + 80 брендов + 97 моделей, батчи по 3) | **191** | ~2-3 ч |
| [mycar.kz](https://mycar.kz) | REST JSON API | 1 | ~37 мин |
| [newauto.kz](https://newauto.kz) | HTML парсинг, slug-ID `/cars/{brand}/{model}` | 241 | ~1 мин |
| [avtorynok.kz](https://avtorynok.kz) | HTML парсинг (стоп по повтору ID) | 1 | ~1 мин |
| [OLX.kz](https://olx.kz) | HTML парсинг (alphanumeric ID `IDqMNaw`) | 1 | ~15 мин |

**Model-level фиды у kolesa:** kolesa.kz глушит пагинацию на 250 страниц × 20 = 5000 объявлений на фид. Поэтому для тяжёлых марок (Toyota, Lada, Hyundai, …) добавлены отдельные под-фиды вида `toyota/camry`, `vaz/2107`, `mercedes-benz/e-class`. Список в `parsers/kolesa/parser.py::MODEL_FEEDS`.

**Alive-check worker:** раз в 12 часов запускается отдельный workflow `alive_check.yml`. Берёт 5000 inactive объявлений kolesa (3–30 дней свежести), GET'ит их URL, и если сайт отдаёт 200 — возвращает в `is_active=TRUE`. Решает проблему false-negative deactivations для объявлений с глубоких страниц, куда основной парсер не добирается. См. `parsers/kolesa/alive_check.py`.

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

3. **Готово.** Парсеры запустятся автоматически каждые 6 часов (01/07/13/19 UTC). Ручной запуск:
   - GitHub → Actions → **Daily Parsers** → Run workflow → выбрать источник (all / kolesa / mycar / …)
   - GitHub → Actions → **Alive Check (Kolesa)** → Run workflow → оживить inactive

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
├── .github/workflows/
│   ├── daily_parsers.yml          # Парсинг — каждые 6ч, 5 источников параллельно
│   └── alive_check.yml            # Оживление inactive — каждые 12ч
├── backend/
│   └── app/
│       ├── api/v1/endpoints/      # analytics.py (все /api/v1/analytics/*), auth.py
│       └── core/                  # config, database, security
├── database/
│   └── init.sql                   # Схема БД + seed данные
├── frontend/
│   ├── components/
│   │   ├── layout/                # Topbar (с live-тикером), FilterBar
│   │   ├── ui/                    # KPI, Badge, FilterDropdown
│   │   ├── charts/                # PriceChart, BoxPlot, Heatmap, Funnel,
│   │   │                          # KZMap (обёртка) + KZMapInner (Leaflet client-only)
│   │   └── feed/                  # RecentFeed
│   ├── pages/
│   │   ├── index.tsx              # Дашборд (KPIs + chart + feed + heatmap + funnel + map + boxplot)
│   │   ├── brands.tsx             # Каталог марок
│   │   ├── profitability.tsx      # Рейтинг рентабельности
│   │   ├── forecast.tsx           # PRO placeholder
│   │   ├── model.tsx              # Детали модели (?brand=&model=)
│   │   ├── listing.tsx            # Детали объявления (?id=)
│   │   └── auth/                  # login, register
│   ├── hooks/                     # useUsdKzt, useSyncFiltersWithUrl
│   ├── store/filters.ts           # zustand filter store с URL-sync
│   ├── styles/globals.css         # Все токены + виджеты
│   └── lib/                       # api.ts, format.ts
├── parsers/
│   ├── requirements.txt           # Зависимости парсеров
│   ├── common/
│   │   ├── db.py                  # asyncpg пул, save_listing, deactivate_old_listings (168h)
│   │   ├── http_client.py         # curl_cffi fetch с retry и ротацией прокси + UA
│   │   ├── proxy_manager.py       # Загрузка и проверка прокси (семафор 200)
│   │   ├── notifier.py            # Telegram уведомления об успехе/ошибке
│   │   ├── deactivate.py          # Entrypoint для deactivate_old_listings
│   │   └── refresh_proxies.py     # Standalone обновление пула прокси
│   ├── kolesa/
│   │   ├── parser.py              # JSON-extraction, 191 фид (15 cities + 80 brands + 97 models)
│   │   └── alive_check.py         # Reviver для inactive listings — HEAD/GET → is_active=TRUE
│   ├── mycar/parser.py            # REST API
│   ├── newauto/parser.py
│   ├── avtorynok/parser.py
│   ├── olx/parser.py
│   └── migrator.py                # Миграция данных между БД
├── render.yaml                    # Render.com blueprint: backend + frontend
├── docker-compose.yml             # Локально: только backend + frontend (БД = Neon)
├── CLAUDE.md                      # Инструкции для AI-агентов (docs-first rules)
├── CHANGELOG.md                   # История изменений
├── PLAN.md                        # План реализации (архивный)
└── .env.example
```

---

## ⚡ GitHub Actions Workflows

### `daily_parsers.yml` — основной парсинг

```
Расписание: 0 */6 * * * (UTC)   → 4 раза в сутки (01 / 07 / 13 / 19 UTC)
Ручной запуск: workflow_dispatch с выбором источника (all / kolesa / mycar / ...)

Джобы:
  1. refresh-proxies     — обновить пул прокси (~1 мин)
  2. parse-{source} ×5   — параллельный запуск всех парсеров
     timeout: 180 мин
  3. deactivate-old      — is_active=FALSE для listings с last_seen > 168h (7 дней)
                           override через DEACTIVATE_THRESHOLD_HOURS env
```

**Kolesa** парсит 191 фид (15 городов + 80 брендов + 97 моделей) батчами по 3 параллельно — 2-3 часа.

### `alive_check.yml` — оживление inactive (kolesa)

```
Расписание: 30 */12 * * * (UTC) → 00:30 и 12:30 UTC (05:30 / 17:30 Астана)
timeout: 120 мин

Один job:
  alive-check — берёт 5000 inactive listings с last_seen в диапазоне 3–30 дней
                  GET'ит listing_url, 200 → is_active=TRUE (closed_at=NULL)
                  2 worker'а × 1.2–2.5s задержка = ~2 req/s (kolesa не банит)
```

**Public repo:** GitHub Actions бесплатен и unlimited для публичных репозиториев, поэтому частый cron не тратит квоту.

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

### Аналитика — сводные

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/api/v1/analytics/summary` | Активные объявления, бренды, средняя цена, источники |
| `GET` | `/api/v1/analytics/price-history` | История средних и медианных цен по периодам |
| `GET` | `/api/v1/analytics/market-overview` | Топ марок, распределение по городам |
| `GET` | `/api/v1/analytics/profitability` | Рентабельность перепродажи по моделям (требует auth, PRO) |
| `GET` | `/api/v1/analytics/profit-ranking` | Публичный рейтинг рентабельности (без auth) |
| `GET` | `/api/v1/analytics/price-boxplot` | Ящики с усами: top-10 марок или модели выбранной марки |

### Аналитика — виджеты

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/api/v1/analytics/heatmap` | Тепловая карта: год × пробег (avg price и volume) |
| `GET` | `/api/v1/analytics/liquidity` | Воронка ликвидности: дней до продажи по корзинам |
| `GET` | `/api/v1/analytics/recent` | Лента свежих объявлений (live feed) |
| `GET` | `/api/v1/analytics/geo` | Карта KZ: координаты городов + объявления и ср. цена |

### Аналитика — детали объявления

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/api/v1/analytics/listing/{id}` | Одно объявление + история цены |
| `GET` | `/api/v1/analytics/valuation?listing_id=...` | Fair-price оценка (p25/median/p75 похожих) |
| `GET` | `/api/v1/analytics/similar?listing_id=...&limit=8` | Похожие объявления |

Все аналитические endpoint'ы поддерживают фильтры: `brand_id[]`, `model_id[]`, `city[]`, `source[]`, `period_days`.

**`include_inactive: bool`** (default `false`) — поддерживается endpoint'ами `/brands`, `/models`, `/summary`, `/market-overview`, `/price-history`, `/price-boxplot`, `/heatmap`, `/cities`, `/geo`. Управляется toggle "Активные / Все" в FilterBar. По умолчанию возвращаются только `is_active=TRUE` объявления; при `true` — вся история. `/recent`, `/liquidity`, `/profit-ranking`, `/listing/{id}`, `/valuation`, `/similar` намеренно не реагируют (см. CHANGELOG).

### Справочники

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/api/v1/analytics/brands` | Список марок с числом активных объявлений |
| `GET` | `/api/v1/analytics/models?brand_id=1` | Модели по марке |
| `GET` | `/api/v1/analytics/cities` | Города с числом объявлений |
| `GET` | `/health` | Healthcheck |

### Auth

| Метод | Путь | Описание |
|-------|------|----------|
| `POST` | `/api/v1/auth/register` | Регистрация |
| `POST` | `/api/v1/auth/login` | Логин (OAuth2 password flow → JWT) |
| `GET` | `/api/v1/auth/me` | Профиль текущего пользователя |

---

## 🐛 Известные особенности

- **Kolesa 5000-лимит на фид:** kolesa.kz глушит пагинацию на 250 страниц × 20 = 5000 объявлений. Поэтому для тяжёлых брендов (Toyota, Lada, Hyundai) одного brand-feed недостаточно — добавлены **model-level feed'ы** в `MODEL_FEEDS`. Каждый под-фид имеет свой 5000-лимит. Toyota: покрытие 5k → ~75k (brand + 14 моделей).
- **Deactivate threshold 168h:** объявления помечаются `is_active=FALSE` только если парсер не видел их ≥7 дней. Слишком маленькое значение (48h ранее) ложно-мертвило живые объявления, которые парсер просто не успел обойти.
- **Alive-check worker:** `parsers/kolesa/alive_check.py` берёт inactive и проверяет их URL напрямую. Работает как компенсация для ситуаций когда объявление активно на сайте, но парсер до него не добрался. Rate-limit: ~2 req/s, kolesa не банит.
- **Kolesa атрибуты:** На страницах листинга kolesa.kz возвращает только `brand`, `model`, `avgPrice` в `attributes` — поля `mileage_km`, `engine_volume_cc`, `fuel_type` и т.д. будут `NULL`. Полные данные доступны только на странице конкретного объявления (парсинг детальных страниц не реализован).
- **Neon Pooler + asyncpg:** Используется `statement_cache_size=0` — обязательно при работе через PgBouncer в transaction-pooling режиме, иначе `InvalidSQLStatementNameError`.
- **Бесплатные прокси:** Включены для mycar/olx/avtorynok/newauto. Для kolesa отключены (`use_proxy=False`) — curl_cffi с Chrome impersonation проходит напрямую, прокси только добавляют задержки через retry-loop.
- **avtorynok.kz пагинация:** Сайт возвращает одни и те же ~16 объявлений на любом номере страницы. Парсер останавливается после первого повтора ID (стоп по `seen_ids`).
- **newauto.kz TLS fingerprinting:** Сайт блокирует curl/aiohttp — возвращает пустой ответ. Работает только через `curl_cffi` с Chrome impersonation. Каталог (/catalog) содержит 241 модель без числовых ID; используем slug-ID вида `bmw-x5`.
- **OLX.kz ID формат:** OLX сменил числовые ID (`ID12345`) на буквенно-цифровые (`IDqMNaw`). Парсер использует `r"ID([A-Za-z0-9]+)"` для поддержки обоих форматов.
- **Next.js static export:** `output: 'export'` → все страницы статичны. Dynamic-компоненты (Leaflet и т.п.) **обязаны** грузиться через `next/dynamic({ ssr: false })`. Dynamic routes использовать через query-string (`?id=`, `?brand=`), не через `[param]`-папки.

---

## 📄 Лицензия

MIT
