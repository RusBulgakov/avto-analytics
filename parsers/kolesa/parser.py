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
import os
import random
import re
import json
import unicodedata
from typing import Optional

from parsers.common.http_client import fetch, IPBlockedError, TarpitError
from parsers.common.db import get_pool, save_listing
from parsers.common.city_normalizer import normalize_city
from parsers.kolesa import early_stop

logger = logging.getLogger("parser.kolesa")

BASE_URL = "https://kolesa.kz"
PAGE_SIZE = 20
MAX_PAGES_PER_CITY = 250  # 250 стр × 20 = 5000 объявлений на город (max на сайте)

# Пауза между страницами внутри одного фида. Workflow'ы задают
# PARSER_REQUEST_DELAY_MIN/MAX давно, но до 2026-08 код их не читал
# (жёстко стояло 2-4 с). Дефолты сохраняют старое локальное поведение.
PAGE_DELAY_MIN = float(os.getenv("PARSER_REQUEST_DELAY_MIN", "2.0"))
PAGE_DELAY_MAX = float(os.getenv("PARSER_REQUEST_DELAY_MAX", "4.0"))

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
    "hyundai", "kia", "genesis", "ssang-yong", "ravon", "daewoo",
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
# ─── City × Brand combinatorial feeds (Phase 2 coverage boost) ───────
# Каждый brand-feed на kolesa упирается в 5000-листинг cap. Toyota ~34k,
# мы видим только 9k через `/cars/toyota/`. Решение: запросить отдельно
# `/cars/toyota/almaty/`, `/cars/toyota/astana/` и т.д. — каждая такая
# комбинация имеет свой 5000-cap. Top-5 городов × top-15 брендов = 75
# новых feeds, которые покрывают ~80% реального gap.
CITY_BRAND_TOP_CITIES = ["almaty", "astana", "shymkent", "taraz", "karaganda"]
CITY_BRAND_TOP_BRANDS = [
    "toyota", "vaz", "hyundai", "kia", "mercedes-benz",
    "volkswagen", "bmw", "chevrolet", "nissan", "lexus",
    "audi", "mitsubishi", "subaru", "daewoo", "honda",
]
CITY_BRAND_FEEDS = [
    f"{brand}/{city}"
    for brand in CITY_BRAND_TOP_BRANDS
    for city in CITY_BRAND_TOP_CITIES
]

# ─── City × Brand × Model для самых "тяжёлых" моделей (Phase 2 coverage) ─
# Toyota Camry в Алматы = 3,200+ объявлений (vs city-brand cap 5k).
# Модельные city-feeds для топ-моделей разбивают heaviest groups дальше.
# 3 топ-города × 10 моделей-тяжеловесов = 30 feeds
CITY_BRAND_MODEL_TOP_CITIES = ["almaty", "astana", "shymkent"]
CITY_BRAND_MODEL_TOP_MODELS = [
    "toyota/camry", "toyota/corolla",
    "toyota/land-cruiser", "toyota/land-cruiser-prado",
    "vaz/2107", "vaz/priora", "vaz/granta",
    "hyundai/accent", "hyundai/sonata", "hyundai/tucson",
]
CITY_BRAND_MODEL_FEEDS = [
    f"{brand_model}/{city}"
    for brand_model in CITY_BRAND_MODEL_TOP_MODELS
    for city in CITY_BRAND_MODEL_TOP_CITIES
]

# Итог: 15 cities + 80 brands + 97 models + 75 city×brand + 30 city×brand×model
# = ~297 уникальных feeds (минус дубли). Дубли обрабатываются ON CONFLICT
# в save_listing — один листинг попадает в несколько feeds, фактически
# сохраняется один раз.
ALL_FEEDS = list(dict.fromkeys(
    CITIES
    + BRAND_FEEDS
    + MODEL_FEEDS
    + CITY_BRAND_FEEDS
    + CITY_BRAND_MODEL_FEEDS
))

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


