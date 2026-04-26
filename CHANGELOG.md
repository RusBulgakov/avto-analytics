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

## 2026-04-26 — Forecast V3 (mileage + holidays) + Backtest V2 (arb-margin)

Три родственных upgrade'a по списку "что хочется добавить":

### #1 Mileage как 3-й фактор regression
- **`/forecast` endpoint**: SQL обогащён `mileage_km` per row + per-week median. Если ≥60% недель имеют mileage AND ≥3 distinct values — запускается **multivariate OLS** на features `[1, week, mileage]`, иначе fallback на single-feature.
- **`ols_multivariate`** helper — Gauss-Jordan elimination в pure Python (без numpy/scipy), решает (X^T X) β = X^T y для произвольного числа features. Возвращает coefficients, R², residual_std.
- Новые поля в response: `mileage_coverage_weeks`, `mileage_coef_usd_per_10k_km`, `multivariate_r2_usd`, `model_features` ("intercept", "week", "mileage", опц. "holiday").

**Validated на проде** — Toyota Camry 2017:
```
2-feature (только week):    R² = 0.001  (шум)
3-feature (+ mileage):      R² = 0.360  (+36 п.п.!)
mileage coefficient: -$302 per 10k km
```
**Mileage объясняет 36% вариации цены** — это огромный сигнал.

### #2 Holiday-dummy infrastructure
- **`_is_holiday_week`** helper в `/forecast`: помечает недели чьё ±7 дней от Нового года, 9 мая, Дня независимости (16 дек), посленалоговых периодов (1 мая / 1 ноября). Список расширяется до 2028.
- При наличии ≥1 holiday-week + ≥3 non-holiday weeks в выборке — **добавляется как 4-й feature** в multivariate OLS.
- Возвращает `holiday_effect_pct` — на сколько % дешевле/дороже в holiday weeks.

**Текущий статус**: наша история (с 2 марта 2026) **не включает** ни одного holiday → `holiday_effect_pct = null`. Инфраструктура заработает после 9 мая 2026 / следующего налогового периода — данные просто наберутся.

### #3 Backtest V2 — арбитражная маржа
- Новый CTE-JOIN `cg = group_p25 AS close-week`: для каждого закрывшегося signal'а считаем **p25 группы на момент closure**, а не последнюю цену самого листинга.
- Новые primary метрики:
  - `avg_arb_margin = AVG((group_p25_at_close - first_price) / first_price)`
  - `median_arb_margin` (median вместо avg — robust к outliers)
- Старые метрики (`avg_listing_margin`, `median_listing_margin`) сохранены как secondary для сравнения.
- **Outlier-guard**: `first_price >= 100,000 ₸ AND first_price > group_p25 * 0.30` — отсекает junk listings с фиктивно низкой ценой.
- Top-winners table теперь имеет колонки: `buy`, `market_p25_at_close`, `arb_margin`, `listing_margin`. Сортировка по `arb_margin DESC`.

**Validated** — Toyota Camry, 60d period, -15% discount, 45d hold:
```
total signals: 1,746  (1,782 без outlier-guard, отсеяли 36 мусорных)
hits (sold ≤45d): 1,465

V1 listing margin:  avg -0.33% / median 0.00%
V2 arb margin:      avg +40%   / median +31%
```
**V2 выявляет реальный 31% арбитраж** который в V1 был невидим. Объяснение: продавцы продают сразу по выставленной цене (не реализуя upside), а покупатель потом перепродаёт по рыночному p25 — это где сидит маржа.

### Frontend changes
- **Forecast KPI**: добавлен 6-й tile "Mileage" (показывает coefficient $/10k km + multivariate R²) когда mileage signal доступен.
- **Backtest section**: KPI "Arb margin" заменил "Avg margin" как primary (median вместо avg для robustness). Top-winners table перестроена: колонки `Купил / Market p25 / Arb margin / Дней`.

### Зависимости
Никаких новых — `ols_multivariate` написана в pure Python (Gauss-Jordan), без numpy/scipy.

### #4 Skip
Prophet/ARIMA — отложено до сентября 2026, когда соберём 6+ месяцев исторических данных.

### #5 Pending
Per-listing fair-price predictor (`/listing` page) — следующий round.

