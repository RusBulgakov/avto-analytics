import asyncio
from parsers.common.db import db_conn, deactivate_old_listings

async def main():
    try:
        async with db_conn() as conn:
            print("Запуск деактивации старых объявлений (last_seen_at < 48 hours)...")
            count = await deactivate_old_listings(conn, hours_threshold=48)
            print(f"Деактивировано старых объявлений: {count}")
    except Exception as e:
        print(f"Ошибка при деактивации: {e}")

if __name__ == "__main__":
    asyncio.run(main())
