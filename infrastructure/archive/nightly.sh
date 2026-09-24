#!/usr/bin/env bash
# Ночной прогон архивного контура — единственная точка входа для launchd
# (com.kolesa.archive-nightly, ежедневно 03:30):
#   1. синк Neon -> kolesa_archive (вс — полный, остальные дни — инкрементальный,
#      чтобы не жечь egress-квоту Neon полной выгрузкой каждый день);
#   2. подрезка Neon (HOT_DAYS + бюджет NEON_MAX_LISTINGS) — ежедневно, а не
#      раз в неделю: при росте ~90 MB/мес недельный цикл оставлял слишком мало
#      запаса до лимита 512 MB.
# Итог пишется в ~/Library/Logs/kolesa-archive/last-status; при сбое —
# уведомление macOS (раньше контур падал молча почти месяц).

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$HOME/Library/Logs/kolesa-archive"
STATUS_FILE="$LOG_DIR/last-status"
mkdir -p "$LOG_DIR"

# shellcheck source=common.sh
. "$SCRIPT_DIR/common.sh"

MODE="incr"
[ "$(date +%u)" = "7" ] && MODE="full"

PRUNE_SYNC_MODE="$MODE" DRY_RUN="${DRY_RUN:-0}" "$SCRIPT_DIR/prune_neon.sh"
rc=$?

if [ "$rc" -eq 0 ]; then
  echo "ok $(date '+%F %T') sync=$MODE" > "$STATUS_FILE"
else
  echo "FAIL rc=$rc $(date '+%F %T') sync=$MODE — см. $LOG_DIR/{sync,prune}.log" > "$STATUS_FILE"
  notify "Ночной синк/подрезка Neon упали (rc=$rc). Логи: ~/Library/Logs/kolesa-archive"
fi
exit "$rc"