---

## 2026-04-26 — `is_in_stock` flag — "В наличии" vs "На заказ"

### Why
Юзер указал что kolesa разделяет объявления на "В наличии" и "На заказ" (последние — машины ещё не привезены в KZ, цена индикативная, часто китайцы BYD / Tesla / Hongqi). Без фильтра они **искажают аналитику**:
- backtest: "На заказ" не закрывается в обычном смысле — переоформляется как заказ → ломает win rate
- profit-ranking: индикативная цена "На заказ" обычно занижена (без learning curve), даёт фантомную маржу
- forecast: тренд цены "На заказ" не отражает реальный рынок б/у

Probe kolesa search-JSON: поле `availability` уже **в top-level** payload, парсить detail-page не нужно.

### Added
- **Schema migration**:
  ```sql
  ALTER TABLE listings ADD COLUMN is_in_stock BOOLEAN DEFAULT NULL;
  CREATE INDEX idx_listings_is_in_stock ON listings(is_in_stock) WHERE is_in_stock = FALSE;
  ```
  TRUE = "В наличии", FALSE = "На заказ", NULL = unknown / не-kolesa источник.
- **Kolesa parser** (`_parse_item`): читает `obj.get("availability")`, маппит `'В наличии' → True, 'На заказ' → False, else None`. Передаёт в data dict как `is_in_stock`.
- **`save_listing`** (parsers/common/db.py): добавлен 19-й параметр `is_in_stock`. ON CONFLICT использует `COALESCE(EXCLUDED.is_in_stock, listings.is_in_stock)` — не перезаписываем existing TRUE/FALSE на NULL если парсер не прислал значение (защита для re-runs других парсеров).

### Changed
- **Analytics endpoints** — junk-filter (3-слойный был emergency + customs + title) → теперь **4-слойный**:
  ```
  AND (l.is_emergency IS NULL OR l.is_emergency = FALSE)
  AND (l.is_customs_cleared IS NULL OR l.is_customs_cleared = TRUE)
  AND (l.is_in_stock IS NULL OR l.is_in_stock = TRUE)   ← новое
  AND title NOT ILIKE ALL([...])
  ```
  Применено в `/profit-ranking`, `/price-boxplot`, `/market-overview`, `/forecast`, `/backtest` — все 5 sites одним replace_all'ом, проверено grep-ом (count=5).

### Backfill
Для существующих active kolesa-listings `is_in_stock = NULL`. После следующего полного парсер-прогона (cron каждые 6h) поле заполнится автоматически из `availability`. До этого `IS NULL` пропускает фильтр (default behavior).

### Estimated impact
Probe показал ~7% китайских объявлений могут быть "На заказ" (BYD, Hongqi, Zeekr, Voyah, Tesla). Для этих марок профит-ranking и backtest сейчас показывали неправильные цифры — теперь будут корректные.

---

## 2026-04-26 — Forecast V2 + Backtest стратегии перепродажи

### Added
- **`fx_history` table** — daily USD/EUR/RUB/CNY → KZT курсы от National Bank of KZ. Backfill 90 дней ad-hoc, далее `parsers/common/fetch_fx.py` daily через `.github/workflows/fetch_fx.yml` (06:00 UTC).
- **`/forecast` V2** — multivariate-style regression:
  - Per-row LATERAL JOIN с `fx_history` (forward-fill для weekend/holiday)
  - Считаем 2 параллельных OLS: на median_kzt и median_usd (price_kzt / fx_rate)
  - Возвращаем оба тренда + `fx_impact_pct = kzt - usd` (вклад движения тенге)
  - Forecast curve в KZT = USD-прогноз × current_rate (отделяет market-движение от FX-шума)
  - Новые params: `year_from`, `year_to` (для поколений типа Camry XV50 = 2014-2018)
- **`/backtest` endpoint** — ретро-тест стратегии "купить дешевле p25, продать в течение 45 дней":
  - Buy signal: `first_price < group_p25 * (1 - discount_threshold)` (default 15%)
  - Hit: `closed_at within hold_days` (default 45)
  - Aggregate: total_signals, hits, misses, win_rate, avg/median_realized_margin, median_days_to_sell
  - + Top-10 winners (top realized margin, with listing URLs)
  - Junk-фильтр applied (битые / не растаможенные не попадают в signals).
