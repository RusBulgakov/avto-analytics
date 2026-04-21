# Handoff: Авто Аналитика KZ — Trading Terminal Redesign

## Overview

Полный редизайн фронтенда «Авто Аналитика KZ» в стиле **trading terminal** (Bloomberg/финансовые дашборды) для аудитории перекупов и автодилеров.

Три страницы:
1. **Dashboard** — обзор рынка с KPI, графиками, картой KZ и топом моделей для перепродажи
2. **Model page** — детальная страница марки/модели (на примере Toyota Camry)
3. **Listing page** — страница отдельного объявления с оценкой «справедливой цены»

## About the Design Files

Файлы в этом бандле — **HTML-прототипы-референсы**, созданные в chat-среде. Это НЕ production-код для прямого копирования.

Задача: **пересоздать эти дизайны в существующем стеке проекта** — `Next.js 14 + TypeScript + SWR + Recharts + framer-motion + zustand` (см. `frontend/package.json`), следуя паттернам кодбейза (`pages/`, `components/layout/`, `components/charts/`, `components/filters/`, `lib/api.ts`).

Прототипы написаны на React 18 через Babel Standalone + inline `<script type="text/babel">`. Вся логика в 3 `.html` файлах + `styles.css` + `data.js` (моки) + `components.jsx` + `charts.jsx`.

## Fidelity

**High-fidelity.** Все цвета, типографика, отступы, интеракции (hover-состояния, переключатели режима хитмапа, pulse на live-индикаторе) — финальные. Пересоздавать пиксель-в-пиксель, используя существующий стек проекта.

Единственное исключение — данные везде mock. Нужно подключить к реальному API (см. раздел **API Endpoints Required** ниже).

---

## Design Tokens

### Colors (CSS custom properties, exactly as in `styles.css`)

**Dark (default):**
```css
--bg: #0a0c10;            /* body background */
--bg-2: #0e1219;          /* subtle depth (filter bar, grid fills) */
--surface: #11151c;       /* cards */
--surface-2: #171c26;     /* nested surfaces, table headers */
--surface-hover: #1c2230;
--border: rgba(255,255,255,0.06);
--border-strong: rgba(255,255,255,0.10);
--text: #e6e9ef;
--text-2: #a5adbb;
--text-muted: #6b7384;
--text-dim: #4a5160;

/* Semantic (trading) */
--up:       #22e0a1;   /* зелёный — рост цены, положительная маржа, ликвидно */
--up-soft:  rgba(34, 224, 161, 0.12);
--up-glow:  rgba(34, 224, 161, 0.35);
--down:     #ff5d73;   /* красный — падение цены, застой */
--down-soft:rgba(255, 93, 115, 0.12);
--accent:   #f4b84a;   /* янтарный — warning/среднее */
--accent-soft: rgba(244, 184, 74, 0.14);
--info:     #6ea8ff;   /* синий — нейтральные метрики */
--info-soft:rgba(110, 168, 255, 0.14);

--grid-line: rgba(255,255,255,0.04);  /* фоновая сетка страницы */
```

**Light theme** — атрибут `data-theme="light"` на `<html>`, переопределяет все переменные. Точные значения в `styles.css`.

### Typography

3 шрифта из Google Fonts:

```
Space Grotesk — заголовки, крупные числа (KPI values, page titles)
  weights: 400, 500, 600, 700
  Применение: class "display" → letter-spacing: -0.02em

Inter — body текст
  weights: 400, 500, 600

JetBrains Mono — все цифры, лейблы, моно-вставки
  weights: 400, 500
  font-feature-settings: "tnum", "zero"  /* табличные цифры */
  Применение: class "mono" и "tnum"
```

### Spacing / Layout

- Page padding: `16px 20px 40px`
- Card border-radius: `10px` (`--radius-lg`), nested `6px` (`--radius`)
- Gap между карточками: `14px`
- Topbar height: `48px`, sticky
- Filter bar height: `~44px` (padding 8px + содержимое)

### Shadows / Effects

