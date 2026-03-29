"""
newauto/parser.py — newauto.kz (новые автомобили от дилеров)
Исправления:
  - external_id берётся из URL (regex), а не из несуществующего data-id
  - year = текущий год если не найден в title (все авто — новые, текущего года)
  - mileage_km = 0 для всех записей (новые авто)
  - condition = "new" всегда
"""
import asyncio, logging, re, unicodedata
from datetime import date
from typing import Optional
from bs4 import BeautifulSoup
from parsers.common.http_client import fetch
from parsers.common.db import db_conn, save_listing
from parsers.common.proxy_manager import proxy_manager

logger = logging.getLogger("parser.newauto")
BASE_URL = "https://newauto.kz"
LIST_URL = f"{BASE_URL}/catalog"
MAX_PAGES = 100  # запасной лимит; реальный стоп — по пустой странице

CURRENT_YEAR = date.today().year


def _slug(t):
    if not t: return None
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")


def _price(raw):
    d = re.sub(r"\D", "", raw)
    return int(d) if d else None


def _extract_id_from_url(url: str) -> Optional[str]:
    """Извлекает числовой ID из URL страницы объявления."""
    m = re.search(r"/(\d+)(?:[/?#]|$)", url)
    return m.group(1) if m else None


def _card(card):
    try:
        a = card.select_one("a[href]")
        if not a: return None
        href = a["href"]
        url = href if href.startswith("http") else BASE_URL + href

        # ID берём из URL, а не из data-id (его нет)
        eid = _extract_id_from_url(url)

        title_el = card.select_one("h2, h3, .name, .car-name, .title")
        title = title_el.get_text(strip=True) if title_el else ""
        parts = title.split()
        brand = parts[0] if parts else None
        model = parts[1] if len(parts) > 1 else None

        # Год: ищем в title, иначе текущий год (новые авто)
        year_m = re.search(r"\b(19|20)\d{2}\b", title)
        year = int(year_m.group(0)) if year_m else CURRENT_YEAR

        price_el = card.select_one(".price, .amount, .car-price")
        price_kzt = _price(price_el.get_text(strip=True)) if price_el else None

        city_el = card.select_one(".city, .dealer-city, .location")
        city = city_el.get_text(strip=True) if city_el else None

        return {
            "source": "newauto",
            "external_id": eid,
            "brand_slug": _slug(brand),
            "model_slug": _slug(model),
            "title": title,
            "year": year,
            "price_kzt": price_kzt,
            "city": city,
            "listing_url": url,
            "condition": "new",   # newauto.kz — только новые авто
            "mileage_km": 0,      # новые авто = нулевой пробег
        }
    except Exception as e:
        logger.debug("newauto карточка: %s", e)
        return None


async def run_parser() -> int:
    logger.info("Старт newauto.kz (год=%d)", CURRENT_YEAR)
    await proxy_manager.refresh()
    total = 0
    async with db_conn() as conn:
        from curl_cffi import requests
        async with requests.AsyncSession(impersonate="chrome") as sess:
            for page in range(1, MAX_PAGES + 1):
                url = LIST_URL if page == 1 else f"{LIST_URL}?page={page}"
                try:
                    html = await fetch(url, use_proxy=False, session=sess)
                except Exception as e:
                    logger.error("newauto стр %d: %s", page, e)
                    break
                soup = BeautifulSoup(html, "lxml")
                cards = soup.select(".car-card, .item, article, .catalog-item")
                items = [_card(c) for c in cards]
                items = [i for i in items if i and i["external_id"]]
                if not items:
                    logger.info("newauto стр %d пуста — стоп", page)
                    break
                for i in items:
                    await save_listing(conn, i)
                    total += 1
                logger.info("newauto стр %d: %d объявлений", page, len(items))
                await asyncio.sleep(2 + page % 3)
    logger.info("newauto завершён: %d", total)
    return total


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import time
    from parsers.common.notifier import send_success, send_error
    
    start = time.time()
    try:
        total = asyncio.run(run_parser())
        asyncio.run(send_success("newauto", total, start, time.time()))
    except Exception as e:
        logger.exception("Парсер newauto упал")
        asyncio.run(send_error("newauto", e))
