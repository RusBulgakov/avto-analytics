"""
common/archive_old.py
Архивация давно-неактивных объявлений в холодные таблицы
listings_archive / price_history_archive (миграция 002).

Зачем: горячая таблица listings распухла до 285k+ строк, Neon free tier
~512 MB. Давно-неактивные (is_active=FALSE и last_seen_at старше порога)
переносятся в архив и удаляются из listings, вместе со своей price_history
(FK ON DELETE CASCADE — иначе история цен была бы молча уничтожена).

Env-переменные:
    ARCHIVE_THRESHOLD_DAYS — порог "давно" в днях (default 30)
    ARCHIVE_BATCH          — размер пачки за транзакцию (default 5000)
    ARCHIVE_DRY_RUN        — "1" (DEFAULT, безопасно): только напечатать
                             план (COUNT + разбивка по source + число строк
                             price_history), НИЧЕГО не писать.
                             "0" — реальный перенос.

Гарантии:
    * План (COUNT + разбивка по source) печатается ВСЕГДА до любой записи
      (правило bulk-SQL из CLAUDE.md).
    * Каждая пачка: INSERT в оба архива + DELETE из listings — в ОДНОЙ
      транзакции. Упали посередине — пачка откатилась целиком.
    * Идемпотентно: повторный прогон после завершения архивирует 0 строк;
      ON CONFLICT DO NOTHING защищает и от аномальных дублей в архиве.

Запуск: PYTHONPATH=. python -m parsers.common.archive_old
"""
import asyncio
import os

import asyncpg

from parsers.common.db import db_conn, close_pool

# Явный список колонок listings (зеркало database/init.sql).
# При добавлении колонки в listings её нужно осознанно добавить сюда,
# в listings_archive (миграция 002) И в database/init.sql — иначе она
# просто не переносится.
LISTING_COLUMNS = [
    "id", "source_id", "external_id", "brand_id", "model_id", "title",
    "year", "mileage_km", "engine_volume_cc", "engine_power_hp",
    "body_type_id", "fuel_type_id", "transmission_id", "drive_type_id",
    "color", "city", "region", "condition", "listing_url", "is_active",
    "first_seen_at", "last_seen_at", "closed_at", "last_checked_at",
    "is_emergency", "is_customs_cleared", "flags_updated_at", "is_in_stock",
]

PRICE_HISTORY_COLUMNS = [
    "id", "listing_id", "price_kzt", "price_usd", "recorded_at",
]

# Условие "кандидат на архивацию". $1 = порог в днях.
# Два варианта: без префикса (запросы только по listings) и с алиасом l.
# (запросы с JOIN sources — там is_active без префикса неоднозначен,
# у sources тоже есть is_active).
_WHERE_ARCHIVABLE = """
    is_active = FALSE
    AND last_seen_at < NOW() - make_interval(days := $1)
"""
_WHERE_ARCHIVABLE_L = """
    l.is_active = FALSE
    AND l.last_seen_at < NOW() - make_interval(days := $1)
"""


async def print_plan(conn: asyncpg.Connection, days: int) -> int:
    """
    Печатает план архивации ДО любой записи: общий COUNT, разбивку
    по source (JOIN sources по source_id — правило CLAUDE.md) и число
    затрагиваемых строк price_history. Возвращает общий COUNT.
    """
    total = await conn.fetchval(
        f"SELECT COUNT(*) FROM listings WHERE {_WHERE_ARCHIVABLE}", days
    )
    print(
        f"План архивации (is_active=FALSE AND last_seen_at < NOW() - {days}d):"
    )
    print(f"  Всего listings под перенос: {total}")

    if total == 0:
        return 0

    rows = await conn.fetch(
        f"""
        SELECT s.name AS source, COUNT(*) AS cnt,
               MIN(l.last_seen_at) AS oldest,
               MAX(l.last_seen_at) AS newest
        FROM listings l
        JOIN sources s ON s.id = l.source_id
        WHERE {_WHERE_ARCHIVABLE_L}
        GROUP BY s.name
        ORDER BY cnt DESC
        """,
        days,
    )
    print("  Разбивка по source:")
    for r in rows:
        print(
            f"    {r['source']:12s} {r['cnt']:>8} шт."
            f"  (last_seen_at: {r['oldest']:%Y-%m-%d} … {r['newest']:%Y-%m-%d})"
        )

    ph_count = await conn.fetchval(
        f"""
        SELECT COUNT(*) FROM price_history
        WHERE listing_id IN (SELECT id FROM listings WHERE {_WHERE_ARCHIVABLE})
        """,
        days,
    )
    print(f"  Строк price_history под перенос: {ph_count}")
    return total


