"""
Тесты rate-limiter'а (app/core/rate_limit.py).

БД не нужна: собираем минимальное FastAPI-приложение с теми же путями
и middleware, что и в проде (app/main.py), но без init_db/lifespan.
"""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.rate_limit import RateLimitMiddleware, parse_rate


def make_app(**limiter_kwargs) -> TestClient:
    app = FastAPI()

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/api/v1/analytics/brands")
    async def brands():
        return []

    @app.get("/api/v1/analytics/profit-ranking")
    async def profit_ranking():
        return []

    app.add_middleware(RateLimitMiddleware, **limiter_kwargs)
    return TestClient(app)


def test_global_limit_returns_429_with_retry_after():
    client = make_app(global_rate="3/minute", heavy_rate="10/minute")
    for _ in range(3):
        assert client.get("/api/v1/analytics/brands").status_code == 200
    resp = client.get("/api/v1/analytics/brands")
    assert resp.status_code == 429
    assert "retry-after" in resp.headers
    assert int(resp.headers["retry-after"]) >= 1
    assert resp.json()["retry_after_seconds"] == int(resp.headers["retry-after"])


def test_heavy_limit_stricter_than_global():
    client = make_app(global_rate="100/minute", heavy_rate="2/minute")
    for _ in range(2):
        assert client.get("/api/v1/analytics/profit-ranking").status_code == 200
    # Третий heavy-запрос — 429, хотя глобальный лимит далеко не исчерпан
    assert client.get("/api/v1/analytics/profit-ranking").status_code == 429
    # Лёгкие эндпоинты при этом живы
    assert client.get("/api/v1/analytics/brands").status_code == 200


def test_heavy_requests_count_toward_global():
    client = make_app(global_rate="3/minute", heavy_rate="100/minute")
    for _ in range(3):
        assert client.get("/api/v1/analytics/profit-ranking").status_code == 200
    # Глобальное окно исчерпано heavy-запросами → и лёгкий получает 429
    assert client.get("/api/v1/analytics/brands").status_code == 429


def test_health_never_limited():
    client = make_app(global_rate="2/minute", heavy_rate="2/minute")
    for _ in range(20):
        assert client.get("/health").status_code == 200


def test_x_forwarded_for_separates_clients():
    client = make_app(global_rate="2/minute", heavy_rate="10/minute")
    h1 = {"X-Forwarded-For": "203.0.113.1"}
    h2 = {"X-Forwarded-For": "203.0.113.2, 10.0.0.1"}
    for _ in range(2):
        assert client.get("/api/v1/analytics/brands", headers=h1).status_code == 200
    # IP #1 исчерпал лимит...
    assert client.get("/api/v1/analytics/brands", headers=h1).status_code == 429
    # ...а IP #2 (leftmost из XFF-цепочки) — нет
    assert client.get("/api/v1/analytics/brands", headers=h2).status_code == 200


def test_options_preflight_not_limited():
    client = make_app(global_rate="1/minute", heavy_rate="1/minute")
    assert client.get("/api/v1/analytics/brands").status_code == 200
    for _ in range(5):
        # CORS preflight не должен съедать лимит и не должен блокироваться
        resp = client.options("/api/v1/analytics/brands")
        assert resp.status_code != 429


def test_disabled_via_flag():
    client = make_app(enabled=False, global_rate="1/minute", heavy_rate="1/minute")
    for _ in range(10):
        assert client.get("/api/v1/analytics/brands").status_code == 200


def test_window_resets(monkeypatch):
    import app.core.rate_limit as rl
    fake_now = [1000.0]
    monkeypatch.setattr(rl.time, "monotonic", lambda: fake_now[0])
    client = make_app(global_rate="2/second", heavy_rate="10/second")
    for _ in range(2):
        assert client.get("/api/v1/analytics/brands").status_code == 200
    assert client.get("/api/v1/analytics/brands").status_code == 429
    fake_now[0] += 1.5  # окно (1 сек) истекло
    assert client.get("/api/v1/analytics/brands").status_code == 200


def test_parse_rate():
    assert parse_rate("60/minute") == (60, 60)
    assert parse_rate("5/second") == (5, 1)
    assert parse_rate("1000/hour") == (1000, 3600)
    with pytest.raises(ValueError):
        parse_rate("sixty per minute")
    with pytest.raises(ValueError):
        parse_rate("60/fortnight")