- **`/forecast` page**:
  - 5 KPI tiles (вместо 4): Тренд KZT, Тренд USD, FX вклад (с пояснением "тенге слабеет/крепнет"), R² (USD), Выборка (с current_fx_rate)
  - Year selector split: "Год от" + "Год до" (для поколений)
  - Новая секция "Ретро-тест стратегии перепродажи" с 4 KPI (Сигналы, Win rate, Avg margin, Median days) + таблица топ-10 успешных сделок с маржой и днями держания

### Validated на проде

**Forecast V2 — Toyota Camry 2017 (8 weeks):**
```
KZT trend  +4.58%/мес  R² 0.04  ← наблюдаемая динамика
USD trend  +8.49%/мес  R² 0.14  ← истинный тренд цены (без FX)
FX impact  -3.91%/мес              ← тенге укрепляется и СКРЫВАЕТ USD-рост
```
Без USD-нормализации этот сигнал не виден — пользователь думает рынок растёт на 4.5%, реально цены идут вверх на 8.5% (а тенге компенсирует).

**Backtest — Toyota Camry за 60 дней (-15% от p25, hold 45д):**
```
total_signals: 1,782
hits (sold ≤45д): 1,482
win_rate: 83.2%
avg_realized_margin: +0.29%
median_realized_margin: +0.00%
median_days_to_sell: 7
```
Insight: сигналы быстро закрываются (7 дней median), но **margin почти ноль**. Продавцы выставляют fair-цену сразу и она не двигается до закрытия. Strategy "купи-подожди-продай" в коротком окне не приносит маржу — нужно сравнивать с **текущим p25 группы на момент продажи**, не с ценой того же листинга. Это V2 backtest для следующей итерации.

### Зависимости
Никаких новых — pure Python.

### Что не сделано (для следующего раунда)
- Backtest V2: сравнивать sell-price с **текущим** p25 группы на момент закрытия (а не last_price того же листинга)
- Forecast: добавить mileage_km как третий фактор regression (сейчас игнорируется)
- Сезонность: holiday calendar / tax periods как dummy variables

---

## 2026-04-26 — MVP Forecast: OLS regression на недельных медианах

### Added
- **`GET /api/v1/analytics/forecast`** — endpoint linear-regression прогноза цены. Параметры: `brand_id` (обяз.), `model_id`, `year`, `history_days` (default 90), `horizon_days` (default 30, до 120), `include_inactive`, `include_junk`. Возвращает: `{historical, forecast, trend_pct_per_month, r2, residual_std_pct, sample_size, horizon_weeks}`.
- **`/forecast` страница** — переписана с placeholder'а на полноценную реализацию:
  - Селекторы: марка → модель → год → горизонт прогноза (2н / 1м / 2м / 3м)
  - 4 KPI: Тренд %/мес, R² качество, Шум (residual std %), Выборка (недель данных)
  - График: фактическая медиана (синяя сплошная) + прогноз (жёлтая пунктирная) + 95% CI (полупрозрачная заливка)
  - Метод-карточка: объяснение MVP-ограничений (нет сезонности, нет KZT/USD, нет смены поколений)

### Algorithm
1. Достаём `price_history` за `history_days` дней для выбранной (brand, model?, year?). Применяется тот же junk-filter что и в /profit-ranking — иначе wreck-цены (например, битый BMW 525 за 600k vs реальные 1.6M) ломают тренд.
2. Группируем по неделям (`DATE_TRUNC('week', recorded_at)`) и берём медиану цены — стабильнее чем avg.
3. **OLS** простой Python-арифметикой (без numpy/scipy в зависимостях):
   ```python
   slope = sum((x_i - x̄)(y_i - ȳ)) / sum((x_i - x̄)²)
   intercept = ȳ - slope * x̄
   ```
4. Residuals → `residual_std = sqrt(RSS / (n-2))` для 95% CI = `±1.96 * residual_std`.
5. R² = `1 - RSS/TSS`.
6. Forecast: `y_future[w] = intercept + slope * (last_idx + w)` для каждой будущей недели.
7. Trend %/мес = `slope * 4 / mean_price * 100`.

