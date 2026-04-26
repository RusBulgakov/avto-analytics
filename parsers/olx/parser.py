"""
olx/parser.py
Парсер для OLX.kz (раздел Транспорт > Автомобили).
Снимает лимит страниц — парсим до тех пор, пока не придёт пустая страница.
"""
import asyncio
import logging
import random
import re
import unicodedata
from typing import Optional

from bs4 import BeautifulSoup

from parsers.common.http_client import fetch
from parsers.common.db import db_conn, save_listing
from parsers.common.proxy_manager import proxy_manager

logger = logging.getLogger("parser.olx")

BASE_URL = "https://www.olx.kz"
ROOT_LIST = f"{BASE_URL}/transport/legkovye-avtomobili/"
# Per-city feeds. OLX режет глобальную pagination на ~10 страниц (только
# первые ~400 объявлений из десятков тысяч). Чтобы обойти — парсим
# каждый из 15 крупных городов KZ как отдельный фид. Каждый дает свой лимит
# pagination; объединение покрывает весь рынок.
CITY_FEEDS = [
    f"{ROOT_LIST}q-almaty/",
    f"{ROOT_LIST}q-astana/",
    f"{ROOT_LIST}q-shymkent/",
    f"{ROOT_LIST}q-karaganda/",
    f"{ROOT_LIST}q-aktobe/",
    f"{ROOT_LIST}q-taraz/",
    f"{ROOT_LIST}q-pavlodar/",
    f"{ROOT_LIST}q-ust-kamenogorsk/",
    f"{ROOT_LIST}q-semey/",
    f"{ROOT_LIST}q-kostanay/",
    f"{ROOT_LIST}q-atyrau/",
    f"{ROOT_LIST}q-petropavlovsk/",
    f"{ROOT_LIST}q-uralsk/",
    f"{ROOT_LIST}q-aktau/",
    f"{ROOT_LIST}q-kyzylorda/",
]
# Корневой фид + per-city. Корневой даёт топ-listings всего KZ.
ALL_FEEDS = [ROOT_LIST] + CITY_FEEDS
# Per-feed лимит. OLX обычно блочит после 10-25 страниц на одной search.
# Останавливаемся раньше при пустом или повторе.
MAX_PAGES = 30


