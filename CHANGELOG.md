# Changelog

Все значимые изменения проекта. Формат основан на [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), версии — date-based. Самое свежее — наверху.

---

## 2026-04-26 — Kolesa parser: безотказность + охват + Telegram прогресс-бар (1b3e30a)

### Added
- **Шардированный workflow `.github/workflows/kolesa_full.yml`** — kolesa.kz вынесен из `daily_parsers.yml` в отдельный workflow, потому что полный прогон 191 фида не влезает в 360-мин GHA timeout. Решение: matrix из 2 параллельных шардов × ~96 фидов × 350-мин timeout. Cron: дважды в сутки (`0 8` + `0 20` UTC).
- **`http_client.py::IPBlockedError`** — кастомный exception для 403/451. Парсер прерывается мгновенно вместо 4×35 = 140 секунд retry на каждой заблокированной странице.
- **`parser.py::_get_feeds_for_shard`** — round-robin разбивка `ALL_FEEDS` через env vars `KOLESA_SHARD_INDEX`/`KOLESA_SHARD_COUNT`. Каждый шард получает равномерный микс городов/брендов/моделей.
- **`parser.py::_validate_model`** — отсекает синтетические модели (`model == brand`, `model == 4-значный год 1990–2030`). Listing сохраняется с `model_id=NULL` через LEFT JOIN, данные не теряются. Реальные модели-числа (Audi 80/100, BMW 525/528, Mazda 626, Porsche 911, Lada 2107/2114) **не отсекаются** — они валидные.
- **Telegram прогресс-бар** в `parser.py::_render_progress_bar` + фоновая `_progress_updater` task. Каждый шард шлёт сообщение в начале и редактирует его каждые 60 сек через `editMessageText` API. Показывает: страниц, фидов, активные фиды, сохранено/новых, прошло/ETA.
- **`notifier.py`**: `send_telegram_message_with_id` (возвращает `message_id`), `edit_telegram_message` (с обработкой "message is not modified").
- **Smoke-check + structured exit codes** в `parser.py::__main__`:
  - `0` = success (`>MIN_SAVED_THRESHOLD=1000`)
  - `1` = IP блок / catastrophic (`<MIN_PARTIAL_THRESHOLD=100`)
  - `2` = непойманное исключение / DB error
  - `10` = partial success (100–1000) — deactivate отменён
- **SIGTERM handler** в `parser.py` — graceful shutdown при GHA-timeout.
- **`daewoo`** добавлен в `BRAND_FEEDS` (~690 active listings раньше попадали только через model-feeds `daewoo/nexia`, `daewoo/matiz`).
- **Auto-trigger `alive_check`** после успешного `kolesa_full`: новый job в `kolesa_full.yml` запускает `gh workflow run "Alive Check (Kolesa)"` если шарды отработали успешно.

### Changed
- **Per-error retry strategy** в `http_client.py::fetch`:
  - `403`/`451` → `IPBlockedError` мгновенно (без retry)
  - `429` → backoff `60×1.5^retry` сек, до 3 попыток
  - `5xx` → exp backoff 3–12 сек, до 3 попыток
  - network/timeout → exp backoff 3–12 сек, до 3 попыток
- **`parse_city`**: `consecutive_errors` сбрасывается **только при успешной загрузке HTML** (раньше сбрасывался на любом исходе включая пустой ответ — это маскировало IP-блок). `IPBlockedError` пробрасывается наверх как сигнал блока, не считается сетевой ошибкой.
- **`run_parser` batch-level health check**:
  - ≥50% батча упало → пауза 60–120 с перед следующим
  - 100% упало → пауза 2–3 мин + попытка восстановиться
  - 2 подряд full-fail → IP блок подтверждён, return `ip_blocked=True`
- **`run_parser` сигнатура**: возвращает `(saved, new, ip_blocked)` вместо `(saved, new)` — `__main__` решает exit code.
- **City normalization** в `_parse_item`: `'0'` → `None`, `'semei'` → `'semey'` (через alias map).
- **`alive_check.yml` cron**: `30 */6 * * *` (каждые 6h) вместо `30 */12 * * *` — ложно-деактивированные исчезают за полдня вместо суток.
- **`daily_parsers.yml`**: убран kolesa из matrix (теперь только mycar/newauto/avtorynok/olx). `concurrency` group + `if: success()` для `deactivate-old`.

### Fixed
- **Локальный кейс `KeyError: 'POSTGRES_HOST'`** при запуске парсера вне GHA: `load_dotenv()` теперь вызывается в `parser.py::__main__` (раньше только в `migrator.py`).
- **`asyncio.wait_for(timeout=35)` поверх `curl_cffi.session.get(timeout=30)`** — curl_cffi иногда висел вечно на зависших TCP, libcurl-таймаут не срабатывал.
- **`continue` вместо `break`** на сетевой ошибке в `parse_city` + счётчик 5 ошибок подряд для защиты от бесконечного висения при мёртвом интернете.
- **9 listings с `model = brand`** + **5 с `model = год`** + **3868 с `city = '0'`** + **5 с `city = 'semei'`** — миграция БД выполнена ad-hoc.

