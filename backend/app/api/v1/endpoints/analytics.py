"""
app/api/v1/endpoints/analytics.py
Аналитические эндпоинты: фильтры, графики цен по времени, рентабельность.
"""
from typing import Optional
from fastapi import APIRouter, Query, Depends, HTTPException

from app.core.database import DBSession
from app.core.security import get_current_user, get_pro_user

router = APIRouter(prefix="/analytics", tags=["Analytics"])


@router.get("/brands", summary="Список марок (публичный)")
async def get_brands():
    """Возвращает все марки с количеством активных объявлений."""
    async with DBSession() as conn:
        rows = await conn.fetch("""
            SELECT b.id, b.name, b.slug, COUNT(l.id) AS listings_count
            FROM brands b
            LEFT JOIN listings l ON l.brand_id = b.id AND l.is_active = TRUE
            GROUP BY b.id, b.name, b.slug
            ORDER BY listings_count DESC
        """)
    return [dict(r) for r in rows]


@router.get("/models", summary="Список моделей по марке (публичный)")
async def get_models(brand_id: int = Query(..., description="ID марки")):
    """Возвращает модели для указанной марки."""
    async with DBSession() as conn:
        rows = await conn.fetch("""
            SELECT m.id, m.name, m.slug, COUNT(l.id) AS listings_count
            FROM models m
            LEFT JOIN listings l ON l.model_id = m.id AND l.is_active = TRUE
            WHERE m.brand_id = $1
            GROUP BY m.id, m.name, m.slug
            ORDER BY listings_count DESC
        """, brand_id)
    return [dict(r) for r in rows]


@router.get("/price-history", summary="График изменения средней цены по времени")
async def get_price_history(
    brand_id: list[int] = Query(None),
    model_id: list[int] = Query(None),
    year: list[int] = Query(None, description="Список годов выпуска"),
    mileage_max: Optional[int] = Query(None),
    city: list[str] = Query(None),
    source: list[str] = Query(None, description="kolesa, olx, mycar и т.д."),
    period_days: int = Query(90, ge=7, le=365, description="Глубина истории в днях"),
):
    """
    Базовый публичный график цен. Возвращает daily/weekly среднее за period_days.
    Поддерживает множественный выбор (массивы) для фильтров.
    """
    conditions = ["ph.recorded_at >= NOW() - ($1 * INTERVAL '1 day')"]
    params: list = [period_days]
    i = 2

    if brand_id:
        conditions.append(f"l.brand_id = ANY(${i}::int[])"); params.append(brand_id); i += 1
    if model_id:
        conditions.append(f"l.model_id = ANY(${i}::int[])"); params.append(model_id); i += 1
    if year:
        conditions.append(f"l.year = ANY(${i}::int[])"); params.append(year); i += 1
    if mileage_max:
        conditions.append(f"l.mileage_km <= ${i}"); params.append(mileage_max); i += 1
    if city:
        # Для строк ищем точные совпадения (без LIKE) для массива
        conditions.append(f"l.city = ANY(${i}::text[])"); params.append(city); i += 1
    if source:
        conditions.append(f"s.name = ANY(${i}::text[])"); params.append(source); i += 1

    where = " AND ".join(conditions)
    query = f"""
        SELECT
            DATE_TRUNC('day', ph.recorded_at) AS date,
            ROUND(AVG(ph.price_kzt))::bigint   AS avg_price_kzt,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ph.price_kzt)::bigint AS median_price_kzt,
            COUNT(DISTINCT l.id)               AS listing_count
        FROM price_history ph
        JOIN listings l ON l.id = ph.listing_id
        JOIN sources  s ON s.id = l.source_id
        WHERE {where}
        GROUP BY DATE_TRUNC('day', ph.recorded_at)
        ORDER BY date ASC
    """
    async with DBSession() as conn:
        rows = await conn.fetch(query, *params)
    return [dict(r) for r in rows]


@router.get("/profitability", summary="Оценка рентабельности модели [PRO]",
            dependencies=[Depends(get_pro_user)])
