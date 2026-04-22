import asyncio
from parsers.common.db import db_conn, deactivate_old_listings

async def main():
    try:
        import os
        hours = int(os.getenv("DEACTIVATE_THRESHOLD_HOURS", "168"))
        async with db_conn() as conn:
            print(f"Запуск деактивации старых объявлений (last_seen_at < {hours} hours)...")
            count = await deactivate_old_listings(conn, hours_threshold=hours)
            print(f"Деактивировано старых объявлений: {count}")
    except Exception as e:
        print(f"Ошибка при деактивации: {e}")

if __name__ == "__main__":
    asyncio.run(main())
