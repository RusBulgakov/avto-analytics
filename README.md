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
┌──────────────────────────────────────────────────────────────────┐
│   GitHub Actions — 3 независимых workflow                        │
│                                                                  │
│  kolesa_full.yml      — 2× в сутки (08:00 + 20:00 UTC)           │
│  matrix [shard 0, 1, 2]      ─ ~99 фидов на шард, 350-мин timeout│
│    │   IPBlockedError → instant exit 1, не ждём 4ч впустую       │
│    │   exit 0  ────► deactivate_old_listings (>168h)             │
│    │   exit 1  ────► deactivate отменён (сохраняем данные)       │
│    └─► auto-trigger → alive_check                                │
│                                                                  │
│  daily_parsers.yml    — каждые 6 часов (только лёгкие парсеры)   │
│  refresh_proxy → ┌─ parse_mycar     (REST API)                   │
│                  ├─ parse_newauto   (241 модель)                 │
│                  ├─ parse_avtorynok                              │
│                  └─ parse_olx                                    │
│                       └→ deactivate_old_listings (>168h)         │
│                                                                  │
│  alive_check.yml      — каждые 6 часов                           │
│  reviver (5000/run) GET'ит inactive → 200 ⇒ is_active=TRUE       │
└──────────────────────────────┬───────────────────────────────────┘
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
| **Планировщик** | GitHub Actions: `kolesa_full` (cron `0 8,20 * * *`, 3 шарда) + `daily_parsers` (cron `0 */6 * * *`) + `alive_check` (cron `30 */6 * * *`) |
| **База данных** | Neon PostgreSQL (serverless, free tier, Pooler через PgBouncer) |
| **Backend** | FastAPI, asyncpg, Uvicorn — на Render (Web Service) |
| **Frontend** | Next.js 14 (static export), TypeScript, SWR, Recharts, Leaflet, zustand — на Render (Static Site) |
| **Уведомления** | Telegram Bot API |
| **Локальная разработка** | Docker Compose (только backend + frontend; БД = Neon) |

---

## 📊 Источники данных

