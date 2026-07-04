"""
Тесты pool_stats/log_pool_stats (parsers/common/db.py, t-0015).

БД не нужна: неинициализированный пул → None без исключений,
инициализированный (стаб) → словарь size/idle/max.
"""
import asyncio

import parsers.common.db as db


class _PoolStub:
    """Минимальный стаб asyncpg.Pool — только интроспекция счётчиков."""
    def get_size(self):
        return 3

    def get_idle_size(self):
        return 2

    def get_max_size(self):
        return 5


def test_pool_stats_uninitialized_returns_none(monkeypatch):
    monkeypatch.setattr(db, "_pool", None)
    assert db.pool_stats() is None


def test_pool_stats_returns_size_idle_max(monkeypatch):
    monkeypatch.setattr(db, "_pool", _PoolStub())
    assert db.pool_stats() == {"size": 3, "idle": 2, "max": 5}


def test_pool_stats_swallows_introspection_errors(monkeypatch):
    class Broken:
        def get_size(self):
            raise RuntimeError("boom")

    monkeypatch.setattr(db, "_pool", Broken())
    assert db.pool_stats() is None


def test_log_pool_stats_uninitialized_is_noop(monkeypatch, caplog):
    monkeypatch.setattr(db, "_pool", None)
    with caplog.at_level("INFO", logger="parsers.common.db"):
        db.log_pool_stats("end-of-run:")  # не должно бросать
    assert caplog.records == []


def test_log_pool_stats_logs_counters(monkeypatch, caplog):
    monkeypatch.setattr(db, "_pool", _PoolStub())
    with caplog.at_level("INFO", logger="parsers.common.db"):
        db.log_pool_stats("end-of-run:")
    assert "end-of-run: pool: size=3 idle=2 max=5" in caplog.text


def test_close_pool_uninitialized_does_not_raise(monkeypatch):
    monkeypatch.setattr(db, "_pool", None)
    asyncio.run(db.close_pool())  # no-op, без исключений