### Validated на проде
- **Toyota Camry 2017**: 8 недель, slope +251k ₸/нед, тренд **+10.0%/мес**, R² 0.18 (данные шумные — мало sample), forecast +4 нед = 11.92M ±2.79M (24% noise band).

### MVP ограничения
- Игнорирует сезонность (например, перед/после налоговых периодов)
- Не учитывает курс KZT/USD (важен для премиум-сегмента)
- Не различает поколения модели (T-Camry XV40 vs XV50 vs XV70 в одной "Camry")
- Один линейный тренд — не ARIMA, не exponential smoothing
- R² < 0.3 на многих группах — данных пока 8 недель macro, шум большой
- Нет PRO-features: сигналы покупки, retro-test стратегии, календарь скидок

### Зависимости
Никаких новых — pure Python (`math.sqrt`), numpy/scipy не добавлены.

---

## 2026-04-26 — Real junk flags from kolesa search-фильтров

### Why
Прошлый junk-filter был эвристикой: title-keyword (ловил 6 listings — kolesa в title только "Brand Model Год г.") + price-outlier (median ± 50%-200%, ловит kolesa-junk через цену). Эвристика OK, но **не точна** — продавец вполне может поставить честную цену на битую машину, и она проскользнёт.

Открытие через probe: kolesa.kz сам различает аварийные/не растаможенные через **search-фильтры**:
- `?need-repair=1` → 3,428 listings (аварийные/не на ходу, ~2% всего рынка)
- `?auto-custom=1` → 5,092 listings (не растаможенные, ~3%)

172 + 255 = **427 страниц search-результатов** vs 53k detail-страниц — парсинг **15 минут вместо 5 часов**, и точность 100% (kolesa сам помечает).

### Added
- **Schema migration** — `listings` получил 3 колонки + 2 partial-индекса:
  - `is_emergency BOOLEAN DEFAULT NULL`  (TRUE = аварийная/не на ходу)
  - `is_customs_cleared BOOLEAN DEFAULT NULL`  (FALSE = не растаможен)
  - `flags_updated_at TIMESTAMPTZ DEFAULT NULL`
  - Partial indexes: `idx_listings_is_emergency WHERE is_emergency=TRUE`, `idx_listings_is_customs_cleared WHERE is_customs_cleared=FALSE` (только для "плохих" — экономия места).
  Миграция применена ad-hoc на Neon.
- **`parsers/kolesa/flags.py`** — новый модуль. Параллельно парсит оба фильтра (через `asyncio.gather`), собирает ID-сеты, делает 3-step UPDATE:
  1. ВСЕ active kolesa-listings → `is_emergency=FALSE, is_customs_cleared=TRUE` (default-mark)
  2. emergency-IDs → `is_emergency=TRUE`
  3. not-cleared-IDs → `is_customs_cleared=FALSE`
- **`.github/workflows/kolesa_flags.yml`** — cron каждые 8 часов (00:15 / 08:15 / 16:15 UTC), timeout 30 мин. Поскольку флаги меняются реже чем listings — частоты достаточно.

### Changed
- **`/profit-ranking`, `/price-boxplot`, `/market-overview`** в `analytics.py`: junk-filter теперь 3-слойный:
  1. **Real DB flags**: `(l.is_emergency IS NULL OR l.is_emergency = FALSE) AND (l.is_customs_cleared IS NULL OR l.is_customs_cleared = TRUE)` — `IS NULL` пропускает (для не-kolesa и старых записей где flags ещё не заполнены)
  2. **Title-keyword fallback** — для OLX/mycar/avtorynok где seller пишет "не на ходу" в title
  3. **Price-outlier фильтр** (только в /profit-ranking) — median ± [50%, 200%] per group, как и раньше

Все 3 слоя активируются `include_junk: bool = False` (default). Toggle "Товарные / Все" в UI работает с новой логикой без изменений.

### Не покрыто
- mycar/olx/avtorynok detail-flag parsing — у них нет аналогичных search-фильтров. Title-keyword + price-outlier остаются единственным способом.
- Историческая корректировка для inactive listings — flags заполняются только для active. Для исторического анализа (toggle "Все") все old закрытые объявления по-прежнему фильтруются эвристикой.

---