async def get_profitability(
    brand_id: list[int] = Query(...),
    model_id: list[int] = Query(None),
    year: list[int] = Query(None),
):
    """
    PRO: Расчёт процента изменения цены за 30/90 дней,
    медианное время продажи (по дням до закрытия объявления).
    """
    async with DBSession() as conn:
        # Прирост/падение цены за 30 и 90 дней
        price_change = await conn.fetch("""
            WITH latest AS (
                SELECT l.id, MAX(ph.price_kzt) AS price_now
                FROM listings l
                JOIN price_history ph ON ph.listing_id = l.id
                    AND ph.recorded_at >= NOW() - INTERVAL '3 day'
                WHERE l.brand_id = ANY($1::int[])
                  AND ($2::int[] IS NULL OR l.model_id = ANY($2::int[]))
                  AND ($3::int[] IS NULL OR l.year = ANY($3::int[]))
                GROUP BY l.id
            ),
            prev30 AS (
                SELECT l.id, MAX(ph.price_kzt) AS price_30d_ago
                FROM listings l
                JOIN price_history ph ON ph.listing_id = l.id
                    AND ph.recorded_at BETWEEN NOW() - INTERVAL '33 day' AND NOW() - INTERVAL '27 day'
                WHERE l.brand_id = ANY($1::int[])
                  AND ($2::int[] IS NULL OR l.model_id = ANY($2::int[]))
                  AND ($3::int[] IS NULL OR l.year = ANY($3::int[]))
                GROUP BY l.id
            )
            SELECT
                ROUND(AVG(100.0 * (latest.price_now - prev30.price_30d_ago) / NULLIF(prev30.price_30d_ago, 0)), 2)
                    AS price_change_30d_pct,
                COUNT(*) AS sample_size
            FROM latest JOIN prev30 ON latest.id = prev30.id
        """, brand_id, model_id, year)

        # Медианное время продажи (дней)
        median_days = await conn.fetchval("""
            SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (
                ORDER BY EXTRACT(EPOCH FROM (l.closed_at - l.first_seen_at)) / 86400
            )
            FROM listings l
            WHERE l.brand_id = ANY($1::int[])
              AND ($2::int[] IS NULL OR l.model_id = ANY($2::int[]))
              AND ($3::int[] IS NULL OR l.year = ANY($3::int[]))
              AND l.is_active = FALSE
              AND l.closed_at IS NOT NULL
              AND l.closed_at > l.first_seen_at
        """, brand_id, model_id, year)

    return {
        "price_change": dict(price_change[0]) if price_change else {},
        "median_days_to_sell": round(median_days, 1) if median_days else None,
    }


@router.get("/summary", summary="Сводная статистика платформы")
async def get_summary(
    brand_id: list[int] = Query(None),
    city: list[str] = Query(None),
    source: list[str] = Query(None),
    year: list[int] = Query(None)
):
    """Возвращает точные значения для верхних счетчиков: объявления, бренды, средняя цена и источники."""
    
    conditions = ["l.is_active = TRUE"]
    params = []
    i = 1

    if brand_id:
        conditions.append(f"l.brand_id = ANY(${i}::int[])"); params.append(brand_id); i += 1
    if city:
        conditions.append(f"l.city = ANY(${i}::text[])"); params.append(city); i += 1
    if source:
        conditions.append(f"s.name = ANY(${i}::text[])"); params.append(source); i += 1
    if year:
        conditions.append(f"l.year = ANY(${i}::int[])"); params.append(year); i += 1

    where = " AND ".join(conditions)

    async with DBSession() as conn:
        counts = await conn.fetchrow(f"""
             SELECT 
                COUNT(DISTINCT l.id) as active_listings,
                COUNT(DISTINCT l.brand_id) as total_brands,
                ROUND(AVG(ph.price_kzt))::bigint as avg_price_kzt
             FROM listings l
             JOIN sources s ON s.id = l.source_id
             LEFT JOIN price_history ph ON ph.listing_id = l.id
                AND ph.recorded_at >= NOW() - INTERVAL '3 day'
             WHERE {where}
        """, *params)
        
        sources_data = await conn.fetch(f"""
            SELECT s.name, COUNT(l.id) as count
            FROM sources s
            LEFT JOIN listings l ON l.source_id = s.id
            WHERE {where}
            GROUP BY s.name
            ORDER BY count DESC
        """, *params)

    return {
        "active_listings": counts["active_listings"],
        "total_brands": counts["total_brands"],
        "avg_price_kzt": counts["avg_price_kzt"],
        "sources": [dict(s) for s in sources_data]
    }


