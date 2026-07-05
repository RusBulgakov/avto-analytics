-- 004_parse_cursor.sql
-- Резюмируемый курсор discovery-парсера kolesa (t-0017, спека §5.1/§5.3).
-- Пишет и читает parsers/kolesa/early_stop.py — НО только при
-- KOLESA_EARLY_STOP=1 (флаг по умолчанию ВЫКЛЮЧЕН: early-stop без рабочего
-- liveness-sweep опасен, см. комментарий в early_stop.py и backlog t-0016).
-- Применять вручную в Neon SQL Editor. Idempotent.
--
-- Дизайн-решения:
--   * feed_key = slug фида как в ALL_FEEDS parser.py ("almaty", "toyota",
--     "toyota/camry", "toyota/almaty", ...). PK (source_id, feed_key) —
--     одна строка на фид, upsert перезаписывает.
--   * cycle_id TEXT — идентификатор цикла discovery. По умолчанию UTC-дата
--     "YYYY-MM-DD" (один цикл в сутки), переопределяется KOLESA_CYCLE_ID.
--     Курсор читается только если cycle_id совпадает с текущим: рестарт
--     джобы в тот же день продолжает с last_page+1, новый день — с 1-й
--     страницы. TEXT (не INT) — чтобы дата или произвольный run-id
--     помещались без конвертации.
--   * last_page — последняя ОБРАБОТАННАЯ страница (записана после сохранения
--     батча объявлений страницы), продолжение с last_page + 1.
--   * Таблица крошечная: ~297 фидов kolesa = максимум ~300 строк.

CREATE TABLE IF NOT EXISTS parse_cursor (
    source_id  INT NOT NULL REFERENCES sources(id),
    feed_key   TEXT NOT NULL,
    last_page  INT NOT NULL DEFAULT 0,
    cycle_id   TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (source_id, feed_key)
);
