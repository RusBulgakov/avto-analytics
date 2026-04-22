# Changelog

Все значимые изменения проекта. Формат основан на [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), версии — date-based. Самое свежее — наверху.

---

## 2026-04-22 — Active/All toggle (исторический режим)

### Added
- **`include_inactive: bool` query param** добавлен в 9 backend endpoints: `/brands`, `/models`, `/summary`, `/market-overview`, `/price-history`, `/price-boxplot`, `/heatmap`, `/cities`, `/geo`. По умолчанию `false` → старое поведение (только `is_active=TRUE`). При `true` фильтр снимается → возвращаются все объявления когда-либо собранные парсером.
- **Frontend toggle "Активные / Все"** в FilterBar (рядом с период-чипами): single global mode на весь дашборд. URL-sync через `?mode=all`. Передаётся во все API-вызовы дашборда.

### Changed
- `FilterState` (`frontend/types/analytics.ts`) — новое поле `include_inactive: boolean`, default `false`.
- `useFilters` zustand-store: добавлены `setIncludeInactive`, парсинг/сериализация `mode=all` в URL.
- `analyticsApi` (`frontend/lib/api.ts`): `getBrands`, `getModels`, `getCities`, `getGeo` теперь принимают опциональный `params` (раньше игнорировали).

### Не трогал намеренно
- `/recent` — live-лента всегда только активные (исторические объявления не имеют смысла в "сейчас на сайте").
- `/liquidity` — оперирует `closed_at` (only-closed), is_active не релевантно.
- `/listing/{id}`, `/valuation`, `/similar` — детали отдельного объявления, режим показывается у самой записи (`is_active`).
- `/profit-ranking` — рейтинг рентабельности по текущему рынку (buy=p25, sell=median у активных). Исторический режим тут не имеет смысла — мёртвые объявления не покупают.

### Use-case
Включил "Все" — увидел весь рынок KZ за всю историю парсинга (с 2 марта 2026), полные распределения по маркам/городам/heatmap. Включил "Активные" (default) — обычный текущий снимок.

---

## 2026-04-22 — alive_check SQL fix + airflow cleanup + bulk revive (`d0e9d1e` + ad-hoc SQL)

### Fixed
- **`parsers/kolesa/alive_check.py`** — первый прогон упал за 19 секунд с
  `UndefinedColumnError: column "source" does not exist`. Схема listings использует
  `source_id` (FK) — нет text-колонки `source`. SELECT перепиcан с
  `JOIN sources s ON s.id = l.source_id WHERE s.name = 'kolesa'`.

### Removed
- **`airflow/dags/daily_parsers_dag.py`** + вся `airflow/` директория. Файлы оставались с марта как "deprecated", но активно вводили в заблуждение AI-агентов и читателей README — другие агенты делали выводы про "Airflow в 03:00 каждую ночь" хотя в проде планировщик = GitHub Actions.

### Manual ops (не в коде, ad-hoc SQL на Neon)
- **One-shot revive:** UPDATE 49,471 inactive kolesa-объявлений → `is_active=TRUE`. Критерий: `last_seen_at` за последние 7 дней + `first_seen_at` не старше 60 дней. Это историческая компенсация ложно-deactivated за период 48h-threshold-эры. Эффект: active 25,305 → 74,912 (×3), Toyota 4,264 → 13,144.

### Changed
- **`CLAUDE.md`** — добавлено правило про `source_id` vs `source`, чтобы агент в будущем не делал ту же ошибку. Убрано упоминание "не трогать airflow/" — папки больше нет.
- **`README.md`** — убрано упоминание `airflow/` в структуре проекта.

---

## 2026-04-22 — Documentation overhaul (`605d9cf`)

### Added
- **`CLAUDE.md`** — канонические правила для AI-агентов: обязательное обновление CHANGELOG + README после каждой значимой доработки, чеклист что считается значимым, технические инварианты, do/don't list, процесс работы.
- **`CHANGELOG.md`** — этот файл; полная история от `3ecf630` (2026-04-20) до текущего момента.

