"""
app/core/database.py — asyncpg connection pool
"""
import ssl as _ssl
from typing import Optional

import asyncpg
from app.core.config import settings

_pool: Optional[asyncpg.Pool] = None


async def init_db():
    global _pool
    kwargs = {
        "dsn": settings.db_url_raw,
        "min_size": 2,
        "max_size": 10,
        # Neon Pooler (PgBouncer, transaction mode) не поддерживает prepared
        # statements между транзакциями — без этого ловится
        # InvalidSQLStatementNameError (см. CLAUDE.md; парсеры уже делают так же).
        "statement_cache_size": 0,
    }
    if settings.db_requires_ssl:
        kwargs["ssl"] = _ssl.create_default_context()
        kwargs["min_size"] = 1
        kwargs["max_size"] = 5
    _pool = await asyncpg.create_pool(**kwargs)


def pool_stats() -> Optional[dict]:
    """
    Поверхностная интроспекция пула для /health (t-0015): без запросов к БД,
    только счётчики соединений. None если пул ещё не инициализирован.
    Цель — ловить утечки соединений к Neon Pooler (size растёт, idle = 0).
    """
    if _pool is None:
        return None
    try:
        return {
            "size": _pool.get_size(),
            "idle": _pool.get_idle_size(),
            "max": _pool.get_max_size(),
        }
    except Exception:  # noqa: BLE001 — healthcheck не должен падать из-за метрик
        return None


async def get_conn() -> asyncpg.Connection:
    return await _pool.acquire()


async def release_conn(conn: asyncpg.Connection):
    await _pool.release(conn)


class DBSession:
    """Async context manager для получения соединения из пула."""
    async def __aenter__(self) -> asyncpg.Connection:
        self.conn = await _pool.acquire()
        return self.conn

    async def __aexit__(self, *args):
        await _pool.release(self.conn)
