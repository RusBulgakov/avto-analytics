"""
common/db.py
Подключение к PostgreSQL через asyncpg + контекстный менеджер.

Поддерживает два режима:
  1. DATABASE_URL (Neon / serverless) — единая строка подключения с SSL
  2. POSTGRES_HOST/USER/PASSWORD/DB (Docker) — обратная совместимость
"""
import os
import ssl as _ssl
from contextlib import asynccontextmanager
from typing import AsyncIterator
from urllib.parse import urlparse, parse_qs

import asyncpg

# Единая нормализация городов вынесена в отдельный модуль (t-0014).
# Кириллица ("Алматы") → latin slug ("almaty"); без этого ~1500 listings
# выпадали с карты (geo endpoint матчит по slug'у из _CITY_COORDS).
from parsers.common.city_normalizer import normalize_city

_pool: asyncpg.Pool | None = None


def _parse_database_url(url: str) -> dict:
    """
    Парсит DATABASE_URL и возвращает kwargs для asyncpg.create_pool.
    asyncpg не понимает ?sslmode=require в URL — передаём ssl отдельно.
    """
    parsed = urlparse(url)
    query_params = parse_qs(parsed.query)

    kwargs = {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "user": parsed.username,
        "password": parsed.password,
        "database": parsed.path.lstrip("/"),
    }

    # Neon требует SSL — создаём контекст если sslmode=require
    sslmode = query_params.get("sslmode", [None])[0]
    if sslmode == "require":
        kwargs["ssl"] = _ssl.create_default_context()

    return kwargs


async def get_pool() -> asyncpg.Pool:
    global _pool
    if _pool is None:
        database_url = os.environ.get("DATABASE_URL")

        if database_url:
            # Режим Neon / serverless: единая строка подключения
            connect_kwargs = _parse_database_url(database_url)
            _pool = await asyncpg.create_pool(
                **connect_kwargs,
                min_size=1,
                max_size=5,
                # Neon использует PgBouncer в transaction-pooling режиме.
                # asyncpg кэширует prepared statements по имени, но PgBouncer
                # может перенаправить следующий запрос на другой backend,
                # где этого statement нет → InvalidSQLStatementNameError.
                # Отключаем кэш — запросы чуть медленнее, но стабильны.
                statement_cache_size=0,
                # Neon/PgBouncer закрывает idle-соединения примерно через 5 мин.
                # max_inactive_connection_lifetime=60 заставляет asyncpg
                # пересоздавать соединения, пролежавшие в пуле >60с, — до того
                # как PgBouncer успеет их убить. Без этого при долгих парсингах
                # пул отдаёт мёртвые коннекты → "connection has been released".
                max_inactive_connection_lifetime=60.0,
            )
        else:
            # Режим Docker: отдельные переменные окружения
            _pool = await asyncpg.create_pool(
                host=os.environ["POSTGRES_HOST"],
                port=int(os.environ.get("POSTGRES_PORT", 5432)),
                user=os.environ["POSTGRES_USER"],
                password=os.environ["POSTGRES_PASSWORD"],
                database=os.environ["POSTGRES_DB"],
                min_size=2,
                max_size=10,
            )
    return _pool


