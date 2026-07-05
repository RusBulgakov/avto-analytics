-- 002_listings_archive.sql
-- Холодный архив: давно-неактивные объявления переносятся из горячей
-- таблицы listings (вместе с их price_history) скриптом
-- parsers/common/archive_old.py, чтобы горячая таблица не упиралась
-- в лимит хранилища Neon free tier (~512 MB).
-- Запустить вручную в Neon SQL Editor. Idempotent.
--
-- Дизайн-решения:
--   * Явный список колонок (не LIKE listings): схема архива зафиксирована
--     на момент миграции и не зависит от порядка применения будущих
--     ALTER TABLE listings. Скрипт архивации тоже использует явный список —
--     при добавлении колонки в listings нужно осознанно добавить её сюда,
--     в archive_old.py И в database/init.sql (копия схемы архива) —
--     иначе она просто не переносится, ничего не падает.
--   * UNIQUE (source_id, external_id) с listings сознательно НЕ перенесён:
--     одно объявление может быть архивировано, переопубликовано с новым UUID
--     и архивировано снова — в архиве это две легитимные строки.
--   * БЕЗ foreign keys на горячие таблицы (sources/brands/models/...) —
--     архив холодный, ссылочная целостность не enforce'ится, id остаются
--     обычными числами. price_history_archive.listing_id тоже без FK.
--   * Индексы минимальные: PK (id) нужен для идемпотентного ON CONFLICT
--     DO NOTHING в скрипте; archived_at — для будущей чистки/аналитики
--     архива; price_history_archive(listing_id) — чтобы историю цен
--     архивного объявления можно было достать без seq scan.
--     Больше индексов не добавляем — они едят то самое хранилище,
--     ради экономии которого архив и заведён.

CREATE TABLE IF NOT EXISTS listings_archive (
    -- Зеркало listings (см. database/init.sql), id сохраняется исходный
    id                  UUID PRIMARY KEY,
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
    -- Когда строка попала в архив
    archived_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_listings_archive_archived_at
    ON listings_archive (archived_at);

CREATE TABLE IF NOT EXISTS price_history_archive (
    -- Зеркало price_history, id сохраняется исходный (не BIGSERIAL —
    -- новые id здесь никогда не генерируются)
    id          BIGINT PRIMARY KEY,
    listing_id  UUID NOT NULL,          -- без FK: listings_archive холодный
    price_kzt   BIGINT NOT NULL,
    price_usd   INT,
    recorded_at TIMESTAMPTZ,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_price_history_archive_listing
    ON price_history_archive (listing_id);
