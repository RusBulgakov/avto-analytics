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
from parsers.common.db import get_pool, save_listing

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

# Все бренды с kolesa.kz — национальный фид /cars/{brand}/
# URL-структура идентична городскому: listing.items.push(...) тот же JSON.
# Даёт доступ ко ВСЕМ объявлениям каждой марки по всему Казахстану.
# Список проверен автоматически — 80 активных брендов на 2026-04-21.
BRAND_FEEDS = [
    # Японские
    "toyota", "nissan", "honda", "mazda", "mitsubishi", "subaru",
    "lexus", "infiniti", "isuzu", "daihatsu", "datsun", "suzuki",
    # Корейские
    "hyundai", "kia", "genesis", "ssang-yong", "ravon",
    # Немецкие
    "bmw", "mercedes-benz", "mercedes-maybach", "volkswagen",
    "audi", "opel", "porsche", "mini",
    # Французские/Итальянские
    "renault", "peugeot", "citroen", "fiat", "maserati",
    # Американские
    "chevrolet", "ford", "cadillac", "dodge", "jeep",
    "chrysler", "lincoln", "gmc", "hummer", "tesla",
    # Британские
    "land-rover", "jaguar", "bentley",
    # Шведские
    "volvo",
    # Китайские
    "chery", "geely", "geely-galaxy", "haval", "great-wall",
    "byd", "changan", "dong-feng", "jac", "faw", "gac",
    "hongqi", "li", "zeekr", "voyah", "wuling", "tank",
    "deepal", "omoda", "jaecoo", "jetour", "exeed",
    "lynk-and-co", "kaiyi", "soueast", "rox", "mg",
    # Советские/Российские
    "vaz",          # ВАЗ (Lada) — 18 706 объявлений
    "gaz",          # ГАЗ — 4 155
    "uaz",          # УАЗ — 758
    "zaz",          # ЗАЗ
    "moskvich",     # Москвич
    # Разные
    "seat", "skoda", "volvo", "lifan",
]

# Модельные фиды для марок-тяжеловесов, где brand-level feed упирается
# в лимит kolesa.kz = 250 страниц × 20 = 5000 объявлений. Без этих subfeed'ов
# 80–90 % Toyota / Lada / Hyundai не попадают в парсинг и протухают как inactive.
# Slug = `brand/model` → URL `/cars/{brand}/{model}/`. Если slug не существует на
# kolesa — фид просто вернёт 0 объявлений и парсер идёт дальше (no-op, safe).
MODEL_FEEDS = [
    # Toyota (топ 10 моделей по количеству объявлений в KZ)
    "toyota/camry", "toyota/corolla",
    "toyota/land-cruiser", "toyota/land-cruiser-prado", "toyota/land-cruiser-100", "toyota/land-cruiser-200",
    "toyota/rav4", "toyota/highlander", "toyota/hilux", "toyota/alphard",
    "toyota/avensis", "toyota/vitz", "toyota/ipsum", "toyota/harrier",
    # Lada — реально большие объёмы, нужны раздельные фиды по поколениям
    "vaz/2107", "vaz/2114", "vaz/2110", "vaz/2112", "vaz/2115", "vaz/2106", "vaz/2109", "vaz/2121",
    "vaz/priora", "vaz/vesta", "vaz/granta", "vaz/kalina", "vaz/largus", "vaz/niva", "vaz/xray",
    # Hyundai
    "hyundai/accent", "hyundai/elantra", "hyundai/sonata", "hyundai/tucson",
    "hyundai/santa-fe", "hyundai/creta", "hyundai/solaris", "hyundai/getz", "hyundai/starex", "hyundai/i30",
    # Kia
    "kia/rio", "kia/cerato", "kia/sportage", "kia/sorento", "kia/optima", "kia/picanto", "kia/k5",
    # Mercedes-Benz — slug на kolesa именно mercedes-benz
    "mercedes-benz/e-class", "mercedes-benz/c-class", "mercedes-benz/s-class",
    "mercedes-benz/ml-class", "mercedes-benz/gl-class", "mercedes-benz/g-class",
    # BMW
    "bmw/3-series", "bmw/5-series", "bmw/7-series", "bmw/x5", "bmw/x3", "bmw/x6",
    # Volkswagen
    "volkswagen/polo", "volkswagen/tiguan", "volkswagen/passat", "volkswagen/jetta", "volkswagen/touareg",
    "volkswagen/golf",
    # Chevrolet — Cobalt / Nexia в KZ массовый сегмент
    "chevrolet/cobalt", "chevrolet/cruze", "chevrolet/aveo", "chevrolet/lacetti",
    "chevrolet/spark", "chevrolet/captiva", "chevrolet/niva",
    # Nissan
    "nissan/x-trail", "nissan/qashqai", "nissan/almera", "nissan/patrol", "nissan/murano", "nissan/juke",
    # Lexus
    "lexus/rx", "lexus/lx", "lexus/es", "lexus/gx",
    # Daewoo Nexia — массовый бюджет-сегмент в KZ
    "daewoo/nexia", "daewoo/matiz",
    # Skoda / Mitsubishi / Audi / Ford
    "skoda/octavia", "skoda/rapid", "skoda/superb",
    "mitsubishi/outlander", "mitsubishi/pajero", "mitsubishi/lancer", "mitsubishi/asx",
    "audi/a6", "audi/a4", "audi/q7", "audi/q5",
    "ford/focus", "ford/escape", "ford/explorer",
]