async def archive_batch(
    conn: asyncpg.Connection, days: int, batch_size: int
) -> tuple[int, int]:
    """
    Переносит одну пачку в архив. Всё в одной транзакции:
    INSERT listings_archive + INSERT price_history_archive + DELETE listings
    (DELETE каскадом удаляет price_history — УЖЕ скопированную в архив).
    Возвращает (перенесено listings, перенесено строк price_history).
    """
    cols = ", ".join(LISTING_COLUMNS)
    ph_cols = ", ".join(PRICE_HISTORY_COLUMNS)

    async with conn.transaction():
        # FOR UPDATE SKIP LOCKED: не дедлочимся с параллельно бегущими
        # парсерами/liveness, которые могут держать lock на строке.
        ids = [
            r["id"]
            for r in await conn.fetch(
                f"""
                SELECT id FROM listings
                WHERE {_WHERE_ARCHIVABLE}
                ORDER BY last_seen_at
                LIMIT $2
                FOR UPDATE SKIP LOCKED
                """,
                days, batch_size,
            )
        ]
        if not ids:
            return 0, 0

        await conn.execute(
            f"""
            INSERT INTO listings_archive ({cols})
            SELECT {cols} FROM listings WHERE id = ANY($1::uuid[])
            ON CONFLICT (id) DO NOTHING
            """,
            ids,
        )
        ph_status = await conn.execute(
            f"""
            INSERT INTO price_history_archive ({ph_cols})
            SELECT {ph_cols} FROM price_history
            WHERE listing_id = ANY($1::uuid[])
            ON CONFLICT (id) DO NOTHING
            """,
            ids,
        )
        await conn.execute(
            "DELETE FROM listings WHERE id = ANY($1::uuid[])", ids
        )

    # "INSERT 0 <n>" → n
    ph_moved = int(ph_status.split()[-1]) if ph_status.startswith("INSERT") else 0
    return len(ids), ph_moved


async def main():
    days = int(os.getenv("ARCHIVE_THRESHOLD_DAYS", "30"))
    batch_size = int(os.getenv("ARCHIVE_BATCH", "5000"))
    dry_run = os.getenv("ARCHIVE_DRY_RUN", "1").strip() != "0"

    if days < 7:
        # Deactivate-порог = 7 дней; всё моложе могло не успеть пройти
        # ни одного alive-check/liveness цикла. Защита от опечатки в env.
        raise SystemExit(
            f"ARCHIVE_THRESHOLD_DAYS={days} < 7 — отказ. Слишком свежие "
            f"inactive могут быть ложно-мёртвыми (deactivate threshold 168h)."
        )

    mode = "DRY-RUN (записи НЕ будет)" if dry_run else "РЕАЛЬНЫЙ ПЕРЕНОС"
    print(
        f"Архивация неактивных объявлений: порог {days} дн., "
        f"пачка {batch_size}, режим: {mode}"
    )

    try:
        async with db_conn() as conn:
            total = await print_plan(conn, days)

            if dry_run:
                print("Dry-run завершён — ничего не записано. "
                      "Для реального прогона: ARCHIVE_DRY_RUN=0")
                return
            if total == 0:
                print("Архивировать нечего — выходим.")
                return

            moved_total, ph_total, batch_no = 0, 0, 0
            while True:
                moved, ph_moved = await archive_batch(conn, days, batch_size)
                if moved == 0:
                    break
                batch_no += 1
                moved_total += moved
                ph_total += ph_moved
                print(
                    f"  Пачка {batch_no}: перенесено {moved} listings "
                    f"(+{ph_moved} price_history), всего {moved_total}/{total}"
                )

            print(
                f"Готово: в архив перенесено {moved_total} listings "
                f"и {ph_total} строк price_history."
            )
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
