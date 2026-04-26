"""
common/http_client.py
Отказоустойчивый HTTP-клиент с ротацией User-Agent и Proxy.

Стратегия retry зависит от типа ошибки:
  - 403 Forbidden          → IP заблокирован, IPBlockedError (instant fail, no retry)
  - 429 Too Many Requests  → длинный backoff (60–120 с), 3 попытки
  - 5xx                    → стандартный exp backoff (3-12 с), 3 попытки
  - Network/timeout        → exp backoff (3-12 с), 3 попытки
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

# Statuses that trigger a retry. 403 убран — он маркер IP-блока, см. IPBlockedError ниже.
RETRYABLE_5XX = {500, 502, 503, 504}
RATE_LIMIT_STATUSES = {429}
BLOCKED_STATUSES = {403, 451}  # 403 Forbidden, 451 Unavailable For Legal Reasons

MAX_RETRIES = 3
INITIAL_BACKOFF = 3.0           # секунды для 5xx/timeout
JITTER_RANGE = 2.0
RATE_LIMIT_BACKOFF_BASE = 60.0  # для 429: минимум 60 с между попытками


class IPBlockedError(Exception):
    """
    Raised когда ответ говорит что IP в блоке (403/451).
    Парсер должен немедленно прекратить работу — retry бесполезен.
    """
    def __init__(self, url: str, status: int):
        super().__init__(f"IP blocked at {url} (HTTP {status})")
        self.url = url
        self.status = status


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
    GET с ротацией прокси и User-Agent через curl_cffi (impersonate Chrome).
    При ошибке повторяет с экспоненциальной задержкой.

    Returns:
        str (HTML) или dict (JSON).
    Raises:
        IPBlockedError — на 403/451 (instant, без retry).
        Exception      — после исчерпания попыток на других ошибках.
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

            try:
                proxies = {"http": proxy, "https": proxy} if proxy else None

                # asyncio.wait_for — жёсткий дедлайн поверх curl_cffi timeout=30.
                # curl_cffi иногда висит вечно на зависших TCP — wait_for гарантирует
                # принудительную отмену через 35 с.
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

                # ── 403/451: IP в блоке, retry бесполезен ──
                if resp.status_code in BLOCKED_STATUSES:
                    logger.error("[%s] HTTP %d — IP заблокирован, прекращаем", url, resp.status_code)
                    raise IPBlockedError(url, resp.status_code)

                # ── 429: rate limit, длинный backoff ──
                if resp.status_code in RATE_LIMIT_STATUSES:
                    backoff = RATE_LIMIT_BACKOFF_BASE * (1.5 ** retries) + random.uniform(0, 10)
                    logger.warning(
                        "[%s] HTTP 429 rate limit — попытка %d/%d, sleep %.0f с",
                        url, retries + 1, MAX_RETRIES, backoff,
                    )
                    if proxy:
                        proxy_manager.remove(proxy)
                        proxy = proxy_manager.get()
                    retries += 1
                    await asyncio.sleep(backoff)
                    continue

                # ── 5xx: server-side issue, нормальный backoff ──
                if resp.status_code in RETRYABLE_5XX:
                    backoff = INITIAL_BACKOFF * (2 ** retries) + random.uniform(0, JITTER_RANGE)
                    logger.warning(
                        "[%s] HTTP %d — попытка %d/%d, sleep %.1f с",
                        url, resp.status_code, retries + 1, MAX_RETRIES, backoff,
                    )
                    if proxy:
                        proxy_manager.remove(proxy)
                        proxy = proxy_manager.get()
                    retries += 1
                    await asyncio.sleep(backoff)
                    continue

                # ── Success ──
                if json:
                    return resp.json()
                return resp.text

            except IPBlockedError:
                raise  # пробрасываем без retry
            except Exception as e:
                last_exc = e
                backoff = INITIAL_BACKOFF * (2 ** retries) + random.uniform(0, JITTER_RANGE)
                logger.warning(
                    "[%s] %s — попытка %d/%d, sleep %.1f с",
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
            session.close()
