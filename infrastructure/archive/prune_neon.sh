#!/usr/bin/env bash
# Подрезка hot window в Neon: удаляет из Neon объявления, не встречавшиеся >= HOT_DAYS дней,
# ТОЛЬКО если они подтверждённо синхронизированы в локальный архив kolesa_archive
# (id есть локально, локальный last_seen_at не старше неонового, локальных строк
# price_history не меньше, чем в Neon). price_history в Neon удаляется каскадом (FK).
#
# Использование:
#   DRY_RUN=1 ./prune_neon.sh     # (по умолчанию) только посчитать и показать
#   DRY_RUN=0 ./prune_neon.sh     # реально удалить + VACUUM
#   HOT_DAYS=90                   # окно хранения в Neon (дней), по умолчанию 90
#
# Перед подрезкой всегда прогоняется полная синхронизация (mode=full).

set -euo pipefail

HOT_DAYS="${HOT_DAYS:-90}"
DRY_RUN="${DRY_RUN:-1}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOCAL_DB="${LOCAL_DB:-kolesa_archive}"
LOG_DIR="$HOME/Library/Logs/kolesa-archive"
TMP_DIR="$(mktemp -d /tmp/kolesa-prune.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

mkdir -p "$LOG_DIR"
exec >> "$LOG_DIR/prune.log" 2>&1

echo "=== prune start $(date '+%F %T') HOT_DAYS=$HOT_DAYS DRY_RUN=$DRY_RUN ==="

# 1. Свежая полная синхронизация — иначе не режем.
"$SCRIPT_DIR/sync_neon_to_local.sh" full

NEON_URL="$(grep -m1 '^DATABASE_URL=' "$REPO_DIR/.env" | cut -d= -f2- | tr -d '"' | tr -d "'")"
npsql() { psql "$NEON_URL" -v ON_ERROR_STOP=1 "$@"; }
lpsql() { psql -h localhost -d "$LOCAL_DB" -v ON_ERROR_STOP=1 "$@"; }

# 2. Кандидаты из Neon: id + last_seen_at + число строк price_history.
CAND="$TMP_DIR/candidates.csv"
npsql -q -c "\\copy (
  SELECT l.id, l.last_seen_at, COALESCE(p.n, 0) AS ph_n
  FROM listings l
  LEFT JOIN (SELECT listing_id, count(*) AS n FROM price_history GROUP BY 1) p ON p.listing_id = l.id
  WHERE l.last_seen_at < now() - interval '$HOT_DAYS days'
) TO '$CAND' WITH (FORMAT csv)"
echo "candidates from neon: $(wc -l < "$CAND" | tr -d ' ')"

# 3. Локальная сверка: одобряем только полностью совпавшие или более полные локально.
APPROVED="$TMP_DIR/approved.csv"
lpsql -q <<SQL
CREATE TEMP TABLE cand (id uuid PRIMARY KEY, last_seen_at timestamptz, ph_n integer);
\\copy cand FROM '$CAND' WITH (FORMAT csv)
CREATE TEMP TABLE local_ph AS SELECT listing_id, count(*) AS n FROM price_history GROUP BY 1;
CREATE INDEX ON local_ph (listing_id);
CREATE TEMP TABLE approved AS
SELECT c.id
FROM cand c
JOIN listings al ON al.id = c.id AND al.last_seen_at >= c.last_seen_at
LEFT JOIN local_ph lp ON lp.listing_id = c.id
WHERE COALESCE(lp.n, 0) >= c.ph_n;
\\copy (SELECT id FROM approved ORDER BY id) TO '$APPROVED' WITH (FORMAT csv)
SELECT 'approved: ' || count(*) FROM approved;
SELECT 'rejected (not fully synced): ' || ((SELECT count(*) FROM cand) - (SELECT count(*) FROM approved));
SQL

N_APPROVED="$(wc -l < "$APPROVED" | tr -d ' ')"
echo "approved for deletion: $N_APPROVED"

if [ "$DRY_RUN" != "0" ]; then
  echo "DRY_RUN=1 — ничего не удалено. Запусти с DRY_RUN=0 чтобы удалить."
  echo "=== prune done (dry) $(date '+%F %T') ==="
  exit 0
fi

if [ "$N_APPROVED" = "0" ]; then
  echo "нечего удалять"
  echo "=== prune done $(date '+%F %T') ==="
  exit 0
fi

# 4. Удаление в Neon одной транзакцией: Neon Pooler (transaction pooling) не хранит
# TEMP-таблицы между автокоммит-стейтментами, поэтому обязателен BEGIN/COMMIT.
npsql -q <<SQL
BEGIN;
CREATE TEMP TABLE prune_ids (id uuid PRIMARY KEY) ON COMMIT DROP;
\\copy prune_ids FROM '$APPROVED' WITH (FORMAT csv)
DELETE FROM listings USING prune_ids WHERE listings.id = prune_ids.id;
COMMIT;
SQL
echo "deleted from neon: $N_APPROVED listings (+ price_history каскадом)"

# 5. VACUUM — освободить страницы под повторное использование.
npsql -q -c "VACUUM ANALYZE listings;" -c "VACUUM ANALYZE price_history;"
npsql -c "SELECT pg_size_pretty(pg_database_size(current_database())) AS neon_db_size;"

echo "=== prune done $(date '+%F %T') ==="
