import asyncio
import os

from parsers.common.db import db_conn, deactivate_old_listings


async def main():
    """
    CLI entry point для деактивации stale-объявлений.

    Env-переменные:
        DEACTIVATE_THRESHOLD_HOURS  — порог "stale" в часах (default 168 = 7 дней)
        DEACTIVATE_SOURCE           — деактивировать только этот source (например, "kolesa")
        DEACTIVATE_EXCLUDE_SOURCES  — comma-separated, деактивировать всё КРОМЕ перечисленного
                                       (используется в daily_parsers.yml: "kolesa", чтобы
                                        падение kolesa-парсера не сносило его данные)

    Если ни SOURCE, ни EXCLUDE не заданы — деактивируем ВСЁ (для ручного запуска).
    """
    try:
        hours = int(os.getenv("DEACTIVATE_THRESHOLD_HOURS", "168"))
        source = os.getenv("DEACTIVATE_SOURCE", "").strip() or None
        exclude_raw = os.getenv("DEACTIVATE_EXCLUDE_SOURCES", "").strip()
        exclude_sources = [s.strip() for s in exclude_raw.split(",") if s.strip()] or None

        if source:
            scope_desc = f"source={source}"
        elif exclude_sources:
            scope_desc = f"all EXCEPT {','.join(exclude_sources)}"
        else:
            scope_desc = "all sources"

        async with db_conn() as conn:
            print(
                f"Запуск деактивации старых объявлений "
                f"(last_seen_at < {hours}h, scope: {scope_desc})..."
            )
            count = await deactivate_old_listings(
                conn,
                hours_threshold=hours,
                source=source,
                exclude_sources=exclude_sources,
            )
            print(f"Деактивировано старых объявлений: {count}")
    except Exception as e:
        print(f"Ошибка при деактивации: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