## 2026-04-26 — Long-tail city cleanup: +56 city normalizations

### Changed
- **`parsers/common/db.py::_CITY_NORMALIZATIONS`** расширен с **36 → 84 entries**. Добавлены:
  - **Алматинская область пригороды**: Талгар, Каскелен, Есик, Жаркент, Текели, Уштобе, Кордай, Отеген, Алмалыбак, Бесагаш — все маппятся в свои собственные latin slug'и (talgar, kaskelen, etc.).
  - **Конаев = Капчагай (переименован 2022)**: 4 варианта (`'конаев'`, `'конаев (капшагай)'`, `'капшагай (конаев)'`, `'капшагай'`) → все на единый `kapchagay`.
  - **Шымкентская область**: Сарыагаш, Аксукент, Шиели, Мерке.
  - **Атырауская / Мангистау**: Кульсары, Бейнеу, Балыкши, Еркинкала.
  - **Северный Казахстан**: Щучинск, Акколь, Атбасар, Нура, Аягоз, Булаево, Бишкуль.
  - **Восточный Казахстан**: Зыряновск, Кокпекты, Белоусовка.
  - **Костанайская**: Затобольск, Житикара.
  - Алиасы: `oral` → `uralsk` (казахское имя), `kostanay` → `kostanai`, `semei` → `semey`.

### Manual ops (ad-hoc Python script — НЕ в репо)
- **283 listings** нормализованы в БД через bulk UPDATE с использованием расширенного `_CITY_NORMALIZATIONS`. После: остаётся 20 active listings в 20 micro-сёлах с по 1 объявлению каждый — long tail, оставляем как есть.

### Why
Города типа `'талгар'` (5), `'каскелен'` (4), `'жаркент'` (10) кириллицей в БД ломали slug-based фильтры/aggregations. Не на карте (нет в `_CITY_COORDS`) — но теперь хотя бы консистентны с остальными фильтрами/queries.

### Note
Эти города **намеренно не добавлены в `_CITY_COORDS`** — они малы (3-14 listings) и на дашборде создавали бы шум. Они учитываются в `/summary`, `/market-overview`, фильтрах — но не в `/geo` (карта KZ).

---

## 2026-04-26 — Junk-listing filter: аварийные / не на ходу / не растаможенные

### Why
Юзер увидел в `/profitability` BMW 525 1994 с margin 73% — фантом. Причина: kolesa.kz парсит **всё подряд**, включая аварийные / не на ходу / не растаможенные / на запчасти. Битый BMW за 600k вместе с целыми за 1.6M ломает p25 (buy_price) — оценка маржи получается мусорной.

### Added
- **`include_junk: bool = False`** query-param в 3 endpoint'ах:
  - **`/profit-ranking`** — title-keyword filter + **price-outlier filter** (median ± [0.5x, 2x] per group). Выкидывает листинги ниже 50% медианы группы (битые / не растаможенные) и выше 200% (typos / эксклюзивные комплектации).
  - **`/price-boxplot`** — только title-keyword filter (boxplot и так показывает разброс — outlier filter избыточен).
  - **`/market-overview`** — title-keyword filter (avg price корректнее).

- **Toggle "Товарные / Все"** в `frontend/pages/profitability.tsx` — позволяет переключиться на raw данные если нужно. Default = "Товарные" (junk excluded). Под page-sub небольшой бейдж `★ исключены аварийные / не на ходу / не растаможенные / на запчасти + price-outliers` пока в "Товарные"-режиме — прозрачность для пользователя.

### Filter logic
```
title NOT ILIKE ALL(ARRAY[
  '%не на ходу%', '%аварий%', '%битая%', '%битый%',
  '%не растамож%', '%не растам%', '%без документ%',
  '%на запчасти%', '%по запчастям%', '%разбит%',
  '%восстанов%', '%утоплен%', '%горел%'
])
+ price BETWEEN group_median * 0.5 AND group_median * 2.0  (только для profit-ranking)
```

### Impact (validated с прода)
До/после junk-filter в /profit-ranking (top-1 по марже):
- **BMW 525 1994**: margin **73.3%** → реалистичные **43.8%** (vol 26 → 23, buy 1.24M → 1.60M)
- **Mitsubishi Galant 1997 (71.4% margin)** — full junk, выпал из топа
- **Daewoo Nexia 2006 (58.3%)** — full junk, выпал
- Топ теперь в honest 40-58% margin диапазоне vs фантомные 60-75%.

