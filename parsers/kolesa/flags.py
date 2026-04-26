"""
parsers/kolesa/flags.py — извлекает реальные флаги объявлений с kolesa.kz через
их собственные search-фильтры:
  - ?need-repair=1   → 'аварийная / не на ходу' (~3,400 объявлений на 04.2026)
  - ?auto-custom=1   → 'не растаможенный'        (~5,000 объявлений)

Вместо парсинга 53k detail-страниц (медленно, ~5 часов) — собираем 2 фида
search-результатов (~430 страниц вместе, ~15 минут), получаем точные ID-сеты
"плохих" объявлений и массово обновляем флаги в БД:

  is_emergency        BOOLEAN  -- TRUE = аварийная или не на ходу
  is_customs_cleared  BOOLEAN  -- FALSE = не растаможенная
  flags_updated_at    TIMESTAMPTZ

Logic:
  1. Default-marking: ВСЕ active kolesa-listings → emergency=FALSE, customs=TRUE
  2. Override через ID-сеты: emergency=TRUE для need-repair-IDs, customs=FALSE
     для auto-custom=1-IDs.

Аналитические endpoints используют эти флаги вместо title-keyword + price-outlier
эвристики (которая остаётся как fallback для не-kolesa источников и для kolesa-
объявлений со старым `flags_updated_at < N часов` или NULL).
"""
import asyncio
import logging
import os
import random
import re
import time
from typing import Optional

from curl_cffi import requests

from parsers.common.db import get_pool
from parsers.common.http_client import USER_AGENTS

logger = logging.getLogger("flags.kolesa")

BASE_URL = "https://kolesa.kz"
PAGE_SIZE = 20  # kolesa возвращает ~20 listings на page
MAX_PAGES = int(os.getenv("KOLESA_FLAGS_MAX_PAGES", "300"))  # safety cap
DELAY_MIN = float(os.getenv("KOLESA_FLAGS_DELAY_MIN", "1.0"))
DELAY_MAX = float(os.getenv("KOLESA_FLAGS_DELAY_MAX", "2.5"))
TIMEOUT = 30


async def _fetch_page(session, url: str, page: int) -> Optional[str]:
    """GET одной страницы фильтра. Returns HTML or None."""
    headers = {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
    }
    sep = "&" if "?" in url else "?"
    page_url = url if page == 1 else f"{url}{sep}page={page}"
    try:
        resp = await asyncio.wait_for(
            session.get(page_url, headers=headers, timeout=TIMEOUT),
            timeout=TIMEOUT + 5,
        )
        if resp.status_code != 200:
            logger.warning("Got HTTP %d on %s", resp.status_code, page_url)
            return None
        return resp.text
    except Exception as e:
        logger.warning("fetch failed %s: %s", page_url, e)
        return None


async def collect_filter_ids(session, filter_url: str, label: str) -> set[str]:
    """Парсит все pages фильтра, возвращает set of external_ids."""
    ids: set[str] = set()
    consecutive_empty = 0
    for page in range(1, MAX_PAGES + 1):
        html = await _fetch_page(session, filter_url, page)
        if not html:
            consecutive_empty += 1
            if consecutive_empty >= 3:
                logger.error("[%s] 3 errors in a row, stopping at page %d", label, page)
                break
            await asyncio.sleep(random.uniform(DELAY_MIN * 2, DELAY_MAX * 2))
            continue
        consecutive_empty = 0
        page_ids = set(re.findall(r'/a/show/(\d+)', html))
        if not page_ids:
            logger.info("[%s] page %d empty — stop", label, page)
            break
        new_count = len(page_ids - ids)
        ids.update(page_ids)
        if new_count == 0:
            # OLX-style зацикленная пагинация — все ID мы уже видели
            logger.info("[%s] page %d — все ID уже виделись, stop", label, page)
            break
        if page % 20 == 0 or page == 1:
            logger.info("[%s] page %d: +%d new (total=%d)", label, page, new_count, len(ids))
        await asyncio.sleep(random.uniform(DELAY_MIN, DELAY_MAX))
    logger.info("[%s] collected %d unique IDs across %d pages", label, len(ids), page)
    return ids


