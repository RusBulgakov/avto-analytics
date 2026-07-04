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


# OLX titles написаны хаотично: Cyrillic/Latin/typos/префиксы. Нужен mapper
# на канонический slug. Lookup по фразе lowercase, multi-word сначала.
# 85% missing brand_id в БД ← брали `parts[0]` без валидации, попадало "Продам", "Срочно".
BRAND_LOOKUP = {
    # English (canonical)
    'toyota': 'toyota', 'nissan': 'nissan', 'honda': 'honda',
    'mazda': 'mazda', 'mitsubishi': 'mitsubishi', 'subaru': 'subaru',
    'lexus': 'lexus', 'infiniti': 'infiniti', 'isuzu': 'isuzu',
    'suzuki': 'suzuki', 'daihatsu': 'daihatsu', 'datsun': 'datsun',
    'hyundai': 'hyundai', 'kia': 'kia', 'genesis': 'genesis',
    'daewoo': 'daewoo', 'ravon': 'ravon', 'ssangyong': 'ssang-yong',
    'bmw': 'bmw', 'volkswagen': 'volkswagen', 'audi': 'audi',
    'opel': 'opel', 'porsche': 'porsche', 'mini': 'mini',
    'mercedes': 'mercedes-benz', 'mercedes-benz': 'mercedes-benz',
    'mercedes benz': 'mercedes-benz', 'mersedes': 'mercedes-benz',
    'mersedes benz': 'mercedes-benz', 'mersedes-benz': 'mercedes-benz',
    'renault': 'renault', 'peugeot': 'peugeot', 'citroen': 'citroen',
    'fiat': 'fiat', 'maserati': 'maserati',
    'chevrolet': 'chevrolet', 'ford': 'ford', 'cadillac': 'cadillac',
    'dodge': 'dodge', 'jeep': 'jeep', 'chrysler': 'chrysler',
    'lincoln': 'lincoln', 'gmc': 'gmc', 'hummer': 'hummer', 'tesla': 'tesla',
    'land rover': 'land-rover', 'land-rover': 'land-rover',
    'jaguar': 'jaguar', 'bentley': 'bentley', 'volvo': 'volvo',
    'chery': 'chery', 'geely': 'geely', 'haval': 'haval',
    'great wall': 'great-wall', 'great-wall': 'great-wall',
    'byd': 'byd', 'changan': 'changan', 'jac': 'jac',
    'omoda': 'omoda', 'jaecoo': 'jaecoo', 'jetour': 'jetour', 'exeed': 'exeed',
    'vaz': 'vaz', 'lada': 'vaz', 'gaz': 'gaz', 'uaz': 'uaz', 'zaz': 'zaz',
    'seat': 'seat', 'skoda': 'skoda', 'lifan': 'lifan',
    # Russian Cyrillic (transliterations + slang)
    'тойота': 'toyota', 'ниссан': 'nissan', 'хонда': 'honda',
    'мазда': 'mazda', 'митсубиси': 'mitsubishi', 'митсубиши': 'mitsubishi',
    'митсубиcи': 'mitsubishi', 'субару': 'subaru', 'лексус': 'lexus',
    'инфинити': 'infiniti', 'сузуки': 'suzuki', 'судзуки': 'suzuki',
    'хёндай': 'hyundai', 'хундай': 'hyundai', 'хундэ': 'hyundai',
    'хюндай': 'hyundai', 'кия': 'kia', 'дэу': 'daewoo', 'дэо': 'daewoo',
    'санг йонг': 'ssang-yong', 'санг-йонг': 'ssang-yong',
    'бмв': 'bmw', 'фольксваген': 'volkswagen', 'фолькс': 'volkswagen',
    'ауди': 'audi', 'опель': 'opel', 'порше': 'porsche',
    'мерседес': 'mercedes-benz', 'мерседес-бенц': 'mercedes-benz',
    'мерседес бенц': 'mercedes-benz', 'мерс': 'mercedes-benz',
    'рено': 'renault', 'пежо': 'peugeot', 'ситроен': 'citroen', 'фиат': 'fiat',
    'шевроле': 'chevrolet', 'шеви': 'chevrolet',
    'форд': 'ford', 'кадиллак': 'cadillac', 'крайслер': 'chrysler',
    'додж': 'dodge', 'джип': 'jeep', 'хаммер': 'hummer', 'тесла': 'tesla',
    'лэнд ровер': 'land-rover', 'лэнд-ровер': 'land-rover',
    'ленд ровер': 'land-rover', 'ленд-ровер': 'land-rover',
    'ягуар': 'jaguar', 'бентли': 'bentley', 'вольво': 'volvo',
    'чери': 'chery', 'джили': 'geely', 'хавал': 'haval', 'хавэйл': 'haval',
    'грейт волл': 'great-wall', 'грейт-волл': 'great-wall',
    'бид': 'byd', 'чанган': 'changan',
    'ваз': 'vaz', 'лада': 'vaz', 'жигули': 'vaz',
    'газ': 'gaz', 'уаз': 'uaz', 'москвич': 'moskvich',
    'шкода': 'skoda', 'сеат': 'seat',
}

# Префиксы которые юзеры ставят перед маркой — игнорируем при матчинге
JUNK_PREFIXES = {
    'продам', 'продаю', 'продается', 'продается', 'срочно', 'обмен',
    'торг', 'куплю', 'продается:', 'продается!', 'продаётся',
}


