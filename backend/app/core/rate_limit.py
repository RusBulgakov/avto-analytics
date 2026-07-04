"""
app/core/rate_limit.py — простой in-memory rate limiter (fixed window, per-IP).

Почему свой, а не slowapi:
- Один инстанс на Render free-tier → shared-состояние (Redis) не нужно,
  обычного dict в памяти процесса достаточно.
- Полный контроль над Retry-After, классами лимитов (global/heavy) и
  определением клиентского IP за прокси Render (X-Forwarded-For).
- Ноль новых зависимостей.

Ограничения by design (осознанные trade-off'ы):
- Fixed window (не sliding): на границе окна возможен кратковременный burst
  до 2x лимита — для защиты от долбёжки тяжёлых SQL этого достаточно.
- Состояние сбрасывается при рестарте процесса — не страшно.
- При нескольких инстансах каждый считает независимо — сейчас инстанс один.

Конфигурация через env (см. app/core/config.py):
- RATE_LIMIT_ENABLED  — выключатель (default: true)
- RATE_LIMIT_GLOBAL   — лимит на все /api/* пути, формат "N/period" (default: "120/minute")
- RATE_LIMIT_HEAVY    — лимит на тяжёлые analytics/insights-эндпоинты (default: "20/minute")

period ∈ second | minute | hour | day.
"""
from __future__ import annotations

import json
import re
import time

# ── Парсинг строки лимита ────────────────────────────────────────────────

_PERIOD_SECONDS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}
_RULE_RE = re.compile(r"^\s*(\d+)\s*/\s*(second|minute|hour|day)\s*$", re.IGNORECASE)


def parse_rate(rule: str) -> tuple[int, int]:
    """'60/minute' → (60, 60). Бросает ValueError на мусор в env."""
    m = _RULE_RE.match(rule)
    if not m:
        raise ValueError(
            f"Некорректный формат rate-limit: {rule!r} (ожидается 'N/second|minute|hour|day')"
        )
    return int(m.group(1)), _PERIOD_SECONDS[m.group(2).lower()]


# ── Определение клиента ──────────────────────────────────────────────────

def client_ip_from_scope(scope) -> str:
    """
    Клиентский IP за reverse-proxy Render: первый (leftmost) адрес из
    X-Forwarded-For, иначе прямой peer address. Без этого все пользователи
    делили бы один IP прокси и лимитер наказывал бы всех сразу.
    """
    for name, value in scope.get("headers", []):
        if name == b"x-forwarded-for":
            first = value.decode("latin-1").split(",")[0].strip()
            if first:
                return first
            break
    client = scope.get("client")
    return client[0] if client else "unknown"


# ── Middleware ───────────────────────────────────────────────────────────

class RateLimitMiddleware:
    """
    Pure-ASGI middleware: fixed-window счётчики per (IP, class).

    Классы:
    - exempt: /health, /api/docs, /api/redoc, /openapi.json, OPTIONS (CORS preflight)
    - heavy:  путь содержит один из HEAVY_SEGMENTS → проверяется heavy-лимит
              И глобальный (тяжёлый запрос — всё ещё запрос)
    - global: всё остальное под /api/
    """

    HEAVY_SEGMENTS = (
        "/profit-ranking",
        "/profitability",
        "/backtest",
        "/forecast",
        # insights/* кешируются (TTL 1h), но кеш обходится перебором query-параметров
        # (brand_id — незамкнутое пространство ключей) → heavy-лимит обязателен
        "/analytics/insights/",
    )
    EXEMPT_PATHS = ("/health", "/api/docs", "/api/redoc", "/openapi.json")
    # Защита от unbounded роста памяти: при превышении — чистка истёкших окон
    MAX_BUCKETS = 10_000

    def __init__(
        self,
        app,
        enabled: bool = True,
        global_rate: str = "120/minute",
        heavy_rate: str = "20/minute",
    ):
        self.app = app
        self.enabled = enabled
        self.global_limit, self.global_window = parse_rate(global_rate)
        self.heavy_limit, self.heavy_window = parse_rate(heavy_rate)
        # (ip, class) -> [window_start: float, count: int]
        self._buckets: dict[tuple[str, str], list] = {}

    # -- учёт --

    def _hit(self, key: tuple[str, str], limit: int, window: int) -> float:
        """
        Инкремент счётчика. Возвращает 0.0 если запрос разрешён,
        иначе — секунды до сброса окна (для Retry-After).
        """
        now = time.monotonic()
        bucket = self._buckets.get(key)
        if bucket is None or now - bucket[0] >= window:
            if len(self._buckets) >= self.MAX_BUCKETS:
                self._prune(now)
            self._buckets[key] = [now, 1]
            return 0.0
        if bucket[1] >= limit:
            return window - (now - bucket[0])
        bucket[1] += 1
        return 0.0

    def _prune(self, now: float) -> None:
        """Убирает истёкшие окна (вызывается редко, только при росте dict)."""
        max_window = max(self.global_window, self.heavy_window)
        expired = [k for k, v in self._buckets.items() if now - v[0] >= max_window]
        for k in expired:
            del self._buckets[k]

    # -- классификация --

    def _is_exempt(self, path: str) -> bool:
        return path in self.EXEMPT_PATHS or not path.startswith("/api/")

    def _is_heavy(self, path: str) -> bool:
        return any(seg in path for seg in self.HEAVY_SEGMENTS)

    # -- ASGI --

    async def __call__(self, scope, receive, send):
        if not self.enabled or scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        if scope.get("method") == "OPTIONS" or self._is_exempt(path):
            await self.app(scope, receive, send)
            return

        ip = client_ip_from_scope(scope)
        retry_after = 0.0
        if self._is_heavy(path):
            retry_after = self._hit((ip, "heavy"), self.heavy_limit, self.heavy_window)
        if not retry_after:
            retry_after = self._hit((ip, "global"), self.global_limit, self.global_window)

        if retry_after:
            await self._send_429(send, retry_after)
            return

        await self.app(scope, receive, send)

    @staticmethod
    async def _send_429(send, retry_after: float) -> None:
        retry_s = max(1, int(retry_after + 0.999))  # округляем вверх, минимум 1 сек
        body = json.dumps(
            {"detail": "Too many requests. Slow down.", "retry_after_seconds": retry_s}
        ).encode()
        await send({
            "type": "http.response.start",
            "status": 429,
            "headers": [
                (b"content-type", b"application/json"),
                (b"retry-after", str(retry_s).encode()),
                (b"content-length", str(len(body)).encode()),
            ],
        })
        await send({"type": "http.response.body", "body": body})
