-- 001_liveness_last_checked_at.sql
-- Liveness sweep: курсор "когда объявление в последний раз пинговали по URL".
-- Отличается от last_seen_at (когда последний раз ВИДЕЛИ живым).
-- Запустить вручную в Neon SQL Editor. Idempotent.

ALTER TABLE listings
    ADD COLUMN IF NOT EXISTS last_checked_at TIMESTAMPTZ DEFAULT NULL;

-- Выбирать "дольше всех не проверенные среди активных" дёшево.
-- NULLS FIRST → новые (ещё не проверенные) идут в голову очереди.
CREATE INDEX IF NOT EXISTS idx_listings_liveness
    ON listings (source_id, last_checked_at NULLS FIRST)
    WHERE is_active;
