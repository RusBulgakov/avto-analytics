from __future__ import annotations
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
async def get_brands(
    include_inactive: bool = Query(False, description="Включать снятые объявления"),
):
    """Возвращает все марки с количеством объявлений (по умолчанию — только активные)."""
    join_filter = "" if include_inactive else "AND l.is_active = TRUE"
    async with DBSession() as conn:
        rows = await conn.fetch(f"""
            SELECT b.id, b.name, b.slug, COUNT(l.id) AS listings_count
            FROM brands b
            LEFT JOIN listings l ON l.brand_id = b.id {join_filter}
            GROUP BY b.id, b.name, b.slug
            ORDER BY listings_count DESC
        """)
    return [dict(r) for r in rows]


@router.get("/models", summary="Список моделей по марке (публичный)")
async def get_models(
    brand_id: int = Query(..., description="ID марки"),
    include_inactive: bool = Query(False, description="Включать снятые объявления"),
):
    """Возвращает модели для указанной марки."""
    join_filter = "" if include_inactive else "AND l.is_active = TRUE"
    async with DBSession() as conn:
        rows = await conn.fetch(f"""
            SELECT m.id, m.name, m.slug, COUNT(l.id) AS listings_count
            FROM models m
            LEFT JOIN listings l ON l.model_id = m.id {join_filter}
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
    include_inactive: bool = Query(False, description="Учитывать снятые объявления"),
    granularity: str = Query(
        "auto",
        pattern="^(auto|day|week|month)$",
        description="Шаг агрегации точек графика. auto = day для ≤14 дней, week для ≤180, month для остального.",
    ),
):
    """
    Базовый публичный график цен. Возвращает avg + median сгруппированные по
    выбранной гранулярности (день / неделя / месяц).

    Зачем weekly default: на kolesa объявление меняет цену в среднем 1.1 раз
    в месяц, поэтому daily-aggregation на 90д даёт разреженную и шумную
    кривую — недельные бакеты на порядок чище.
    """
    # Auto-resolve granularity на основе периода
    if granularity == "auto":
        if period_days <= 14:
            granularity = "day"
        elif period_days <= 180:
            granularity = "week"
        else:
            granularity = "month"
    # Whitelist уже валидирован regex'ом на param-уровне, но дополнительно фильтруем
    # перед интерполяцией в SQL — granularity_resolved только из known set.
    granularity_resolved = {"day": "day", "week": "week", "month": "month"}[granularity]

    conditions = ["ph.recorded_at >= NOW() - ($1 * INTERVAL '1 day')"]
    if not include_inactive:
        conditions.append("l.is_active = TRUE")
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
            DATE_TRUNC('{granularity_resolved}', ph.recorded_at) AS date,
            ROUND(AVG(ph.price_kzt))::bigint   AS avg_price_kzt,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ph.price_kzt)::bigint AS median_price_kzt,
            COUNT(DISTINCT l.id)               AS listing_count
        FROM price_history ph
        JOIN listings l ON l.id = ph.listing_id
        JOIN sources  s ON s.id = l.source_id
        WHERE {where}
        GROUP BY DATE_TRUNC('{granularity_resolved}', ph.recorded_at)
        ORDER BY date ASC
    """
    async with DBSession() as conn:
        rows = await conn.fetch(query, *params)
    # Возвращаем гранулярность вместе с точками, чтобы фронт знал что показал бэк (для auto-режима)
    return {
        "granularity": granularity_resolved,
        "points": [dict(r) for r in rows],
    }


@router.get("/price-candles", summary="Свечи распределения цен по времени")
async def get_price_candles(
    brand_id: Optional[int] = Query(None),
    model_id: Optional[int] = Query(None),
    city: list[str] = Query(None),
    source: list[str] = Query(None),
    period_days: int = Query(180, ge=14, le=730, description="Глубина истории в днях"),
    granularity: str = Query(
        "auto",
        pattern="^(auto|day|week|month)$",
        description="Шаг бакета. auto = week для ≤90 дней, month для остального.",
    ),
    include_inactive: bool = Query(False, description="Учитывать снятые объявления"),
    min_count: int = Query(5, ge=1, le=50, description="Минимум точек в бакете для отображения"),
):
    """
    Возвращает квартили цен по временным бакетам — distribution-style свечи
    (не OHLC). Каждый бакет: P5 / Q1 / median / Q3 / P95 + count.

    Frontend рисует свечи: тело = Q1-Q3, усы = P5-P95, точка = медиана,
    цвет = направление медианы относительно прошлого бакета.
    """
    if granularity == "auto":
        granularity = "week" if period_days <= 90 else "month"
    granularity_resolved = {"day": "day", "week": "week", "month": "month"}[granularity]

    conditions = [
        "ph.recorded_at >= NOW() - ($1 * INTERVAL '1 day')",
        "ph.price_kzt > 0",
    ]
    if not include_inactive:
        conditions.append("l.is_active = TRUE")
    params: list = [period_days]
    i = 2

    if brand_id:
        conditions.append(f"l.brand_id = ${i}"); params.append(brand_id); i += 1
    if model_id:
        conditions.append(f"l.model_id = ${i}"); params.append(model_id); i += 1
    if city:
        conditions.append(f"l.city = ANY(${i}::text[])"); params.append(city); i += 1
    if source:
        conditions.append(f"s.name = ANY(${i}::text[])"); params.append(source); i += 1

    where = " AND ".join(conditions)
    params.append(min_count)
    min_count_idx = i

    query = f"""
        WITH bucketed AS (
            SELECT
                DATE_TRUNC('{granularity_resolved}', ph.recorded_at) AS bucket,
                ph.price_kzt AS price
            FROM price_history ph
            JOIN listings l ON l.id = ph.listing_id
            JOIN sources  s ON s.id = l.source_id
            WHERE {where}
        )
        SELECT
            bucket AS date,
            COUNT(*)::int AS count,
            PERCENTILE_CONT(0.05) WITHIN GROUP (ORDER BY price)::bigint AS whisker_low,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY price)::bigint AS p25,
            PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY price)::bigint AS median,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY price)::bigint AS p75,
            PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY price)::bigint AS whisker_high
        FROM bucketed
        GROUP BY bucket
        HAVING COUNT(*) >= ${min_count_idx}
        ORDER BY bucket ASC
    """
    async with DBSession() as conn:
        rows = await conn.fetch(query, *params)

    return {
        "granularity": granularity_resolved,
        "candles": [dict(r) for r in rows],
    }


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
    year: list[int] = Query(None),
    include_inactive: bool = Query(False, description="Считать также снятые объявления"),
):
    """Возвращает точные значения для верхних счетчиков: объявления, бренды, средняя цена и источники."""

    conditions = []
    if not include_inactive:
        conditions.append("l.is_active = TRUE")
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

    where = " AND ".join(conditions) if conditions else "TRUE"

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
    year: list[int] = Query(None),
    include_inactive: bool = Query(False, description="Считать также снятые объявления"),
):
    """Топ-20 марок по количеству объявлений + средняя цена. С учетом фильтров."""

    conditions = []
    if not include_inactive:
        conditions.append("l.is_active = TRUE")
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

    where = " AND ".join(conditions) if conditions else "TRUE"

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
    include_inactive: bool = Query(False, description="Учитывать снятые объявления"),
):
    """
    Без brand_id → топ-10 марок по количеству объявлений.
    С brand_id  → топ-10 моделей выбранной марки.
    Возвращает min, Q1, median, Q3, max + count (совпадает с market-overview).
    """
    active_filter = "" if include_inactive else "AND l.is_active = TRUE"
    conditions = ["ph.price_kzt > 0"]
    if not include_inactive:
        conditions.append("l.is_active = TRUE")
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
                WHERE 1=1 {active_filter} {brand_filter}
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
                WHERE 1=1 {active_filter}
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


