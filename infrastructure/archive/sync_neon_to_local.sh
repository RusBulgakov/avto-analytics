#!/usr/bin/env bash
# Синхронизация Neon (прод, hot window) -> локальный Postgres kolesa_archive (полная история).
# Запускается на Mac mini (launchd, см. com.kolesa.archive-sync.plist) или вручную.
#
# Режимы:
#   ./sync_neon_to_local.sh          # инкрементально (listings по timestamp-колонкам, price_history по recorded_at)
#   ./sync_neon_to_local.sh full     # полная пересинхронизация listings + price_history (медленнее, раз в неделю)
#
# Принцип: архив только НАКАПЛИВАЕТ — никакие строки локально не удаляются.
# Справочные таблицы упсертятся целиком, listings/price_history — по watermark из sync_state.

set -euo pipefail

MODE="${1:-incr}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
LOCAL_DB="${LOCAL_DB:-kolesa_archive}"
LOG_DIR="$HOME/Library/Logs/kolesa-archive"
TMP_DIR="$(mktemp -d /tmp/kolesa-sync.XXXXXX)"
trap 'rm -rf "$TMP_DIR"' EXIT

mkdir -p "$LOG_DIR"
exec >> "$LOG_DIR/sync.log" 2>&1

echo "=== sync start $(date '+%F %T') mode=$MODE ==="

NEON_URL="$(grep -m1 '^DATABASE_URL=' "$REPO_DIR/.env" | cut -d= -f2- | tr -d '"' | tr -d "'")"
if [ -z "$NEON_URL" ]; then echo "FATAL: DATABASE_URL not found in $REPO_DIR/.env"; exit 1; fi

npsql() { psql "$NEON_URL" -v ON_ERROR_STOP=1 "$@"; }
lpsql() { psql -h localhost -d "$LOCAL_DB" -v ON_ERROR_STOP=1 "$@"; }

# --- служебная таблица watermark'ов ---
lpsql -q -c "CREATE TABLE IF NOT EXISTS sync_state (
  table_name text PRIMARY KEY,
  last_sync_at timestamptz NOT NULL
);"

# Момент начала синка по часам Neon — станет новым watermark после успеха.
SYNC_START="$(npsql -t -A -c 'SELECT now();')"
echo "neon now: $SYNC_START"

# --- генератор списка колонок (по локальной схеме, чтобы \copy и INSERT совпадали) ---
cols_of() { # $1 = table
  lpsql -t -A -c "SELECT string_agg(quote_ident(attname), ',' ORDER BY attnum)
    FROM pg_attribute
    WHERE attrelid = 'public.$1'::regclass AND attnum > 0 AND NOT attisdropped;"
}

pk_of() { # $1 = table -> comma-separated PK cols
  lpsql -t -A -c "SELECT string_agg(quote_ident(a.attname), ',' ORDER BY x.ord)
    FROM pg_index i
    JOIN LATERAL unnest(i.indkey) WITH ORDINALITY AS x(attnum, ord) ON true
    JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = x.attnum
    WHERE i.indrelid = 'public.$1'::regclass AND i.indisprimary;"
}

set_clause_of() { # $1 = table, $2 = pk cols -> "col = EXCLUDED.col, ..." без PK
  lpsql -t -A -c "SELECT string_agg(quote_ident(attname) || ' = EXCLUDED.' || quote_ident(attname), ', ')
    FROM pg_attribute
    WHERE attrelid = 'public.$1'::regclass AND attnum > 0 AND NOT attisdropped
      AND attname <> ALL (string_to_array('$2', ','));"
}

# --- универсальный upsert таблицы: Neon -> local ---
sync_table() { # $1 = table, $2 = optional WHERE для Neon-выборки, $3 = optional guard для INSERT из stg
  local t="$1" where="${2:-}" guard="${3:-}" cols pk setc csv
  cols="$(cols_of "$t")"
  pk="$(pk_of "$t")"
  if [ -z "$cols" ] || [ -z "$pk" ]; then
    echo "WARN: skip $t (no local table or no PK) — обнови схему архива вручную"
    return 0
  fi
  setc="$(set_clause_of "$t" "$pk")"
  csv="$TMP_DIR/$t.csv"
  npsql -q -c "\\copy (SELECT $cols FROM public.$t ${where:+WHERE $where}) TO '$csv' WITH (FORMAT csv)"
  local conflict_action="DO NOTHING"
  [ -n "$setc" ] && conflict_action="DO UPDATE SET $setc"
  lpsql -q <<SQL
BEGIN;
CREATE TEMP TABLE stg (LIKE public.$t INCLUDING DEFAULTS);
\\copy stg ($cols) FROM '$csv' WITH (FORMAT csv)
INSERT INTO public.$t ($cols)
SELECT $cols FROM stg
${guard:+WHERE $guard}
ON CONFLICT ($pk) $conflict_action;
COMMIT;
SQL
  local n
  n="$(wc -l < "$csv" | tr -d ' ')"
  echo "synced $t: $n rows${where:+ (incremental)}"
}

# Guard для price_history: строка могла появиться в Neon позже снапшота listings —
# пропускаем, догонится следующим синком (инкремент с запасом 3 дня).
PH_GUARD="EXISTS (SELECT 1 FROM public.listings l WHERE l.id = stg.listing_id)"

# --- справочники и мелкие таблицы: всегда целиком ---
for t in sources brands models body_types fuel_types transmission_types drive_types \
         fx_history subscription_plans users user_subscriptions parser_runs; do
  sync_table "$t"
done

# --- listings ---
if [ "$MODE" = "full" ]; then
  sync_table listings
else
  WM="$(lpsql -t -A -c "SELECT COALESCE((SELECT last_sync_at FROM sync_state WHERE table_name='listings')::text, '1970-01-01');")"
  sync_table listings "GREATEST(first_seen_at, last_seen_at,
      COALESCE(closed_at, 'epoch'::timestamptz),
      COALESCE(flags_updated_at, 'epoch'::timestamptz),
      COALESCE(last_checked_at, 'epoch'::timestamptz)) >= '$WM'::timestamptz - interval '3 days'"
fi

# --- price_history (append-only) ---
if [ "$MODE" = "full" ]; then
  sync_table price_history "" "$PH_GUARD"
else
  WMP="$(lpsql -t -A -c "SELECT COALESCE((SELECT last_sync_at FROM sync_state WHERE table_name='price_history')::text, '1970-01-01');")"
  sync_table price_history "recorded_at >= '$WMP'::timestamptz - interval '3 days'" "$PH_GUARD"
fi

# --- watermark только после полного успеха ---
lpsql -q -c "INSERT INTO sync_state (table_name, last_sync_at)
  VALUES ('listings', '$SYNC_START'), ('price_history', '$SYNC_START')
  ON CONFLICT (table_name) DO UPDATE SET last_sync_at = EXCLUDED.last_sync_at;"

echo "counts local: $(lpsql -t -A -c "SELECT 'listings='||(SELECT count(*) FROM listings)||' price_history='||(SELECT count(*) FROM price_history);")"
echo "=== sync done $(date '+%F %T') ==="