### Changed
- **`README.md`** — полностью actualized:
  - Архитектурная диаграмма: 2 workflow вместо 1, 191 фид, Render + Neon
  - Таблица источников: kolesa 94 → 191 фид, время 30мин → 2-3ч
  - Секция workflow'ов: оба `daily_parsers.yml` + `alive_check.yml` с cron'ами
  - API endpoints: было 4, стало 15 (добавлены heatmap, liquidity, recent, geo, listing/{id}, valuation, similar, profit-ranking, price-boxplot, auth/*)
  - Project structure: новые frontend директории (layout/ui/charts/feed), все 6 страниц, zustand store, `alive_check.py`
  - Known quirks: 5000/feed cap, 168h threshold, alive-check worker, static-export constraint

---

## 2026-04-22 — Parser depth + alive-check revive (`e177dda`)

### Added
- **97 model-level feeds** для Kolesa parser: `toyota/camry`, `vaz/2107`, `mercedes-benz/e-class`, `hyundai/accent` и т.д. Обходит лимит пагинации kolesa (5000 объявлений на фид) — Toyota теперь покрывается через 14 sub-feed'ов × 5k = ~75k вместо 5k. Общее число фидов: **94 → 191**.
- **`parsers/kolesa/alive_check.py`** — новый worker, который GET'ит listing_url у inactive объявлений и возвращает их в активные при HTTP 200. Rate-limited: 2 workers × 1.2–2.5s задержка = ~2 req/s. Batch 5000/run.
- **`.github/workflows/alive_check.yml`** — новый workflow, крутится каждые 12 часов (00:30 и 12:30 UTC). Независимо от главного Daily Parsers.

### Changed
- **`parsers/common/db.py::deactivate_old_listings`** — default threshold 48h → **168h (7 дней)**. Переопределяется env `DEACTIVATE_THRESHOLD_HOURS`. Было: живые объявления с глубоких страниц помечались dead за 2 дня. Стало: 7-дневное окно = 4 парсер-прохода в запасе.
- **`.github/workflows/daily_parsers.yml`** — cron `0 1 * * *` → `0 */6 * * *` (4× в сутки). Timeout 330 → 180 мин. GitHub Actions для public-репо бесплатен, частота не стоит денег.

### Impact
После первого полного цикла (3–4 часа) active_listings ожидаемо вырастет **23k → 70–100k**. Toyota: 3 950 → ~25 000 активных.

---

## 2026-04-22 — Frontend compact charts + real map (`57ed138`, `16d0b76`)

### Added
- **Реальная карта Казахстана на Leaflet + OpenStreetMap** (CartoDB dark tiles) вместо ручного SVG-силуэта. Маркеры — `CircleMarker` с размером по объёму объявлений.
- **`components/charts/KZMapInner.tsx`** — client-only компонент (обёрнут в `next/dynamic` с `ssr:false`), содержит статическую таблицу lat/lng для 35 городов KZ.
- **Dependencies:** `leaflet@1.9.4`, `react-leaflet@4.2.1`, `@types/leaflet@1.9.12`.

### Changed
- **Heatmap клетка:** `aspect-ratio:1.35/1` → фиксированная `height:20px`. На широких экранах сокращает вертикальную высоту с ~1000px до ~350px.
- **BoxPlot:** ROW_H 44 → 22, boxH 18 → 10, wrapper `maxWidth:820`, explicit `height` на svg — больше не растягивается при `preserveAspectRatio=meet`.
- **Grids** `.grid-2-1` / `.grid-1-1` / `.grid-1-1-1`: `align-items:start` — карточки не стретчатся под высоту самой высокой. Убирает пустое пространство под "Динамика цен".
- **Recent feed:** wrapper с `maxHeight:360px; overflow-y:auto`.
- **Funnel:** padding 10 → 6, bar-wrap height 20 → 14.
- **Recent row:** padding 10 14 → 7 14.
- **card-b:** padding `16px` → `14px 16px`.

---

## 2026-04-21 — Brands / Profitability / Forecast pages + public profit ranking (`b0ca9a0`)

### Added
- **`/brands`** — каталог марок (поиск + сетка), клик открывает дашборд с фильтром по марке.
- **`/profitability`** — рейтинг моделей по потенциалу маржи перепродажи. Фильтры: `min_volume`, `limit`.
- **`/forecast`** — placeholder для будущей PRO-фичи "прогноз цены".
- **`GET /api/v1/analytics/profit-ranking`** — новый публичный endpoint для рейтинга рентабельности (не требует auth).

### Removed
- Photo placeholder блоки с listing-страницы (фото не парсятся).

### Changed
- Listing grid: `1.3fr / 1fr` → `1fr / 1fr` (равные колонки без фото).

---

## 2026-04-21 — Trading terminal redesign steps 6–8 (`01bba6c`)

### Added
- **Filter dropdowns** — portal-based dropdown для марки/модели/цены/года/пробега/города с анимированным сворачиванием.
- **KZ map v1** — SVG-силуэт с абсолютно-позиционированными city pins (позже заменён на Leaflet, см. выше).
- **Model page** (`/model?brand=...&model=...`) — детальный экран по модели.
- **Listing page** (`/listing?id=...`) — детальный экран по объявлению с historic price chart, fair-price gauge, similar listings.

### Changed
- Роутинг динамических страниц: вместо `[param]`-папок — query-string (`?id=`, `?brand=`), совместимо с `output: 'export'`.
- zustand store для фильтров с двусторонней URL-синхронизацией (`useSyncFiltersWithUrl`).

---

## 2026-04-21 — Kolesa IP-block protection (`6ae4156`)

### Changed
- `CITY_CONCURRENCY`: 5 → 3 параллельных feed'а. GitHub Actions datacenter-IP триггерил kolesa anti-abuse при 5 × requests/3s = 100 req/min.
- Inter-batch sleep 8–15 сек между группами фидов.
- Early-stop: если все фиды в батче тайм-аутнули — IP, видимо, заблокирован, парсер завершается корректно (с тем что успел собрать).

---

## 2026-04-21 — Listing details + fair-price + geo (`06d9807`)

### Added endpoints
- `GET /api/v1/analytics/listing/{id}` — одно объявление с историей цены (`price_history` JOIN).
- `GET /api/v1/analytics/valuation?listing_id=...` — fair-price оценка: p25/median/p75 по похожим объявлениям (тот же brand/model/year ±1/mileage ±20%).
- `GET /api/v1/analytics/similar?listing_id=...&limit=8` — похожие объявления.
- `GET /api/v1/analytics/geo` — список городов с координатами (x/y %), объявлениями и средней ценой для карты KZ.

### Added frontend
- Fair-price gauge + price history + similar listings на странице `/listing`.
- Feed консумации `/geo` для KZMap v1 на дашборде.

---

## 2026-04-21 — Analytics: heatmap + liquidity funnel + recent feed (`9e1050e`)

### Added
- **`GET /api/v1/analytics/heatmap`** — 14 лет × 6 mileage buckets, avg price + volume.
- **`GET /api/v1/analytics/liquidity`** — distribution `days_to_sell` по корзинам (0–3, 4–7, …, 90+).
- **`GET /api/v1/analytics/recent`** — live-лента свежих объявлений (обновляется каждые 30 сек).
- **`GET /api/v1/analytics/cities`** — список городов с числом объявлений.
- Фронт-компоненты: `Heatmap.tsx`, `Funnel.tsx`, `RecentFeed.tsx`.

---

## 2026-04-21 — Trading terminal redesign steps 1–3 (`3b6d252`)

### Changed
- Полный передел визуала под "trading terminal" эстетику: темная палитра (bg `#0a0c10`, surface `#11151c`), токены `--up/--down/--accent/--info`, Space Grotesk для заголовков, JetBrains Mono для цифр, Inter для тела.
- `_app.tsx`: `next/font` для Inter + Space Grotesk + JetBrains Mono.
- Новые layout-компоненты: `Topbar` (с live-тикером USD/KZT и active listings), `FilterBar`, `KPI`.

---

## 2026-04-21 — Deploy consolidation: Netlify → all-Render (`00cb165`)

### Changed
- Перенос фронта с Netlify на Render (Static Site). Бэк остаётся на Render (Web Service). Теперь единый dashboard.
- `render.yaml` добавлен в root с двумя сервисами: `kolesa-backend`, `kolesa-frontend`.
- `docker-compose.yml` упрощён — убраны postgres/redis/airflow/parsers/nginx (это дело парсеров/Neon/Render).

---

## 2026-04-20 — Kolesa feed expansion к ALL brands (`f945f98`, `3ecf630`)

### Added
- Kolesa parser: 15 cities + **79 brand feeds** (изначально было только top-15). Общее число фидов: 30 → 94.
- `BRAND_FEEDS` список в `parsers/kolesa/parser.py` с deduplication через `dict.fromkeys`.

### Changed
- Concurrency: 5 → 3 параллельных feed'а (`CITY_CONCURRENCY=3`) — GitHub Actions IP не блочится.
- Inter-batch sleep 8–15 сек, stop-on-IP-block логика.

---

## 2026-04-20 — README sync before brand expansion (`c401e8b`)

### Changed
- README обновлён под 94 kolesa feed'а и все накопленные парсерные фиксы (до v1.0 инфраструктуры).

---

## 2026-04-19 — Три парсерных бага (`89d13e6`)

### Fixed
- **avtorynok.kz:** бесконечная пагинация — сайт отдаёт те же ~16 объявлений на любой page-num. Добавлен стоп по first-repeat через `seen_ids`.
- **newauto.kz:** без числовых ID — используем slug-ID вида `bmw-x5` из `/catalog/{brand}/{model}`. Плюс обход TLS-fingerprint блокировки через `curl_cffi` Chrome impersonation.
- **OLX.kz:** смена формата ID — `ID12345` → `IDqMNaw`. Регэксп обновлён на `r"ID([A-Za-z0-9]+)"`.

---

## Ранее

См. `git log` для истории до `89d13e6`. До 2026-04-19 проект шёл без формального changelog.