- Cards: no shadow, only `1px solid var(--border)`
- Tweaks panel: `0 16px 50px rgba(0,0,0,0.5)`
- Live dot: pulse animation (`opacity 1 ↔ 0.5`, 2s ease-in-out infinite)
- Body background: **grid pattern** — два linear-gradient по 1px с шагом `48px`, цвет `var(--grid-line)`

### Radii
- Cards: 10px
- Buttons, chips, badges: 4–6px
- Rank pills, small: 3px

---

## Screens

### 1. Dashboard (`Dashboard.html` → `pages/index.tsx`)

**Структура сверху вниз:**

1. **Topbar** (sticky, 48px)
   - Лого `[градиентный квадрат 22×22] Авто Аналитика / KZ · V1`
   - Навигация: Дашборд · Марки · Рентабельность · Прогноз
   - **Ticker** (моно, 11.5px): `● LIVE {total}` · `INDEX {value} ▲/▼ {delta}%` · `USD/KZT {value} ▲/▼ {delta}%`
   - Кнопки: `⌕ Поиск [⌘K]`, `⚙` (открывает Tweaks)

2. **FilterBar** (sticky под topbar, bg `--bg-2`)
   - Label `ФИЛЬТРЫ` + chips: Марка, Модель, Город, Год, Цена, Пробег
   - Разделитель, потом **period-group** с кнопками `7Д · 1М · 3М · 6М · 1Г · Все`
   - Справа: `обновлено HH:MM`

3. **KPI Row** — 4 плитки в grid 4-col (mobile: 1-col)
   - **ИНДЕКС ЦЕН AA·IDX** — большое число (34px Space Grotesk), дельта за 30 дней, спарклайн в углу (абс. позиционирование right: 18px, top: 16px)
   - **ТОП МАРЖА** — +25.1% с подписью модели
   - **ЛИКВИДНОСТЬ** — 18 дн (inverted: снижение = зелёное)
   - **USD/KZT** — курс и корреляция с ценой
   - Плитки соединены 1px gaps, общий border-radius 10px на grid-контейнере

4. **Grid 2:1** — Главный график + Лента
   - **Card: Индекс авторынка KZ** — LineChart 300px, overlay USD/KZT пунктиром, аннотации (`ЦБ −0.5%`, `USD пик`)
   - **Card: Лента new listings** — 8 строк, каждая clickable → Listing page. В строке: марка/модель · год · цена моно · дельта ▼/▲ · `{N}м` назад

5. **Grid 2:1** — Heatmap + Funnel
   - **Matrix год×пробег** — 14 строк × 6 колонок, cell aspect-ratio 1.35:1. Hover → inline caption выше таблицы. Toggle: Цена / Объём (gradient: `surface-2 → accent → up` для цены, `surface-2 → info` для объёма)
   - **Воронка ликвидности** — 7 строк (0–3д … 90+), горизонтальные бары от зелёного до красного, count моно, %

6. **Grid 2:1** — Карта + Источники
   - **KZ Map** — SVG силуэт Казахстана (упрощённый path), пины городов (abs-позиционирование по %), размер пина ∝ числу объявлений, glow-shadow. Hover → показывает ср. цену
   - **Источники данных** — 5 площадок с цветной точкой, прогресс-бар, счётчик

7. **Profit Table (full width)** — топ моделей для перепродажи
   - Колонки: #, Модель (brand+model+gen), Год, Покупка, Продажа, **Маржа** (badge up), Дней, Объём, Риск (badge up/accent/down)
   - Header sticky при скролле внутри карточки

8. **Grid 1:1** — Топ марок + Объём торгов

### 2. Model page (`Model.html` → `pages/model/[brand]/[model].tsx`)

- Breadcrumb моно: `Дашборд / Марки / Toyota / Camry`
- **Hero card** — название + badges (поколение, «● Ликвидная»), справа большой ценник (48px Space Grotesk), badge delta, тираж. Ниже `stat-inline` с 7 метриками (медиана, мин/макс, ср. пробег, ср. год, дней на продажу, маржа, прогноз)
- Grid 2:1 — график 90 дней (3 линии: Ср/Медиана/Прогноз пунктиром) + список моделей Toyota с active-строкой
- Heatmap (такой же как на дашборде, но отфильтрован по модели)
- Таблица **активных объявлений** с колонкой «Vs. медиана» (badge up/down)
- Grid 1:1:1 — По городам · Распределение цен (гистограмма 9 bins, медиана подсвечена) · Сравнение конкурентов