def _validate_model(model: Optional[str], brand: Optional[str]) -> Optional[str]:
    """
    Возвращает model если он валиден, иначе None.

    Listing всё равно сохраняется (с model_id=NULL в БД через LEFT JOIN),
    данные не теряются — просто не привязываются к мусорной модели.

    Отсекаем:
    - пусто / None / нестрока
    - длина < 2 символов
    - 4-значный год в диапазоне 1990–2030 (попадает в model когда
      name = "Brand 2020 г." и нет реальной submodel)
    - совпадение с brand (kolesa отдаёт "Toyota"/"Toyota" когда submodel
      не извлёк — синтетическая привязка ухудшает аналитику)

    НЕ отсекаем чистые цифры в общем случае — много легитимных моделей
    обозначается числом: Audi 80/100, BMW 525/528/530/535, Mercedes 190,
    Mazda 626/323, Porsche 911, Lada 2107/2114/2110, и т.п. (~20k объявл).

    1-символьные модели сохраняются: Mazda 6/3/2, BMW 3/5/7 — реальные.
    Раньше отсекали → 68 Mazda 6 listings потеряли model_id.
    """
    if not model or not isinstance(model, str):
        return None
    cleaned = model.strip()
    if not cleaned:  # пусто после strip
        return None
    # 4-значный год → не модель (Lada 2107 — 4 цифры, но НЕ в диапазоне годов)
    if re.fullmatch(r"\d{4}", cleaned):
        year_val = int(cleaned)
        if 1990 <= year_val <= 2030:
            return None
    # Совпадение с brand — kolesa так делает когда не извлёк submodel
    if brand and cleaned.lower() == brand.strip().lower():
        return None
    return cleaned


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

        # name: "Toyota Land Cruiser Prado 2018 г." → brand=Toyota, model="Land Cruiser Prado", year=2018
        # Стратегия: brand = первое слово; model = всё между brand и 4-значным годом;
        # year = 4-значное число в диапазоне 1990..2030.
        parts = name.split()
        brand = parts[0] if parts else None
        year = None
        year_idx: Optional[int] = None
        for j, p in enumerate(parts):
            if re.fullmatch(r"\d{4}", p) and 1990 <= int(p) <= 2030:
                year = int(p)
                year_idx = j
                break
        # Title-derived model: всё между brand-словом и годом
        title_model = None
        if year_idx is not None and year_idx > 1:
            title_model = " ".join(parts[1:year_idx]).strip()
        elif len(parts) > 1:
            title_model = parts[1]

        # Из attributes — brand точнее (полные имена брендов), но model часто single-word
        # сокращение (kolesa отдаёт "Land" вместо "Land Cruiser"). Поэтому выбираем
        # самый длинный (по числу слов) из доступных кандидатов.
        attrs = obj.get("attributes") or {}
        brand = attrs.get("brand") or brand
        attr_model = attrs.get("model")

        candidates = [m for m in (title_model, attr_model) if m and isinstance(m, str)]
        model = max(candidates, key=lambda m: len(m.split())) if candidates else None

        # availability: 'В наличии' / 'На заказ' / (other rare) → is_in_stock
        # На заказ — машина ещё не привезена в KZ (часто китайцы / Tesla),
        # цена индикативная, искажает аналитику. Хранится в JSON top-level
        # (search-page), парсить детальную страницу не нужно.
        availability = obj.get("availability")
        if availability == "В наличии":
            is_in_stock = True
        elif availability == "На заказ":
            is_in_stock = False
        else:
            is_in_stock = None

        # Валидация — отсекаем синтетические модели (год, =brand, цифры).
        # При невалидной — model=None → listing сохранится без model_id (LEFT JOIN),
        # данные сохраняются, но мусорные привязки не плодятся.
        model = _validate_model(model, brand)

        price_kzt = obj.get("unitPrice")

        # Город — единая нормализация (parsers/common/city_normalizer):
        # "0"/"" → None, "semei" → "semey", алиас → canonical latin slug
        city = normalize_city(obj.get("city"))

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
            "brand_name": brand,
            "model_name": model,
            "is_in_stock": is_in_stock,
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