def _extract_brand_and_model(title: str) -> tuple[Optional[str], Optional[str]]:
    """
    Из title типа "Продам Kia Carens 2014" / "Мерседес С-220 кузов 202" /
    "Mersedes benz W224" возвращает (canonical_brand_slug, model_text)
    либо (None, None) если бренд не распознан.
    """
    if not title:
        return None, None
    norm = title.lower()
    # Убираем диакритику для надёжности (ё→е и т.п.)
    norm = norm.replace('ё', 'е')
    words = re.split(r"[\s,]+", norm)
    # Стрипаем junk-префиксы
    while words and words[0] in JUNK_PREFIXES:
        words.pop(0)
    if not words:
        return None, None

    # Ищем бренд: сначала 2-слово (Mercedes Benz, Land Rover), потом 1-слово.
    # Также пробуем не только parts[0], а сканируем первые 3 позиции —
    # на случай "Срочно продам Kia Carens" где не всё убрали JUNK_PREFIXES.
    for start in range(min(3, len(words))):
        for n in (2, 1):
            if start + n <= len(words):
                phrase = ' '.join(words[start:start + n])
                slug = BRAND_LOOKUP.get(phrase)
                if slug:
                    # Модель — следующее за брендом, до года/мусора
                    model_words = words[start + n:]
                    model_clean = []
                    for w in model_words:
                        if re.fullmatch(r"(19|20)\d{2}г?\.?", w):
                            break
                        # Стопаем на чисто-русских "продам", "состояние" итп
                        if w in JUNK_PREFIXES or w in {'года', 'г.', 'года.', '-'}:
                            continue
                        model_clean.append(w)
                    model_text = ' '.join(model_clean).strip(' ,.-') or None
                    if model_text and len(model_text) > 50:
                        # Подозрительно длинная "модель" (юзер вписал описание) — отрезаем
                        model_text = model_text.split()[0]
                    return slug, model_text
    return None, None


def _parse_price(raw: str) -> Optional[int]:
    digits = re.sub(r"\D", "", raw)
    return int(digits) if digits else None


def _parse_card(card) -> Optional[dict]:
    """
    Парсит одну карточку OLX. Структура (стабильна на 2026-05):
      [data-cy='l-card'] — корневой div
        ├── id="<numeric_id>"           ← OLX numeric ID, fallback к external_id
        ├── a[href]                      ← ссылка с IDxxx внутри
        ├── p[0]                         ← TITLE
        ├── p[1]                         ← location-date ("Город - 02 апреля 2026 г.")
        ├── p[2]                         ← year + mileage ("2014  - 354 000 км")
        ├── [data-testid='ad-price']     ← price ("1 700 000 тг.")
    """
    try:
        link_tag = card.select_one("a[href]")
        if not link_tag:
            return None
        url = link_tag.get("href", "")
        if not url.startswith("http"):
            url = BASE_URL + url

        # external_id: предпочитаем regex по URL (формат /d/.../IDxxx.html),
        # fallback на numeric id атрибут карточки.
        id_match = re.search(r"ID([A-Za-z0-9]+)", url)
        external_id = id_match.group(1) if id_match else (card.get("id") or None)

        # OLX пишет данные карточки в 3 фиксированных <p> тега (с 2025-04).
        # Старые селекторы h6/h4/[data-cy='ad-card-title'] больше не работают —
        # это причина 85% missing brand_id и 6% empty titles в БД.
        ps = card.find_all("p")
        title_text = ps[0].get_text(strip=True) if len(ps) >= 1 else ""
        loc_text = ps[1].get_text(strip=True) if len(ps) >= 2 else ""
        year_mileage_text = ps[2].get_text(strip=True) if len(ps) >= 3 else ""

        # Brand/model через нормализацию: title-ы хаотичны (Cyrillic/Latin/typos/префиксы).
        brand_slug, model_text = _extract_brand_and_model(title_text)
        # brand_name выводим из slug (save_listing использует это для INSERT brands)
        brand_name = brand_slug.replace("-", " ").title() if brand_slug else None

        # Год — из p[2] (надёжнее чем из title с user-noise)
        year_match = re.search(r"\b(19|20)\d{2}\b", year_mileage_text or title_text)
        year = int(year_match.group(0)) if year_match else None

        # Пробег — только из p[2], OLX даёт в полных км ("354 000 км")
        mileage_km = None
        m = re.search(r"([\d\s]+)\s*км", year_mileage_text)
        if m:
            try:
                mileage_km = int(re.sub(r"\s", "", m.group(1)))
            except ValueError:
                mileage_km = None

        # Цена
        price_el = card.select_one("[data-testid='ad-price'], [data-testid='priceBlock']")
        price_text = price_el.get_text(strip=True) if price_el else ""
        price_kzt = _parse_price(price_text)

        # Город — из p[1], формат "Город - дата" или "Город, район - дата"
        city = None
        if loc_text:
            cm = re.match(r"^(.+?)\s*-\s*", loc_text)
            if cm:
                city = cm.group(1).strip()
                # Отсекаем район после запятой ("Алматы, Турксибский р-н" → "Алматы")
                city = city.split(",")[0].strip()

        return {
            "source": "olx",
            "external_id": external_id,
            "brand_slug": brand_slug,
            "model_slug": _slug(model_text),
            "brand_name": brand_name,
            "model_name": model_text,
            "title": title_text or None,
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
    from parsers.common.run_stats import record_and_alert
    
    start = time.time()
    try:
        total, total_new = asyncio.run(run_parser())
        asyncio.run(send_success("olx", total, start, time.time(), total_new))
        # Smart-thresholds: запись метрик + алерт при тихой деградации (best-effort)
        asyncio.run(record_and_alert("olx", total, total_new))
    except Exception as e:
        logger.exception("Парсер olx упал")
        asyncio.run(send_error("olx", e))
