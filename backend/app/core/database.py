"""
app/core/database.py — asyncpg connection pool
"""
import asyncpg
from app.core.config import settings

_pool: asyncpg.Pool | None = None


async def init_db():
    global _pool
    _pool = await asyncpg.create_pool(
        dsn=settings.db_url_raw,
        min_size=5,
        max_size=20,
    )


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
