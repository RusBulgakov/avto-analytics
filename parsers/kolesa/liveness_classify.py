"""Чистый классификатор ответа kolesa /a/show/{id} — alive / closed / transient.

Без сети и БД, чтобы юнит-тестировать в любом окружении.
Сигнал (см. спеку §1, провалидировано на реальных страницах):
  - Живой лист: HTTP 200 И тело содержит canonical/title именно ЭТОГО объявления
    (`/a/show/{external_id}` в canonical, либо `№{external_id}` в <title>).
  - 404/410, либо 200 без маркеров этого листа (kolesa отдаёт дженерик-главную) → closed.
  - 5xx / 429 / -1 (сеть/таймаут) → transient (НЕ закрываем).
"""
import re

ALIVE = "alive"
CLOSED = "closed"
TRANSIENT = "transient"

# Транзиентные коды: сеть/таймаут (-1), rate-limit (429), серверные 5xx.
_TRANSIENT_CODES = {-1, 429, 500, 502, 503, 504}


def classify_listing(status_code: int, body: str | None, external_id: str) -> str:
    if status_code in _TRANSIENT_CODES:
        return TRANSIENT
    if status_code in (404, 410):
        return CLOSED
    if status_code == 200 and body and _is_listing_page(body, external_id):
        return ALIVE
    # Любой иной 200 (soft-404 / редирект на главную / чужой лист) или прочие коды → closed.
    if status_code == 200:
        return CLOSED
    # Неожиданный код (403/451/3xx и т.п.) — безопаснее не закрывать.
    return TRANSIENT


def _is_listing_page(body: str, external_id: str) -> bool:
    """True, если тело — страница именно объявления external_id."""
    eid = re.escape(external_id)
    if re.search(rf'/a/show/{eid}\b', body):       # canonical/og:url на себя
        return True
    if re.search(rf'№\s*{eid}\b', body):            # <title> ... №{id}: цена ...
        return True
    return False