### Impact
- Парсер больше **не зависает на 7+ часов** на одном HTTP-запросе и не крутится 4 часа впустую при IP-блоке.
- При неудачном прогоне `deactivate-old` **не запускается** → перестаём терять живые объявления (вчера потеряли 11,864 за один день).
- 2× прогона в сутки + alive_check каждые 6h → доля свежих (`<24h`) listings должна вырасти с 5.6% до целевых 80%+.
- Telegram-наблюдаемость: видно прогресс шардов в реальном времени, легко поймать аномалию ещё в процессе.

### Migration ops (ad-hoc, не в репо)
```sql
UPDATE listings SET city = NULL  WHERE city = '0';     -- 3868
UPDATE listings SET city = 'semey' WHERE city = 'semei'; -- 5
UPDATE listings l SET model_id = NULL FROM brands b, models m
  WHERE l.brand_id=b.id AND l.model_id=m.id AND LOWER(m.name)=LOWER(b.name); -- 9
UPDATE listings l SET model_id = NULL FROM models m
  WHERE l.model_id=m.id AND m.name ~ '^(199[0-9]|20[0-2][0-9]|2030)$'; -- 5
```

---

## 2026-04-26 — Распространение `brand_name`/`model_name` на остальные парсеры

### Changed
- **`parsers/mycar/parser.py`**, **`parsers/olx/parser.py`**, **`parsers/newauto/parser.py`**, **`parsers/avtorynok/parser.py`** теперь возвращают в data dict явные поля `brand_name` и `model_name` (раньше передавали только `*_slug` + `title`, db.py приходилось вытаскивать имя из title через split-фолбэк). Симметрия с уже-обновлённым `parsers/kolesa/parser.py`.

### Why
`save_listing` в `parsers/common/db.py` (после фикса `9250e23`) предпочитает `data.get("model_name")` над title-split. Если парсер передаёт его — БД получает наиболее точное имя. Этот коммит делает 4 оставшихся парсера консистентными — теперь все 5 источников питают БД одинаково богатой meta-информацией о моделях, и фолбэк на title-split в `save_listing` остаётся только для обратной совместимости (если кто-то добавит шестой парсер и забудет про эти поля).

### Audit-fix в CHANGELOG (без code changes)
4 моих предыдущих заголовка не имели SHA-anchor по правилу `CLAUDE.md` (формат `YYYY-MM-DD — описание (sha)`). Добавлены:
- `2026-04-26 — Multi-word model names` → `9250e23`
- `2026-04-26 — Profitability: filter garbage model names` → `fb31179`
- `2026-04-26 — Time-aggregated charts` → `bfc4802`
- `2026-04-22 — Active/All toggle` → `7737f95`

---

## 2026-04-26 — Multi-word model names — `Land Cruiser Prado`, не просто `Land` (`9250e23`)

### Fixed
- **Parser kolesa (`parsers/kolesa/parser.py::_parse_item`)** — извлекает model из title как **всё между brand и 4-значным годом**, вместо `parts[1]` (наивный). Title `"Toyota Land Cruiser Prado 2018 г."` → `model = "Land Cruiser Prado"`, не "Land".
- **Парсер выбирает самый информативный кандидат**: `attrs.model` (от kolesa, часто single-word типа "Land") и `title_model` (multi-word из title) — берётся вариант с наибольшим числом слов.
- **Передача в БД**: `_parse_item` теперь возвращает явное поле `model_name` в data dict (было только `model_slug`). `save_listing` использует его, fallback на старую логику для других парсеров.

### Changed
- **`save_listing` в `parsers/common/db.py`**: ON CONFLICT при upsert моделей теперь **сохраняет multi-word имя**, если новая запись пришла с укороченным:
  ```sql
  ON CONFLICT (brand_id, slug) DO UPDATE
  SET name = CASE
      WHEN array_length(string_to_array(EXCLUDED.name, ' '), 1)
           >= array_length(string_to_array(models.name, ' '), 1)
      THEN EXCLUDED.name
      ELSE models.name
  END
  ```
  Раньше `SET name = EXCLUDED.name` всегда переписывал; следующий парсер run после ручной чистки откатил бы данные обратно.

### Manual ops (ad-hoc Python script — НЕ в репо)
- **Bulk DB cleanup: 807 моделей переименовано** через title-derived multi-word имена. Подход: для каждой модели из listings найти sample title, извлечь имя regex'ом (стрип brand-префикса с учётом локализованных вариантов "ВАЗ (Lada)" / "Mercedes-Benz", обрезать год). Примеры:
  - `Toyota Land` → `Land Cruiser Prado` (slug=`land-cruiser-prado`, 4009 listings)
  - `Toyota Land` → `Land Cruiser` (slug=`land-cruiser`, 2824)
  - `Hyundai Santa` → `Santa Fe`
  - `Lada (Lada)` → `Priora` / `Granta` / `Vesta` (slug-specific)
  - `Mercedes Benz E` → `E 230` / `E 200` / `E 320` (по slug-modification)
  - `Toyota Mark` → `Mark II`
  - `Mitsubishi Montero` → `Montero Sport`

