"""
common/city_dry_run.py
Dry-run нормализации городов по существующим данным (t-0014).
READ-ONLY — только SELECT, НИКАКИХ UPDATE. Обязательный шаг перед любым
bulk-UPDATE городов (правило CLAUDE.md: сначала old → new по всем
distinct, посмотреть глазами, только потом трогать данные).

Печатает все DISTINCT значения listings.city, для которых
normalize_city(old) != old, с количеством строк. Решение о bulk-UPDATE
принимает владелец вручную по этому отчёту.

Запуск (нужен DATABASE_URL):
    DATABASE_URL=postgres://... python -m parsers.common.city_dry_run
"""
import asyncio

from parsers.common.db import get_pool, close_pool
from parsers.common.city_normalizer import normalize_city

QUERY = """
SELECT city, COUNT(*) AS cnt
FROM listings
WHERE city IS NOT NULL
GROUP BY city
ORDER BY cnt DESC
"""


async def run() -> None:
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(QUERY)
    finally:
        await close_pool()

    changed = []
    unchanged_rows = 0
    for r in rows:
        new = normalize_city(r["city"])
        if new != r["city"]:
            changed.append((r["city"], new, r["cnt"]))
        else:
            unchanged_rows += r["cnt"]

    total_changed_rows = sum(c for _, _, c in changed)
    print(f"DISTINCT городов в БД: {len(rows)}")
    print(f"Без изменений: {len(rows) - len(changed)} значений ({unchanged_rows} строк)")
    print(f"Изменились бы: {len(changed)} значений ({total_changed_rows} строк)")
    print()
    if changed:
        print(f"{'old':<40} {'new':<30} {'rows':>8}")
        print("-" * 80)
        for old, new, cnt in changed:
            print(f"{old!r:<40} {str(new)!r:<30} {cnt:>8}")
    print()
    print("Это dry-run: данные НЕ изменялись. Bulk-UPDATE — только вручную")
    print("после просмотра этого отчёта владельцем.")


if __name__ == "__main__":
    asyncio.run(run())