def _slug(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _parse_price(raw: str) -> Optional[int]:
    digits = re.sub(r"\D", "", raw)
    return int(digits) if digits else None


def _parse_card(card) -> Optional[dict]:
    try:
        link_tag = card.select_one("a[href]")
        if not link_tag:
            return None
        url = link_tag.get("href", "")
        if not url.startswith("http"):
            url = BASE_URL + url

        # ID из URL вида /d/obyavlenie/.../IDqMNaw.html
        # OLX перешёл с числовых ID (ID12345) на буквенно-цифровые (IDqMNaw)
        id_match = re.search(r"ID([A-Za-z0-9]+)", url)
        external_id = id_match.group(1) if id_match else None

        title_el = card.select_one("h6, h4, [data-cy='ad-card-title']")
        title_text = title_el.get_text(strip=True) if title_el else ""

        # Формат обычно "Марка Модель, год"
        clean = re.sub(r",.*", "", title_text)
        parts = clean.split()
        brand = parts[0] if parts else None
        model = parts[1] if len(parts) > 1 else None
        year_match = re.search(r"\b(19|20)\d{2}\b", title_text)
        year = int(year_match.group(0)) if year_match else None

        price_el = card.select_one("[data-testid='ad-price'], .price")
        price_text = price_el.get_text(strip=True) if price_el else ""
        price_kzt = _parse_price(price_text)

        location_el = card.select_one("[data-testid='location-date'], .price-label")
        city = None
        if location_el:
            loc_text = location_el.get_text(strip=True)
            city_match = re.match(r"([^,\d]+)", loc_text)
            if city_match:
                city = city_match.group(1).strip()

        # Пробег: бейдж с числом + "км" или "тыс. км"
        mileage_km = None
        for badge in card.select("[data-testid='ad-card-param'], .css-1xsifub"):
            badge_text = badge.get_text(strip=True)
            km_match = re.search(r"([\d\s]+)\s*(?:тыс\.\s*)?км", badge_text, re.IGNORECASE)
            if km_match:
                km_raw = int(re.sub(r"\s", "", km_match.group(1)))
                # Определяем тысячи км или обычные км
                mileage_km = km_raw * 1000 if "тыс" in badge_text.lower() or km_raw < 1000 else km_raw
                break

        return {
            "source": "olx",
            "external_id": external_id,
            "brand_slug": _slug(brand),
            "model_slug": _slug(model),
            "brand_name": brand,
            "model_name": model,
            "title": title_text,
            "year": year,
            "price_kzt": price_kzt,
            "city": city,
            "listing_url": url,
            "condition": "used",
            "mileage_km": mileage_km,
        }
    except Exception as e:
        logger.debug("Ошибка парсинга карточки OLX: %s", e)
        return None


async def parse_page(feed_url: str, page: int, session=None) -> list[dict]:
    params = {"page": page} if page > 1 else None
    try:
        html = await fetch(feed_url, params=params, use_proxy=True, session=session)
    except Exception as e:
        logger.error("OLX feed=%s page=%d error: %s", feed_url, page, e)
        return []

    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("[data-cy='l-card'], .offer-wrapper")
    results = [_parse_card(c) for c in cards]
    return [r for r in results if r and r["external_id"]]


async def parse_feed(feed_url: str, session, conn, seen_ids: set) -> tuple[int, int]:
    """Один фид (root либо per-city). Останавливается на пустой странице или
    при повторе IDs (OLX иногда зацикливается в pagination)."""
    saved = 0
    new = 0
    for page in range(1, MAX_PAGES + 1):
        listings = await parse_page(feed_url, page, session)
        if not listings:
            logger.info("OLX feed=%s page=%d пусто — стоп.", feed_url, page)
            break

        # Stop-on-repeat: если все ID на странице мы уже видели в этом проходе
        new_ids = [l["external_id"] for l in listings if l["external_id"] not in seen_ids]
        if not new_ids:
            logger.info("OLX feed=%s page=%d — все ID уже виделись, стоп.", feed_url, page)
            break
        for l in listings:
            seen_ids.add(l["external_id"])

        for item in listings:
            _, is_new = await save_listing(conn, item)
            saved += 1
            if is_new:
                new += 1

        logger.info("OLX feed=%s page=%d: %d items (%d новых ID)", feed_url, page, len(listings), len(new_ids))
        await asyncio.sleep(random.uniform(2.5, 5.0))
    return saved, new


async def run_parser() -> tuple[int, int]:
    logger.info("Старт OLX.kz — %d фидов (root + %d городов)", len(ALL_FEEDS), len(CITY_FEEDS))
    await proxy_manager.refresh()
    total_saved = 0
    total_new = 0
    seen_ids: set = set()  # глобальный across-feeds dedup чтобы не дублировать save

    async with db_conn() as conn:
        from curl_cffi import requests
        async with requests.AsyncSession(impersonate="chrome") as session:
            for i, feed in enumerate(ALL_FEEDS):
                logger.info("OLX [%d/%d] feed=%s", i + 1, len(ALL_FEEDS), feed)
                try:
                    s, n = await parse_feed(feed, session, conn, seen_ids)
                    total_saved += s
                    total_new += n
                except Exception as e:
                    logger.error("OLX feed=%s упал: %s", feed, e)
                # Между фидами пауза побольше — OLX может троттлить
                await asyncio.sleep(random.uniform(8.0, 15.0))

    logger.info("OLX завершён. Всего: %d, новых: %d, unique_ids: %d", total_saved, total_new, len(seen_ids))
    return total_saved, total_new


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import time
    from parsers.common.notifier import send_success, send_error
    
    start = time.time()
    try:
        total, total_new = asyncio.run(run_parser())
        asyncio.run(send_success("olx", total, start, time.time(), total_new))
    except Exception as e:
        logger.exception("Парсер olx упал")
        asyncio.run(send_error("olx", e))