### 3. Listing page (`Listing.html` → `pages/listing/[id].tsx`)

- Breadcrumb
- Hero card — тайтл + badges (источник, «● активно», «цена снижена 3 раза»), большой ценник, USD-эквивалент
- Grid 1.3:1
  - **Слева:** Placeholder фото 4:3 + 4 thumbnails + таблица характеристик (12 полей)
  - **Справа:**
    - **Fair price gauge** — горизонтальная цветная шкала (up→accent→down), метка «ЭТА ЦЕНА». Ниже 3 колонки: Дёшево / Честная (подсвечена) / Дорого. Внизу зелёный callout-блок с выводом модели
    - **История цены** — LineChart 140px + 6 строк с датой/ценой/дельтой
    - 2 кнопки: «Открыть на kolesa.kz →» и «★ В избранное» (вторая в up-styled)
- **Похожие объявления** — таблица с колонкой «Vs. это» (+/- к текущей)

---

## Components to Build (в `frontend/components/`)

Существующие `Header.tsx`, `FilterPanel.tsx`, `PriceChart.tsx`, `BoxPlot.tsx` **переписать** под новый стиль.

### `components/layout/Topbar.tsx` (заменяет `Header.tsx`)
- Ticker тянет данные из нового `/analytics/ticker` endpoint (poll каждые 30с через SWR)
- Kbd-хинт на кнопке поиска — `<kbd>⌘K</kbd>`

### `components/layout/FilterBar.tsx` (заменяет `FilterPanel.tsx`)
- Сейчас фильтры в левом сайдбаре — перенести в верхнюю chip-панель
- При клике на chip открывается dropdown/drawer
- Period-group — 6 кнопок, shared state в zustand store

### `components/ui/KPI.tsx`
Props: `label`, `value`, `unit?`, `delta?`, `foot`, `sparkData?`, `sparkColor?`, `inverted?` (для ликвидности: rising = bad)

### `components/ui/Sparkline.tsx`
Чистый SVG: line + optional area fill + dot на последней точке. Width/height пропсы.

### `components/ui/Badge.tsx`
Варианты: `up | down | accent | info | neutral`. Font: mono, 10.5px.

### `components/charts/LineChart.tsx`
**Вариант A (быстрый):** оставить Recharts, применить palette из tokens.
**Вариант B (точнее):** перенести мой ручной SVG LineChart (see `charts.jsx`). Он:
- Поддерживает несколько series с опциями `{color, dashed, area}`
- Показывает Y-tick grid, X-labels каждые n/4 (формат `-{N}д`)
- Аннотации (вертикальная линия + caption)
- Last-point dot
Я рекомендую B — он легче и точно попадает в дизайн.

### `components/charts/Heatmap.tsx`
- Grid `36px repeat(6, 1fr)`, gap 2px
- Cell aspect-ratio `1.35/1`
- Toggle Цена/Объём (internal state)
- Hover-state через React state, caption рендерится ВНЕ таблицы (наверху)
- Gradient строится через `color-mix(in oklch, ...)` — поддерживается в Chrome 111+/Safari 16.4+

### `components/charts/KZMap.tsx`
- SVG viewBox `0 0 100 50`, `preserveAspectRatio="none"`, единственный path силуэта Казахстана (см. `charts.jsx`)
- Города — absolute divs поверх SVG, позиционирование в %
- Данные городов пока захардкожены (14 штук, координаты в `data.js → CITIES`). На бэке нужен endpoint `/analytics/geo` с такой же структурой

### `components/charts/Funnel.tsx`
- 7 фиксированных bucket'ов по дням на продажу
- Grid `90px 1fr 70px 60px`
- Цвета — интерполяция от `--up` к `--down` через `--accent`

