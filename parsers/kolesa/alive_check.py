"""
parsers/kolesa/alive_check.py — оживление inactive объявлений.

Главный парсер kolesa видит только первые 5000 объявлений на фид (лимит
пагинации сайта). Объявления с глубоких страниц протухают как is_active=FALSE
после 7 дней, даже если физически ещё живы на сайте.

Этот worker перед-очная проверка: берёт батч inactive kolesa-объявлений
(3–30 дней свежести), GET'ит их listing_url с ротацией UA, и если страница
возвращает 200 — возвращает is_active=TRUE. Если 404/410 — подтверждаем
"мёртвое" (просто обновляем last_seen_at, чтобы не перечекать скоро).

Rate-limit: 2 параллельных worker'а, задержка 1.2-2.5 сек между запросами.
~2 req/sec общий → kolesa.kz такие rate не банит.

Батч 5000 на прогон → ~60-80 минут работы (укладываемся в free-tier GHA).
Запускается отдельным workflow (alive_check.yml) каждые 12 часов.
"""
import asyncio
import logging
import os
import random
import time
from typing import Optional

from curl_cffi import requests

from parsers.common.db import get_pool
from parsers.common.http_client import USER_AGENTS

logger = logging.getLogger("alive_check.kolesa")

BATCH_SIZE = int(os.getenv("ALIVE_CHECK_BATCH", "5000"))
CONCURRENCY = int(os.getenv("ALIVE_CHECK_CONCURRENCY", "2"))
DELAY_MIN = float(os.getenv("ALIVE_CHECK_DELAY_MIN", "1.2"))
DELAY_MAX = float(os.getenv("ALIVE_CHECK_DELAY_MAX", "2.5"))
TIMEOUT = 20


async def _check_one(session, url: str) -> int:
    """Возвращает HTTP status code или -1 при network error."""
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }
    try:
        # kolesa иногда отдаёт разные коды на HEAD vs GET — используем GET
        # с timeout'ом чтобы не скачивать всю страницу если сильно долго.
        resp = await asyncio.wait_for(
            session.get(url, headers=headers, timeout=TIMEOUT, allow_redirects=True),
            timeout=TIMEOUT + 5,
        )
        return resp.status_code
    except Exception as e:
        logger.debug("check failed for %s: %s", url, e)
        return -1


async def _worker(name: str, q: asyncio.Queue, session, pool) -> tuple[int, int, int]:
    """Вытаскивает задачи из очереди пока не опустеет, возвращает (revived, dead, errors)."""
    revived = confirmed_dead = errors = 0
    while True:
        try:
            item = q.get_nowait()
        except asyncio.QueueEmpty:
            break

        listing_id, url = item["id"], item["listing_url"]
        status = await _check_one(session, url)

        if status == 200:
            try:
                async with pool.acquire() as c:
                    await c.execute(
                        """UPDATE listings
                           SET is_active = TRUE,
                               last_seen_at = NOW(),
                               closed_at = NULL
                           WHERE id = $1""",
                        listing_id,
                    )
                revived += 1
                if revived % 100 == 0:
                    logger.info("[%s] revived %d", name, revived)
            except Exception as e:
                logger.warning("[%s] update failed for %s: %s", name, listing_id, e)
                errors += 1
        elif status in (404, 410):
            # Объявление реально закрыто. Обновим last_seen чтобы не перечекать
            # слишком скоро (следующий раз попадёт в выборку только через 3+ дня).
            try:
                async with pool.acquire() as c:
                    await c.execute(
                        "UPDATE listings SET last_seen_at = NOW() WHERE id = $1",
                        listing_id,
                    )
                confirmed_dead += 1
            except Exception as e:
                logger.warning("[%s] update failed: %s", name, e)
                errors += 1
        else:
            # 5xx / network / timeout / unexpected — оставляем как было, попробуем потом
            errors += 1

        await asyncio.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
        q.task_done()

    return revived, confirmed_dead, errors


async def run_alive_check() -> dict:
    """Главная функция: выбирает батч inactive, прогоняет через worker'ов."""
    pool = await get_pool()

    async with pool.acquire() as conn:
        rows = await conn.fetch(
            """
            SELECT l.id, l.listing_url
            FROM listings l
            JOIN sources s ON s.id = l.source_id
            WHERE l.is_active = FALSE
              AND s.name = 'kolesa'
              AND l.listing_url IS NOT NULL
              AND (l.last_seen_at IS NULL OR l.last_seen_at < NOW() - INTERVAL '3 days')
              AND (l.last_seen_at IS NULL OR l.last_seen_at > NOW() - INTERVAL '30 days')
            ORDER BY l.last_seen_at DESC NULLS LAST
            LIMIT $1
            """,
            BATCH_SIZE,
        )

    if not rows:
        logger.info("no inactive listings to check — skipping")
        return {"revived": 0, "confirmed_dead": 0, "errors": 0, "checked": 0}

    logger.info(
        "Checking %d inactive kolesa listings (concurrency=%d, delay=%.1f-%.1fs)",
        len(rows), CONCURRENCY, DELAY_MIN, DELAY_MAX,
    )

    q: asyncio.Queue = asyncio.Queue()
    for r in rows:
        q.put_nowait({"id": r["id"], "listing_url": r["listing_url"]})

    async with requests.AsyncSession(impersonate="chrome") as session:
        tasks = [_worker(f"w{i}", q, session, pool) for i in range(CONCURRENCY)]
        results = await asyncio.gather(*tasks)

    stats = {
        "revived": sum(r[0] for r in results),
        "confirmed_dead": sum(r[1] for r in results),
        "errors": sum(r[2] for r in results),
        "checked": len(rows),
    }
    logger.info(
        "Alive check done: revived=%d confirmed_dead=%d errors=%d (of %d checked)",
        stats["revived"], stats["confirmed_dead"], stats["errors"], stats["checked"],
    )
    return stats


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    start = time.time()
    try:
        stats = asyncio.run(run_alive_check())
        elapsed = time.time() - start
        print(
            f"Alive check finished in {elapsed:.0f}s: "
            f"revived={stats['revived']} dead={stats['confirmed_dead']} "
            f"errors={stats['errors']} of {stats['checked']} checked"
        )
    except Exception as e:
        logger.exception("alive_check failed")
        raise