# =============================================================================
# NEW: Trading Terminal endpoints (heatmap, liquidity funnel, recent, cities)
# =============================================================================

@router.get("/heatmap", summary="Тепловая карта: год × пробег (ср. цена и объём)")
async def get_heatmap(
    brand_id: Optional[int] = Query(None),
    model_id: Optional[int] = Query(None),
    city: list[str] = Query(None),
    source: list[str] = Query(None),
    include_inactive: bool = Query(False, description="Учитывать снятые объявления"),
):
    """
    Группирует объявления по (year, mileage_bucket) и возвращает
    среднюю цену + объём. Используется для heatmap-матрицы на дашборде.
    Бакеты пробега в тыс. км: 0-20, 20-50, 50-100, 100-150, 150-200, 200+
    """
    conditions = [
        "l.year BETWEEN 2008 AND EXTRACT(YEAR FROM NOW())::int",
        "l.mileage_km IS NOT NULL",
        "ph.price_kzt > 0",
    ]
    if not include_inactive:
        conditions.append("l.is_active = TRUE")
    params: list = []
    i = 1
    if brand_id:
        conditions.append(f"l.brand_id = ${i}"); params.append(brand_id); i += 1
    if model_id:
        conditions.append(f"l.model_id = ${i}"); params.append(model_id); i += 1
    if city:
        conditions.append(f"l.city = ANY(${i}::text[])"); params.append(city); i += 1
    if source:
        conditions.append(f"s.name = ANY(${i}::text[])"); params.append(source); i += 1

    where = " AND ".join(conditions)
    query = f"""
        WITH latest_price AS (
            SELECT DISTINCT ON (listing_id) listing_id, price_kzt
            FROM price_history
            WHERE recorded_at >= NOW() - INTERVAL '7 day'
            ORDER BY listing_id, recorded_at DESC
        )
        SELECT
            l.year AS year,
            CASE
                WHEN l.mileage_km < 20000  THEN '0-20'
                WHEN l.mileage_km < 50000  THEN '20-50'
                WHEN l.mileage_km < 100000 THEN '50-100'
                WHEN l.mileage_km < 150000 THEN '100-150'
                WHEN l.mileage_km < 200000 THEN '150-200'
                ELSE '200+'
            END AS mileage_bucket,
            ROUND(AVG(ph.price_kzt))::bigint AS avg_price_kzt,
            COUNT(*)::int AS volume
        FROM listings l
        JOIN sources s ON s.id = l.source_id
        JOIN latest_price ph ON ph.listing_id = l.id
        WHERE {where}
        GROUP BY l.year, mileage_bucket
        HAVING COUNT(*) >= 2
        ORDER BY l.year DESC, mileage_bucket
    """
    async with DBSession() as conn:
        rows = await conn.fetch(query, *params)
    return [dict(r) for r in rows]


