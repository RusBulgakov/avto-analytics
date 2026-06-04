"""parsers/kolesa/liveness.py — liveness sweep активных kolesa-объявлений.

Тянет батчи активных listing'ов (дольше всех не проверенные первыми по
last_checked_at NULLS FIRST), GET'ит listing_url, и:
  - ALIVE   → last_seen_at=now(), last_checked_at=now(), closed_at=NULL
  - CLOSED  → is_active=FALSE, closed_at=now(), last_checked_at=now()  ← «продано»
  - TRANSIENT → last_checked_at=now() (не блокируем голову очереди, перечек в след. цикле)

Резюмируемость — через персистентный last_checked_at (никаких offset'ов).
Time-boxed: воркеры останавливаются по per-item дедлайну (TIME_BUDGET_MIN), так что
прогон не может перелететь бюджет, даже если kolesa тарпитит запросы.

Анти-тарпит (IP датацентра GHA): сессия curl_cffi прогревается на search-странице
(как фид-парсер), чтобы получить анти-бот cookie перед GET'ами /a/show/; короткий
timeout + 1 быстрый retry + Referer. Диагностические счётчики r_* показывают,
сколько ответов ok / timeout / blocked / error.

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
REQ_TIMEOUT = float(os.getenv("LIVENESS_REQ_TIMEOUT", "8"))   # короткий — тарпит должен падать быстро
MAX_TRIES = int(os.getenv("LIVENESS_MAX_TRIES", "2"))          # 1 попытка + 1 быстрый retry
WARM = os.getenv("LIVENESS_WARM", "1") == "1"
WARM_URL = os.getenv("LIVENESS_WARM_URL", "https://kolesa.kz/cars/")

_REASONS = ("r_ok", "r_timeout", "r_blocked", "r_error")


def _headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Referer": "https://kolesa.kz/",
        "Connection": "keep-alive",
    }


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


async def _warm_session(session) -> None:
    """Прогрев: один GET по search-странице, чтобы получить анти-бот cookie."""
    try:
        await asyncio.wait_for(
            session.get(WARM_URL, headers=_headers(), timeout=REQ_TIMEOUT + 6,
                        allow_redirects=True),
            timeout=REQ_TIMEOUT + 9,
        )
        logger.info("session warmed via %s", WARM_URL)
    except Exception as e:
        logger.warning("warm failed (%s): %s", type(e).__name__, e)


async def _fetch_listing(session, url: str, external_id: str, deadline: float):
    """Возвращает (verdict, reason). reason ∈ {ok, timeout, blocked, error}."""
    last_reason = "error"
    for attempt in range(MAX_TRIES):
        if time.monotonic() >= deadline:
            break
        try:
            resp = await asyncio.wait_for(
                session.get(url, headers=_headers(), timeout=REQ_TIMEOUT,
                            allow_redirects=True),
                timeout=REQ_TIMEOUT + 3,
            )
            sc = resp.status_code
            if sc in (403, 451):
                return TRANSIENT, "blocked"   # IP-блок — не закрываем
            return classify_listing(sc, resp.text, external_id), "ok"
        except asyncio.TimeoutError:
            last_reason = "timeout"
        except Exception as e:
            last_reason = "error"
            logger.debug("check error for %s: %s", url, e)
        if attempt + 1 < MAX_TRIES and time.monotonic() < deadline:
            await asyncio.sleep(random.uniform(0.5, 1.5))
    return TRANSIENT, last_reason


async def _worker(q: asyncio.Queue, session, pool, totals: dict, dry_run: bool,
                  deadline: float) -> None:
    while time.monotonic() < deadline:
        try:
            row = q.get_nowait()
        except asyncio.QueueEmpty:
            return
        verdict, reason = await _fetch_listing(
            session, row["listing_url"], str(row["external_id"]), deadline)
        totals[verdict] += 1
        totals["checked"] += 1
        totals["r_" + reason] += 1
        try:
            await apply_verdict(pool, row["id"], verdict, dry_run)
        except Exception as e:
            logger.warning("apply failed for %s: %s", row["id"], e)
            totals["errors"] += 1
        await asyncio.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
        q.task_done()


async def run_liveness(dry_run: bool = DRY_RUN) -> dict:
    pool = await get_pool()
    async with pool.acquire() as c:
        source_id = await c.fetchval("SELECT id FROM sources WHERE name='kolesa'")
    if source_id is None:
        raise RuntimeError("kolesa source not found")

    totals = {ALIVE: 0, CLOSED: 0, TRANSIENT: 0, "checked": 0, "errors": 0}
    for r in _REASONS:
        totals[r] = 0

    logger.info("liveness start: budget=%.0fmin batch=%d concurrency=%d "
                "req_timeout=%.0fs warm=%s dry_run=%s",
                TIME_BUDGET_MIN, BATCH, CONCURRENCY, REQ_TIMEOUT, WARM, dry_run)

    async with requests.AsyncSession(impersonate="chrome") as session:
        if WARM:
            await _warm_session(session)
        deadline = time.monotonic() + TIME_BUDGET_MIN * 60
        while time.monotonic() < deadline:
            rows = await select_liveness_batch(pool, source_id, BATCH)
            if not rows:
                logger.info("queue drained — all active listings checked")
                break
            q: asyncio.Queue = asyncio.Queue()
            for r in rows:
                q.put_nowait(r)
            await asyncio.gather(*[_worker(q, session, pool, totals, dry_run, deadline)
                                   for _ in range(CONCURRENCY)])
            logger.info("progress: checked=%d alive=%d closed=%d transient=%d "
                        "| ok=%d timeout=%d blocked=%d error=%d",
                        totals["checked"], totals[ALIVE], totals[CLOSED], totals[TRANSIENT],
                        totals["r_ok"], totals["r_timeout"], totals["r_blocked"], totals["r_error"])
            if dry_run:
                logger.info("dry-run: single sample batch processed, stopping")
                break
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
          f"closed={stats['closed']} transient={stats['transient']} errors={stats['errors']} "
          f"| ok={stats['r_ok']} timeout={stats['r_timeout']} "
          f"blocked={stats['r_blocked']} error={stats['r_error']}")