### Why
До фикса: kolesa.kz сам в JSON-attributes отдаёт `model = "Land"` для всех Land Cruiser/Prado/100/200. Парсер брал это значение, db.py поверх на CONFLICT переписывал name на single-word. В UI юзер видел два бренда "Toyota Land" с одинаковым именем но разными slug'ами и думал что это дубли.

---

## 2026-04-26 — Profitability: filter garbage model names (`fb31179`)

### Changed
- **`/profit-ranking` SQL** теперь отфильтровывает мусорные модели в `WHERE`-clause:
  - `m.name NOT LIKE '(%'` — исключает синтетические fallback'и парсера kolesa типа `"(Lada)"`, `"(Toyota)"` (когда парсер не извлёк реальную submodel — берёт бренд в скобках).
  - `LOWER(m.name) <> LOWER(b.name)` — исключает кейсы где `model.name == brand.name` (тоже признак отсутствия реальной модели).

### Why
Скриншот юзера на /profitability показывал топы как `Lada (Lada) — 5 раз` подряд и `Volkswagen Golf — 3 раза`. Дубликаты — потому что бэк уже агрегировал по `brand_id+model_id+year` (разные года), но фронт-таблица `<th>Год</th>` была добавлена в коммит `01bba6c`/после, и пока не была видна в проде. Деплой frontend подтянет колонку. Дополнительно — мусорные модели "(Lada)" теперь не попадают в rankings вообще, поскольку это data-quality артефакт парсера.

### TODO (не сделано в этом коммите)
- Reparser fix: убрать в `parsers/kolesa/parser.py::_parse_item` fallback на `"(brand)"` для `model_slug` — лучше пропускать запись чем сохранять с мусорной моделью.

---

## 2026-04-26 — Time-aggregated charts: weekly price-history + price-candles widget (`bfc4802`)

### Added
- **`/api/v1/analytics/price-candles`** — новый endpoint, возвращает квартили цен (P5/Q1/median/Q3/P95) по временным бакетам. Параметры: `period_days` (14–730, default 180), `granularity` ('auto'|'day'|'week'|'month', auto = week для ≤90д иначе month), `min_count` (минимум точек в бакете, default 5), плюс стандартные фильтры (brand_id, model_id, city, source, include_inactive). Ответ: `{granularity, candles: [{date, count, whisker_low, p25, median, p75, whisker_high}]}`.
- **`granularity` query-param в `/price-history`** — `'auto'|'day'|'week'|'month'`. Auto: ≤14д→day, ≤180д→week, >180д→month. Работает потому что в среднем на kolesa объявление меняет цену 1.1 раз в месяц — daily-бакеты дают разреженную шумную кривую.
- **`PriceCandles`** (`frontend/components/charts/PriceCandles.tsx`) — кастомный SVG-компонент distribution-style свечей. Тело = Q1–Q3, усы = P5–P95, медиана = тик, цвет = направление медианы относительно прошлого бакета (up/down). Hover = детали бакета внизу карточки.
- **Granularity chip-group в card-h "Динамика цен"** (`[авто] [1д] [1н] [1м]`) — пользователь может переопределить auto-resolve.
- **Новая section "Свечи цен — распределение по времени"** на дашборде, прямо перед "Распределение цен по маркам". Свой собственный chip-group для granularity. Реагирует на фильтры (brand/model/city/source/include_inactive).

### Breaking
- **`/api/v1/analytics/price-history` return shape**: было `[{date, avg_price_kzt, ...}]`, стало `{granularity: 'day'|'week'|'month', points: [{date, avg_price_kzt, ...}]}`. Frontend (`index.tsx`, `model.tsx`) обновлены — извлекают `.points` и `.granularity`. Если есть внешние consumer'ы — придётся адаптировать.

### Changed
- `analyticsApi.getPriceCandles` добавлен в `frontend/lib/api.ts`.
- `PriceChart` теперь принимает `granularity?: 'day'|'week'|'month'` для корректного форматирования tick'ов и tooltip'ов (для week — диапазон "1 апр – 7 апр", для month — "Апрель 2026").

### Why
Машины не меняют цену день в день: реальный rate ≈ 1 запись price_history per listing per month. Daily-бакеты для длинных периодов (90д+) производили шумную лесенку; weekly-бакеты сглаживают и делают тренды читаемыми. Свечи же показывают, что разброс цен на новостройку и битое сильно отличается даже внутри одной модели — и это нужный сигнал для трейдера.

---

## 2026-04-22 — Active/All toggle (исторический режим) (`7737f95`)

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
