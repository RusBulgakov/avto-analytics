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
    include_junk: bool = Query(
        False,
        description="Учитывать junk-listings (аварийные / не на ходу / не растаможенные / на запчасти). По умолчанию исключены — иначе средняя цена занижена.",
    ),
):
    """Топ-20 марок по количеству объявлений + средняя цена. С учетом фильтров."""

    conditions = []
    if not include_inactive:
        conditions.append("l.is_active = TRUE")
    if not include_junk:
        # DB-flags (из parsers/kolesa/flags.py) + title-keyword fallback
        conditions.append("(l.is_emergency IS NULL OR l.is_emergency = FALSE)")
        conditions.append("(l.is_customs_cleared IS NULL OR l.is_customs_cleared = TRUE)")
        conditions.append("""l.title NOT ILIKE ALL(ARRAY[
            '%не на ходу%', '%аварий%', '%битая%', '%битый%',
            '%не растамож%', '%не растам%', '%без документ%',
            '%на запчасти%', '%по запчастям%', '%разбит%',
            '%восстанов%', '%утоплен%', '%горел%'
          ])""")
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
    include_junk: bool = Query(
        False,
        description="Учитывать аварийные / не на ходу / не растаможенные / на запчасти. По умолчанию исключены — иначе boxplot уши уходят далеко вниз и picture неинформативная.",
    ),
):
    """
    Без brand_id → топ-10 марок по количеству объявлений.
    С brand_id  → топ-10 моделей выбранной марки.
    Возвращает min, Q1, median, Q3, max + count (совпадает с market-overview).
    """
    active_filter = "" if include_inactive else "AND l.is_active = TRUE"
    # Junk-фильтр для /price-boxplot: DB-флаги (если parsers/kolesa/flags.py
    # их заполнил) + title-keyword fallback для не-kolesa источников.
    junk_keyword_clause = "" if include_junk else """
          AND (l.is_emergency IS NULL OR l.is_emergency = FALSE)
          AND (l.is_customs_cleared IS NULL OR l.is_customs_cleared = TRUE)
          AND l.title NOT ILIKE ALL(ARRAY[
            '%не на ходу%', '%аварий%', '%битая%', '%битый%',
            '%не растамож%', '%не растам%', '%без документ%',
            '%на запчасти%', '%по запчастям%', '%разбит%',
            '%восстанов%', '%утоплен%', '%горел%'
          ])
    """
    conditions = ["ph.price_kzt > 0"]
    if not include_inactive:
        conditions.append("l.is_active = TRUE")
    if not include_junk:
        conditions.append("(l.is_emergency IS NULL OR l.is_emergency = FALSE)")
        conditions.append("(l.is_customs_cleared IS NULL OR l.is_customs_cleared = TRUE)")
        conditions.append("""l.title NOT ILIKE ALL(ARRAY[
            '%не на ходу%', '%аварий%', '%битая%', '%битый%',
            '%не растамож%', '%не растам%', '%без документ%',
            '%на запчасти%', '%по запчастям%', '%разбит%',
            '%восстанов%', '%утоплен%', '%горел%'
          ])""")
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
                  {junk_keyword_clause}
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
                  {junk_keyword_clause}
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
    include_junk: bool = Query(
        False,
        description=(
            "Учитывать ли мусорные листинги: аварийные / не на ходу / не растаможенные / "
            "на запчасти. По умолчанию они исключены — иначе ломают p25 (buy_price) "
            "и порождают фантомную маржу. Title-keyword + price-outlier filter."
        ),
    ),
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

    # Junk-фильтр (3 слоя):
    #   1. Real DB flags (kolesa: parsers/kolesa/flags.py заполняет is_emergency
    #      и is_customs_cleared из ?need-repair=1 / ?auto-custom=1 search-фидов)
    #   2. Title-keyword fallback — для OLX/mycar/avtorynok где seller пишет
    #      "не на ходу" / "битая" в title
    #   3. Price-outlier фильтр (median ± 50%-200%) — ниже в CTE
    junk_keyword_filter = "" if include_junk else """
          AND (l.is_emergency IS NULL OR l.is_emergency = FALSE)
          AND (l.is_customs_cleared IS NULL OR l.is_customs_cleared = TRUE)
          AND l.title NOT ILIKE ALL(ARRAY[
            '%не на ходу%', '%аварий%', '%битая%', '%битый%',
            '%не растамож%', '%не растам%', '%без документ%',
            '%на запчасти%', '%по запчастям%', '%разбит%',
            '%восстанов%', '%утоплен%', '%горел%'
          ])
    """

    # Outlier-фильтр: цены < 50% и > 200% от median группы (brand+model+year)
    # отбрасываются перед расчётом percentile. Это убирает на kolesa листинги,
    # которые продают аварийные/без документов за 30-50% от рынка (фейковые
    # buy_price → фантомная маржа), и эксклюзивные комплектации/typos сверху.
    # Структура: priced → group_med (median per group) → clean (within band).
    outlier_filter_sql = ""
    if include_junk:
        outlier_filter_sql = "  -- include_junk: true → outlier filter отключён"
    else:
        outlier_filter_sql = "WHERE p.price_kzt BETWEEN g.m_price * 0.5 AND g.m_price * 2.0"

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
        ),
        priced AS (
            SELECT l.id, l.brand_id, l.model_id, l.year, latest.price_kzt
            FROM listings l
            JOIN latest ON latest.listing_id = l.id
            JOIN brands b ON b.id = l.brand_id
            JOIN models m ON m.id = l.model_id
            WHERE l.is_active = TRUE AND l.year IS NOT NULL{year_filter}
              AND m.name NOT LIKE '(%'
              AND LOWER(m.name) <> LOWER(b.name)
              {junk_keyword_filter}
        ),
        group_med AS (
            SELECT brand_id, model_id, year,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_kzt) AS m_price
            FROM priced
            GROUP BY brand_id, model_id, year
        ),
        clean AS (
            SELECT p.*
            FROM priced p
            JOIN group_med g
              ON g.brand_id = p.brand_id AND g.model_id = p.model_id AND g.year = p.year
            {outlier_filter_sql}
        )
        SELECT
            b.name AS brand,
            m.name AS model,
            c.year::int AS year,
            COUNT(*)::int AS volume,
            PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY c.price_kzt)::bigint AS buy_price,
            PERCENTILE_CONT(0.5)  WITHIN GROUP (ORDER BY c.price_kzt)::bigint AS sell_price,
            PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY c.price_kzt)::bigint AS high_price,
            sold.median_days
        FROM clean c
        JOIN brands b ON b.id = c.brand_id
        JOIN models m ON m.id = c.model_id
        LEFT JOIN sold ON sold.brand_id = c.brand_id AND sold.model_id = c.model_id AND sold.year = c.year
        GROUP BY b.name, m.name, c.year, sold.median_days
        HAVING COUNT(*) >= $1
        ORDER BY
            ((PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY c.price_kzt) -
              PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY c.price_kzt))
             / NULLIF(PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY c.price_kzt), 0)) DESC NULLS LAST
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


