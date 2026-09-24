-- neon_compact.sql — вернуть Neon файловое место после крупной подрезки.
--
--   psql "<DIRECT (не -pooler) DATABASE_URL>" -v ON_ERROR_STOP=1 -f neon_compact.sql
--
-- Зачем: лимит Neon (512 MB) считает РАЗМЕР ФАЙЛОВ. После DELETE + VACUUM
-- место внутри heap переиспользуется, но файлы не уменьшаются, а индексы с
-- растущим ключом (price_history.id/recorded_at, kolesa external_id) растут
-- правым краем и требуют НОВЫЕ страницы → «could not extend file» на каждой
-- вставке цены, хотя таблицы наполовину пусты (так было 2026-09-25 после
-- подрезки 148k объявлений: listings писались, price_history — нет).
--
-- Как: REINDEX пересобирает индекс без мёртвых записей (−25…40% после
-- подрезки). Но ему самому нужно место под новую копию, а у потолка его нет —
-- поэтому сначала дропаем 4 вторичных индекса listings (~55 MB файлов),
-- пересобираем остальные по возрастанию размера и создаём дропнутые заново.
-- Всё CONCURRENTLY: чтение/запись парсеров и бэка не блокируются.
-- На время работы (минуты) фильтры по city/brand/year/is_active идут seq scan.
--
-- Если упало посередине: SELECT indexrelid::regclass FROM pg_index WHERE NOT indisvalid;
-- — DROP INDEX CONCURRENTLY невалидных (*_ccnew) и перезапустить скрипт
-- (все шаги идемпотентны).

\timing on
SELECT pg_size_pretty(sum(pg_database_size(datname))) AS cluster_before FROM pg_database;

-- 1. Освобождаем файлы под пересборку
DROP INDEX CONCURRENTLY IF EXISTS idx_listings_city;
DROP INDEX CONCURRENTLY IF EXISTS idx_listings_brand;
DROP INDEX CONCURRENTLY IF EXISTS idx_listings_year;
DROP INDEX CONCURRENTLY IF EXISTS idx_listings_is_active;

-- 2. Пересборка раздутых индексов (по возрастанию размера)
REINDEX INDEX CONCURRENTLY idx_listings_model;
REINDEX INDEX CONCURRENTLY price_history_pkey;
REINDEX INDEX CONCURRENTLY idx_price_history_listing;
REINDEX INDEX CONCURRENTLY idx_price_history_recorded_at;
REINDEX INDEX CONCURRENTLY listings_pkey;
REINDEX INDEX CONCURRENTLY listings_source_id_external_id_key;

-- 3. Возвращаем вторичные индексы (определения = database/init_neon.sql)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_listings_is_active ON public.listings USING btree (is_active);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_listings_year ON public.listings USING btree (year);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_listings_brand ON public.listings USING btree (brand_id);
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_listings_city ON public.listings USING btree (city);

SELECT indexrelid::regclass AS invalid_index FROM pg_index WHERE NOT indisvalid;
SELECT pg_size_pretty(sum(pg_database_size(datname))) AS cluster_after FROM pg_database;
