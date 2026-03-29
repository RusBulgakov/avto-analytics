"""
avtorynok/parser.py
Парсер для avtorynok.kz
Убран жёсткий лимит страниц — стоп по пустой странице.
Добавлено извлечение пробега и объёма двигателя из строки описания.
"""
import asyncio, logging, re, unicodedata
from typing import Optional
from bs4 import BeautifulSoup
from parsers.common.http_client import fetch
from parsers.common.db import db_conn, save_listing
from parsers.common.proxy_manager import proxy_manager

logger = logging.getLogger("parser.avtorynok")
BASE_URL = "https://avtorynok.kz"
LIST_URL = f"{BASE_URL}/cars"
MAX_PAGES = 500  # запасной стоп; реально — по пустой странице


def _slug(t: Optional[str]) -> Optional[str]:
    if not t: return None
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")


def _price(raw: str) -> Optional[int]:
    d = re.sub(r"\D", "", raw)
    return int(d) if d else None


def _parse_engine_volume(text: str) -> Optional[int]:
    """Ищет объём двигателя в строке вида '2.0 / бензин' → 2000 cc."""
    m = re.search(r"(\d+[.,]\d+)\s*(?:л|l)", text, re.IGNORECASE)
    if m:
        try:
            return int(float(m.group(1).replace(",", ".")) * 1000)
        except ValueError:
            pass
    return None


def _parse_mileage(text: str) -> Optional[int]:
    """Ищет пробег в строке вида '150 000 км' или '150 тыс. км'."""
    # 'тыс. км' вариант
    m = re.search(r"([\d\s]+)\s*тыс\.?\s*км", text, re.IGNORECASE)
    if m:
        try:
            return int(re.sub(r"\s", "", m.group(1))) * 1000
        except ValueError:
            pass
    # 'нnnnn км' вариант
    m = re.search(r"([\d\s]{4,})\s*км", text, re.IGNORECASE)
    if m:
        try:
            return int(re.sub(r"\s", "", m.group(1)))
        except ValueError:
            pass
    return None


def _parse_fuel(text: str) -> Optional[str]:
    """Ищет тип топлива в строке описания."""
    lowered = text.lower()
    if "дизел" in lowered:
        return "Дизель"
    if "газ" in lowered or "lpg" in lowered:
        return "Газ"
    if "электр" in lowered:
        return "Электро"
    if "гибрид" in lowered or "hybrid" in lowered:
        return "Гибрид"
    if "бензин" in lowered or "petrol" in lowered:
        return "Бензин"
    return None


def _parse_card(card) -> Optional[dict]:
    try:
        # ID from div id attribute: "message85883" → "85883"
        card_id = card.get("id", "")
        external_id = re.sub(r"\D", "", card_id) or None

        a = card.select_one("a[href]")
        if not a: return None
        href = a["href"]
        url = href if href.startswith("http") else BASE_URL + href

        title_el = card.select_one(".row-messageads--in-001")
        title = title_el.get_text(strip=True) if title_el else ""

        parts = title.split()
        brand = parts[0] if parts else None
        model = parts[1] if len(parts) > 1 else None

        # row-messageads--in-002: "1995 г., Кулан, 2.0 / бензин, 150 000 км ..."
        desc_el = card.select_one(".row-messageads--in-002")
        desc = desc_el.get_text(strip=True) if desc_el else ""

        year_m = re.search(r"\b(19|20)\d{2}\b", desc)
        year = int(year_m.group(0)) if year_m else None

        # city — второй токен через запятую
        desc_parts = [p.strip() for p in desc.split(",")]
        city = desc_parts[1] if len(desc_parts) > 1 else None
        if city:
            city = re.sub(r"\s+г\.", "", city).strip()

        # Новые поля из строки описания
        mileage_km = _parse_mileage(desc)
        engine_volume_cc = _parse_engine_volume(desc)
        fuel_type = _parse_fuel(desc)

        price_el = card.select_one(".row-messageads--in-003")
        price_kzt = _price(price_el.get_text(strip=True)) if price_el else None

        return {
            "source": "avtorynok",
            "external_id": external_id,
            "brand_slug": _slug(brand),
            "model_slug": _slug(model),
            "title": title,
            "year": year,
            "price_kzt": price_kzt,
            "city": city,
            "listing_url": url,
            "condition": "used",
            "mileage_km": mileage_km,
            "engine_volume_cc": engine_volume_cc,
            "fuel_type": fuel_type,
        }
    except Exception as e:
        logger.debug("Ошибка карточки avtorynok: %s", e)
        return None


async def run_parser() -> int:
    logger.info("Старт парсинга avtorynok.kz")
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
                    logger.error("avtorynok стр %d: %s", page, e)
                    break
                soup = BeautifulSoup(html, "lxml")
                cards = soup.select(".row-adsblock")
                items = [_parse_card(c) for c in cards]
                items = [i for i in items if i and i["external_id"]]
                if not items:
                    logger.info("avtorynok стр %d пуста — стоп", page)
                    break
                for item in items:
                    await save_listing(conn, item)
                    total += 1
                logger.info("avtorynok стр %d: %d объявлений", page, len(items))
                await asyncio.sleep(2 + page % 3)
    logger.info("avtorynok завершён: %d", total)
    return total


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import time
    from parsers.common.notifier import send_success, send_error
    
    start = time.time()
    try:
        total = asyncio.run(run_parser())
        asyncio.run(send_success("avtorynok", total, start, time.time()))
    except Exception as e:
        logger.exception("Парсер avtorynok упал")
        asyncio.run(send_error("avtorynok", e))
