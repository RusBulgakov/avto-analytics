"""
kolesa/parser.py
Парсер для kolesa.kz — извлекает встроенный JSON из HTML.
Колеса вставляет каждое объявление через listing.items.push({...}) внутри тега <script>,
что позволяет не парсить CSS-классы, а читать структурированные данные напрямую.

Стратегия масштабирования:
  - Параллельный сбор по городам (Алматы, Астана, Шымкент, ...)
  - Каждый город даёт до 250 страниц × 20 = 5000 объявлений
  - Итого до ~75 000 за один DAG run (15 городов × 5000)
"""
import asyncio
import logging
import random
import re
import json
import unicodedata
from typing import Optional

from parsers.common.http_client import fetch
from parsers.common.db import db_conn, save_listing
from parsers.common.proxy_manager import proxy_manager

logger = logging.getLogger("parser.kolesa")

BASE_URL = "https://kolesa.kz"
PAGE_SIZE = 20
MAX_PAGES_PER_CITY = 250  # 250 стр × 20 = 5000 объявлений на город (max на сайте)

# Крупные города Казахстана (slug из URL kolesa.kz)
CITIES = [
    "almaty",
    "astana",
    "shymkent",
    "karaganda",
    "aktobe",
    "taraz",
    "ust-kamenogorsk",
    "pavlodar",
    "semey",
    "kostanai",
    "atyrau",
    "petropavlovsk",
    "uralsk",
    "kokshetau",
    "ekibastuz",
]

# Маппинг типов кузова из колес-атрибутов
BODY_TYPE_MAP = {
    "sedan": "Седан",
    "hatchback": "Хэтчбек",
    "suv": "Внедорожник",
    "crossover": "Кроссовер",
    "minivan": "Минивэн",
    "wagon": "Универсал",
    "coupe": "Купе",
    "convertible": "Кабриолет",
    "pickup": "Пикап",
    "van": "Фургон",
}

FUEL_TYPE_MAP = {
    "gasoline": "Бензин",
    "petrol": "Бензин",
    "diesel": "Дизель",
    "gas": "Газ",
    "hybrid": "Гибрид",
    "electric": "Электро",
    "lpg": "Газ",
}

TRANSMISSION_MAP = {
    "automatic": "Автомат",
    "manual": "Механика",
    "variator": "Вариатор",
    "robot": "Робот",
    "mechanic": "Механика",
}

DRIVE_MAP = {
    "front": "Передний",
    "rear": "Задний",
    "full": "Полный",
    "4wd": "Полный",
    "awd": "Полный",
}