async def parse_city(city: str, session, pool, progress: Optional[dict] = None) -> tuple[int, int]:
    """Парсит все страницы для одного города. Каждый вызов берёт свой коннект из пула.

    progress: опциональный shared dict для обновления прогресс-бара в Telegram.
    Ожидаемые ключи: 'pages_done' (int), 'total_saved' (int), 'total_new' (int),
    'active_feeds' (set[str]). parse_city инкрементит их атомарно.
    """
    saved = 0
    new_saved = 0
    consecutive_errors = 0
    pages_ok = 0  # успешно загруженные страницы этого фида (для детекта тарпита)
    MAX_CONSECUTIVE_ERRORS = 5  # >5 подряд = интернет лежит, нет смысла продолжать
    if progress is not None:
        progress['active_feeds'].add(city)

    # ── Phase 2 (t-0017): newest-first + early-stop + курсор — ВСЁ ТОЛЬКО при
    # KOLESA_EARLY_STOP=1. Default 0 → es_enabled=False → ни одна ветка ниже
    # не активна, поведение фида байт-в-байт как раньше.
    # ОПАСНО включать, пока liveness-sweep не работает (t-0016) — глубокие
    # страницы перестанут получать last_seen_at и 168h-deactivate их убьёт.
    # Подробности: parsers/kolesa/early_stop.py (докстринг модуля).
    es_enabled = early_stop.early_stop_enabled()
    tracker = early_stop.EarlyStopTracker(
        enabled=es_enabled, threshold=early_stop.early_stop_pages(),
    )
    sort_query = ""
    cycle = ""
    start_page = 1
    if es_enabled:
        sort_query = early_stop.sort_param()
        cycle = early_stop.cycle_id()
        try:
            async with pool.acquire() as conn:
                start_page = await early_stop.load_cursor(conn, "kolesa", city, cycle) + 1
        except Exception as e:
            logger.warning(
                "kolesa %s: не удалось прочитать parse_cursor (%s) — старт с 1-й страницы",
                city, e,
            )
            start_page = 1
        if start_page > 1:
            logger.info(
                "kolesa %s: цикл %s — продолжаем со страницы %d (parse_cursor)",
                city, cycle, start_page,
            )

    for page in range(start_page, MAX_PAGES_PER_CITY + 1):
        if city == "all":
            url = f"{BASE_URL}/cars/" if page == 1 else f"{BASE_URL}/cars/?page={page}"
        else:
            url = f"{BASE_URL}/cars/{city}/" if page == 1 else f"{BASE_URL}/cars/{city}/?page={page}"
        if es_enabled and sort_query:
            # Сортировка «свежие первыми» — только под флагом (см. выше)
            url += ("&" if "?" in url else "?") + sort_query

        try:
            # use_proxy=False: бесплатные прокси блокируются kolesa и добавляют
            # до 45s задержки на каждую страницу из-за retry-цикла — итого 5+ часов
            # на 15 городов. curl_cffi с Chrome impersonation проходит напрямую.
            html = await fetch(url, use_proxy=False, session=session)
            consecutive_errors = 0  # сбрасываем счётчик при УСПЕШНОЙ загрузке HTML
            pages_ok += 1
        except IPBlockedError:
            # 403/451 → IP в блоке. Не пытаемся retry, а пробрасываем наверх,
            # чтобы run_parser мог сделать pause-and-retry на уровне батча
            # либо аварийно завершиться с exit code 1.
            if progress is not None:
                progress['active_feeds'].discard(city)
            raise
        except Exception as e:
            consecutive_errors += 1
            if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                if pages_ok == 0:
                    # Ни одной успешной страницы за весь фид + серия таймаутов
                    # подряд = tarpit IP-блок (kolesa вешает соединения вместо
                    # 403), а не проблема конкретного фида. Пробрасываем как
                    # IP-блок → run_parser через consecutive_full_fails прервёт
                    # прогон (exit 1, deactivate отменён) за ~15 минут вместо
                    # 12+ часов мёртвых ретраев до GHA-таймаута в 350 мин.
                    logger.error(
                        "kolesa %s: %d таймаутов подряд без единой успешной "
                        "страницы — tarpit IP-блок",
                        city, consecutive_errors,
                    )
                    if progress is not None:
                        progress['active_feeds'].discard(city)
                    raise TarpitError(url) from e
                logger.error(
                    "kolesa %s: %d ошибок подряд — прерываем фид",
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

        # Per-page дельта (для обновления shared progress state)
        page_saved = 0
        page_new = 0

        # Сохраняем с одним retry при ошибке соединения:
        # если соединение умерло (Neon/PgBouncer timeout) — берём свежее из пула.
        for attempt in range(2):
            failed_items = []
            async with pool.acquire() as conn:
                for item in items:
                    try:
                        _, is_new = await save_listing(conn, item)
                        saved += 1
                        page_saved += 1
                        if is_new:
                            new_saved += 1
                            page_new += 1
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

        # Обновляем shared-state для прогресс-бара (атомарно — GIL + asyncio single thread)
        if progress is not None:
            progress['pages_done'] = progress.get('pages_done', 0) + 1
            progress['total_saved'] = progress.get('total_saved', 0) + page_saved
            progress['total_new'] = progress.get('total_new', 0) + page_new

        # ── Phase 2 (t-0017), только при KOLESA_EARLY_STOP=1: записываем курсор
        # после обработанной страницы (best-effort) и проверяем early-stop.
        # «Новый» = is_new из save_listing (INSERT, объявления не было в БД).
        if es_enabled:
            try:
                async with pool.acquire() as conn:
                    await early_stop.save_cursor(conn, "kolesa", city, page, cycle)
            except Exception as e:
                logger.warning("kolesa %s: не удалось записать parse_cursor: %s", city, e)
            if tracker.record_page(page_new):
                logger.info(
                    "kolesa %s стр %d: early-stop — %d подряд страниц без новых объявлений",
                    city, page, tracker.consecutive_zero_pages,
                )
                break

        await asyncio.sleep(random.uniform(PAGE_DELAY_MIN, PAGE_DELAY_MAX))

    if progress is not None:
        progress['active_feeds'].discard(city)

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

    # ── Ротация фидов между прогонами ──
    # kolesa тарпитит GHA-runner уже через ~7 минут (~50 страниц на IP): без
    # ротации каждый прогон успевает обновить ТОЛЬКО первые фиды списка
    # (almaty, karaganda, ...), остальные неделями не получают last_seen_at.
    # Детерминированный сдвиг по GITHUB_RUN_NUMBER (одинаков для всех шардов
    # одного прогона) распределяет «окно до бана» по всем фидам. Ротация —
    # циклическая перестановка того же множества: здоровый полный прогон
    # по-прежнему покрывает все фиды. Локально (без GHA) offset = 0.
    rotation = 0
    run_number = _os.getenv("GITHUB_RUN_NUMBER", "")
    if run_number.isdigit() and ALL_FEEDS:
        # ×37 (взаимно просто с 297): соседние прогоны стартуют с далёких фидов
        rotation = (int(run_number) * 37) % len(ALL_FEEDS)
        if rotation:
            logger.info("Ротация фидов: offset %d (run #%s)", rotation, run_number)
    rotated_feeds = ALL_FEEDS[rotation:] + ALL_FEEDS[:rotation]

    if shard_count < 1 or shard_index < 0 or shard_index >= shard_count:
        logger.warning("Некорректный SHARD_INDEX=%d при SHARD_COUNT=%d — запускаем все фиды",
                       shard_index, shard_count)
        return rotated_feeds, 0, 1

    # Round-robin: фид i идёт в шард (i % shard_count)
    feeds = [f for idx, f in enumerate(rotated_feeds) if idx % shard_count == shard_index]
    return feeds, shard_index, shard_count


def _fmt_duration(sec: float) -> str:
    """Форматирует секунды в '1ч 23м' или '45м 30с'."""
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    return f"{h}ч {m:02d}м" if h else f"{m}м {s:02d}с"


def _render_progress_bar(
    *, source_tag: str, pages_done: int, total_pages_estimate: int,
    feeds_done: int, total_feeds: int, active_feeds: set,
    total_saved: int, total_new: int, elapsed_sec: float,
) -> str:
    """
    Рендерит HTML прогресс-бар.
    Прогресс считается **по фидам** (feeds_done / total_feeds), а не по
    страницам — потому что страницы непредсказуемы (короткий feed = 1 page,
    toyota = 250). Раньше при оценке `len(feeds) * 50` короткие feeds давали
    `pct=1%` и ETA = 17 дней, что выглядело абсурдно.

    ETA — adaptive: предсказывает оставшееся время на основе уже завершённых
    фидов (avg pages per done feed × remaining feeds / current rate).
    """
    # Прогресс по фидам (стабильнее)
    pct = (feeds_done / total_feeds * 100) if total_feeds else 0
    pct = min(pct, 99.9)
    bar_width = 20
    filled = int(bar_width * pct / 100)
    bar = "█" * filled + "░" * (bar_width - filled)

    # Adaptive ETA — экстраполируем по реальному avg pages per done feed
    if feeds_done >= 3 and elapsed_sec > 60 and pages_done > 0:
        avg_pages_per_feed = pages_done / max(1, feeds_done)
        pages_remaining_est = (total_feeds - feeds_done) * avg_pages_per_feed
        rate = pages_done / elapsed_sec  # pages/sec
        eta_str = _fmt_duration(pages_remaining_est / rate) if rate > 0 else "—"
    else:
        eta_str = "—"

    active_str = ", ".join(sorted(active_feeds)[:3]) if active_feeds else "—"
    if len(active_feeds) > 3:
        active_str += f" +{len(active_feeds) - 3}"

    return (
        f"🕷 <b>{source_tag}</b>\n"
        f"<code>[{bar}]</code> {pct:.1f}%\n"
        f"Страниц: {pages_done:,}  •  Фидов: {feeds_done}/{total_feeds}\n"
        f"Сейчас: <i>{active_str}</i>\n"
        f"Сохранено: <b>{total_saved:,}</b>  (+{total_new:,} новых)\n"
        f"Прошло: {_fmt_duration(elapsed_sec)}  |  ETA: {eta_str}"
    )


async def _progress_updater(
    progress: dict, message_id: int, source_tag: str,
    total_pages_estimate: int, total_feeds: int, run_start: float,
    stop_event: asyncio.Event,
):
    """
    Фоновая задача: обновляет Telegram-сообщение каждые 60 сек,
    пока stop_event не установлен.
    """
    from parsers.common.notifier import edit_telegram_message
    import time as _time
    while not stop_event.is_set():
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60)
            break  # получили stop_event
        except asyncio.TimeoutError:
            pass  # прошла 1 минута — обновляем

        try:
            await edit_telegram_message(
                message_id,
                _render_progress_bar(
                    source_tag=source_tag,
                    pages_done=progress.get('pages_done', 0),
                    total_pages_estimate=total_pages_estimate,
                    feeds_done=progress.get('feeds_done', 0),
                    total_feeds=total_feeds,
                    active_feeds=progress.get('active_feeds', set()),
                    total_saved=progress.get('total_saved', 0),
                    total_new=progress.get('total_new', 0),
                    elapsed_sec=_time.time() - run_start,
                ),
            )
        except Exception as e:
            logger.warning("progress_updater: ошибка редактирования: %s", e)