@router.get("/liquidity", summary="Воронка ликвидности: дни на продажу")
async def get_liquidity(
    brand_id: Optional[int] = Query(None),
    model_id: Optional[int] = Query(None),
    city: list[str] = Query(None),
    source: list[str] = Query(None),
):
    """
    Распределение закрытых объявлений по времени жизни
    (closed_at - first_seen_at) в 7 бакетах. Активные не считаются —
    только те, что реально продались/скрылись.
    """
    conditions = [
        "l.closed_at IS NOT NULL",
        "l.first_seen_at IS NOT NULL",
        "l.closed_at > l.first_seen_at",
        "l.closed_at >= NOW() - INTERVAL '180 day'",
    ]
    params: list = []
    i = 1
    if brand_id:
        conditions.append(f"l.brand_id = ${i}"); params.append(brand_id); i += 1
    if model_id:
        conditions.append(f"l.model_id = ${i}"); params.append(model_id); i += 1
    if city:
        conditions.append(f"l.city = ANY(${i}::text[])"); params.append(city); i += 1
    if source:
        conditions.append(f"s.name = ANY(${i}::text[])"); params.append(source); i += 1

    where = " AND ".join(conditions)
    query = f"""
        WITH days AS (
            SELECT EXTRACT(EPOCH FROM (l.closed_at - l.first_seen_at)) / 86400 AS d
            FROM listings l
            JOIN sources s ON s.id = l.source_id
            WHERE {where}
        )
        SELECT bucket, COUNT(*)::int AS count FROM (
            SELECT CASE
                WHEN d < 4   THEN '0-3'
                WHEN d < 8   THEN '4-7'
                WHEN d < 15  THEN '8-14'
                WHEN d < 31  THEN '15-30'
                WHEN d < 61  THEN '31-60'
                WHEN d < 91  THEN '61-90'
                ELSE '90+'
            END AS bucket
            FROM days
        ) t
        GROUP BY bucket
    """
    async with DBSession() as conn:
        rows = await conn.fetch(query, *params)

    order = ['0-3', '4-7', '8-14', '15-30', '31-60', '61-90', '90+']
    counts = {r['bucket']: r['count'] for r in rows}
    total = sum(counts.values()) or 1
    return [
        {
            "bucket": b,
            "count": counts.get(b, 0),
            "pct": round(100.0 * counts.get(b, 0) / total, 1),
        }
        for b in order
    ]


