"""
common/neon_capacity.py
Ранний сигнал «Neon скоро переполнится» — до того, как упадут парсеры.

    python -m parsers.common.neon_capacity

Лимит free tier считает размер ФАЙЛОВ всего кластера (все БД, включая
postgres/template*). Пока внутри таблиц есть свободные страницы после
подрезки, файлы не растут; когда растут — запас кончается. Поэтому метрика
= сумма pg_database_size по всем БД против NEON_LIMIT_MB.

При >= NEON_WARN_MB: GHA-аннотация ::warning:: + сообщение в Telegram.
Exit 0 всегда (сигнал, а не авария); exit 1 только если БД недоступна.

Прецеденты: 2026-08-29 и 2026-09-20…25 — Neon упёрся в 512 MB, все пишущие
workflow падали с DiskFullError, во второй раз — почти неделю, потому что
архивный контур на Mac mini молча не запускался (TCC).
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

from parsers.common.db import close_pool, get_pool
from parsers.common.notifier import send_telegram_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("neon_capacity")

LIMIT_MB = float(os.getenv("NEON_LIMIT_MB", "512"))
WARN_MB = float(os.getenv("NEON_WARN_MB", "470"))


async def main() -> int:
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            cluster = await conn.fetchval("SELECT sum(pg_database_size(datname))::bigint FROM pg_database")
            n_listings = await conn.fetchval("SELECT count(*) FROM listings")
            oldest = await conn.fetchval("SELECT min(last_seen_at) FROM listings")
    except Exception as e:
        logger.error("Neon недоступен: %s", e)
        return 1
    finally:
        await close_pool()

    used_mb = cluster / 1024 / 1024
    pct = used_mb / LIMIT_MB * 100
    summary = (
        f"Neon: {used_mb:.0f} / {LIMIT_MB:.0f} MB ({pct:.0f}%), "
        f"listings={n_listings}, самый старый last_seen={oldest:%Y-%m-%d}"
    )
    logger.info(summary)

    if used_mb >= WARN_MB:
        msg = (
            f"{summary}. Порог {WARN_MB:.0f} MB. Проверь архивный контур на Mac mini "
            f"(~/Library/Logs/kolesa-archive/last-status) и прогони "
            f"infrastructure/archive/prune_neon.sh + neon_compact.sql"
        )
        if os.getenv("GITHUB_ACTIONS") == "true":
            print(f"::warning title=Neon capacity::{msg}", flush=True)
        await send_telegram_message(f"⚠️ <b>Neon почти полон</b>\n{msg}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
