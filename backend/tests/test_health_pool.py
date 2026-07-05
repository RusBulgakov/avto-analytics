"""
Тесты формы ответа /health с блоком pool (t-0015).

БД не нужна: вызываем handler напрямую и подменяем module-level _pool
в app.core.database стабом с интроспекцией size/idle/max.
Реальный lifespan (init_db) не запускается.
"""
import asyncio

import app.core.database as database
from app.main import health


class _PoolStub:
    def get_size(self):
        return 4

    def get_idle_size(self):
        return 1

    def get_max_size(self):
        return 10


def test_health_pool_null_when_not_initialized(monkeypatch):
    monkeypatch.setattr(database, "_pool", None)
    body = asyncio.run(health())
    assert body == {"status": "ok", "service": "automarket-api", "pool": None}


def test_health_pool_block_shape(monkeypatch):
    monkeypatch.setattr(database, "_pool", _PoolStub())
    body = asyncio.run(health())
    assert body["status"] == "ok"
    assert body["pool"] == {"size": 4, "idle": 1, "max": 10}