@router.get("/recent", summary="Лента свежих объявлений")
async def get_recent(
    limit: int = Query(8, ge=1, le=50),
    brand_id: Optional[int] = Query(None),
    city: list[str] = Query(None),
    source: list[str] = Query(None),
):
    """Последние N активных объявлений, с дельтой цены относительно
    первой записи price_history (положительная — выросла, отрицательная — снизилась)."""
    conditions = ["l.is_active = TRUE"]
    params: list = []
    i = 1
    if brand_id:
        conditions.append(f"l.brand_id = ${i}"); params.append(brand_id); i += 1
    if city:
        conditions.append(f"l.city = ANY(${i}::text[])"); params.append(city); i += 1
    if source:
        conditions.append(f"s.name = ANY(${i}::text[])"); params.append(source); i += 1

    where = " AND ".join(conditions)
    query = f"""
        WITH latest AS (
            SELECT DISTINCT ON (listing_id) listing_id, price_kzt, recorded_at
            FROM price_history
            ORDER BY listing_id, recorded_at DESC
        ),
        first_price AS (
            SELECT DISTINCT ON (listing_id) listing_id, price_kzt
            FROM price_history
            ORDER BY listing_id, recorded_at ASC
        )
        SELECT
            l.id::text AS id,
            b.name AS brand,
            m.name AS model,
            l.year,
            lp.price_kzt AS price_kzt,
            (lp.price_kzt - fp.price_kzt) AS price_delta_kzt,
            l.mileage_km,
            l.city,
            s.name AS source,
            l.listing_url,
            l.first_seen_at
        FROM listings l
        JOIN sources s ON s.id = l.source_id
        LEFT JOIN brands b ON b.id = l.brand_id
        LEFT JOIN models m ON m.id = l.model_id
        JOIN latest lp ON lp.listing_id = l.id
        LEFT JOIN first_price fp ON fp.listing_id = l.id
        WHERE {where}
        ORDER BY l.first_seen_at DESC NULLS LAST
        LIMIT ${i}
    """
    params.append(limit)
    async with DBSession() as conn:
        rows = await conn.fetch(query, *params)
    return [dict(r) for r in rows]


@router.get("/cities", summary="Список городов с числом объявлений")
async def get_cities(
    include_inactive: bool = Query(False, description="Учитывать снятые объявления"),
):
    """Все города с количеством объявлений. Для фильтра."""
    active_filter = "" if include_inactive else "AND l.is_active = TRUE"
    async with DBSession() as conn:
        rows = await conn.fetch(f"""
            SELECT
                l.city AS name,
                COUNT(*)::int AS listings_count
            FROM listings l
            WHERE l.city IS NOT NULL
              AND l.city <> ''
              {active_filter}
            GROUP BY l.city
            ORDER BY listings_count DESC
            LIMIT 50
        """)
    return [dict(r) for r in rows]