async def close_pool() -> None:
    """Корректно закрывает пул соединений."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def db_conn() -> AsyncIterator[asyncpg.Connection]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        yield conn


async def save_listing(conn: asyncpg.Connection, data: dict) -> str:
    """
    Вставляет или обновляет объявление, возвращает UUID листинга.
    Если цена изменилась — записывает новую запись в price_history.
    Автоматически создает связи с брендами и моделями.
    """
    # 0. Нормализация city перед вставкой — гарантирует latin slug в БД
    # независимо от того, что прислал парсер (OLX/mycar часто кириллицу).
    if data.get("city"):
        data = {**data, "city": normalize_city(data["city"])}

    # 1. Upsert бренда
    if data.get("brand_slug"):
        # Use slug.title() as name fallback — more reliable than splitting the full title
        # e.g. "land-rover" → "Land-Rover" vs "Land" from "Land Rover Defender ..."
        brand_slug = data["brand_slug"]
        brand_name = brand_slug.replace("-", " ").title()
        await conn.execute(
            """
            INSERT INTO brands (name, slug) VALUES ($1, $2)
            ON CONFLICT (slug) DO UPDATE SET name = EXCLUDED.name
            """,
            brand_name, brand_slug
        )

    # 2. Upsert модели
    if data.get("brand_slug") and data.get("model_slug"):
        # Предпочитаем model_name которое парсер уже извлёк (multi-word типа
        # "Land Cruiser Prado"). Старые парсеры его не передают — fallback
        # на наивный split title по словам, потом на slug. Naive parts[1]
        # ломал многословные модели ("Toyota Land Cruiser Prado" → "Land").
        model_name = data.get("model_name")
        if not model_name:
            # Fallback: вытащить из title всё между brand и 4-значным годом
            title = data.get("title") or ""
            parts = title.split()
            year_idx = None
            for j, p in enumerate(parts):
                if p.isdigit() and len(p) == 4 and 1990 <= int(p) <= 2030:
                    year_idx = j
                    break
            if year_idx is not None and year_idx > 1:
                model_name = " ".join(parts[1:year_idx]).strip()
            elif len(parts) > 1:
                model_name = parts[1]
            else:
                model_name = data["model_slug"].replace("-", " ").title()

        # ON CONFLICT: если в БД уже многословное имя (например "Land Cruiser
        # Prado"), а парсер прислал укорот ("Land") — НЕ перезаписываем. Берём
        # вариант с большим числом слов; при равенстве — новое.
        await conn.execute(
            """
            INSERT INTO models (brand_id, name, slug)
            SELECT id, $2, $3 FROM brands WHERE slug = $1
            ON CONFLICT (brand_id, slug) DO UPDATE
            SET name = CASE
                WHEN array_length(string_to_array(EXCLUDED.name, ' '), 1) >=
                     COALESCE(array_length(string_to_array(models.name, ' '), 1), 0)
                THEN EXCLUDED.name
                ELSE models.name
            END
            """,
            data["brand_slug"], model_name, data["model_slug"]
        )

    # 3. Upsert листинга
    row = await conn.fetchrow(
        """
        INSERT INTO listings (
            source_id, external_id, brand_id, model_id, title, year, mileage_km,
            engine_volume_cc, engine_power_hp, body_type_id, fuel_type_id,
            transmission_id, drive_type_id, color, city, region, condition,
            listing_url, is_active, last_seen_at, is_in_stock
        )
        SELECT
            s.id, $2, b.id, m.id, $5, $6, $7,
            $8, $9, bt.id, ft.id,
            tt.id, dt.id, $14, $15, $16, $17,
            $18, TRUE, NOW(), $19
        FROM sources s
        LEFT JOIN brands b ON b.slug = $3
        LEFT JOIN models m ON m.slug = $4 AND m.brand_id = b.id
        LEFT JOIN body_types bt ON bt.name = $10
        LEFT JOIN fuel_types ft ON ft.name = $11
        LEFT JOIN transmission_types tt ON tt.name = $12
        LEFT JOIN drive_types dt ON dt.name = $13
        WHERE s.name = $1
        ON CONFLICT (source_id, external_id) DO UPDATE
            SET last_seen_at = NOW(),
                is_active = TRUE,
                -- Обновляем is_in_stock только если парсер прислал известное
                -- значение (TRUE/FALSE). NULL не перезаписывает existing.
                is_in_stock = COALESCE(EXCLUDED.is_in_stock, listings.is_in_stock)
        RETURNING id, (xmax = 0) AS is_new
        """,
        data["source"], data["external_id"],
        data.get("brand_slug"), data.get("model_slug"),
        data.get("title"), data.get("year"), data.get("mileage_km"),
        data.get("engine_volume_cc"), data.get("engine_power_hp"),
        data.get("body_type"), data.get("fuel_type"),
        data.get("transmission"), data.get("drive_type"),
        data.get("color"), data.get("city"), data.get("region"),
        data.get("condition", "used"), data.get("listing_url"),
        data.get("is_in_stock"),
    )

    if not row:
        return None, False

    listing_id = row["id"]
    is_new = row["is_new"]

    price = data.get("price_kzt")
    if listing_id and price:
        # Пишем цену только если она изменилась (или первая запись)
        last_price = await conn.fetchval(
            "SELECT price_kzt FROM price_history WHERE listing_id=$1 ORDER BY recorded_at DESC LIMIT 1",
            listing_id,
        )
        if last_price != price:
            await conn.execute(
                "INSERT INTO price_history (listing_id, price_kzt, price_usd) VALUES ($1, $2, $3)",
                listing_id, price, data.get("price_usd"),
            )

    return listing_id, is_new


async def deactivate_old_listings(
    conn: asyncpg.Connection,
    hours_threshold: int = 168,
    source: str | None = None,
    exclude_sources: list[str] | None = None,
) -> int:
    """
    Деактивирует объявления, которые не обновлялись больше `hours_threshold` часов.
    Проставляет is_active = FALSE и closed_at = NOW().
    Возвращает количество деактивированных записей.

    Default 168h (7 дней). Раньше был 48h, но kolesa.kz глушит пагинацию
    на 250 страниц (= 5000 объявлений на feed), из-за чего модели-тяжеловесы
    (Toyota, Lada, Hyundai) не полностью покрываются за один проход парсера
    и их живые объявления ошибочно помечались неактивными после 2 суток.
    С 7-дневным окном живые объявления успевают попасть хотя бы в один из
    4 ежедневных проходов парсера.

    Args:
        source:           если задан — деактивируем ТОЛЬКО этот source (по name).
                          Используется в kolesa_full.yml: deactivate-old должен
                          трогать только kolesa, чтобы не задеть свежие mycar/olx.
        exclude_sources:  если задан — деактивируем ВСЁ КРОМЕ этих sources.
                          Используется в daily_parsers.yml: kolesa исключается,
                          чтобы падение тяжёлого парсера не убивало живые kolesa-
                          объявления (его deactivate живёт в kolesa_full.yml).

    Если оба параметра не заданы — поведение как раньше: deactivate ВСЕХ source
    (для CLI вызова и совместимости).
    """
    sql = """
        UPDATE listings
        SET is_active = FALSE, closed_at = NOW()
        WHERE is_active = TRUE
          AND last_seen_at < NOW() - make_interval(hours := $1)
    """
    params: list = [hours_threshold]

    if source:
        sql += " AND source_id = (SELECT id FROM sources WHERE name = $2)"
        params.append(source)
    elif exclude_sources:
        sql += " AND source_id NOT IN (SELECT id FROM sources WHERE name = ANY($2::text[]))"
        params.append(exclude_sources)

    closed_count = await conn.execute(sql, *params)
    # Returns a string like "UPDATE 15", we extract the number
    return int(float(closed_count.split()[1])) if closed_count.startswith("UPDATE") else 0
