#!/usr/bin/env bash
# Общие функции архивного контура (source'ится из sync/prune/nightly).

# Где взять DATABASE_URL Neon. Порядок важен:
#   1) $KOLESA_ENV_FILE — явный override;
#   2) ~/.config/kolesa-archive/neon.env — пишет install.sh (chmod 600);
#   3) .env в корне репо — только для ручного запуска из терминала.
# launchd НЕ может читать репо: он лежит в ~/Documents, а macOS (TCC) запрещает
# фоновым процессам доступ туда → "Operation not permitted" (exit 126). Именно
# так контур молча не работал с 2026-08-29 по 2026-09-25 и Neon снова упёрся
# в 512 MB. Поэтому install.sh копирует всё нужное за пределы ~/Documents.
load_neon_url() { # $1 = repo dir (fallback)
  local f url=""
  for f in "${KOLESA_ENV_FILE:-}" "$HOME/.config/kolesa-archive/neon.env" "${1:-}/.env"; do
    [ -n "$f" ] && [ -f "$f" ] || continue
    url="$(grep -m1 '^DATABASE_URL=' "$f" 2>/dev/null | cut -d= -f2- | tr -d '"' | tr -d "'")" || true
    [ -n "$url" ] && break
  done
  if [ -z "$url" ]; then
    echo "FATAL: DATABASE_URL не найден (KOLESA_ENV_FILE, ~/.config/kolesa-archive/neon.env, ${1:-?}/.env)"
    return 1
  fi
  NEON_URL="$url"
}

# Уведомление владельцу: macOS notification (launchd-агент живёт в GUI-сессии)
# + строка в лог. Сбой уведомления не должен ронять скрипт.
notify() { # $1 = текст
  local msg
  msg="$(printf '%s' "$1" | tr -d '"\\')"
  echo "NOTIFY: $msg"
  /usr/bin/osascript -e "display notification \"$msg\" with title \"Kolesa archive\" sound name \"Basso\"" \
    >/dev/null 2>&1 || true
}