# =============================================================================
# Geography, listing detail, valuation
# =============================================================================

# DB city slug → (display name, x% on silhouette, y% on silhouette)
# Coordinates are SVG-space percents (0..100), not real lat/lon. Keep in sync
# with frontend KZMap viewBox.
_CITY_COORDS: dict[str, tuple[str, float, float]] = {
    "almaty":          ("Алматы",          75, 82),
    "astana":          ("Астана",          52, 42),
    "shymkent":        ("Шымкент",         55, 88),
    "karaganda":       ("Караганда",       55, 55),
    "aktobe":          ("Актобе",          24, 43),
    "pavlodar":        ("Павлодар",        62, 32),
    "ust-kamenogorsk": ("Усть-Каменогорск", 82, 37),
    "kostanay":        ("Костанай",        42, 27),
    "kostanai":        ("Костанай",        42, 27),
    "atyrau":          ("Атырау",          14, 62),
    "uralsk":          ("Уральск",         16, 42),
    "oral":            ("Уральск",         16, 42),
    "semey":           ("Семей",           76, 42),
    "taraz":           ("Тараз",           60, 85),
    "kyzylorda":       ("Кызылорда",       42, 75),
    "aktau":           ("Актау",           8,  74),
    "petropavlovsk":   ("Петропавловск",   48, 18),
    "temirtau":        ("Темиртау",        56, 52),
    "kokshetau":       ("Кокшетау",        50, 30),
    "turkestan":       ("Туркестан",       50, 86),
    "ekibastuz":       ("Экибастуз",       64, 28),
    "taldykorgan":     ("Талдыкорган",     78, 73),
    "zhezkazgan":      ("Жезказган",       42, 60),
    "ridder":          ("Риддер",          88, 35),
    "balkhash":        ("Балхаш",          67, 60),
    "satpayev":        ("Сатпаев",         40, 60),
    "rudny":           ("Рудный",          38, 26),
    "stepnogorsk":     ("Степногорск",     54, 32),
    "kentau":          ("Кентау",          48, 84),
    "zhanaozen":       ("Жаноозен",        10, 78),
    "arkalyk":         ("Аркалык",         44, 42),
    "kapchagay":       ("Капчагай",        76, 80),
    "khromtau":        ("Хромтау",         26, 46),
    "shu":             ("Шу",              60, 78),
}


@router.get("/geo", summary="Карта KZ: координаты городов + объявления и ср. цена")
async def get_geo(
    include_inactive: bool = Query(False, description="Учитывать снятые объявления"),
):
    """Возвращает список городов из словаря _CITY_COORDS с количеством объявлений
    и средней ценой. Города БЕЗ координат отбрасываются."""
    active_filter = "" if include_inactive else "AND l.is_active = TRUE"
    slugs = list(_CITY_COORDS.keys())
    async with DBSession() as conn:
        rows = await conn.fetch(f"""
            SELECT
                LOWER(l.city) AS slug,
                COUNT(DISTINCT l.id)::int AS listings,
                ROUND(AVG(ph.price_kzt))::bigint AS avg_price_kzt
            FROM listings l
            JOIN sources s ON s.id = l.source_id
            LEFT JOIN price_history ph ON ph.listing_id = l.id
                AND ph.recorded_at >= NOW() - INTERVAL '7 day'
            WHERE LOWER(l.city) = ANY($1::text[])
              {active_filter}
            GROUP BY LOWER(l.city)
        """, slugs)
    by_slug = {r["slug"]: r for r in rows}
    result = []
    for slug, (display, x, y) in _CITY_COORDS.items():
        r = by_slug.get(slug)
        result.append({
            "slug": slug,
            "name": display,
            "x": x,
            "y": y,
            "listings": int(r["listings"]) if r else 0,
            "avg_price_kzt": int(r["avg_price_kzt"]) if r and r["avg_price_kzt"] else None,
        })
    return result


