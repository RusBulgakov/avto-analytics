"""
common/refresh_proxies.py
Standalone скрипт для обновления пула прокси.
Используется в GitHub Actions перед запуском парсеров.
"""
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

from parsers.common.proxy_manager import proxy_manager


async def main():
    print("Обновление пула прокси...")
    await proxy_manager.refresh()
    count = len(proxy_manager._working_proxies)
    print(f"Рабочих прокси: {count}")
    if count == 0:
        print("⚠️ Нет рабочих прокси, парсеры будут работать напрямую")


if __name__ == "__main__":
    asyncio.run(main())