@router.get("/market-overview", summary="Обзор рынка по маркам/моделям (публичный)")
async def market_overview(
    brand_id: list[int] = Query(None, description="Опциональный массив ID марок"),
    city: list[str] = Query(None),
    source: list[str] = Query(None),
    year: list[int] = Query(None)
):
    """Топ-20 марок по количеству объявлений + средняя цена. С учетом фильтров."""
    
    conditions = ["l.is_active = TRUE"]
    params = []
    i = 1

    if brand_id:
        conditions.append(f"l.brand_id = ANY(${i}::int[])"); params.append(brand_id); i += 1
    if city:
        conditions.append(f"l.city = ANY(${i}::text[])"); params.append(city); i += 1
    if source:
        conditions.append(f"s.name = ANY(${i}::text[])"); params.append(source); i += 1
    if year:
        conditions.append(f"l.year = ANY(${i}::int[])"); params.append(year); i += 1

    where = " AND ".join(conditions)

    async with DBSession() as conn:
        if brand_id and len(brand_id) == 1:
            # Если выбрана ровно одна марка, показываем топ моделей этой марки
            query = f"""
                SELECT
                    m.name AS brand,
                    COUNT(DISTINCT l.id) AS active_listings,
                    ROUND(AVG(ph.price_kzt))::bigint AS avg_price_kzt,
                    MIN(ph.price_kzt) AS min_price_kzt,
                    MAX(ph.price_kzt) AS max_price_kzt
                FROM models m
                JOIN listings l ON l.model_id = m.id
                JOIN sources s ON s.id = l.source_id
                LEFT JOIN price_history ph ON ph.listing_id = l.id AND ph.recorded_at >= NOW() - INTERVAL '3 day'
                WHERE {where} AND l.brand_id = {brand_id[0]}
                GROUP BY m.name
                ORDER BY active_listings DESC
                LIMIT 20
            """
        else:
            # Иначе показываем топ марок
            query = f"""
                SELECT
                    b.name AS brand,
                    COUNT(DISTINCT l.id) AS active_listings,
                    ROUND(AVG(ph.price_kzt))::bigint AS avg_price_kzt,
                    MIN(ph.price_kzt) AS min_price_kzt,
                    MAX(ph.price_kzt) AS max_price_kzt
                FROM brands b
                JOIN listings l ON l.brand_id = b.id
                JOIN sources s ON s.id = l.source_id
                LEFT JOIN price_history ph ON ph.listing_id = l.id AND ph.recorded_at >= NOW() - INTERVAL '3 day'
                WHERE {where}
                GROUP BY b.name
                ORDER BY active_listings DESC
                LIMIT 20
            """
        rows = await conn.fetch(query, *params)
        
    return [dict(r) for r in rows]


