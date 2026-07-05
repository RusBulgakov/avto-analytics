-- 003_parser_runs.sql
-- Smart-thresholds (t-0009): история метрик прогонов парсеров для детекции
-- «тихой деградации» — прогон с exit 0, но saved/new в разы ниже обычного
-- (сломанные селекторы или частичный бан; так молча ломался OLX до 2026-05-02).
-- Пишет и читает parsers/common/run_stats.py после каждого прогона.
-- Запустить вручную в Neon SQL Editor. Idempotent.
--
-- Дизайн-решения:
--   * Гранулярность = (source_id, shard_index, shard_count): kolesa гоняется
--     3 шардами, сравнивать шард с полным прогоном бессмысленно — baseline
--     ищется только среди прогонов ТОЙ ЖЕ шардовой конфигурации. При смене
--     числа шардов история естественно начинается заново.
--   * status: 'ok' — нормальный прогон (становится baseline'ом для следующих
--     сравнений), 'degraded' — метрики упали ниже порога PARSER_ALERT_DROP_PCT
--     (такой прогон записывается, но baseline НЕ понижает).
--   * active_after — nullable задел под счётчик активных объявлений после
--     прогона (сейчас парсеры его не заполняют).
--   * Таблица крошечная (~5 строк/день на источник) — индекса под выборку
--     baseline достаточно.

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

-- Выборка baseline: последний status='ok' прогон той же гранулярности
CREATE INDEX IF NOT EXISTS idx_parser_runs_baseline
    ON parser_runs (source_id, shard_index, shard_count, finished_at DESC);
