"""parsers/kolesa/liveness.py — liveness sweep активных kolesa-объявлений.

Тянет батчи активных listing'ов (дольше всех не проверенные первыми по
last_checked_at NULLS FIRST), GET'ит listing_url, и:
  - ALIVE   → last_seen_at=now(), last_checked_at=now(), closed_at=NULL
  - CLOSED  → is_active=FALSE, closed_at=now(), last_checked_at=now()  ← «продано»
  - TRANSIENT → last_checked_at=now() (не блокируем голову очереди, перечек в след. цикле)

Резюмируемость — через персистентный last_checked_at (никаких offset'ов).
Time-boxed: крутит батчи пока не выйдет LIVENESS_TIME_BUDGET_MIN или не опустеет очередь.
Запускается отдельным workflow (kolesa_liveness.yml).
"""
import asyncio
import logging
import os
import random
import time

from curl_cffi import requests

from parsers.common.db import get_pool
from parsers.common.http_client import USER_AGENTS
from parsers.kolesa.liveness_classify import classify_listing, ALIVE, CLOSED, TRANSIENT

logger = logging.getLogger("liveness.kolesa")

BATCH = int(os.getenv("LIVENESS_BATCH", "500"))
CONCURRENCY = int(os.getenv("LIVENESS_CONCURRENCY", "2"))
DELAY_MIN = float(os.getenv("LIVENESS_DELAY_MIN", "1.2"))
DELAY_MAX = float(os.getenv("LIVENESS_DELAY_MAX", "2.5"))
TIME_BUDGET_MIN = float(os.getenv("LIVENESS_TIME_BUDGET_MIN", "300"))
DRY_RUN = os.getenv("LIVENESS_DRY_RUN", "0") == "1"
TIMEOUT = 20


async def select_liveness_batch(pool, source_id: int, limit: int):
    async with pool.acquire() as c:
        return await c.fetch(
            """
            SELECT id, external_id, listing_url
            FROM listings
            WHERE source_id = $1 AND is_active = TRUE AND listing_url IS NOT NULL
            ORDER BY last_checked_at NULLS FIRST
            LIMIT $2
            """,
            source_id, limit,
        )


async def apply_verdict(pool, listing_id, verdict: str, dry_run: bool) -> None:
    if dry_run:
        return
    async with pool.acquire() as c:
        if verdict == ALIVE:
            await c.execute(
                "UPDATE listings SET last_seen_at=NOW(), last_checked_at=NOW(), "
                "closed_at=NULL WHERE id=$1", listing_id)
        elif verdict == CLOSED:
            await c.execute(
                "UPDATE listings SET is_active=FALSE, closed_at=NOW(), "
                "last_checked_at=NOW() WHERE id=$1", listing_id)
        else:  # TRANSIENT — только сдвигаем курсор, состояние не трогаем
            await c.execute(
                "UPDATE listings SET last_checked_at=NOW() WHERE id=$1", listing_id)


async def _check_one(session, url: str, external_id: str) -> str:
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Connection": "keep-alive",
    }
    try:
        resp = await asyncio.wait_for(
            session.get(url, headers=headers, timeout=TIMEOUT, allow_redirects=True),
            timeout=TIMEOUT + 5,
        )
        return classify_listing(resp.status_code, resp.text, external_id)
    except Exception as e:
        logger.debug("check failed for %s: %s", url, e)
        return classify_listing(-1, None, external_id)  # → TRANSIENT


async def _worker(q: asyncio.Queue, session, pool, totals: dict) -> None:
    while True:
        try:
            row = q.get_nowait()
        except asyncio.QueueEmpty:
            return
        verdict = await _check_one(session, row["listing_url"], str(row["external_id"]))
        try:
            await apply_verdict(pool, row["id"], verdict, DRY_RUN)
        except Exception as e:
            logger.warning("apply failed for %s: %s", row["id"], e)
            totals["errors"] += 1
        totals[verdict] += 1
        totals["checked"] += 1
        await asyncio.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
        q.task_done()


async def run_liveness(dry_run: bool = DRY_RUN) -> dict:
    pool = await get_pool()
    async with pool.acquire() as c:
        source_id = await c.fetchval("SELECT id FROM sources WHERE name='kolesa'")
    if source_id is None:
        raise RuntimeError("kolesa source not found")

    totals = {ALIVE: 0, CLOSED: 0, TRANSIENT: 0, "checked": 0, "errors": 0}
    deadline = time.monotonic() + TIME_BUDGET_MIN * 60
    logger.info("liveness start: budget=%.0fmin batch=%d concurrency=%d dry_run=%s",
                TIME_BUDGET_MIN, BATCH, CONCURRENCY, dry_run)

    async with requests.AsyncSession(impersonate="chrome") as session:
        while time.monotonic() < deadline:
            rows = await select_liveness_batch(pool, source_id, BATCH)
            if not rows:
                logger.info("queue drained — all active listings checked")
                break
            q: asyncio.Queue = asyncio.Queue()
            for r in rows:
                q.put_nowait(r)
            await asyncio.gather(*[_worker(q, session, pool, totals)
                                   for _ in range(CONCURRENCY)])
            logger.info("progress: checked=%d alive=%d closed=%d transient=%d",
                        totals["checked"], totals[ALIVE], totals[CLOSED], totals[TRANSIENT])
    return totals


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    start = time.time()
    stats = asyncio.run(run_liveness())
    elapsed = time.time() - start
    print(f"Liveness done in {elapsed:.0f}s {'[DRY-RUN] ' if DRY_RUN else ''}"
          f"checked={stats['checked']} alive={stats['alive']} "
          f"closed={stats['closed']} transient={stats['transient']} errors={stats['errors']}")
