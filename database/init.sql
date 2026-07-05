-- =============================================
-- ИНИЦИАЛИЗАЦИЯ БАЗЫ ДАННЫХ
-- Авторынок Аналитика Казахстана
-- =============================================

-- Дополнительная база для Airflow
CREATE DATABASE airflow_db;

-- Подключаемся к основной БД
\c automarket_db;

-- Расширения
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm"; -- для быстрого поиска по тексту

-- =============================================
-- СПРАВОЧНИКИ
-- =============================================

CREATE TABLE IF NOT EXISTS sources (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(50) NOT NULL UNIQUE,   -- 'kolesa', 'olx', etc.
    display_name VARCHAR(100) NOT NULL,
    base_url    TEXT NOT NULL,
    is_active   BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS brands (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL UNIQUE,  -- 'Toyota', 'BMW'
    slug        VARCHAR(100) NOT NULL UNIQUE,
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS models (
    id          SERIAL PRIMARY KEY,
    brand_id    INT NOT NULL REFERENCES brands(id) ON DELETE CASCADE,
    name        VARCHAR(100) NOT NULL,         -- 'Camry', 'X5'
    slug        VARCHAR(100) NOT NULL,
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (brand_id, slug)
);

CREATE TABLE IF NOT EXISTS body_types (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(50) NOT NULL UNIQUE    -- 'Седан', 'Кросс', 'Хэтч'
);

CREATE TABLE IF NOT EXISTS fuel_types (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(50) NOT NULL UNIQUE    -- 'Бензин', 'Дизель', 'Гибрид'
);

CREATE TABLE IF NOT EXISTS transmission_types (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(50) NOT NULL UNIQUE    -- 'Автомат', 'Механика', 'Вариатор'
);

CREATE TABLE IF NOT EXISTS drive_types (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(50) NOT NULL UNIQUE    -- 'Полный', 'Передний', 'Задний'
);

-- =============================================
-- ОБЪЯВЛЕНИЯ
-- =============================================

CREATE TABLE IF NOT EXISTS listings (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id           INT NOT NULL REFERENCES sources(id),
    external_id         VARCHAR(255) NOT NULL,    -- ID объявления на сайте-источнике
    brand_id            INT REFERENCES brands(id),
    model_id            INT REFERENCES models(id),
    title               TEXT,
    year                SMALLINT,
    mileage_km          INT,
    engine_volume_cc    INT,                       -- объем в куб.см
    engine_power_hp     SMALLINT,
    body_type_id        INT REFERENCES body_types(id),
    fuel_type_id        INT REFERENCES fuel_types(id),
    transmission_id     INT REFERENCES transmission_types(id),
    drive_type_id       INT REFERENCES drive_types(id),
    color               VARCHAR(50),
    city                VARCHAR(100),
    region              VARCHAR(100),
    condition           VARCHAR(20),               -- 'used', 'new'
    listing_url         TEXT,
    is_active           BOOLEAN DEFAULT TRUE,      -- FALSE = объявление снято (продано)
    first_seen_at       TIMESTAMPTZ DEFAULT NOW(),
    last_seen_at        TIMESTAMPTZ DEFAULT NOW(),
    closed_at           TIMESTAMPTZ,               -- когда объявление исчезло (продано)
    last_checked_at     TIMESTAMPTZ DEFAULT NULL,  -- liveness: когда последний раз пинговали URL
    -- Quality flags (заполняются parsers/kolesa/flags.py из ?need-repair=1 / ?auto-custom=1)
    is_emergency        BOOLEAN DEFAULT NULL,      -- TRUE = аварийная или не на ходу
    is_customs_cleared  BOOLEAN DEFAULT NULL,      -- FALSE = не растаможен
    flags_updated_at    TIMESTAMPTZ DEFAULT NULL,  -- когда последний раз обновляли флаги
    -- Availability (заполняется kolesa parser из top-level field availability)
    is_in_stock         BOOLEAN DEFAULT NULL,      -- TRUE = "В наличии", FALSE = "На заказ"
    UNIQUE (source_id, external_id)
);

CREATE INDEX idx_listings_brand ON listings(brand_id);
CREATE INDEX idx_listings_model ON listings(model_id);
CREATE INDEX idx_listings_year ON listings(year);
CREATE INDEX idx_listings_city ON listings(city);
CREATE INDEX idx_listings_is_active ON listings(is_active);
CREATE INDEX idx_listings_first_seen ON listings(first_seen_at);
CREATE INDEX IF NOT EXISTS idx_listings_liveness ON listings (source_id, last_checked_at NULLS FIRST) WHERE is_active;
-- Partial indexes — только для "плохих" listings (TRUE / FALSE) — отбрасываем NULL/нормальные
CREATE INDEX IF NOT EXISTS idx_listings_is_emergency ON listings(is_emergency) WHERE is_emergency = TRUE;
CREATE INDEX IF NOT EXISTS idx_listings_is_customs_cleared ON listings(is_customs_cleared) WHERE is_customs_cleared = FALSE;
CREATE INDEX IF NOT EXISTS idx_listings_is_in_stock ON listings(is_in_stock) WHERE is_in_stock = FALSE;

-- =============================================
-- FX HISTORY (USD/KZT и др. валюты от NBK)
-- =============================================
-- Заполняется parsers/common/fetch_fx.py daily из National Bank of Kazakhstan API.
-- Используется /forecast endpoint для USD-нормализованной regression
-- (отделяет тренд цены от тренда KZT).
CREATE TABLE IF NOT EXISTS fx_history (
    rate_date    DATE PRIMARY KEY,
    usd_kzt      NUMERIC(10, 4) NOT NULL,
    eur_kzt      NUMERIC(10, 4),
    rub_kzt      NUMERIC(10, 4),
    cny_kzt      NUMERIC(10, 4),
    recorded_at  TIMESTAMPTZ DEFAULT NOW()
);

-- =============================================
-- ИСТОРИЯ ЦЕН
-- =============================================

CREATE TABLE IF NOT EXISTS price_history (
    id          BIGSERIAL PRIMARY KEY,
    listing_id  UUID NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    price_kzt   BIGINT NOT NULL,                  -- цена в тенге
    price_usd   INT,                              -- цена в долларах (если указана)
    recorded_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_price_history_listing ON price_history(listing_id);
CREATE INDEX idx_price_history_recorded_at ON price_history(recorded_at);

-- =============================================
-- ХОЛОДНЫЙ АРХИВ
-- =============================================
-- Давно-неактивные объявления (is_active=FALSE, last_seen_at старше
-- ARCHIVE_THRESHOLD_DAYS, default 30) переносятся сюда из listings
-- скриптом parsers/common/archive_old.py (workflow archive.yml),
-- чтобы горячая таблица не упиралась в лимит Neon free tier (~512 MB).
-- Зеркала listings/price_history + archived_at. Без FK на горячие
-- таблицы (архив холодный, id остаются обычными числами) и с
-- минимумом индексов (индексы едят хранилище, ради которого архив
-- и заведён). Полные комментарии к дизайну —
-- database/migrations/002_listings_archive.sql.

CREATE TABLE IF NOT EXISTS listings_archive (
    id                  UUID PRIMARY KEY,          -- исходный id из listings
    source_id           INT NOT NULL,
    external_id         VARCHAR(255) NOT NULL,
    brand_id            INT,
    model_id            INT,
    title               TEXT,
    year                SMALLINT,
    mileage_km          INT,
    engine_volume_cc    INT,
    engine_power_hp     SMALLINT,
    body_type_id        INT,
    fuel_type_id        INT,
    transmission_id     INT,
    drive_type_id       INT,
    color               VARCHAR(50),
    city                VARCHAR(100),
    region              VARCHAR(100),
    condition           VARCHAR(20),
    listing_url         TEXT,
    is_active           BOOLEAN,
    first_seen_at       TIMESTAMPTZ,
    last_seen_at        TIMESTAMPTZ,
    closed_at           TIMESTAMPTZ,
    last_checked_at     TIMESTAMPTZ,
    is_emergency        BOOLEAN,
    is_customs_cleared  BOOLEAN,
    flags_updated_at    TIMESTAMPTZ,
    is_in_stock         BOOLEAN,
    archived_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_listings_archive_archived_at
    ON listings_archive (archived_at);

CREATE TABLE IF NOT EXISTS price_history_archive (
    id          BIGINT PRIMARY KEY,     -- исходный id из price_history
    listing_id  UUID NOT NULL,          -- без FK: listings_archive холодный
    price_kzt   BIGINT NOT NULL,
    price_usd   INT,
    recorded_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_price_history_archive_listing
    ON price_history_archive (listing_id);

-- =============================================
-- МОНИТОРИНГ ПАРСЕРОВ (миграция 003)
-- =============================================
-- История метрик прогонов для детекции «тихой деградации» (exit 0, но
-- saved/new упали ниже порога PARSER_ALERT_DROP_PCT). Пишется и читается
-- parsers/common/run_stats.py. Гранулярность (source_id, shard_index,
-- shard_count): шардовые прогоны kolesa сравниваются только между собой.
-- status: 'ok' — baseline для следующих сравнений; 'degraded' — упавший
-- прогон (записывается, но baseline не понижает). Полные комментарии —
-- database/migrations/003_parser_runs.sql.

CREATE TABLE IF NOT EXISTS parser_runs (
    id           BIGSERIAL PRIMARY KEY,
    source_id    INT NOT NULL REFERENCES sources(id),
    shard_index  INT NOT NULL DEFAULT 0,
    shard_count  INT NOT NULL DEFAULT 1,
    saved        INT NOT NULL,
    new_count    INT NOT NULL,
    active_after INT,
    status       TEXT NOT NULL DEFAULT 'ok' CHECK (status IN ('ok', 'degraded')),
    finished_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_parser_runs_baseline
    ON parser_runs (source_id, shard_index, shard_count, finished_at DESC);

-- =============================================
-- КУРСОР DISCOVERY-ПАРСЕРА (миграция 004)
-- =============================================
-- Резюмируемый курсор фидов kolesa (t-0017). Пишется/читается
-- parsers/kolesa/early_stop.py ТОЛЬКО при KOLESA_EARLY_STOP=1 (флаг по
-- умолчанию выключен — см. предупреждение в early_stop.py). feed_key = slug
-- фида ("almaty", "toyota/camry", ...); cycle_id = UTC-дата "YYYY-MM-DD"
-- (или KOLESA_CYCLE_ID); last_page = последняя обработанная страница.
-- Полные комментарии — database/migrations/004_parse_cursor.sql.

CREATE TABLE IF NOT EXISTS parse_cursor (
    source_id  INT NOT NULL REFERENCES sources(id),
    feed_key   TEXT NOT NULL,
    last_page  INT NOT NULL DEFAULT 0,
    cycle_id   TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_id, feed_key)
);

-- =============================================
-- ПОЛЬЗОВАТЕЛИ И ПОДПИСКИ
-- =============================================

CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email           VARCHAR(255) NOT NULL UNIQUE,
    hashed_password TEXT NOT NULL,
    full_name       VARCHAR(200),
    phone           VARCHAR(20),
    is_active       BOOLEAN DEFAULT TRUE,
    is_verified     BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS subscription_plans (
    id              SERIAL PRIMARY KEY,
    name            VARCHAR(50) NOT NULL,         -- 'free', 'pro', 'business'
    display_name    VARCHAR(100) NOT NULL,
    price_kzt       INT DEFAULT 0,
    duration_days   INT DEFAULT 0,                -- 0 = бессрочный (free)
    features        JSONB DEFAULT '{}'::jsonb,
    is_active       BOOLEAN DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS user_subscriptions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    plan_id         INT NOT NULL REFERENCES subscription_plans(id),
    started_at      TIMESTAMPTZ DEFAULT NOW(),
    expires_at      TIMESTAMPTZ,
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_user_subs_user ON user_subscriptions(user_id);
CREATE INDEX idx_user_subs_active ON user_subscriptions(is_active, expires_at);

-- =============================================
-- SEED: Первоначальные данные
-- =============================================

INSERT INTO sources (name, display_name, base_url) VALUES
    ('kolesa',     'Колеса.кз',       'https://kolesa.kz'),
    ('avtorynok',  'Авторынок.кз',    'https://avtorynok.kz'),
    ('mycar',      'MyCar.kz',        'https://mycar.kz'),
    ('newauto',    'NewAuto.kz',      'https://newauto.kz'),
    ('olx',        'OLX.kz',          'https://www.olx.kz')
ON CONFLICT DO NOTHING;

INSERT INTO subscription_plans (name, display_name, price_kzt, duration_days, features) VALUES
    ('free', 'Бесплатный', 0, 0, '{"basic_charts": true, "filters": true, "history_days": 30}'),
    ('pro', 'Профи', 4990, 30,  '{"basic_charts": true, "filters": true, "history_days": 365, "profitability": true, "median_days": true, "export": true}'),
    ('business', 'Бизнес', 14990, 30, '{"basic_charts": true, "filters": true, "history_days": 730, "profitability": true, "median_days": true, "export": true, "api_access": true, "bulk_analysis": true}')
ON CONFLICT DO NOTHING;

INSERT INTO body_types (name) VALUES ('Седан'), ('Кроссовер'), ('Хэтчбек'), ('Универсал'), ('Минивэн'), ('Пикап'), ('Купе'), ('Кабриолет'), ('Фургон') ON CONFLICT DO NOTHING;
INSERT INTO fuel_types (name) VALUES ('Бензин'), ('Дизель'), ('Гибрид'), ('Электро'), ('Газ/Бензин') ON CONFLICT DO NOTHING;
INSERT INTO transmission_types (name) VALUES ('Автомат'), ('Механика'), ('Вариатор'), ('Робот') ON CONFLICT DO NOTHING;
INSERT INTO drive_types (name) VALUES ('Передний'), ('Задний'), ('Полный') ON CONFLICT DO NOTHING;