Title-keyword filter ловит только **6 listings** в БД (0.01%) — потому что kolesa в title пишет только "Brand Model Год г." без описаний. Sellers пишут "не на ходу" в OLX/mycar (где title содержит description). Зато **price-outlier filter** ловит kolesa-junk через ценовые аномалии.

### Не покрыто (TODO для бэклога)
- Парсинг **detail-страниц kolesa** (`/a/show/{id}`) для извлечения реальных флагов `is_emergency`, `is_customs_cleared`, `runs` в схему `listings`. Сейчас kolesa search-JSON флаги не отдаёт. Это бы дало **точный** фильтр вместо эвристики, но цена — 53k extra HTTP запросов на каждый прогон. Альтернатива — парсить только когда `last_seen_at < N часов`, чтобы amortized cost был меньше.

---

## 2026-04-26 — Mobile responsive pass

### Added
- **Burger menu в `Topbar`** — на ширине <640px все nav-ссылки (`.nav`) скрыты, а появляется кнопка `☰`. По клику разворачивается fullscreen overlay с большими route-tap'ами (Дашборд / Марки / Рентабельность / Прогноз). Overlay закрывается при клике на ссылку, на пустое место, или при route change. `body` блокируется от скролла пока меню открыто.
- **CSS: `.topbar-burger`, `.mobile-nav-overlay`, `.mobile-nav`** — display:none на десктопе, видимы только в мобильном media query. Backdrop-filter blur для затемнения фона.

### Changed (`globals.css`)
- **Mobile <640px**: `topbar-btn` (Поиск + ⚙ Настройки) скрыты — место для burger. `brand-meta` ("KZ · V1") скрыт. `card-h` теперь `flex-wrap: wrap` с `gap: 8px`, title занимает 100% ширины — chip-group переезжает на следующий ряд (раньше упирались/обрезались). `card-b` padding 14→12px. `page-title` 24→22, `card-title` 13.5→13. Heatmap клетки 20→22px высота с font 9px (для лучшего тач-таргета).
- **Mobile <768px**: таблицы `.tbl` внутри `.card-b` получают `display:block; overflow-x:auto` — wide-tables (profit-ranking 8 колонок) перестали ломать layout, скроллятся горизонтально с `-webkit-overflow-scrolling: touch`. Td/th padding 14→8/10, font-size до 12px.

### Why
До фикса: на 375px/iPhone 12 (типичный мобильник) `.nav` скрыт без замены — пользователь не мог перейти из дашборда на /brands или /profitability вообще. Таблица рейтинга упиралась в правый край и просто обрезалась. `.card-h` с длинным title и chip-group выталкивал последний рядом.

### Что не правил (намеренно)
- KZMap (Leaflet): height 380 фикс, scroll-zoom отключён — норм на тач.
- PriceCandles/BoxPlot: SVG viewBox auto-scale через width:100%, на узком становится мельче, но читаемо.
- PriceChart (Recharts ResponsiveContainer): свой responsive, не трогаем.
- FilterBar: уже `overflow-x: auto` — chip-group переполняется в горизонтальный скролл, что приемлемо.

---

## 2026-04-26 — Boost coverage: OLX per-city + mycar no-proxy

### Changed
- **`parsers/olx/parser.py`**: один root-фид → **16 фидов** (root + 15 per-city). OLX режет global pagination на ~10 страниц (~400 объявлений из десятков тысяч). Per-city фиды (`q-almaty/`, `q-astana/`, …) обходят этот cap. Добавлен **across-feeds dedup** через `seen_ids: set` — один и тот же `external_id` не сохраняется дважды если попался в нескольких фидах. **Stop-on-repeat-page**: если все ID на текущей странице уже видели — стоп (защита от OLX-зацикленной пагинации). Delay уменьшен 5–14с → 2.5–5с между страницами одного фида + 8–15с между фидами.
- **`parsers/mycar/parser.py`**: `use_proxy=True` → **`False`** (публичный REST API не блочит, бесплатные прокси добавляли 30-45с retry-задержки впустую). `PAGE_SIZE=24` → **50** (API позволяет, in 2× меньше запросов на тот же объём). `MAX_PAGES=200` → **600** (теоретический потолок 30k вместо 4.8k). Между запросами `sleep 2.0` → **1.0** (REST быстрее HTML). Логирование reduced: every 10-я page или последняя.

