"""
mycar/parser.py — mycar.kz
Использует официальный JSON REST API: https://api.mycar.kz/api/publications/
Максимально извлекает все доступные поля из богатого API-ответа.
"""
import asyncio, logging, re, unicodedata
from typing import Optional
from parsers.common.http_client import fetch
from parsers.common.db import db_conn, save_listing
from parsers.common.proxy_manager import proxy_manager

logger = logging.getLogger("parser.mycar")
BASE_URL = "https://mycar.kz"
API_URL = "https://api.mycar.kz/cars/api/publications/"
PAGE_SIZE = 50           # API позволяет до 50 на страницу — выгружаем больше за запрос
MAX_PAGES = 600          # 50 × 600 = до 30k объявлений; реальный стоп — data["next"]=null


def _slug(t: Optional[str]) -> Optional[str]:
    if not t:
        return None
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", t.lower()).strip("-")


def _parse_engine_volume(raw) -> Optional[int]:
    """Converts engine volume to cc. Accepts litres (2.0) or cc (2000)."""
    if raw is None:
        return None
    try:
        val = float(str(raw).replace(",", "."))
        return int(val * 1000) if val <= 20 else int(val)
    except (ValueError, TypeError):
        return None


def _parse_item(item: dict) -> Optional[dict]:
    try:
        external_id = str(item.get("id", "")) or None
        brand = item.get("car_mark_name") or item.get("brand_name")
        model = item.get("car_model_name") or item.get("model_name")
        year = item.get("year_manufactured") or item.get("year")
        mileage = item.get("mileage")
        price_raw = item.get("price", "") or ""
        price_kzt = int(float(re.sub(r"[^\d.]", "", str(price_raw)))) if price_raw else None
        city_info = item.get("city_info") or {}
        city = city_info.get("name") if isinstance(city_info, dict) else item.get("city")
        pub_url = item.get("publication_url") or f"{BASE_URL}/announcement/{external_id}"
        title = f"{brand} {model} {year}".strip() if brand else ""

        # Engine volume: API returns litres (2.0) — convert to cc
        engine_volume_cc = _parse_engine_volume(
            item.get("engine_capacity") or item.get("engine_volume")
        )

        # Fuel type
        fuel_type = (
            item.get("fuel_type_name")
            or item.get("fuel_type")
            or (item.get("fuel_type_info") or {}).get("name")
        )

        # Transmission
        transmission = (
            item.get("transmission_type_name")
            or item.get("transmission")
            or (item.get("transmission_info") or {}).get("name")
        )

        # Body type
        body_type = (
            item.get("body_type_name")
            or item.get("body_type")
            or (item.get("body_type_info") or {}).get("name")
        )

        # Drive type
        drive_type = (
            item.get("drive_type_name")
            or item.get("drive_type")
            or (item.get("drive_type_info") or {}).get("name")
        )

        # Color
        color = (
            item.get("color_name")
            or item.get("color")
            or (item.get("color_info") or {}).get("name")
        )

        # Engine power
        engine_power_hp = item.get("engine_power") or item.get("horse_power")

        return {
            "source": "mycar",
            "external_id": external_id,
            "brand_slug": _slug(brand),
            "model_slug": _slug(model),
            "brand_name": brand,
            "model_name": model,
            "title": title,
            "year": year,
            "mileage_km": mileage,
            "price_kzt": price_kzt,
            "city": city,
            "listing_url": pub_url,
            "condition": "used",
            # Новые поля
            "engine_volume_cc": engine_volume_cc,
            "engine_power_hp": engine_power_hp,
            "fuel_type": fuel_type,
            "transmission": transmission,
            "body_type": body_type,
            "drive_type": drive_type,
            "color": color,
        }
    except Exception as e:
        logger.debug("mycar item error: %s", e)
        return None


async def run_parser() -> tuple[int, int]:
    logger.info("Старт mycar.kz (JSON API)")
    await proxy_manager.refresh()
    total = 0
    new_total = 0

    async with db_conn() as conn:
        from curl_cffi import requests
        async with requests.AsyncSession(impersonate="chrome") as sess:
            for page in range(0, MAX_PAGES):
                offset = page * PAGE_SIZE
                try:
                    # use_proxy=False — public REST API mycar отдаёт всем; бесплатные
                    # прокси добавляют 30-45с задержки на retry-цикл, без выигрыша.
                    data = await fetch(
                        API_URL,
                        params={"ordering": "-modified", "limit": PAGE_SIZE, "offset": offset},
                        json=True,
                        use_proxy=False,
                        session=sess,
                    )
                except Exception as e:
                    logger.error("mycar API offset=%d: %s", offset, e)
                    break

                results = data.get("results", []) if isinstance(data, dict) else []
                if not results:
                    logger.info("mycar: нет данных на offset=%d, завершаем.", offset)
                    break

                items = [_parse_item(r) for r in results]
                items = [i for i in items if i and i["external_id"]]
                for item in items:
                    _, is_new = await save_listing(conn, item)
                    total += 1
                    if is_new:
                        new_total += 1

                if page % 10 == 0 or len(items) < PAGE_SIZE:
                    logger.info("mycar offset=%d: %d объявлений (total=%d, new=%d)", offset, len(items), total, new_total)
                await asyncio.sleep(1.0)  # API быстрее чем HTML — короткая пауза

                # API возвращает next=null если страниц больше нет
                if not data.get("next"):
                    logger.info("mycar: next=null на offset=%d — конец фида", offset)
                    break

    logger.info("mycar завершён: %d, новых: %d", total, new_total)
    return total, new_total


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    import time
    from parsers.common.notifier import send_success, send_error
    from parsers.common.run_stats import record_and_alert
    
    start = time.time()
    try:
        total, total_new = asyncio.run(run_parser())
        asyncio.run(send_success("mycar", total, start, time.time(), total_new))
        # Smart-thresholds: запись метрик + алерт при тихой деградации (best-effort)
        asyncio.run(record_and_alert("mycar", total, total_new))
    except Exception as e:
        logger.exception("Парсер mycar упал")
        asyncio.run(send_error("mycar", e))
