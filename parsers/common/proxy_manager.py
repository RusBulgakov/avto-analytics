"""
common/proxy_manager.py
Менеджер бесплатных прокси: скачивает актуальный список,
проверяет работоспособность и выдаёт рабочий прокси.
"""
import asyncio
import logging
import random
from typing import Optional

import aiohttp

logger = logging.getLogger(__name__)

# Публичные источники бесплатных HTTP-прокси
PROXY_SOURCES = [
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
]

CHECK_URL = "https://httpbin.org/ip"
CHECK_TIMEOUT = 5


class ProxyManager:
    """Синглтон-менеджер для пула рабочих прокси."""

    def __init__(self):
        self._working_proxies: list[str] = []

    async def refresh(self) -> None:
        """Скачивает и проверяет прокси из всех источников."""
        raw: list[str] = []
        async with aiohttp.ClientSession() as session:
            for url in PROXY_SOURCES:
                try:
                    async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as r:
                        text = await r.text()
                        raw.extend(line.strip() for line in text.splitlines() if line.strip())
                except Exception as e:
                    logger.warning("Не удалось загрузить прокси из %s: %s", url, e)

        logger.info("Загружено %d сырых прокси, начинаю проверку...", len(raw))
        # Фиксируем порядок одним list — set() каждый раз даёт разный порядок,
        # из-за чего zip(set(raw), results) мог паровать не те прокси с результатами.
        unique_proxies = list(set(raw))
        sem = asyncio.Semaphore(200)  # не более 200 одновременных проверок
        tasks = [self._check(proxy, sem) for proxy in unique_proxies]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        self._working_proxies = [p for p, ok in zip(unique_proxies, results) if ok is True]
        logger.info("Рабочих прокси: %d", len(self._working_proxies))

    async def _check(self, proxy: str, sem: asyncio.Semaphore | None = None) -> bool:
        """Возвращает True, если прокси работает."""
        async def _do_check(session: aiohttp.ClientSession) -> bool:
            try:
                async with session.get(
                    CHECK_URL,
                    proxy=f"http://{proxy}",
                    timeout=aiohttp.ClientTimeout(total=CHECK_TIMEOUT),
                ) as r:
                    return r.status == 200
            except Exception:
                return False

        if sem is not None:
            async with sem:
                async with aiohttp.ClientSession() as session:
                    return await _do_check(session)
        else:
            async with aiohttp.ClientSession() as session:
                return await _do_check(session)

    def get(self) -> Optional[str]:
        """Возвращает случайный рабочий прокси или None."""
        if not self._working_proxies:
            return None
        proxy = random.choice(self._working_proxies)
        return f"http://{proxy}"

    def remove(self, proxy: str) -> None:
        """Удаляет плохой прокси из пула."""
        url = proxy.replace("http://", "")
        try:
            self._working_proxies.remove(url)
        except ValueError:
            pass


proxy_manager = ProxyManager()