| Площадка | Метод | Фидов | Время парсинга |
|----------|-------|:-----:|----------------|
| [Kolesa.kz](https://kolesa.kz) | Embedded JSON из HTML (15 городов + 81 бренд + 97 моделей + 75 город×бренд + 30 город×бренд×модель, батчи по 2, **3 шарда параллельно**) | **297** | ~4.5 ч (per shard) |
| [mycar.kz](https://mycar.kz) | REST JSON API | 1 | ~37 мин |
| [newauto.kz](https://newauto.kz) | HTML парсинг, slug-ID `/cars/{brand}/{model}` | 241 | ~1 мин |
| [avtorynok.kz](https://avtorynok.kz) | HTML парсинг (стоп по повтору ID) | 1 | ~1 мин |
| [OLX.kz](https://olx.kz) | HTML парсинг (alphanumeric ID `IDqMNaw`) | 1 | ~15 мин |

**Model-level фиды у kolesa:** kolesa.kz глушит пагинацию на 250 страниц × 20 = 5000 объявлений на фид. Поэтому для тяжёлых марок (Toyota, Lada, Hyundai, …) добавлены отдельные под-фиды вида `toyota/camry`, `vaz/2107`, `mercedes-benz/e-class`. Список в `parsers/kolesa/parser.py::MODEL_FEEDS`.

**Alive-check worker:** **каждые 6 часов** запускается отдельный workflow `alive_check.yml`. Берёт 5000 inactive объявлений kolesa (3–30 дней свежести), GET'ит их URL, и если сайт отдаёт 200 — возвращает в `is_active=TRUE`. Решает проблему false-negative deactivations для объявлений с глубоких страниц, куда основной парсер не добирается. См. `parsers/kolesa/alive_check.py`. Также автоматически триггерится после успешного `kolesa_full` через `gh workflow run`.

**Шардирование kolesa:** `kolesa_full.yml` использует matrix из 3 параллельных GHA jobs × ~99 фидов × ~4.5ч на шард. Полный прогон 297 фидов в один job не влез бы в 360-мин лимит GHA. Round-robin распределение в `parser.py::_get_feeds_for_shard` даёт балансировку (микс городов/брендов/моделей).

**Безотказность kolesa:** парсер использует **structured exit codes** (`0`=success, `1`=IP блок, `2`=DB error, `10`=partial). При IP-блоке (403/451) парсер прерывается **мгновенно** через `IPBlockedError` без 4× retry — это критично, потому что иначе шард тратил ~4 часа впустую. `deactivate-old` запускается **только** при exit 0 — иначе сохраняем существующие данные вместо слепой деактивации.

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

3. **Готово.** Расписание:
   - **Kolesa Full Parse (sharded):** 08:00 + 20:00 UTC (2× в сутки, ~4.5ч на шард)
   - **Daily Parsers (light):** каждые 6 часов (00/06/12/18 UTC) — mycar/newauto/avtorynok/olx
   - **Alive Check (Kolesa):** каждые 6 часов (00:30/06:30/12:30/18:30 UTC)

   Ручной запуск:
   - GitHub → Actions → **Kolesa Full Parse (sharded)** → Run workflow → можно указать `shard_count`
   - GitHub → Actions → **Daily Parsers (light)** → Run workflow → выбрать источник (all / mycar / …)
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
│   ├── kolesa_full.yml            # Kolesa.kz — 2× в сутки, 3 шарда параллельно
│   ├── daily_parsers.yml          # Лёгкие парсеры — каждые 6ч (mycar/newauto/avtorynok/olx)
│   └── alive_check.yml            # Оживление inactive — каждые 6ч + auto после kolesa
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
│   │   ├── forecast.tsx           # Прогноз цен: OLS-регрессия V3 (KZT + USD)
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
│   │   ├── http_client.py         # curl_cffi fetch + IPBlockedError + per-error retry strategy
│   │   ├── proxy_manager.py       # Загрузка и проверка прокси (семафор 200)
│   │   ├── notifier.py            # Telegram: send_*, send_*_with_id, edit_telegram_message
│   │   ├── deactivate.py          # Entrypoint для deactivate_old_listings
│   │   └── refresh_proxies.py     # Standalone обновление пула прокси
│   ├── kolesa/
│   │   ├── parser.py              # JSON-extraction, 297 фидов + sharding + Telegram progress
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

### `kolesa_full.yml` — kolesa.kz (sharded, самый тяжёлый источник)

```
Расписание: 0 8,20 * * * (UTC)   → 2 раза в сутки (08:00 + 20:00 UTC)
Ручной запуск: workflow_dispatch с возможностью переопределить shard_count
Concurrency group: kolesa-full (cancel-in-progress: false — ждём в очереди)

Джобы:
  1. kolesa-shard ×3     — matrix [shard_index: 0, 1, 2]
                           каждый шард парсит ~99 фидов из 297, timeout 350 мин
                           ENV: KOLESA_SHARD_INDEX, KOLESA_SHARD_COUNT, MIN_SAVED_THRESHOLD
                           Exit codes: 0=success / 1=IP блок / 2=DB error / 10=partial
  2. deactivate-old      — ТОЛЬКО при exit 0 ВСЕХ шардов (if: success())
                           is_active=FALSE для listings с last_seen > 168h
  3. trigger-alive-check — auto-запуск alive_check после успешной деактивации
  4. summary             — финальное сообщение в Telegram (✅ / ⚠️ / 🔴)
```

**Шардирование:** `_get_feeds_for_shard` round-robin распределяет 297 фидов (15 городов + 81 бренд + 97 моделей + 75 город×бренд + 30 город×бренд×модель) по индексу `i % shard_count`. Каждый шард — ~99 фидов ≈ 4.5 часа.

**Telegram прогресс-бар:** каждый шард отправляет `kolesa[1/3]` / `kolesa[2/3]` / `kolesa[3/3]` сообщение в начале и редактирует его каждые 60 секунд через `editMessageText`. Показывает: текущие активные фиды, страниц обработано, фидов завершено, сохранено/новых, ETA.

### `daily_parsers.yml` — лёгкие парсеры

```
Расписание: 0 */6 * * * (UTC)   → 4 раза в сутки (00 / 06 / 12 / 18 UTC)
Ручной запуск: workflow_dispatch с выбором источника (all / mycar / newauto / ...)

Джобы:
  1. refresh-proxies     — обновить пул прокси (~1 мин)
  2. parse-{source} ×4   — параллельный запуск парсеров: mycar, newauto, avtorynok, olx
                           timeout: 180 мин
  3. deactivate-old      — if: success() — is_active=FALSE при last_seen > 168h
```

**Kolesa тут НЕТ** — вынесен в `kolesa_full.yml` потому что не влезает в 360-мин лимит GHA.

### `alive_check.yml` — оживление inactive (kolesa)

```
Расписание: 30 */6 * * * (UTC)  → 4 раза в сутки (00:30 / 06:30 / 12:30 / 18:30 UTC)
timeout: 120 мин
Также автоматически триггерится после успешного kolesa_full

Один job:
  alive-check — берёт 5000 inactive listings с last_seen в диапазоне 3–30 дней
                  GET'ит listing_url, 200 → is_active=TRUE (closed_at=NULL)
                  2 worker'а × 1.2–2.5s задержка = ~2 req/s (kolesa не банит)
```

**Public repo:** GitHub Actions бесплатен и unlimited для публичных репозиториев, поэтому частый cron не тратит квоту.

### `kolesa_liveness.yml` — детектор «продано» (liveness sweep)

Курсор-резюмируемый проход по ВСЕМ активным kolesa-объявлениям (порядок —
`last_checked_at NULLS FIRST`, дольше всех не проверенные первыми). GET `listing_url`:
`200`+маркеры листа (`№{id}`/canonical) → `last_seen_at=now()`; `404/410`/soft-404 →
`is_active=FALSE, closed_at=now()` (момент продажи); `5xx/429/сеть` → не трогаем.
Time-boxed 300 мин, 4×/сутки (`15 1,7,13,19 UTC`), ~2 req/s. Резюмируемость — через
`listings.last_checked_at`. Поглощает роль `alive_check` (тот лишь реанимировал inactive,
но не ставил `closed_at`). См. `parsers/kolesa/liveness.py`.

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
               is_active, first_seen_at, last_seen_at, closed_at, last_checked_at)
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
| `GET` | `/api/v1/analytics/summary` | Активные объявления, бренды, средняя цена, источники. Params: `brand_id[]`, `model_id[]`, `city[]`, `source[]`, `year[]`, `include_inactive` |
| `GET` | `/api/v1/analytics/price-history` | История средних и медианных цен по периодам |
| `GET` | `/api/v1/analytics/market-overview` | Топ марок (или моделей выбранной марки, с `slug` для ссылок). Params: `brand_id[]`, `model_id[]`, `city[]`, `source[]`, `year[]` |
| `GET` | `/api/v1/analytics/profitability` | Рентабельность перепродажи по моделям (требует auth, PRO) |
| `GET` | `/api/v1/analytics/profit-ranking` | Публичный рейтинг рентабельности (без auth) |
| `GET` | `/api/v1/analytics/price-boxplot` | Ящики с усами: top-10 марок или модели выбранной марки |

### Аналитика — виджеты

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/api/v1/analytics/heatmap` | Тепловая карта: год × пробег (avg price и volume) |
| `GET` | `/api/v1/analytics/liquidity` | Воронка ликвидности: дней до продажи по корзинам |
| `GET` | `/api/v1/analytics/recent` | Лента свежих объявлений (live feed). Params: `brand_id`, `model_id`, `city[]`, `source[]`, `limit` |
| `GET` | `/api/v1/analytics/geo` | Карта KZ: координаты городов + объявления и ср. цена. Params: `brand_id[]`, `model_id[]`, `year[]`, `include_inactive`; слаги-синонимы городов агрегируются, города с 0 объявлений не возвращаются |
| `GET` | `/api/v1/analytics/price-candles` | Свечи цен по времени: P5/Q1/median/Q3/P95 в бакетах day/week/month. `granularity=auto` (default) → week для ≤90д, month для остального. |
| `GET` | `/api/v1/analytics/forecast` | Прогноз медианной цены V2: OLS на двух осях (KZT + USD-нормализованной), with FX-вклад. Params: `brand_id` (обяз.), `model_id?`, `year?`, `year_from?`, `year_to?`, `history_days=90`, `horizon_days=30`. Returns `{historical, forecast, trend_pct_per_month_kzt, trend_pct_per_month_usd, fx_impact_pct, r2_kzt, r2_usd, current_fx_rate, sample_size}`. |
| `GET` | `/api/v1/analytics/backtest` | Ретро-тест стратегии "купить дешевле p25 группы, продать в течение N дней". Params: `brand_id?`, `model_id?`, `year_from?`, `year_to?`, `period_days=60`, `discount_threshold=0.15`, `hold_days=45`. Returns `{total_signals, hits, win_rate, avg_realized_margin, median_days_to_sell, top_winners[]}`. |

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
- **Kolesa anti-bot из GHA:** kolesa.kz агрессивно блокирует burst запросов из Azure-датацентра. Эмпирически 4 шарда × 3 concurrent (12 одновременных) → IP блок за ~10 минут; ~80 req/min ловит накопительный бан через ~4ч. **Текущая рабочая конфигурация: 3 шарда × 2 concurrent (6 одновременных) + delay 4–7с (~66 req/min)** — укладывается в 350-мин timeout без бана. Не повышайте rate/concurrency — потеряете весь прогон.
- **Kolesa structured exit codes:** парсер возвращает `0`/`1`/`2`/`10` в зависимости от исхода. Workflow gate'ит `deactivate-old` через `if: success()` → при `IPBlockedError` или partial-успехе deactivate **не запускается**, сохраняем существующие данные. Без этого 1 неудачный прогон стирал 11k+ живых объявлений (произошло 2026-04-23).
- **Kolesa model validator (`_validate_model`):** парсер отсекает синтетические модели где `model == brand` или `model == год выпуска`. **НЕ отсекает модели-числа** (Audi 80, BMW 525, Mazda 626, Porsche 911, Lada 2107) — это валидные имена. Listing с невалидной моделью сохраняется с `model_id=NULL`.
- **Deactivate threshold 168h:** объявления помечаются `is_active=FALSE` только если парсер не видел их ≥7 дней. Override через `DEACTIVATE_THRESHOLD_HOURS` env. Слишком маленькое значение (48h ранее) ложно-мертвило живые объявления, которые парсер просто не успел обойти.
- **Alive-check worker:** `parsers/kolesa/alive_check.py` берёт inactive и проверяет их URL напрямую. Работает как компенсация для ситуаций когда объявление активно на сайте, но парсер до него не добрался. Rate-limit: ~2 req/s, kolesa не банит. Запускается каждые 6h + автоматически после успешного `kolesa_full`.
- **Kolesa атрибуты:** На страницах листинга kolesa.kz возвращает только `brand`, `model`, `avgPrice` в `attributes` — поля `mileage_km`, `engine_volume_cc`, `fuel_type` и т.д. будут `NULL`. Полные данные доступны только на странице конкретного объявления (парсинг детальных страниц не реализован).
- **Neon Pooler + asyncpg:** Используется `statement_cache_size=0` — обязательно при работе через PgBouncer в transaction-pooling режиме, иначе `InvalidSQLStatementNameError`.
- **Бесплатные прокси:** Включены для mycar/olx/avtorynok/newauto. Для kolesa отключены (`use_proxy=False`) — curl_cffi с Chrome impersonation проходит напрямую, прокси только добавляют задержки через retry-loop.
- **avtorynok.kz пагинация:** Сайт возвращает одни и те же ~16 объявлений на любом номере страницы. Парсер останавливается после первого повтора ID (стоп по `seen_ids`).
- **newauto.kz TLS fingerprinting:** Сайт блокирует curl/aiohttp — возвращает пустой ответ. Работает только через `curl_cffi` с Chrome impersonation. Каталог (/catalog) содержит 241 модель без числовых ID; используем slug-ID вида `bmw-x5`.
- **OLX.kz ID формат:** OLX сменил числовые ID (`ID12345`) на буквенно-цифровые (`IDqMNaw`). Парсер использует `r"ID([A-Za-z0-9]+)"` для поддержки обоих форматов.
- **Next.js static export:** `output: 'export'` → все страницы статичны. Dynamic-компоненты (Leaflet и т.п.) **обязаны** грузиться через `next/dynamic({ ssr: false })`. Dynamic routes использовать через query-string (`?id=`, `?brand=`), не через `[param]`-папки.
- **Render static БЕЗ catch-all rewrite:** в `render.yaml` у kolesa-frontend НЕ должно быть rewrite `/* → /index.html` — Render Static сам отдаёт `brands.html` для `/brands`. С rewrite'ом любой прямой URL показывал дашборд (deep-links и SEO мертвы). Убрано 2026-07-05.
- **bcrypt закреплён на 4.0.1:** passlib 1.7.4 несовместим с bcrypt≥4.1 (удалён `bcrypt.__about__`) — `hash_password` кидает AttributeError, register отдаёт 500. Не обновляйте bcrypt без миграции с passlib.
- **Санитизация моделей в `save_listing`:** mycar/avtorynok/olx приносят user-текст в model («camry тоета камри на разбор») — `_sanitize_model_name` режет до ведущих ASCII-токенов (макс 3) и пересчитывает slug, чтобы listing попадал в каноническую модель. Полностью кириллические имена не отбрасываются (режутся до 2 токенов), но slug у них пустой → модель не создаётся.
- **OLX разметка (2026-07):** title карточки в `<h4>`, первый `<p>` — цена. Парсер классифицирует `<p>` по содержимому («тг» → цена, «км» → год/пробег, « - » → локация-дата); при следующей смене разметки смотреть `_parse_card`.

---

## 📄 Лицензия

MIT
