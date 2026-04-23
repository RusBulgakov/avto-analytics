"""
common/http_client.py
Отказоустойчивый HTTP-клиент с ротацией User-Agent и Proxy,
экспоненциальными задержками при Retry.
"""
import asyncio
import logging
import random
from typing import Any, Optional

from curl_cffi import requests

from .proxy_manager import proxy_manager

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_3_1) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3.1 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36 Edg/121.0.0.0",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_3 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Mobile/15E148 Safari/604.1",
]

RETRYABLE_STATUSES = {403, 429, 500, 502, 503, 504}
MAX_RETRIES = 3
INITIAL_BACKOFF = 3.0  # секунды
JITTER_RANGE = 2.0


def _headers() -> dict[str, str]:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }


async def fetch(
    url: str,
    *,
    params: Optional[dict] = None,
    json: bool = False,
    use_proxy: bool = True,
    session: Optional[requests.AsyncSession] = None,
) -> Any:
    """
    Делает GET-запрос с ротацией прокси и User-Agent через curl_cffi (impersonate Chrome).
    При ошибке повторяет с экспоненциальной задержкой.
    Возвращает str (HTML) или dict (JSON).
    """
    close_session = session is None
    if close_session:
        session = requests.AsyncSession(impersonate="chrome")

    proxy = proxy_manager.get() if use_proxy else None
    retries = 0
    last_exc: Optional[Exception] = None

    try:
        while retries <= MAX_RETRIES:
            headers = _headers()
            backoff = INITIAL_BACKOFF * (2 ** retries) + random.uniform(0, JITTER_RANGE)

            try:
                # curl_cffi proxy format is typically {"http": proxy, "https": proxy} or a string, let's use string
                # or just pass proxy string if it works. requests accepts strings.
                proxies = {"http": proxy, "https": proxy} if proxy else None

                # asyncio.wait_for — жёсткий дедлайн поверх curl_cffi timeout=30.
                # curl_cffi иногда висит вечно на зависших TCP-соединениях
                # (timeout= внутри libcurl не срабатывает). wait_for гарантирует,
                # что корутина будет принудительно отменена через 35 с.
                resp = await asyncio.wait_for(
                    session.get(
                        url,
                        headers=headers,
                        params=params,
                        proxies=proxies,
                        timeout=30,
                    ),
                    timeout=35,
                )
                
                if resp.status_code in RETRYABLE_STATUSES:
                    logger.warning(
                        "[%s] HTTP %d — попытка %d/%d, следующая через %.1f с",
                        url, resp.status_code, retries + 1, MAX_RETRIES, backoff,
                    )
                    if proxy:
                        proxy_manager.remove(proxy)
                        proxy = proxy_manager.get()

                    retries += 1
                    await asyncio.sleep(backoff)
                    continue

                if json:
                    return resp.json()
                return resp.text

            except Exception as e:
                last_exc = e
                logger.warning(
                    "[%s] %s — попытка %d/%d, следующая через %.1f с",
                    url, type(e).__name__, retries + 1, MAX_RETRIES, backoff,
                )
                if proxy:
                    proxy_manager.remove(proxy)
                    proxy = proxy_manager.get()

                retries += 1
                await asyncio.sleep(backoff)

        raise last_exc or Exception(f"Исчерпаны попытки для {url}")
    finally:
        if close_session:
            # curl_cffi AsyncSession doesn't explicitly require await close() but close() is safe
            session.close()
