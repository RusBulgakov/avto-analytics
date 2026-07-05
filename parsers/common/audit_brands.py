"""
common/audit_brands.py
Аудит покрытия брендов kolesa-фидами (t-0014). READ-ONLY — только SELECT.

Проблема: kolesa.kz режет пагинацию на 250 стр × 20 = 5000 объявлений на
фид. Популярный бренд БЕЗ собственного feed'а в BRAND_FEEDS виден только
через городские фиды и теряет покрытие. Скрипт находит такие бренды:

  1. Берёт из БД активные бренды kolesa с количеством объявлений
     (фильтр по source_id через подзапрос к sources — НЕ по тексту).
  2. Импортирует фактические фиды из parsers.kolesa.parser
     (BRAND_FEEDS + бренды из MODEL_FEEDS + CITY_BRAND_TOP_BRANDS).
  3. Печатает бренды с > THRESHOLD активных объявлений, у которых
     НЕТ своего фида, по убыванию количества.

Запуск (нужен DATABASE_URL):
    DATABASE_URL=postgres://... python -m parsers.common.audit_brands
    # порог настраивается: --threshold 100 (default)
"""
import argparse
import asyncio

from parsers.common.db import get_pool, close_pool
from parsers.kolesa import parser as kolesa_parser

QUERY = """
SELECT b.slug, b.name, COUNT(*) AS cnt
FROM listings l
JOIN brands b ON l.brand_id = b.id
WHERE l.is_active
  AND l.source_id = (SELECT id FROM sources WHERE name = 'kolesa')
GROUP BY b.slug, b.name
HAVING COUNT(*) > $1
ORDER BY cnt DESC
"""


def covered_brand_slugs() -> set[str]:
    """Slug'и брендов, у которых уже есть хоть один собственный фид."""
    covered = set(kolesa_parser.BRAND_FEEDS)
    covered |= {m.split("/", 1)[0] for m in kolesa_parser.MODEL_FEEDS}
    covered |= set(kolesa_parser.CITY_BRAND_TOP_BRANDS)
    return covered


async def run(threshold: int) -> None:
    covered = covered_brand_slugs()
    pool = await get_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(QUERY, threshold)
    finally:
        await close_pool()

    missing = [r for r in rows if r["slug"] not in covered]

    print(f"Активных брендов kolesa с > {threshold} объявлений: {len(rows)}")
    print(f"Фидов покрывают брендов: {len(covered)}")
    print()
    if not missing:
        print("Все популярные бренды покрыты собственными фидами.")
        return
    print(f"БЕЗ собственного фида ({len(missing)}) — кандидаты в BRAND_FEEDS:")
    print(f"{'slug':<25} {'name':<25} {'active':>8}")
    print("-" * 60)
    for r in missing:
        print(f"{r['slug']:<25} {r['name']:<25} {r['cnt']:>8}")
    print()
    print("Добавить в BRAND_FEEDS (parsers/kolesa/parser.py):")
    print(", ".join(f'"{r["slug"]}"' for r in missing))


def main() -> None:
    ap = argparse.ArgumentParser(description="Аудит брендов без kolesa-фида (read-only)")
    ap.add_argument("--threshold", type=int, default=100,
                    help="минимум активных объявлений (default 100)")
    args = ap.parse_args()
    asyncio.run(run(args.threshold))


if __name__ == "__main__":
    main()