@router.get("/listing/{listing_id}", summary="Одно объявление с историей цены")
async def get_listing(listing_id: str):
    """Получить детали объявления + всю историю цены."""
    async with DBSession() as conn:
        listing = await conn.fetchrow("""
            SELECT
                l.id::text AS id,
                l.external_id,
                l.title,
                l.year,
                l.mileage_km,
                l.city,
                l.listing_url,
                l.first_seen_at,
                l.last_seen_at,
                l.is_active,
                b.id AS brand_id,
                b.name AS brand,
                m.id AS model_id,
                m.name AS model,
                s.name AS source
            FROM listings l
            JOIN sources s ON s.id = l.source_id
            LEFT JOIN brands b ON b.id = l.brand_id
            LEFT JOIN models m ON m.id = l.model_id
            WHERE l.id = $1::uuid
        """, listing_id)
        if not listing:
            raise HTTPException(status_code=404, detail="listing not found")

        history = await conn.fetch("""
            SELECT recorded_at AS date, price_kzt
            FROM price_history
            WHERE listing_id = $1::uuid
            ORDER BY recorded_at ASC
        """, listing_id)

    return {
        **dict(listing),
        "price_history": [dict(h) for h in history],
    }


@router.get("/valuation", summary="Fair-price оценка для объявления")
async def get_valuation(listing_id: str = Query(...)):
    """Сравнивает цену объявления с распределением похожих активных
    (тот же brand/model, ±1 год, ±15% пробега) за последние 14 дней.
    Возвращает fair_low (p10), median (p50), fair_high (p90), verdict."""
    async with DBSession() as conn:
        base = await conn.fetchrow("""
            SELECT l.id::text AS id, l.brand_id, l.model_id, l.year,
                   l.mileage_km,
                   (SELECT price_kzt FROM price_history
                    WHERE listing_id = l.id
                    ORDER BY recorded_at DESC LIMIT 1) AS current_price
            FROM listings l WHERE l.id = $1::uuid
        """, listing_id)
        if not base:
            raise HTTPException(status_code=404, detail="listing not found")

        if not (base["brand_id"] and base["model_id"] and base["year"]):
            return {"error": "insufficient_data"}

        mileage = base["mileage_km"]
        mileage_lo = int(mileage * 0.85) if mileage else None
        mileage_hi = int(mileage * 1.15) if mileage else None

        if mileage_lo is not None:
            stats = await conn.fetchrow("""
                WITH latest AS (
                    SELECT DISTINCT ON (listing_id) listing_id, price_kzt
                    FROM price_history
                    WHERE recorded_at >= NOW() - INTERVAL '14 day'
                    ORDER BY listing_id, recorded_at DESC
                )
                SELECT
                    PERCENTILE_CONT(0.1) WITHIN GROUP (ORDER BY latest.price_kzt)::bigint AS fair_low,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY latest.price_kzt)::bigint AS median,
                    PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY latest.price_kzt)::bigint AS fair_high,
                    COUNT(*)::int AS sample_size
                FROM listings l
                JOIN latest ON latest.listing_id = l.id
                WHERE l.brand_id = $1
                  AND l.model_id = $2
                  AND l.year BETWEEN $3 AND $4
                  AND l.mileage_km BETWEEN $5 AND $6
                  AND l.id <> $7::uuid
            """, base["brand_id"], base["model_id"],
                 base["year"] - 1, base["year"] + 1,
                 mileage_lo, mileage_hi, listing_id)
        else:
            stats = await conn.fetchrow("""
                WITH latest AS (
                    SELECT DISTINCT ON (listing_id) listing_id, price_kzt
                    FROM price_history
                    WHERE recorded_at >= NOW() - INTERVAL '14 day'
                    ORDER BY listing_id, recorded_at DESC
                )
                SELECT
                    PERCENTILE_CONT(0.1) WITHIN GROUP (ORDER BY latest.price_kzt)::bigint AS fair_low,
                    PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY latest.price_kzt)::bigint AS median,
                    PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY latest.price_kzt)::bigint AS fair_high,
                    COUNT(*)::int AS sample_size
                FROM listings l
                JOIN latest ON latest.listing_id = l.id
                WHERE l.brand_id = $1
                  AND l.model_id = $2
                  AND l.year BETWEEN $3 AND $4
                  AND l.id <> $5::uuid
            """, base["brand_id"], base["model_id"],
                 base["year"] - 1, base["year"] + 1, listing_id)

    current = int(base["current_price"]) if base["current_price"] else None
    fair_low = stats["fair_low"]
    fair_high = stats["fair_high"]
    median = stats["median"]
    verdict = None
    margin_if_resell = None
    if current and fair_low and fair_high and median:
        if current < fair_low:
            verdict = "cheap"
            margin_if_resell = round(100.0 * (median - current) / current, 1)
        elif current > fair_high:
            verdict = "expensive"
        else:
            verdict = "fair"

    return {
        "listing_id": listing_id,
        "current": current,
        "fair_low": fair_low,
        "median": median,
        "fair_high": fair_high,
        "sample_size": stats["sample_size"],
        "verdict": verdict,
        "margin_if_resell_pct": margin_if_resell,
    }