### `components/ui/Tweaks.tsx`
Панель настроек. На проде это Settings drawer пользователя. Начальный MVP: dark/light switcher в topbar, хранить в localStorage + `data-theme` на `<html>`.

---

## Interactions & Behavior

### Topbar ticker
- Poll `/analytics/ticker` каждые 30 сек через SWR `refreshInterval: 30000`
- `LIVE` точка pulse-анимация (уже в CSS, `.live-dot`)

### Filter chips
- Клик на chip → открыть dropdown (react-select уже в deps). Multi-select для brand/model/city, range для year/price/mileage
- Active-state chip: `background: var(--info-soft); border-color: var(--info); color: var(--info)`
- Фильтры в zustand store, сохраняются в URL searchParams

### Heatmap
- Hover cell → обновить caption сверху, добавить outline на cell + scale(1.05)
- Toggle Цена/Объём — local useState

### KZ Map
- Hover city pin → увеличить dot (scale 1.25), показать city-label + city-price
- Click → navigate на `/model?city=X` (пока — на дашборд с предзаполненным фильтром)

### Live feed (dashboard)
- Poll `/analytics/recent` каждые 30 сек
- Клик на строку → `/listing/[id]`

### Tables
- Hover row → `background: var(--surface-2)`
- Sticky header со стилем `background: var(--bg-2)`

### Theme switching
- Атрибут `data-theme="light"|"dark"` на `<html>`
- Persist в `localStorage.setItem('theme', ...)`
- На SSR — читать из cookie, чтобы не было FOUC

### Анимации
- Cards — без hover-transform (в отличие от текущего glossy стиля). Только background/border
- Bars, fills — `transition: width 0.4s` при смене данных
- Используйте `framer-motion` только для page transitions и дорогих эффектов; большинство — чистый CSS

---

## State Management (zustand)

```ts
// store/filters.ts
interface FilterState {
  brand_id: number[]
  model_id: number[]
  city: string[]
  year: [number, number] | null
  price: [number, number] | null
  mileage: [number, number] | null
  period: 7 | 30 | 90 | 180 | 365 | 'all'
  source: string[]
  setFilter: <K extends keyof FilterState>(k: K, v: FilterState[K]) => void
  reset: () => void
}

// store/ui.ts
interface UIState {
  theme: 'dark' | 'light'
  density: 'compact' | 'normal'
  commandPaletteOpen: boolean
  setTheme: (t: 'dark' | 'light') => void
}
```

Фильтры синхронить с URL через `next/router` для shareable links.

---

## API Endpoints Required

Существующие (`lib/api.ts`) покрывают ~60% нужд. Нужно добавить в `backend/app/api/v1/endpoints/analytics.py`:

| Endpoint | Назначение | Возвращает |
|---|---|---|
| `GET /analytics/ticker` | Topbar live ticker | `{total_listings, index_value, index_delta_30d, usd_kzt, usd_delta}` |
| `GET /analytics/price-index?period_days=` | Главный график + KPI индекса | `[{day: number, value: number}]` (база 100 = первый день периода) |
| `GET /analytics/liquidity?...filters` | Воронка | `[{bucket: '0-3', '4-7', ..., count: number}]` |
| `GET /analytics/heatmap?brand_id=&model_id=` | Матрица год×пробег | `[{year, mileage_bucket, avg_price_kzt, volume}]` |
| `GET /analytics/geo` | Карта | `[{city, lat, lon, listings, avg_price_kzt}]` — координаты в `database/seeds` |
| `GET /analytics/valuation?listing_id=` | Fair-price оценщик | `{fair_low, fair_high, current, median, verdict: 'cheap'|'fair'|'expensive', margin_if_resell}` |
| `GET /analytics/recent?limit=8` | Live feed | `[{id, brand, model, year, price, mileage, city, source, created_minutes_ago, price_delta}]` |
| `GET /analytics/profitability` | уже есть, нужно расширить | добавить `days_to_sell`, `volume`, `risk: 'low'|'medium'|'high'` |
| `GET /analytics/usd-kzt?period_days=` | Курс | `[{day, value}]` — cron job из Нацбанка РК |

