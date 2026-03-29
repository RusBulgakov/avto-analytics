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
    }
    if settings.db_requires_ssl:
        kwargs["ssl"] = _ssl.create_default_context()
        kwargs["min_size"] = 1
        kwargs["max_size"] = 5
    _pool = await asyncpg.create_pool(**kwargs)


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
