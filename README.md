# 🚗 Авто Аналитика KZ

> Платформа для мониторинга и анализа авторынка Казахстана — агрегирует объявления с 5 площадок, строит аналитику по ценам, маркам и городам.

---

## 🔍 Что это

**Авто Аналитика KZ** — это self-hosted система, которая:

- **Парсит** объявления с Kolesa.kz, OLX.kz, mycar.kz, avtoronok.kz, newauto.kz ежедневно по расписанию
- **Хранит** историю цен для анализа трендов и расчёта рентабельности перепродажи
- **Визуализирует** данные через дашборд с фильтрами по марке, модели, городу, году и источнику

---

## 🏗️ Архитектура

```
┌─────────────────────────────────────────────────────┐
│                   Airflow (03:00)                   │
│  refresh_proxy → parse_* (parallel) → deactivate   │
└────────────┬────────────────────────────────────────┘
             │ asyncpg
     ┌───────▼────────┐
     │   PostgreSQL   │  listings, price_history, brands, models
     └───────┬────────┘
             │
     ┌───────▼────────┐        ┌──────────────┐
     │  FastAPI API   │◄───────│  Next.js 14  │
     │  /api/v1/      │        │  Dashboard   │
     └────────────────┘        └──────────────┘
             ▲
         Nginx (80/443)
```

| Компонент | Технологии |
|-----------|-----------|
| **Frontend** | Next.js 14, TypeScript, SWR, Framer Motion |
| **Backend** | FastAPI, asyncpg, Uvicorn |
| **Парсеры** | Python, curl_cffi (Chrome impersonation), BeautifulSoup, asyncio |
| **Планировщик** | Apache Airflow 2.x |
| **База данных** | PostgreSQL 15 |
| **Инфраструктура** | Docker Compose, Nginx |

---

## 📊 Источники данных

| Площадка | Метод | Объявлений/запуск |
|----------|-------|------------------|
| [Kolesa.kz](https://kolesa.kz) | Embedded JSON из HTML (15 городов) | ~30 000 |
| [mycar.kz](https://mycar.kz) | REST JSON API | ~2 400 |
| [newauto.kz](https://newauto.kz) | HTML парсинг | ~4 600 |
| [avtorynok.kz](https://avtorynok.kz) | HTML парсинг | ~480 |
| [OLX.kz](https://olx.kz) | HTML парсинг | ~500 |

---

## 🚀 Быстрый старт

### 1. Требования

- Docker & Docker Compose
- Git

### 2. Клонировать и настроить

```bash
git clone https://gitlab.com/bulgakov.ruslan.kaznu/avto-analytics.git
cd avto-analytics
cp .env.example .env
# Отредактируйте .env — укажите пароли БД, JWT secret и т.д.
```

### 3. Запустить

```bash
docker compose up -d
```

Сервисы поднимутся автоматически:

| Сервис | URL |
|--------|-----|
| Дашборд | http://localhost |
| API | http://localhost/api/v1 |
| Airflow UI | http://localhost:8080 |

### 4. Первый запуск парсеров

```bash
# Вручную через Airflow UI или CLI:
docker compose exec airflow-webserver airflow dags trigger daily_car_parsers
```

---

## ⚙️ Конфигурация (.env)

```env
# База данных
POSTGRES_USER=automarket
POSTGRES_PASSWORD=your_secure_password
POSTGRES_DB=automarket

# Backend
SECRET_KEY=your_jwt_secret_here
DATABASE_URL=postgresql+asyncpg://automarket:password@postgres:5432/automarket

# Airflow
AIRFLOW__CORE__FERNET_KEY=your_fernet_key
_PIP_ADDITIONAL_REQUIREMENTS=curl_cffi==0.6.0b9 beautifulsoup4 lxml asyncpg tenacity python-dotenv
```

---

## 📁 Структура проекта

```
.
├── airflow/
│   └── dags/
│       └── daily_parsers_dag.py   # DAG: ежедневный запуск парсеров
├── backend/
│   └── app/
│       ├── api/v1/endpoints/      # analytics, auth
│       └── core/                  # config, database, security
├── database/
│   └── init.sql                   # Схема БД
├── frontend/
│   ├── components/                # FilterPanel, PriceChart, Header
│   ├── pages/                     # Dashboard, Login
│   └── lib/api.ts                 # API-клиент
├── infrastructure/
│   └── nginx/nginx.conf
├── parsers/
│   ├── common/                    # http_client, db, proxy_manager
│   ├── kolesa/parser.py           # JSON-extraction (15 городов)
│   ├── mycar/parser.py            # REST API
│   ├── newauto/parser.py
│   ├── avtorynok/parser.py
│   └── olx/parser.py
└── docker-compose.yml
```

---

## 🔌 API

### Аналитика

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/api/v1/analytics/summary` | Общая статистика (активные объявления, бренды, средняя цена, источники) |
| `GET` | `/api/v1/analytics/price-history` | История средних цен по периодам |
| `GET` | `/api/v1/analytics/market-overview` | Топ марок и распределение по городам |
| `GET` | `/api/v1/analytics/profitability` | Рентабельность перепродажи по моделям |

Все эндпоинты поддерживают фильтры: `brand_id[]`, `model_id[]`, `city[]`, `source[]`, `year[]`

### Фильтры

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/api/v1/filters/brands` | Список марок |
| `GET` | `/api/v1/filters/models?brand_id=1` | Модели по марке |
| `GET` | `/api/v1/filters/cities` | Города |

---

## 🗄️ Схема БД

```sql
brands (id, name, slug)
models (id, brand_id, name, slug)
sources (id, name)
listings (id, source_id, brand_id, model_id, external_id, title,
          year, mileage_km, city, listing_url, condition,
          is_active, first_seen_at, last_seen_at, closed_at)
price_history (id, listing_id, price_kzt, recorded_at)
```

---

## 🤝 Разработка

```bash
# Бэкенд (hot reload)
docker compose up backend --build

# Фронтенд
cd frontend && npm install && npm run dev

# Запуск одного парсера вручную
docker compose exec airflow-webserver bash -c \
  "cd /opt/airflow/project && python -m parsers.kolesa.parser"
```

---

## 📄 Лицензия

MIT