async def run_parser() -> tuple[int, int, bool]:
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
    # Concurrency регулируется через env (workflow задаёт 2 при 3 шардах,
    # чтобы total simultaneous = 6 — предел kolesa anti-bot).
    # Default 3 для local runs (один процесс).
    CITY_CONCURRENCY = int(os.getenv("KOLESA_CITY_CONCURRENCY", "3"))

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
    from parsers.common.notifier import send_telegram_message_with_id, edit_telegram_message
    import time

    pool = await get_pool()

    total_saved = 0
    total_new = 0
    total_batches = (len(feeds) + CITY_CONCURRENCY - 1) // CITY_CONCURRENCY
    # Оценка общего числа страниц для прогресса:
    # средний фид ~50 страниц (города до 250, бренды/модели 5-100).
    # Корректируется автоматически — если парсер кончит раньше, pct достигнет 99.9%
    TOTAL_PAGES_ESTIMATE = len(feeds) * 50

    # Тег источника для прогресс-бара (shard-aware)
    source_tag = (f"kolesa[{shard_index + 1}/{shard_count}]"
                  if shard_count > 1 else "kolesa")

    # Shared state для фонового updater'а
    progress: dict = {
        'pages_done': 0,
        'feeds_done': 0,
        'total_saved': 0,
        'total_new': 0,
        'active_feeds': set(),
    }

    # Отправляем стартовое сообщение → получаем message_id для редактирования
    run_start = time.time()
    progress_msg_id = await send_telegram_message_with_id(
        _render_progress_bar(
            source_tag=source_tag, pages_done=0, total_pages_estimate=TOTAL_PAGES_ESTIMATE,
            feeds_done=0, total_feeds=len(feeds), active_feeds=set(),
            total_saved=0, total_new=0, elapsed_sec=0,
        )
    )

    # Фоновая задача-обновлятель (обновляет Telegram каждые 60 сек)
    stop_event = asyncio.Event()
    updater_task = None
    if progress_msg_id is not None:
        updater_task = asyncio.create_task(
            _progress_updater(
                progress, progress_msg_id, source_tag,
                TOTAL_PAGES_ESTIMATE, len(feeds), run_start, stop_event,
            )
        )

    # Счётчики для детекции IP-блока:
    #   ip_block_events — сколько раз получали IPBlockedError на любом фиде
    #   consecutive_full_fails — сколько подряд батчей провалились на 100%
    ip_block_events = 0
    consecutive_full_fails = 0
    ip_blocked = False  # финальный флаг для exit code

    async def _process_batch(batch_feeds: list[str], session, pool):
        """Прогоняет батч фидов, возвращает (n_saved_added, n_new_added, n_failed, n_ip_blocked)."""
        tasks = [parse_city(feed, session, pool, progress) for feed in batch_feeds]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        b_saved, b_new, b_failed, b_blocked = 0, 0, 0, 0
        for feed, result in zip(batch_feeds, results):
            if isinstance(result, IPBlockedError):
                logger.warning("kolesa %s: IP блок на %s", feed, result.url)
                b_failed += 1
                b_blocked += 1
            elif isinstance(result, Exception):
                logger.error("kolesa %s: фид упал — %s", feed, result)
                b_failed += 1
            else:
                count, new_count = result
                b_saved += count
                b_new += new_count
                progress['feeds_done'] = progress.get('feeds_done', 0) + 1
                logger.info("kolesa %s: итого %d (%d новых)", feed, count, new_count)
        return b_saved, b_new, b_failed, b_blocked

    async with requests.AsyncSession(impersonate="chrome") as session:
        # Разбиваем на батчи — не кладём весь сайт одновременно
        for batch_num, i in enumerate(range(0, len(feeds), CITY_CONCURRENCY)):
            batch = feeds[i : i + CITY_CONCURRENCY]
            logger.info("Батч %d/%d фидов: %s", batch_num + 1, total_batches, batch)

            saved_d, new_d, failed_d, blocked_d = await _process_batch(batch, session, pool)
            total_saved += saved_d
            total_new += new_d
            ip_block_events += blocked_d

            # Анализ результатов батча для health-check
            full_fail = (failed_d == len(batch))
            half_fail = (failed_d / len(batch) >= 0.5)

            if full_fail:
                consecutive_full_fails += 1
            else:
                consecutive_full_fails = 0

            # ── Сценарий A: ≥50% батча упали → длинная пауза, без retry ──
            # Часто spike rate-limit'а — проходит за 1-2 минуты. Не делаем повторный
            # запуск батча (риск двойной нагрузки), просто притормозим перед следующим.
            if half_fail and not full_fail:
                pause = random.uniform(60, 120)
                logger.warning(
                    "Батч %d: %d/%d фидов упали (>50%%) — пауза %.0f с перед следующим батчем",
                    batch_num + 1, failed_d, len(batch), pause,
                )
                await asyncio.sleep(pause)

            # ── Сценарий B: 100% батча упали → возможен IP-блок ──
            if full_fail:
                if consecutive_full_fails >= 2:
                    logger.error(
                        "%d батча подряд упали на 100%% — IP блок подтверждён, прерываем",
                        consecutive_full_fails,
                    )
                    ip_blocked = True
                    break
                # Первый full-fail — длинная пауза, может пройдёт
                pause = random.uniform(120, 180)
                logger.warning(
                    "Батч %d целиком упал — пауза %.0f с (попытка восстановиться)",
                    batch_num + 1, pause,
                )
                await asyncio.sleep(pause)

            # Пауза между батчами: снижает вероятность rate limit для следующего батча
            if i + CITY_CONCURRENCY < len(feeds):
                await asyncio.sleep(random.uniform(8.0, 15.0))

    # Если был хоть один IPBlockedError но не дошли до full_fail — фиксируем
    if ip_block_events > 0 and not ip_blocked:
        logger.warning("Видели %d IP-block событий за прогон (но без подряд-фейлов батчей)", ip_block_events)

    # Останавливаем фоновый updater до финального сообщения
    if updater_task is not None:
        stop_event.set()
        try:
            await asyncio.wait_for(updater_task, timeout=5)
        except asyncio.TimeoutError:
            updater_task.cancel()

    shard_tag = f" SHARD {shard_index + 1}/{shard_count}" if shard_count > 1 else ""
    logger.info("Парсинг kolesa.kz%s завершён. Всего: %d, новых: %d", shard_tag, total_saved, total_new)

    # Финальное обновление прогресс-бара — 100% с итогами
    if progress_msg_id is not None:
        elapsed = time.time() - run_start
        el_m, el_s = divmod(int(elapsed), 60)
        el_h, el_m = divmod(el_m, 60)
        elapsed_str = f"{el_h}ч {el_m:02d}м {el_s:02d}с" if el_h else f"{el_m}м {el_s:02d}с"
        if ip_blocked:
            icon = "🔴"
            status = "ПРЕРВАН (IP блок)"
        else:
            icon = "✅"
            status = "завершён"
        await edit_telegram_message(
            progress_msg_id,
            f"{icon} <b>{source_tag}</b> {status}\n"
            f"<code>[{'█' * 20}]</code>\n"
            f"Сохранено: <b>{total_saved:,}</b>  (+{total_new:,} новых)\n"
            f"Время: {elapsed_str}"
        )

    return total_saved, total_new, ip_blocked