# Итоговый список задач: сначала города (региональный охват),
# затем все бренды (национальный охват), затем тяжёлые модели (обход лимита 5000/фид).
# ON CONFLICT в save_listing обрабатывает дубли — только обновляет last_seen_at.
ALL_FEEDS = CITIES + list(dict.fromkeys(BRAND_FEEDS)) + MODEL_FEEDS

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


async def parse_city(city: str, session, pool) -> tuple[int, int]:
    """Парсит все страницы для одного города. Каждый вызов берёт свой коннект из пула."""
    saved = 0
    new_saved = 0
    consecutive_errors = 0
    MAX_CONSECUTIVE_ERRORS = 5  # >5 подряд = интернет лежит, нет смысла продолжать
    for page in range(1, MAX_PAGES_PER_CITY + 1):
        if city == "all":
            url = f"{BASE_URL}/cars/" if page == 1 else f"{BASE_URL}/cars/?page={page}"
        else:
            url = f"{BASE_URL}/cars/{city}/" if page == 1 else f"{BASE_URL}/cars/{city}/?page={page}"

        try:
            # use_proxy=False: бесплатные прокси блокируются kolesa и добавляют
            # до 45s задержки на каждую страницу из-за retry-цикла — итого 5+ часов
            # на 15 городов. curl_cffi с Chrome impersonation проходит напрямую.
            html = await fetch(url, use_proxy=False, session=session)
            consecutive_errors = 0  # сбрасываем счётчик при успехе
        except Exception as e:
            consecutive_errors += 1
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                logger.error(
                    "kolesa %s: %d ошибок подряд — интернет недоступен, прерываем фид",
                    city, consecutive_errors,
                )
                break
            logger.warning(
                "kolesa %s стр %d: ошибка сети (%s) — пропускаем [%d/%d]",
                city, page, e, consecutive_errors, MAX_CONSECUTIVE_ERRORS,
            )
            await asyncio.sleep(random.uniform(5.0, 10.0))
            continue

        items_raw = _extract_items_from_html(html)
        if not items_raw:
            logger.info("kolesa %s стр %d: нет объявлений — стоп", city, page)
            break

        items = [_parse_item(o) for o in items_raw]
        items = [i for i in items if i and i["external_id"]]

        # Сохраняем с одним retry при ошибке соединения:
        # если соединение умерло (Neon/PgBouncer timeout) — берём свежее из пула.
        for attempt in range(2):
            failed_items = []
            async with pool.acquire() as conn:
                for item in items:
                    try:
                        _, is_new = await save_listing(conn, item)
                        saved += 1
                        if is_new:
                            new_saved += 1
                    except Exception as e:
                        err = str(e)
                        if "released back to the pool" in err or "connection was closed" in err or "closed in the middle" in err:
                            # Мёртвое соединение — добавим в retry-список, выйдем из блока
                            failed_items.append(item)
                        else:
                            logger.warning("kolesa: не удалось сохранить %s: %s", item.get("external_id"), e)
            if not failed_items:
                break
            if attempt == 0:
                logger.warning("kolesa %s стр %d: %d ошибок соединения, retry со свежим коннектом", city, page, len(failed_items))
                items = failed_items  # повторим только упавшие
            else:
                logger.error("kolesa %s стр %d: %d объявлений потеряно после retry", city, page, len(failed_items))

        logger.info("kolesa %s стр %d: %d объявлений", city, page, len(items))

        await asyncio.sleep(random.uniform(2.0, 4.0))

    return saved, new_saved


def _get_feeds_for_shard() -> tuple[list[str], int, int]:
    """
    Разбивает ALL_FEEDS на шарды по env vars KOLESA_SHARD_INDEX / KOLESA_SHARD_COUNT.
    Используется для параллельного запуска в GitHub Actions matrix.

    Пример: SHARD_COUNT=4, SHARD_INDEX=0 → берём каждый 4-й фид начиная с 0.
    Round-robin распределение даёт балансировку (города, бренды, модели перемешаны).

    Возвращает (feeds_for_this_shard, shard_index, shard_count).
    По умолчанию (нет env vars) → все фиды, один шард.
    """
    import os as _os
    try:
        shard_count = int(_os.getenv("KOLESA_SHARD_COUNT", "1"))
        shard_index = int(_os.getenv("KOLESA_SHARD_INDEX", "0"))
    except ValueError:
        shard_count, shard_index = 1, 0

    if shard_count < 1 or shard_index < 0 or shard_index >= shard_count:
        logger.warning("Некорректный SHARD_INDEX=%d при SHARD_COUNT=%d — запускаем все фиды",
                       shard_index, shard_count)
        return ALL_FEEDS, 0, 1

    # Round-robin: фид i идёт в шард (i % shard_count)
    feeds = [f for idx, f in enumerate(ALL_FEEDS) if idx % shard_count == shard_index]
    return feeds, shard_index, shard_count


