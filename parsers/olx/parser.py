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
LIST_URL = f"{BASE_URL}/transport/legkovye-avtomobili/"
# Нет жёсткого лимита — останавливаемся по пустой странице
MAX_PAGES = 500


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


async def parse_page(page: int, session=None) -> list[dict]:
    params = {"page": page} if page > 1 else None
    try:
        html = await fetch(LIST_URL, params=params, use_proxy=True, session=session)
    except Exception as e:
        logger.error("OLX страница %d недоступна: %s", page, e)
        return []

    soup = BeautifulSoup(html, "lxml")
    cards = soup.select("[data-cy='l-card'], .offer-wrapper")
    results = [_parse_card(c) for c in cards]
    return [r for r in results if r and r["external_id"]]


async def run_parser() -> tuple[int, int]:
    logger.info("Старт парсинга OLX.kz (без лимита страниц)")
    await proxy_manager.refresh()
    total_saved = 0
    total_new = 0

    async with db_conn() as conn:
        from curl_cffi import requests
        async with requests.AsyncSession(impersonate="chrome") as session:
            for page in range(1, MAX_PAGES + 1):
                listings = await parse_page(page, session)
                if not listings:
                    logger.info("Страница %d OLX пуста — останавливаемся.", page)
                    break
                for item in listings:
                    _, is_new = await save_listing(conn, item)
                    total_saved += 1
                    if is_new:
                        total_new += 1

                logger.info("OLX страница %d: обработано %d объявлений", page, len(listings))

                delay = random.uniform(5.0, 14.0)
                await asyncio.sleep(delay)

    logger.info("Парсинг OLX.kz завершён. Всего: %d, новых: %d", total_saved, total_new)
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