if __name__ == "__main__":
    import sys
    import signal
    from dotenv import load_dotenv
    load_dotenv()  # грузит .env из текущей директории (для локального запуска)
    logging.basicConfig(level=logging.INFO)
    import time
    import os as _os_main
    from parsers.common.notifier import send_error

    # Для осмысленного имени в Telegram уведомлении в случае шардирования
    _shard_count = int(_os_main.getenv("KOLESA_SHARD_COUNT", "1"))
    _shard_index = int(_os_main.getenv("KOLESA_SHARD_INDEX", "0"))
    source_tag = f"kolesa[{_shard_index + 1}/{_shard_count}]" if _shard_count > 1 else "kolesa"

    # ──────────────────────────────────────────────────────────────────────
    # Exit codes (workflow интерпретирует):
    #   0  = успех, deactivate можно запускать
    #   1  = IP блок выявлен (consecutive batch fails) — deactivate ОТМЕНИТЬ
    #   2  = непойманное исключение / DB error
    #  10  = partial success (сохранили <MIN_SAVED_THRESHOLD но >MIN_PARTIAL)
    #        — deactivate ОТМЕНИТЬ
    # ──────────────────────────────────────────────────────────────────────
    MIN_SAVED_THRESHOLD = int(_os_main.getenv("MIN_SAVED_THRESHOLD", "1000"))
    MIN_PARTIAL_THRESHOLD = int(_os_main.getenv("MIN_PARTIAL_THRESHOLD", "100"))

    # ── SIGTERM handler для GHA timeout ──
    # GHA даёт 60 сек после kill-сигнала перед force kill. За это время надо
    # сохранить состояние и закрыть message в Telegram (уже сохранилось как 100%).
    # Регистрируем флаг — главный цикл проверит через event loop.
    _sigterm_received = {'flag': False}

    def _on_sigterm(signum, frame):
        logger.warning("SIGTERM получен — graceful shutdown в процессе")
        _sigterm_received['flag'] = True

    signal.signal(signal.SIGTERM, _on_sigterm)

    start = time.time()
    try:
        total, total_new, ip_blocked = asyncio.run(run_parser())
    except IPBlockedError as e:
        logger.error("IP блок: %s", e)
        asyncio.run(send_error(source_tag, e))
        sys.exit(1)
    except Exception as e:
        logger.exception("Парсер kolesa упал")
        asyncio.run(send_error(source_tag, e))
        sys.exit(2)

    # ── Smart-thresholds: запись метрик прогона + алерт при тихой деградации ──
    # ip_blocked-прогоны не записываем: они прерваны на середине, сравнивать
    # их не с чем, и об IP-блоке уже сигналят exit 1 и 🔴 в Telegram.
    # Partial-прогоны (exit 10) записываются как обычные: status определяет
    # только сравнение с baseline (PARSER_ALERT_DROP_PCT); partial с просадкой
    # меньше порога запишется как 'ok' и станет новым baseline.
    # record_and_alert best-effort — прогон не уронит.
    if not ip_blocked:
        from parsers.common.run_stats import record_and_alert
        asyncio.run(record_and_alert(
            "kolesa", total, total_new,
            shard_index=_shard_index, shard_count=_shard_count,
        ))

    # ── Анализ результата ──
    if ip_blocked:
        logger.error("Парсер прерван по IP-блоку. Exit 1 → deactivate отменён.")
        sys.exit(1)

    if total < MIN_PARTIAL_THRESHOLD:
        logger.error(
            "Сохранено %d < %d — катастрофически мало (вероятно блок). Exit 1.",
            total, MIN_PARTIAL_THRESHOLD,
        )
        sys.exit(1)

    if total < MIN_SAVED_THRESHOLD:
        logger.warning(
            "Partial success: сохранено %d (порог %d). Exit 10 → deactivate отменён.",
            total, MIN_SAVED_THRESHOLD,
        )
        sys.exit(10)

    logger.info("Парсер успешно завершён: %d сохранено, %d новых.", total, total_new)
    sys.exit(0)