### Why
До фикса:
```
kolesa     53,874  (96%)
mycar       1,244
olx           372    ← на olx.kz реально десятки тысяч
newauto       241    (полный inventory новых авто, OK)
avtorynok     227    (сайт by design ограничивает ~16 active, OK)
```
OLX парсер вообще не видел >400 объявлений всего из-за site-pagination cap. mycar был зажат прокси-задержками + малым page-size + хардкод 200 страниц.

### Expected impact
После следующих GHA-прогонов:
- **OLX**: 372 → ~5,000–10,000 active (16 фидов × ~10 страниц × ~40 cards, минус дубли)
- **mycar**: 1,244 → ~5,000–8,000 active (300+ страниц на 50 cards без прокси-троттлинга)
- **Total non-kolesa**: 4% → 15–25% от объёма платформы.

---

## 2026-04-26 — City normalization: 14+ городов добавлены на карту

### Added
- **`parsers/common/db.py::_normalize_city`** — helper, нормализующий city перед `INSERT`. Маппит 36 кириллических имён в latin slug'и, обрезает мусорные суффиксы `" - Сегодня в"` / `" -"` (только с пробелами вокруг дефиса — не ломает `ust-kamenogorsk` / `land-rover`). Вызывается в начале `save_listing`. Защита от регрессии — независимо от того, что присылает парсер.
- **`backend/.../analytics.py::_CITY_COORDS`** расширен с 20 → **34 городов**: добавлены `ekibastuz`, `taldykorgan`, `zhezkazgan`, `ridder`, `balkhash`, `satpayev`, `rudny`, `stepnogorsk`, `kentau`, `zhanaozen`, `arkalyk`, `kapchagay`, `khromtau`, `shu`. Все эти slug'и реально присутствуют в DB после нормализации.

### Manual ops (ad-hoc Python script — НЕ в репо)
- **Bulk DB cleanup: ~1700 listings** мигрированы из кириллицы / суффикс-мусора в latin slug'и:
  - `Алматы` (670) / `Астана` (363) / `Шымкент` (101) / `Караганда` (92) и т.д. → latin slug'и
  - `Костанай - Сегодня в` / `Павлодар -` / `Семей - Сегодня в` → чистые slug'и
  - `Талдыкорган` (25) / `Кызылорда` (14) / `Жанаозен` (24) / `Сатпаев` (19) → latin
- **Pavlodar теперь видим на карте**: было 0 в `/geo`, стало 321 active.

### Incident & rollback (учиться на ошибке)
**Инцидент:** Первая итерация моего regex-нормализатора `\s*-\s*.*$` (БЕЗ обязательных пробелов вокруг дефиса) **поломала 18,481 `ust-kamenogorsk` → `ust`**, потому что захватывала валидные дефисы внутри slug'ов. Также применённый затем `.lower()` к non-mapped значениям превратил латинские slug'и в lowercase копии.
**Rollback:** `UPDATE listings SET city = 'ust-kamenogorsk' WHERE city IN ('ust', 'усть')` — восстановлено 18,481 + 138 listings.
**V2 фикс:** regex теперь `\s+-\s*.*$` (минимум один пробел перед дефисом), и `_normalize_city` НЕ применяет `.lower()` к не-маппированным значениям — возвращает их как есть.
**Урок (логировано в `CLAUDE.md`):** при массовых SQL миграциях `city`-style данных всегда тестировать regex на dry-run выводе **до** UPDATE, особенно когда в выходных данных есть значения с дефисами.

### Why
OLX и mycar парсеры пишут city в кириллице (`"Алматы"`), kolesa — в latin slug (`"almaty"`). `/geo` endpoint матчит по latin slug'у, поэтому ~1500 кириллических listings не попадали на карту. Также мусор типа `"Павлодар - Сегодня в"` (это парсер схватил часть HTML текста рядом с city) тоже не матчился.

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