# =============================================================================
# Прогноз цены — OLS regression on weekly median (PUBLIC)
# =============================================================================

@router.get("/forecast", summary="Прогноз медианной цены: OLS regression на недельных бакетах (с USD-нормализацией)")
async def get_forecast(
    brand_id: int = Query(..., description="ID марки"),
    model_id: Optional[int] = Query(None, description="ID модели (опционально)"),
    year: Optional[int] = Query(None, ge=1990, le=2030, description="Конкретный год (опц.)"),
    year_from: Optional[int] = Query(None, ge=1990, le=2030, description="Год от (для диапазона/поколения)"),
    year_to: Optional[int] = Query(None, ge=1990, le=2030, description="Год до"),
    history_days: int = Query(90, ge=28, le=365, description="Глубина истории для regression"),
    horizon_days: int = Query(30, ge=7, le=120, description="На сколько дней вперёд прогнозировать"),
    include_inactive: bool = Query(False, description="Учитывать снятые объявления в обучении"),
    include_junk: bool = Query(
        False,
        description="Учитывать аварийные / не растаможенные. Default false — мы не хотим что junk портил тренд.",
    ),
):
    """
    Прогноз цены — OLS regression на недельных медианах + USD-нормализация.

    Алгоритм:
      1. Достаём price_history за `history_days` дней. Junk-фильтр стандартный.
      2. Per-row LEFT JOIN LATERAL с fx_history → берём USD-курс за дату записи
         (если в выходной нет курса — последний доступный, forward-fill).
      3. Агрегируем по неделям: median_kzt, median_usd, week_avg_usd_rate.
      4. OLS отдельно на median_kzt и median_usd. Это даёт два параллельных
         тренда: "цена в KZT" (как видит покупатель) и "цена в USD"
         (отделено от тренда KZT — это "истинный" тренд стоимости авто).
      5. Forecast в обеих валютах. KZT прогноз = USD прогноз * current_rate.
      6. fx_impact_pct = (kzt_trend - usd_trend) — сколько из изменения цены
         объясняется курсом, а сколько — реальным движением рынка.

    Возвращает:
      - historical[]: {date, median_kzt, median_usd, count, fx_rate}
      - forecast[]:   {date, median_kzt, median_usd, low/high (95% CI)}
      - trend_pct_per_month_kzt и _usd
      - r2_kzt, r2_usd
      - fx_impact_pct (доля тренда от FX vs market)
      - sample_size
    """
    import math

    conditions = [
        "ph.recorded_at >= NOW() - ($1 * INTERVAL '1 day')",
        "ph.price_kzt > 0",
        "l.brand_id = $2",
    ]
    params: list = [history_days, brand_id]
    i = 3

    if model_id:
        conditions.append(f"l.model_id = ${i}"); params.append(model_id); i += 1
    if year:
        conditions.append(f"l.year = ${i}"); params.append(year); i += 1
    if year_from:
        conditions.append(f"l.year >= ${i}"); params.append(year_from); i += 1
    if year_to:
        conditions.append(f"l.year <= ${i}"); params.append(year_to); i += 1
    if not include_inactive:
        conditions.append("l.is_active = TRUE")
    if not include_junk:
        conditions.append("(l.is_emergency IS NULL OR l.is_emergency = FALSE)")
        conditions.append("(l.is_customs_cleared IS NULL OR l.is_customs_cleared = TRUE)")
        conditions.append("""l.title NOT ILIKE ALL(ARRAY[
            '%не на ходу%', '%аварий%', '%битая%', '%битый%',
            '%не растамож%', '%не растам%', '%без документ%',
            '%на запчасти%', '%по запчастям%', '%разбит%',
            '%восстанов%', '%утоплен%', '%горел%'
        ])""")

    where = " AND ".join(conditions)
    query = f"""
        WITH priced AS (
            -- Каждая запись price_history с FX-курсом за день записи (forward-fill)
            SELECT
                DATE_TRUNC('week', ph.recorded_at) AS week_start,
                ph.price_kzt::numeric AS price_kzt,
                fx.usd_kzt::numeric AS usd_rate,
                l.id AS listing_id
            FROM price_history ph
            JOIN listings l ON l.id = ph.listing_id
            LEFT JOIN LATERAL (
                SELECT usd_kzt FROM fx_history
                WHERE rate_date <= ph.recorded_at::date
                ORDER BY rate_date DESC LIMIT 1
            ) fx ON TRUE
            WHERE {where}
        )
        SELECT
            week_start,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY price_kzt)::bigint AS median_kzt,
            PERCENTILE_CONT(0.5) WITHIN GROUP (
                ORDER BY (price_kzt / NULLIF(usd_rate, 0))
            )::numeric(14, 2) AS median_usd,
            AVG(usd_rate)::numeric(10, 4) AS week_usd_rate,
            COUNT(DISTINCT listing_id)::int AS listing_count
        FROM priced
        WHERE usd_rate IS NOT NULL
        GROUP BY week_start
        ORDER BY week_start ASC
    """

    async with DBSession() as conn:
        rows = await conn.fetch(query, *params)
        # Текущий курс для конвертации forecast USD → KZT
        current_rate = await conn.fetchval(
            "SELECT usd_kzt FROM fx_history ORDER BY rate_date DESC LIMIT 1"
        )

    points = [
        (
            r["week_start"],
            int(r["median_kzt"]),
            float(r["median_usd"] or 0),
            float(r["week_usd_rate"] or 0),
            r["listing_count"],
        )
        for r in rows
    ]
    n = len(points)

    historical = [
        {
            "date": d.isoformat(),
            "median_kzt": kzt,
            "median_usd": round(usd, 2),
            "fx_rate": round(rate, 2),
            "count": c,
        }
        for d, kzt, usd, rate, c in points
    ]

    if n < 4:
        return {
            "historical": historical,
            "forecast": [],
            "trend_pct_per_month_kzt": None,
            "trend_pct_per_month_usd": None,
            "r2_kzt": None,
            "r2_usd": None,
            "fx_impact_pct": None,
            "sample_size": n,
            "current_fx_rate": float(current_rate) if current_rate else None,
            "error": "Недостаточно данных для прогноза (минимум 4 недели)",
        }

    # OLS-helper для вычисления slope, intercept, R², residual_std
    def ols(ys: list[float]) -> tuple[float, float, float, float]:
        xs = list(range(len(ys)))
        x_mean = sum(xs) / len(xs)
        y_mean = sum(ys) / len(ys)
        sxx = sum((x - x_mean) ** 2 for x in xs)
        sxy = sum((xs[k] - x_mean) * (ys[k] - y_mean) for k in range(len(xs)))
        slope = sxy / sxx if sxx else 0.0
        intercept = y_mean - slope * x_mean
        residuals = [ys[k] - (intercept + slope * xs[k]) for k in range(len(xs))]
        rss = sum(r * r for r in residuals)
        tss = sum((y - y_mean) ** 2 for y in ys)
        r2 = (1 - rss / tss) if tss > 0 else 0.0
        rstd = math.sqrt(rss / max(1, len(ys) - 2))
        return slope, intercept, r2, rstd

    ys_kzt = [float(p[1]) for p in points]
    ys_usd = [float(p[2]) for p in points]

    slope_kzt, intercept_kzt, r2_kzt, rstd_kzt = ols(ys_kzt)
    slope_usd, intercept_usd, r2_usd, rstd_usd = ols(ys_usd)

    mean_kzt = sum(ys_kzt) / n
    mean_usd = sum(ys_usd) / n

    trend_kzt = (slope_kzt * 4 / mean_kzt * 100) if mean_kzt else 0.0
    trend_usd = (slope_usd * 4 / mean_usd * 100) if mean_usd else 0.0
    # FX-вклад: разница между трендом в KZT и трендом в USD.
    # > 0 → KZT-цены растут быстрее USD-цен из-за ослабления тенге
    # < 0 → KZT-цены растут медленнее USD-цен (тенге укрепляется)
    fx_impact = trend_kzt - trend_usd

    # Forecast: используем USD-тренд (он чище, без FX-шума), потом конвертируем в KZT
    horizon_weeks = max(1, math.ceil(horizon_days / 7))
    last_week_start = points[-1][0]
    last_fx_rate = float(current_rate) if current_rate else points[-1][3]

    forecast = []
    for w in range(1, horizon_weeks + 1):
        future_idx = (n - 1) + w
        pred_usd = intercept_usd + slope_usd * future_idx
        pred_kzt = pred_usd * last_fx_rate
        future_date = last_week_start + timedelta(days=7 * w)
        ci_half_kzt = 1.96 * rstd_kzt
        forecast.append({
            "date": future_date.isoformat(),
            "median_kzt": int(max(0, pred_kzt)),
            "median_usd": round(max(0, pred_usd), 2),
            "low": int(max(0, pred_kzt - ci_half_kzt)),
            "high": int(pred_kzt + ci_half_kzt),
        })

    return {
        "historical": historical,
        "forecast": forecast,
        "trend_pct_per_month_kzt": round(trend_kzt, 2),
        "trend_pct_per_month_usd": round(trend_usd, 2),
        "fx_impact_pct": round(fx_impact, 2),
        "r2_kzt": round(r2_kzt, 3),
        "r2_usd": round(r2_usd, 3),
        "residual_std_pct_kzt": round(rstd_kzt / mean_kzt * 100, 2) if mean_kzt else None,
        "sample_size": n,
        "horizon_weeks": horizon_weeks,
        "current_fx_rate": round(last_fx_rate, 2),
    }