@router.get("/similar", summary="Похожие объявления")
async def get_similar(listing_id: str = Query(...), limit: int = Query(8, ge=1, le=30)):
    """Активные объявления той же марки/модели ± 1 год, близкий пробег."""
    async with DBSession() as conn:
        base = await conn.fetchrow("""
            SELECT brand_id, model_id, year, mileage_km
            FROM listings WHERE id = $1::uuid
        """, listing_id)
        if not base or not base["brand_id"]:
            return []

        mileage = base["mileage_km"] or 0
        rows = await conn.fetch("""
            WITH latest AS (
                SELECT DISTINCT ON (listing_id) listing_id, price_kzt
                FROM price_history
                ORDER BY listing_id, recorded_at DESC
            )
            SELECT
                l.id::text AS id,
                b.name AS brand, m.name AS model,
                l.year, l.mileage_km, l.city,
                s.name AS source, l.listing_url,
                latest.price_kzt AS price_kzt
            FROM listings l
            JOIN sources s ON s.id = l.source_id
            LEFT JOIN brands b ON b.id = l.brand_id
            LEFT JOIN models m ON m.id = l.model_id
            JOIN latest ON latest.listing_id = l.id
            WHERE l.is_active = TRUE
              AND l.id <> $1::uuid
              AND l.brand_id = $2
              AND l.model_id = $3
              AND l.year BETWEEN $4 AND $5
              AND ($6::int = 0 OR ABS(COALESCE(l.mileage_km, $6) - $6) < 30000)
            ORDER BY ABS(COALESCE(l.mileage_km, $6) - $6) ASC NULLS LAST
            LIMIT $7
        """, listing_id, base["brand_id"], base["model_id"],
             base["year"] - 1 if base["year"] else 1900,
             base["year"] + 1 if base["year"] else 2100,
             mileage, limit)
    return [dict(r) for r in rows]


# =============================================================================
# Public profitability ranking (без PRO auth) — для страницы /profitability
# =============================================================================