@router.get("/price-boxplot", summary="Ящики с усами: топ-10 марок или моделей выбранной марки")
async def get_price_boxplot(
    brand_id: Optional[int] = Query(None, description="Если передан — показывает топ-10 моделей этой марки"),
    city: list[str] = Query(None),
    source: list[str] = Query(None),
    year: list[int] = Query(None),
):
    """
    Без brand_id → топ-10 марок по количеству активных объявлений.
    С brand_id  → топ-10 моделей выбранной марки.
    Возвращает min, Q1, median, Q3, max + count (совпадает с market-overview).
    """
    conditions = ["l.is_active = TRUE", "ph.price_kzt > 0"]
    params: list = []
    i = 1

    if city:
        conditions.append(f"l.city = ANY(${i}::text[])"); params.append(city); i += 1
    if source:
        conditions.append(f"s.name = ANY(${i}::text[])"); params.append(source); i += 1
    if year:
        conditions.append(f"l.year = ANY(${i}::int[])"); params.append(year); i += 1

    where = " AND ".join(conditions)

    if brand_id:
        # Режим моделей: топ-10 моделей выбранной марки
        brand_filter = f"AND l.brand_id = ${i}"
        params.append(brand_id); i += 1
        query = f"""
            WITH top_models AS (
                SELECT m.id, m.name, COUNT(l.id) AS listing_count
                FROM models m
                JOIN listings l ON l.model_id = m.id
                WHERE l.is_active = TRUE {brand_filter}
                GROUP BY m.id, m.name
                ORDER BY listing_count DESC
                LIMIT 10
            ),
            model_prices AS (
                SELECT
                    m.name          AS label,
                    m.listing_count AS total_count,
                    ph.price_kzt    AS price
                FROM top_models m
                JOIN listings l  ON l.model_id = m.id
                JOIN sources  s  ON s.id = l.source_id
                JOIN price_history ph ON ph.listing_id = l.id
                    AND ph.recorded_at >= NOW() - INTERVAL '7 day'
                WHERE {where} {brand_filter}
            )
            SELECT
                label,
                MAX(total_count)                                             AS count,
                PERCENTILE_CONT(0.0)  WITHIN GROUP (ORDER BY price)::bigint AS min_price,
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY price)::bigint AS q1,
                PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY price)::bigint AS median,
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY price)::bigint AS q3,
                PERCENTILE_CONT(1.0)  WITHIN GROUP (ORDER BY price)::bigint AS max_price
            FROM model_prices
            GROUP BY label
            HAVING COUNT(DISTINCT price) >= 3
            ORDER BY median DESC
        """
    else:
        # Режим марок: топ-10 марок
        query = f"""
            WITH top_brands AS (
                SELECT b.id, b.name, COUNT(l.id) AS listing_count
                FROM brands b
                JOIN listings l ON l.brand_id = b.id
                WHERE l.is_active = TRUE
                GROUP BY b.id, b.name
                ORDER BY listing_count DESC
                LIMIT 10
            ),
            brand_prices AS (
                SELECT
                    b.name          AS label,
                    b.listing_count AS total_count,
                    ph.price_kzt    AS price
                FROM top_brands b
                JOIN listings l  ON l.brand_id = b.id
                JOIN sources  s  ON s.id = l.source_id
                JOIN price_history ph ON ph.listing_id = l.id
                    AND ph.recorded_at >= NOW() - INTERVAL '7 day'
                WHERE {where}
            )
            SELECT
                label,
                MAX(total_count)                                             AS count,
                PERCENTILE_CONT(0.0)  WITHIN GROUP (ORDER BY price)::bigint AS min_price,
                PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY price)::bigint AS q1,
                PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY price)::bigint AS median,
                PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY price)::bigint AS q3,
                PERCENTILE_CONT(1.0)  WITHIN GROUP (ORDER BY price)::bigint AS max_price
            FROM brand_prices
            GROUP BY label
            HAVING COUNT(DISTINCT price) >= 3
            ORDER BY median DESC
        """

    async with DBSession() as conn:
        rows = await conn.fetch(query, *params)

    result = []
    for r in rows:
        d = dict(r)
        # Переименовываем label → brand для совместимости с фронтом
        d["brand"] = d.pop("label")
        iqr = (d["q3"] or 0) - (d["q1"] or 0)
        d["whisker_low"]  = max(d["min_price"] or 0, (d["q1"] or 0) - int(1.5 * iqr))
        d["whisker_high"] = min(d["max_price"] or 0, (d["q3"] or 0) + int(1.5 * iqr))
        result.append(d)

    return result