def _slug(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _parse_price(raw: str) -> Optional[int]:
    digits = re.sub(r"\D", "", str(raw))
    return int(digits) if digits else None


def _extract_items_from_html(html: str) -> list[dict]:
    """
    Извлекает JSON-данные о листингах из вызовов listing.items.push({...})
    прямо из HTML без CSS-парсинга. Быстро и надёжно.
    """
    items = []
    pattern = re.compile(r'listing\.items\.push\((\{.*?\})\)', re.DOTALL)
    for m in pattern.finditer(html):
        try:
            obj = json.loads(m.group(1))
            items.append(obj)
        except json.JSONDecodeError:
            pass
    return items


def _normalize_map(val: Optional[str], mapping: dict) -> Optional[str]:
    """Normalize a value through a known mapping dict."""
    if not val:
        return None
    key = val.lower().strip()
    return mapping.get(key, val.title())  # fallback: capitalize original


def _parse_engine_volume(raw) -> Optional[int]:
    """Convert engine volume to cc. Accepts '2.0', 2.0 (litres) → 2000 cc."""
    if raw is None:
        return None
    try:
        litres = float(str(raw).replace(",", "."))
        # If already in cc range (>100) — use directly
        if litres > 100:
            return int(litres)
        # Litres → cc
        return int(litres * 1000)
    except (ValueError, TypeError):
        return None


def _parse_item(obj: dict) -> Optional[dict]:
    """Конвертирует JSON-объект из listing.items.push() в структуру для БД."""
    try:
        external_id = str(obj.get("id", "")) or None
        name = obj.get("name", "")

        # name: "Toyota Camry 2022 г." → brand=Toyota, model=Camry, year=2022
        parts = name.split()
        brand = parts[0] if parts else None
        model = parts[1] if len(parts) > 1 else None
        year = None
        for p in parts:
            if re.fullmatch(r"\d{4}", p) and 1990 <= int(p) <= 2030:
                year = int(p)
                break

        # Из attributes — точнее для марки/модели и богатые данные
        attrs = obj.get("attributes") or {}
        brand = attrs.get("brand") or brand
        model = attrs.get("model") or model

        price_kzt = obj.get("unitPrice")

        city = obj.get("city")
        region = obj.get("region")

        # URL
        url = obj.get("url", "").replace("\\/", "/")
        if not url and external_id:
            url = f"{BASE_URL}/a/show/{external_id}"

        # === Дополнительные поля из attributes ===
        # Пробег: атрибут "run" в тысячах км или просто км
        mileage_raw = attrs.get("run") or attrs.get("mileage")
        mileage_km = None
        if mileage_raw is not None:
            try:
                km = int(re.sub(r"\D", "", str(mileage_raw)))
                # Если значение маленькое (< 1000) — вероятно в тысячах км
                mileage_km = km * 1000 if km < 1000 else km
            except (ValueError, TypeError):
                pass

        # Объём двигателя
        engine_volume_cc = _parse_engine_volume(
            attrs.get("engine_volume") or attrs.get("engineDisplacement")
        )

        # Тип топлива
        fuel_type = _normalize_map(
            attrs.get("engine_type") or attrs.get("fuel_type") or attrs.get("car_drive_fuel"),
            FUEL_TYPE_MAP,
        )

        # Трансмиссия
        transmission = _normalize_map(
            attrs.get("transmission") or attrs.get("gearbox"),
            TRANSMISSION_MAP,
        )

        # Тип кузова
        body_type = _normalize_map(
            attrs.get("body") or attrs.get("body_type"),
            BODY_TYPE_MAP,
        )

        # Привод
        drive_type = _normalize_map(
            attrs.get("drive") or attrs.get("drive_type") or attrs.get("car_drive"),
            DRIVE_MAP,
        )

        # Цвет
        color = attrs.get("color") or attrs.get("color_name")
        if color:
            color = color.strip().title()

        return {
            "source": "kolesa",
            "external_id": external_id,
            "brand_slug": _slug(brand),
            "model_slug": _slug(model),
            "title": name,
            "year": year,
            "price_kzt": price_kzt,
            "city": city,
            "region": region,
            "listing_url": url,
            "condition": "new" if obj.get("isNewAuto") else "used",
            # Новые поля
            "mileage_km": mileage_km,
            "engine_volume_cc": engine_volume_cc,
            "fuel_type": fuel_type,
            "transmission": transmission,
            "body_type": body_type,
            "drive_type": drive_type,
            "color": color,
        }
    except Exception as e:
        logger.debug("kolesa item error: %s", e)
        return None


async def parse_city(city: str, session, conn) -> tuple[int, int]:
    """Парсит все страницы для одного города. Возвращает количество (сохранённых, новых)."""
    saved = 0
    new_saved = 0
    for page in range(1, MAX_PAGES_PER_CITY + 1):
        if city == "all":
            url = f"{BASE_URL}/cars/" if page == 1 else f"{BASE_URL}/cars/?page={page}"
        else:
            url = f"{BASE_URL}/cars/{city}/" if page == 1 else f"{BASE_URL}/cars/{city}/?page={page}"

        try:
            html = await fetch(url, use_proxy=True, session=session)
        except Exception as e:
            logger.error("kolesa %s стр %d: %s", city, page, e)
            break

        items_raw = _extract_items_from_html(html)
        if not items_raw:
            logger.info("kolesa %s стр %d: нет объявлений — стоп", city, page)
            break

        items = [_parse_item(o) for o in items_raw]
        items = [i for i in items if i and i["external_id"]]
        for item in items:
            _, is_new = await save_listing(conn, item)
            saved += 1
            if is_new:
                new_saved += 1

        logger.info("kolesa %s стр %d: %d объявлений", city, page, len(items))

        await asyncio.sleep(random.uniform(3.0, 8.0))

    return saved, new_saved


async def run_parser() -> tuple[int, int]:
    """Основная функция — запускает сбор данных по всем городам."""
    logger.info("Старт парсинга kolesa.kz (JSON-режим, %d городов)", len(CITIES))
    await proxy_manager.refresh()

    total_saved = 0
    total_new = 0
    async with db_conn() as conn:
        from curl_cffi import requests
        async with requests.AsyncSession(impersonate="chrome") as session:
            for city in CITIES:
                logger.info("--- Город: %s ---", city)
                count, new_count = await parse_city(city, session, conn)
                total_saved += count
                total_new += new_count
                logger.info("kolesa %s: итого %d (%d новых)", city, count, new_count)
                await asyncio.sleep(random.uniform(5.0, 10.0))

    logger.info("Парсинг kolesa.kz завершён. Всего: %d, новых: %d", total_saved, total_new)
    return total_saved, total_new


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import time
    from parsers.common.notifier import send_success, send_error
    
    start = time.time()
    try:
        total, total_new = asyncio.run(run_parser())
        asyncio.run(send_success("kolesa", total, start, time.time(), total_new))
    except Exception as e:
        logger.exception("Парсер kolesa упал")
        asyncio.run(send_error("kolesa", e))