@router.get(
    "/profit-ranking",
    summary="Рейтинг моделей по потенциалу маржи (публичный)"
)
async def get_profit_ranking(
    limit: int = Query(20, ge=1, le=100),
    min_volume: int = Query(10, ge=3, le=200, description="Мин. число активных объявлений"),
    year_from: int = Query(None, ge=1990, le=2030, description="Год выпуска от"),
    year_to: int = Query(None, ge=1990, le=2030, description="Год выпуска до"),
):
    """
    Возвращает топ-N моделей по оценочной марже перепродажи.

    Логика оценки (без учёта PRO-сигналов):
      - "Buy"    = 25-й перцентиль текущих цен модели
      - "Sell"   = медиана текущих цен модели
      - Margin % = (sell - buy) / buy * 100
      - Volume   = количество активных объявлений
      - Days     = медианное время закрытия для этой модели (по закрытым за 180д)
      - Risk     = 'low' (sample >= 40 & margin < 30), 'medium' (sample >= 20),
                   'high' (sample < 20)

    Данные берутся из price_history (последнее значение за 7 дней).
    """
    # Динамически добавляем условие по году если задан диапазон
    year_filter = ""
    params: list = [min_volume, limit]
    if year_from:
        params.append(year_from)
        year_filter += f" AND l.year >= ${len(params)}"
    if year_to:
        params.append(year_to)
        year_filter += f" AND l.year <= ${len(params)}"

    query = f"""
        WITH latest AS (
            SELECT DISTINCT ON (listing_id) listing_id, price_kzt
            FROM price_history
            WHERE recorded_at >= NOW() - INTERVAL '7 day'
              AND price_kzt > 0
            ORDER BY listing_id, recorded_at DESC
        ),
        sold AS (
            SELECT l.brand_id, l.model_id, l.year,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (
                       ORDER BY EXTRACT(EPOCH FROM (l.closed_at - l.first_seen_at)) / 86400
                   ) AS median_days
            FROM listings l
            WHERE l.closed_at IS NOT NULL
              AND l.first_seen_at IS NOT NULL
              AND l.closed_at > l.first_seen_at
              AND l.closed_at >= NOW() - INTERVAL '180 day'
            GROUP BY l.brand_id, l.model_id, l.year
        )
        SELECT
            b.name AS brand,
            m.name AS model,
            l.year::int AS year,
            COUNT(*)::int AS volume,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY latest.price_kzt)::bigint AS buy_price,
            PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY latest.price_kzt)::bigint AS sell_price,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY latest.price_kzt)::bigint AS high_price,
            sold.median_days
        FROM listings l
        JOIN latest ON latest.listing_id = l.id
        JOIN brands b ON b.id = l.brand_id
        JOIN models m ON m.id = l.model_id
        LEFT JOIN sold ON sold.brand_id = l.brand_id AND sold.model_id = l.model_id AND sold.year = l.year
        WHERE l.is_active = TRUE AND l.year IS NOT NULL{year_filter}
          -- Отфильтровываем мусорные модели парсера: "(Lada)", "(Toyota)" и кейсы где
          -- модель == имя бренда (когда parser не извлёк реальную submodel).
          AND m.name NOT LIKE '(%'
          AND LOWER(m.name) <> LOWER(b.name)
        GROUP BY b.name, m.name, l.year, sold.median_days
        HAVING COUNT(*) >= $1
        ORDER BY
            ((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY latest.price_kzt) -
              PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY latest.price_kzt))
             / NULLIF(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY latest.price_kzt), 0)) DESC NULLS LAST
        LIMIT $2
    """
    async with DBSession() as conn:
        rows = await conn.fetch(query, *params)

    result = []
    for r in rows:
        buy = r["buy_price"]
        sell = r["sell_price"]
        margin_pct = None
        if buy and sell and buy > 0:
            margin_pct = round(100.0 * (sell - buy) / buy, 1)
        vol = r["volume"]
        if vol >= 40 and (margin_pct is None or margin_pct < 30):
            risk = "low"
        elif vol >= 20:
            risk = "medium"
        else:
            risk = "high"
        result.append({
            "brand": r["brand"],
            "model": r["model"],
            "year": r["year"],
            "volume": vol,
            "buy_price": int(buy) if buy else None,
            "sell_price": int(sell) if sell else None,
            "high_price": int(r["high_price"]) if r["high_price"] else None,
            "margin_pct": margin_pct,
            "median_days_to_sell": round(float(r["median_days"]), 1) if r["median_days"] else None,
            "risk": risk,
        })
    return result