async def apply_flags(pool, emergency_ids: set[str], not_cleared_ids: set[str]) -> dict:
    """
    Атомарно обновляет флаги в БД:
      1. ALL active kolesa → emergency=FALSE, customs=TRUE, flags_updated_at=NOW()
      2. emergency_ids → emergency=TRUE
      3. not_cleared_ids → customs=FALSE
    """
    async with pool.acquire() as conn:
        # Шаг 1: default-mark — kolesa source_id
        kolesa_id = await conn.fetchval("SELECT id FROM sources WHERE name = 'kolesa'")
        if not kolesa_id:
            raise RuntimeError("source 'kolesa' not found in sources table")

        baseline_result = await conn.execute("""
            UPDATE listings
            SET is_emergency = FALSE,
                is_customs_cleared = TRUE,
                flags_updated_at = NOW()
            WHERE source_id = $1 AND is_active = TRUE
        """, kolesa_id)
        baseline_n = int(baseline_result.split()[1]) if baseline_result.startswith("UPDATE") else 0

        # Шаг 2: override is_emergency=TRUE для собранных IDs
        if emergency_ids:
            res = await conn.execute("""
                UPDATE listings
                SET is_emergency = TRUE, flags_updated_at = NOW()
                WHERE source_id = $1 AND external_id = ANY($2::text[])
            """, kolesa_id, list(emergency_ids))
            emergency_n = int(res.split()[1]) if res.startswith("UPDATE") else 0
        else:
            emergency_n = 0

        # Шаг 3: override is_customs_cleared=FALSE для собранных IDs
        if not_cleared_ids:
            res = await conn.execute("""
                UPDATE listings
                SET is_customs_cleared = FALSE, flags_updated_at = NOW()
                WHERE source_id = $1 AND external_id = ANY($2::text[])
            """, kolesa_id, list(not_cleared_ids))
            not_cleared_n = int(res.split()[1]) if res.startswith("UPDATE") else 0
        else:
            not_cleared_n = 0

    return {
        "baseline_marked": baseline_n,
        "emergency_marked": emergency_n,
        "not_cleared_marked": not_cleared_n,
    }


async def run_flags() -> dict:
    pool = await get_pool()

    logger.info("Старт kolesa flags collection")
    start = time.time()

    async with requests.AsyncSession(impersonate="chrome") as session:
        # Параллельно — оба фильтра
        emergency_task = collect_filter_ids(
            session, f"{BASE_URL}/cars/?need-repair=1", "emergency"
        )
        not_cleared_task = collect_filter_ids(
            session, f"{BASE_URL}/cars/?auto-custom=1", "not_cleared"
        )
        emergency_ids, not_cleared_ids = await asyncio.gather(emergency_task, not_cleared_task)

    elapsed_collect = time.time() - start
    logger.info(
        "Collected: emergency=%d, not_cleared=%d in %.0fs",
        len(emergency_ids), len(not_cleared_ids), elapsed_collect,
    )

    stats = await apply_flags(pool, emergency_ids, not_cleared_ids)
    stats["emergency_collected"] = len(emergency_ids)
    stats["not_cleared_collected"] = len(not_cleared_ids)
    stats["elapsed_s"] = round(time.time() - start, 1)

    logger.info("Flags applied: %s", stats)
    return stats


if __name__ == "__main__":
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    try:
        stats = asyncio.run(run_flags())
        print(
            f"✓ Flags collection done in {stats['elapsed_s']}s\n"
            f"  baseline_marked    : {stats['baseline_marked']}\n"
            f"  emergency_collected: {stats['emergency_collected']}\n"
            f"  emergency_marked   : {stats['emergency_marked']}\n"
            f"  not_cleared_collected: {stats['not_cleared_collected']}\n"
            f"  not_cleared_marked : {stats['not_cleared_marked']}\n"
        )
    except Exception as e:
        logger.exception("kolesa flags failed")
        raise