async def run_parser() -> tuple[int, int]:
    """Основная функция — запускает сбор данных по всем городам + брендам параллельно.

    Фиды (города + бренды + модели) запускаются батчами по CITY_CONCURRENCY одновременно.
    Каждый фид берёт свой коннект из asyncpg пула → нет конфликтов.
    - Города (15 шт.): региональный охват по крупным городам KZ
    - Бренды (79 шт.): все бренды kolesa.kz — полный национальный охват
    - Модели (97 шт.): тяжёлые модели для обхода лимита 5000/фид
    Итого 191 фид × 5000 max ≈ до 950 000 объявлений за один полный прогон.
    Дубли (объявление появляется в городском и брендовом фидах) — без проблем:
    save_listing использует ON CONFLICT → только обновляет last_seen_at.

    Поддерживает шардирование через KOLESA_SHARD_INDEX / KOLESA_SHARD_COUNT
    для параллельного запуска в GitHub Actions (4 шарда × 3ч = полный прогон ≤ 3ч).
    """
    # 3 параллельных фида вместо 5: GitHub Actions datacenter IP блокируется
    # kolesa.kz при слишком высоком burst rate (5 × req/3s = 100 req/min → timeout).
    # При 3 параллельных = 60 req/min — проходит без блока.
    CITY_CONCURRENCY = 3

    feeds, shard_index, shard_count = _get_feeds_for_shard()

    if shard_count > 1:
        logger.info(
            "Старт kolesa.kz SHARD %d/%d: %d фидов из %d (по %d одновременно)",
            shard_index + 1, shard_count, len(feeds), len(ALL_FEEDS), CITY_CONCURRENCY,
        )
    else:
        logger.info(
            "Старт парсинга kolesa.kz (%d городов + %d брендов + %d моделей = %d фидов, по %d одновременно)",
            len(CITIES), len(BRAND_FEEDS), len(MODEL_FEEDS), len(ALL_FEEDS), CITY_CONCURRENCY,
        )

    from curl_cffi import requests

    pool = await get_pool()

    total_saved = 0
    total_new = 0

    async with requests.AsyncSession(impersonate="chrome") as session:
        # Разбиваем на батчи — не кладём весь сайт одновременно
        for batch_num, i in enumerate(range(0, len(feeds), CITY_CONCURRENCY)):
            batch = feeds[i : i + CITY_CONCURRENCY]
            logger.info("Батч %d/%d фидов: %s", batch_num + 1,
                        (len(feeds) + CITY_CONCURRENCY - 1) // CITY_CONCURRENCY, batch)
            tasks = [parse_city(feed, session, pool) for feed in batch]
            results = await asyncio.gather(*tasks, return_exceptions=True)

            timeout_count = 0
            for feed, result in zip(batch, results):
                if isinstance(result, Exception):
                    logger.error("kolesa %s: фид упал — %s", feed, result)
                    timeout_count += 1
                else:
                    count, new_count = result
                    total_saved += count
                    total_new += new_count
                    logger.info("kolesa %s: итого %d (%d новых)", feed, count, new_count)

            # Если все фиды в батче тайм-аутнули — IP заблокирован, нет смысла продолжать
            if timeout_count == len(batch):
                logger.warning("Все %d фидов в батче тайм-аутнули — вероятно IP заблокирован, завершаем", len(batch))
                break

            # Пауза между батчами: снижает вероятность rate limit для следующего батча
            if i + CITY_CONCURRENCY < len(feeds):
                await asyncio.sleep(random.uniform(8.0, 15.0))

    shard_tag = f" SHARD {shard_index + 1}/{shard_count}" if shard_count > 1 else ""
    logger.info("Парсинг kolesa.kz%s завершён. Всего: %d, новых: %d", shard_tag, total_saved, total_new)
    return total_saved, total_new


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()  # грузит .env из текущей директории (для локального запуска)
    logging.basicConfig(level=logging.INFO)
    import time
    import os as _os_main
    from parsers.common.notifier import send_success, send_error

    # Для осмысленного имени в Telegram уведомлении в случае шардирования
    _shard_count = int(_os_main.getenv("KOLESA_SHARD_COUNT", "1"))
    _shard_index = int(_os_main.getenv("KOLESA_SHARD_INDEX", "0"))
    source_tag = f"kolesa[{_shard_index + 1}/{_shard_count}]" if _shard_count > 1 else "kolesa"

    start = time.time()
    try:
        total, total_new = asyncio.run(run_parser())
        asyncio.run(send_success(source_tag, total, start, time.time(), total_new))
    except Exception as e:
        logger.exception("Парсер kolesa упал")
        asyncio.run(send_error(source_tag, e))
