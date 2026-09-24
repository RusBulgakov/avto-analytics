#!/usr/bin/env bash
# Установка / обновление архивного контура в launchd на Mac mini.
# Запускать из терминала после ЛЮБОЙ правки скриптов в infrastructure/archive/
# (launchd исполняет копии, а не файлы репо):
#
#   ./infrastructure/archive/install.sh            # установить/обновить
#   ./infrastructure/archive/install.sh --run-now  # + сразу прогнать через launchd
#
# Почему копии: репо лежит в ~/Documents, а macOS (TCC) запрещает фоновым
# launchd-процессам читать ~/Documents — агенты, указывавшие прямо в репо,
# падали с "Operation not permitted" (exit 126) с 2026-08-29 по 2026-09-25.
# Поэтому скрипты копируются в ~/.local/share/kolesa-archive, а DATABASE_URL —
# в ~/.config/kolesa-archive/neon.env (chmod 600). Full Disk Access для
# /bin/bash НЕ выдаём: это открыло бы весь диск любому bash-скрипту.

set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SRC_DIR/../.." && pwd)"
RUNTIME_DIR="${KOLESA_ARCHIVE_HOME:-$HOME/.local/share/kolesa-archive}"
CONF_DIR="$HOME/.config/kolesa-archive"
AGENTS_DIR="$HOME/Library/LaunchAgents"
LABEL="com.kolesa.archive-nightly"
DOMAIN="gui/$(id -u)"

mkdir -p "$RUNTIME_DIR" "$CONF_DIR" "$AGENTS_DIR" "$HOME/Library/Logs/kolesa-archive"

# 1. Скрипты
install -m 755 "$SRC_DIR/common.sh" "$SRC_DIR/sync_neon_to_local.sh" \
  "$SRC_DIR/prune_neon.sh" "$SRC_DIR/nightly.sh" "$RUNTIME_DIR/"
echo "scripts -> $RUNTIME_DIR"

# 2. Секрет Neon (только DATABASE_URL, не весь .env)
url="$(grep -m1 '^DATABASE_URL=' "$REPO_DIR/.env" | cut -d= -f2- | tr -d '"' | tr -d "'")"
if [ -z "$url" ]; then echo "FATAL: DATABASE_URL не найден в $REPO_DIR/.env"; exit 1; fi
( umask 077; printf 'DATABASE_URL=%s\n' "$url" > "$CONF_DIR/neon.env" )
chmod 600 "$CONF_DIR/neon.env"
echo "env -> $CONF_DIR/neon.env (600)"

# 3. launchd: убираем старые агенты (sync/prune смотрели прямо в репо) и ставим nightly
for old in com.kolesa.archive-sync com.kolesa.archive-prune "$LABEL"; do
  launchctl bootout "$DOMAIN/$old" 2>/dev/null || true
done
rm -f "$AGENTS_DIR/com.kolesa.archive-sync.plist" "$AGENTS_DIR/com.kolesa.archive-prune.plist"

sed -e "s#__RUNTIME_DIR__#$RUNTIME_DIR#g" -e "s#__HOME__#$HOME#g" \
  "$SRC_DIR/$LABEL.plist" > "$AGENTS_DIR/$LABEL.plist"
plutil -lint "$AGENTS_DIR/$LABEL.plist" >/dev/null
launchctl bootstrap "$DOMAIN" "$AGENTS_DIR/$LABEL.plist"
echo "launchd: $LABEL loaded (daily 03:30)"

if [ "${1:-}" = "--run-now" ]; then
  launchctl kickstart "$DOMAIN/$LABEL"
  echo "kickstarted — итог в ~/Library/Logs/kolesa-archive/last-status"
fi