Индекс цен — взвешенное среднее `price_kzt` по всем активным объявлениям, нормализованное на 100 относительно первого дня окна. Пересчитывать ежедневно и кэшировать в материализованной view.

---

## Files in this bundle

```
design_handoff_trading_terminal/
├── README.md          ← этот файл
├── Dashboard.html     ← прототип главной
├── Model.html         ← прототип страницы модели (Toyota Camry)
├── Listing.html       ← прототип страницы объявления
├── styles.css         ← ВСЕ дизайн-токены и компонентные стили. Большая часть переносится 1:1 в globals.css
├── data.js            ← моки (use для понимания структуры данных)
├── components.jsx     ← Topbar, FilterBar, KPI, Sparkline, Tweaks, fmt helpers
└── charts.jsx         ← LineChart, Heatmap, KZMap, Funnel
```

Открой любой `.html` локально в браузере — он полностью рабочий (данные mock).

---

## Migration Steps (рекомендуемый порядок)

1. **Токены** — заменить `styles/globals.css` на содержимое из `styles.css` (убрать старый `Mobile-First, Premium Dark Theme` блок). Добавить шрифты через `next/font` или `<link>` в `_document.tsx`
2. **Layout chrome** — новый `Topbar.tsx` + `FilterBar.tsx`, удалить старый Header и левый сайдбар фильтров
3. **UI primitives** — `KPI.tsx`, `Sparkline.tsx`, `Badge.tsx`. Используйте в существующем `pages/index.tsx`, чтобы сразу увидеть эффект
4. **Charts** — перенести `LineChart`, `Heatmap`, `KZMap`, `Funnel` из `charts.jsx` в TSX
5. **Dashboard page** — переписать `pages/index.tsx` под новую структуру (KPI row → grid 2:1 → heatmap/funnel → map/sources → profit table)
6. **Новые страницы** — `pages/model/[brand]/[model].tsx` и `pages/listing/[id].tsx`
7. **API** — добавить endpoints (см. таблицу выше), использовать SWR, сохранить совместимость с текущими
8. **Theme switcher** — persist в localStorage, SSR через cookies

---

## Copy (все тексты на русском, строго как в прототипах)

Ключевые фразы, которые должны быть дословно:
- KPI labels (caps, letter-spacing 0.08em): `ИНДЕКС ЦЕН AA·IDX`, `ТОП МАРЖА`, `ЛИКВИДНОСТЬ`, `USD/KZT`
- `база 100 = 01 янв 2026`
- `медиана времени продажи`
- `корреляция с ценой: +0.78 (за 90 дн.)`
- Topbar nav: `Дашборд · Марки · Рентабельность · Прогноз`
- Fair price gauge: `дёшево · честная цена · дорого`
- Verdicts в стиле: `Цена на 4.5% ниже медианы для Camry 2019 с пробегом 70–80 тыс км. При покупке и быстрой перепродаже за 14 дней — потенциальная маржа +6.1%.`

---

## Notes для Claude Code

- Проект — Next.js 14 (pages router, не app). Следуй существующим паттернам в `pages/`, `components/`, `lib/`
- TypeScript strict mode — типизируй всё, включая API responses. Создай `types/analytics.ts`
- Старые компоненты (`Header.tsx`, `FilterPanel.tsx`, `index.module.css`, `Header.module.css`) — после миграции **удалить**
- Не тяни лишние зависимости: всё рисуется на CSS + SVG, Recharts можно оставить для LineChart или заменить на ручной SVG из `charts.jsx`
- `framer-motion` — только для page transitions между страницами, не для мелких hover-эффектов
- Mobile breakpoints: `1024px` (сайдбар-грид → 1-col), `640px` (topbar упрощается, ticker скрывается)
- Accessibility: все интерактивные элементы должны быть `<button>` или `<a>`, не `<div onClick>`
- При реализации SVG KZ-карты лучше взять реальный GeoJSON Казахстана и отрендерить через `d3-geo` — мой path это упрощённый силуэт для прототипа
- `color-mix(in oklch, ...)` — проверь caniuse; для совместимости с старыми браузерами сделай fallback через обычные hex
