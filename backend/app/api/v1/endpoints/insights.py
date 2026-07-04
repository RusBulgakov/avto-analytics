"""
app/api/v1/endpoints/insights.py
Pre-computed инсайты для контент-стратегии (/analytics/insights/*).

Статьи блога пуллят готовые цифры отсюда вместо хардкода в текст:
- price-drop-leaders — топ моделей по падению медианной цены за период
- seasonality        — средняя/медианная цена по календарным месяцам и сезонам
- brand-volatility   — стабильность цены по брендам (CV месячных медиан)
- price-buckets      — распределение активных объявлений по ценовым корзинам

Все публичные, все тяжёлые по SQL → два слоя защиты:
1. In-memory TTL-кеш (default 1 час, env INSIGHTS_CACHE_TTL_SEC). Выбран
   вместо materialized view осознанно: один инстанс на Render free-tier,
   ноль новых зависимостей, не нужна миграция и оркестрация REFRESH.
   Trade-off: кеш сбрасывается при рестарте процесса — первый запрос после
   деплоя платит полную цену запроса (сотни мс — приемлемо).
2. Heavy-класс rate-limit'а (20/min, см. app/core/rate_limit.py): кеш не
   спасает от cache-busting перебором параметров (brand_id — незамкнутое
   пространство ключей), лимитер — спасает.
"""
from __future__ import annotations

import time
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings
from app.core.database import DBSession

router = APIRouter(prefix="/analytics/insights", tags=["Insights"])


# ── TTL-кеш ──────────────────────────────────────────────────────────────

class TTLCache:
    """
    Минимальный in-memory TTL-кеш: dict key → (expires_at, value).

    maxsize защищает от роста памяти при переборе параметров (каждая
    уникальная комбинация query-параметров — отдельный ключ): при
    переполнении сначала выбрасываются истёкшие записи, затем ближайшие
    к истечению. `now` инъектируется в тестах (monotonic-семантика).
    """

    def __init__(self, ttl_seconds: float, maxsize: int = 256):
        self.ttl = ttl_seconds
        self.maxsize = maxsize
        self._store: dict[str, tuple[float, Any]] = {}

    def get(self, key: str, now: Optional[float] = None) -> Optional[Any]:
        now = time.monotonic() if now is None else now
        entry = self._store.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if now >= expires_at:
            del self._store[key]
            return None
        return value

    def set(self, key: str, value: Any, now: Optional[float] = None) -> None:
        now = time.monotonic() if now is None else now
        if key not in self._store and len(self._store) >= self.maxsize:
            self._evict(now)
        self._store[key] = (now + self.ttl, value)

    def _evict(self, now: float) -> None:
        expired = [k for k, (exp, _) in self._store.items() if now >= exp]
        for k in expired:
            del self._store[k]
        # Всё ещё полон (все записи живые) — убираем ближайшую к истечению
        if len(self._store) >= self.maxsize:
            oldest = min(self._store, key=lambda k: self._store[k][0])
            del self._store[oldest]

    def __len__(self) -> int:
        return len(self._store)


_cache = TTLCache(ttl_seconds=settings.INSIGHTS_CACHE_TTL_SEC)

# Latest-price CTE без time-window (та же логика, что в /summary и
# /market-overview): price_history пополняется только при изменении цены,
# поэтому свежесть текущей цены гарантируется l.is_active, а не окном.
_LATEST_PRICE_CTE = """
    latest_price AS (
        SELECT DISTINCT ON (listing_id) listing_id, price_kzt
        FROM price_history
        WHERE price_kzt > 0
        ORDER BY listing_id, recorded_at DESC
    )
"""


# ── 1. Лидеры падения цены ───────────────────────────────────────────────

@router.get("/price-drop-leaders", summary="Топ моделей по падению медианной цены за период")
async def price_drop_leaders(
    period_days: int = Query(90, description="Глубина сравнения: 90, 180 или 365 дней"),
    limit: int = Query(10, ge=1, le=50),
    min_samples: int = Query(20, ge=5, le=200, description="Минимум объявлений модели в каждом из двух окон"),
):
    """
    Сравнивает медианную цену модели в 14-дневном окне НАЧАЛА периода
    с медианой за ПОСЛЕДНИЕ 14 дней. Возвращает только реально подешевевшие
    модели, отсортированные по drop_pct (положительный = падение).

    Медиана вместо среднего + порог min_samples — защита от выбросов и шума
    маленьких выборок (одна перекупская девятка не должна делать «тренд»).
    """
    if period_days not in (90, 180, 365):
        raise HTTPException(status_code=422, detail="period_days must be one of: 90, 180, 365")

    cache_key = f"drop-leaders:{period_days}:{limit}:{min_samples}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    query = """
        WITH then_window AS (
            SELECT l.model_id,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ph.price_kzt)::bigint AS median_then,
                   COUNT(DISTINCT l.id)::int AS sample_then
            FROM price_history ph
            JOIN listings l ON l.id = ph.listing_id
            WHERE ph.price_kzt > 0
              AND l.model_id IS NOT NULL
              AND ph.recorded_at >= NOW() - ($1 * INTERVAL '1 day')
              AND ph.recorded_at <  NOW() - ($1 * INTERVAL '1 day') + INTERVAL '14 days'
            GROUP BY l.model_id
        ),
        now_window AS (
            SELECT l.model_id,
                   PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ph.price_kzt)::bigint AS median_now,
                   COUNT(DISTINCT l.id)::int AS sample_now
            FROM price_history ph
            JOIN listings l ON l.id = ph.listing_id
            WHERE ph.price_kzt > 0
              AND l.model_id IS NOT NULL
              AND ph.recorded_at >= NOW() - INTERVAL '14 days'
            GROUP BY l.model_id
        )
        SELECT
            b.name AS brand,
            m.name AS model,
            t.model_id,
            t.median_then AS median_then_kzt,
            n.median_now  AS median_now_kzt,
            ROUND((t.median_then - n.median_now) * 100.0 / t.median_then, 2)::float AS drop_pct,
            t.sample_then,
            n.sample_now
        FROM then_window t
        JOIN now_window n USING (model_id)
        JOIN models m ON m.id = t.model_id
        JOIN brands b ON b.id = m.brand_id
        WHERE t.sample_then >= $2
          AND n.sample_now  >= $2
          AND t.median_then > 0
          AND n.median_now < t.median_then
        ORDER BY drop_pct DESC
        LIMIT $3
    """
    async with DBSession() as conn:
        rows = await conn.fetch(query, period_days, min_samples, limit)

    payload = {
        "meta": {
            "period_days": period_days,
            "window_days": 14,
            "min_samples": min_samples,
            "method": (
                "median price_kzt over price_history: 14-day window at period start "
                "vs last 14 days; only models with median_now < median_then; "
                "drop_pct = (median_then - median_now) / median_then * 100"
            ),
        },
        "leaders": [dict(r) for r in rows],
    }
    _cache.set(cache_key, payload)
    return payload


# ── 2. Сезонность цен ────────────────────────────────────────────────────

_SEASONS = {
    "winter": (12, 1, 2),
    "spring": (3, 4, 5),
    "summer": (6, 7, 8),
    "autumn": (9, 10, 11),
}


@router.get("/seasonality", summary="Средняя/медианная цена по месяцам и сезонам")
async def seasonality(
    brand_id: Optional[int] = Query(None, ge=1, description="Ограничить одной маркой"),
):
    """
    Календарная сезонность: avg + median price_kzt по месяцам за всю
    доступную историю price_history (глобально или по одной марке).
    Сезоны агрегируются из месяцев взвешенно по числу наблюдений.

    Внимание для статей: это индекс наблюдаемых цен, состав выборки между
    месяцами меняется (парсинг стартовал не в январе) — см. observations.
    """
    cache_key = f"seasonality:{brand_id}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    conditions = ["ph.price_kzt > 0"]
    params: list = []
    if brand_id is not None:
        conditions.append("l.brand_id = $1")
        params.append(brand_id)
    where = " AND ".join(conditions)

    query = f"""
        SELECT
            EXTRACT(MONTH FROM ph.recorded_at)::int AS month,
            ROUND(AVG(ph.price_kzt))::bigint AS avg_price_kzt,
            PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ph.price_kzt)::bigint AS median_price_kzt,
            COUNT(*)::int AS observations,
            COUNT(DISTINCT l.id)::int AS listings
        FROM price_history ph
        JOIN listings l ON l.id = ph.listing_id
        WHERE {where}
        GROUP BY EXTRACT(MONTH FROM ph.recorded_at)
        ORDER BY month
    """
    async with DBSession() as conn:
        rows = await conn.fetch(query, *params)

    months = [dict(r) for r in rows]
    by_month = {m["month"]: m for m in months}

    seasons = []
    for season, season_months in _SEASONS.items():
        present = [by_month[mo] for mo in season_months if mo in by_month]
        total_obs = sum(m["observations"] for m in present)
        seasons.append({
            "season": season,
            "months": list(season_months),
            "avg_price_kzt": (
                round(sum(m["avg_price_kzt"] * m["observations"] for m in present) / total_obs)
                if total_obs else None
            ),
            "observations": total_obs,
        })

    payload = {
        "meta": {
            "brand_id": brand_id,
            "method": (
                "avg/median of all price_history observations grouped by calendar "
                "month (full available history); season avg is observation-weighted "
                "mean of month averages"
            ),
        },
        "months": months,
        "seasons": seasons,
    }
    _cache.set(cache_key, payload)
    return payload


# ── 3. Волатильность цен по брендам ──────────────────────────────────────

@router.get("/brand-volatility", summary="Волатильность цены по брендам (CV месячных медиан)")
async def brand_volatility(
    period_days: int = Query(365, ge=90, le=730, description="Глубина истории"),
    min_months: int = Query(3, ge=2, le=12, description="Минимум месячных точек у бренда"),
    min_listings_per_month: int = Query(30, ge=5, le=500, description="Минимум объявлений бренда в месяце"),
    limit: int = Query(20, ge=1, le=50),
    order: str = Query(
        "stable",
        pattern="^(stable|volatile)$",
        description="stable = самые стабильные первыми (для «почему Toyota держит цену»), volatile = наоборот",
    ),
):
    """
    Метрика: coefficient of variation (stddev / mean, в %) МЕСЯЧНЫХ МЕДИАН
    цены бренда за период. Медиана внутри месяца гасит выбросы и смену
    состава объявлений; CV нормирует на уровень цен — Toyota и Lada
    сравнимы несмотря на разный порядок цен. Ниже volatility_pct = бренд
    стабильнее держит цену.
    """
    cache_key = f"brand-volatility:{period_days}:{min_months}:{min_listings_per_month}:{limit}:{order}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    # order валидирован pattern'ом; в SQL — только из whitelist-словаря
    direction = {"stable": "ASC", "volatile": "DESC"}[order]

    query = f"""
        WITH monthly AS (
            SELECT
                l.brand_id,
                DATE_TRUNC('month', ph.recorded_at) AS month,
                PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY ph.price_kzt) AS median_price
            FROM price_history ph
            JOIN listings l ON l.id = ph.listing_id
            WHERE ph.price_kzt > 0
              AND l.brand_id IS NOT NULL
              AND ph.recorded_at >= NOW() - ($1 * INTERVAL '1 day')
            GROUP BY l.brand_id, DATE_TRUNC('month', ph.recorded_at)
            HAVING COUNT(DISTINCT l.id) >= $2
        )
        SELECT
            b.name AS brand,
            mo.brand_id,
            COUNT(*)::int AS months,
            ROUND(AVG(mo.median_price)::numeric)::bigint AS avg_monthly_median_kzt,
            ROUND(STDDEV_SAMP(mo.median_price)::numeric)::bigint AS stddev_kzt,
            ROUND((STDDEV_SAMP(mo.median_price) * 100.0 / NULLIF(AVG(mo.median_price), 0))::numeric, 2)::float AS volatility_pct
        FROM monthly mo
        JOIN brands b ON b.id = mo.brand_id
        GROUP BY mo.brand_id, b.name
        HAVING COUNT(*) >= $3 AND STDDEV_SAMP(mo.median_price) IS NOT NULL
        ORDER BY volatility_pct {direction}
        LIMIT $4
    """
    async with DBSession() as conn:
        rows = await conn.fetch(query, period_days, min_listings_per_month, min_months, limit)

    payload = {
        "meta": {
            "period_days": period_days,
            "min_months": min_months,
            "min_listings_per_month": min_listings_per_month,
            "order": order,
            "method": (
                "volatility_pct = coefficient of variation (sample stddev / mean * 100) "
                "of MONTHLY MEDIAN price_kzt per brand; months with fewer than "
                "min_listings_per_month distinct listings are excluded"
            ),
        },
        "brands": [dict(r) for r in rows],
    }
    _cache.set(cache_key, payload)
    return payload


# ── 4. Ценовые корзины ───────────────────────────────────────────────────

@router.get("/price-buckets", summary="Распределение активных объявлений по ценовым корзинам")
async def price_buckets(
    bucket_size_kzt: int = Query(2_000_000, ge=250_000, le=10_000_000, description="Ширина корзины в тенге"),
    max_price_kzt: int = Query(20_000_000, ge=1_000_000, le=100_000_000,
                               description="Потолок шкалы: всё дороже попадает в overflow-корзину"),
):
    """
    Гистограмма ТЕКУЩИХ цен активных объявлений (последняя запись
    price_history на listing). Дороже max_price_kzt — одна overflow-корзина
    (to_kzt = null). share_pct — доля корзины от всех приценённых активных.
    """
    n_full_buckets = max_price_kzt // bucket_size_kzt
    if n_full_buckets < 2 or n_full_buckets > 40:
        raise HTTPException(
            status_code=422,
            detail="max_price_kzt / bucket_size_kzt must yield between 2 and 40 buckets",
        )

    cache_key = f"price-buckets:{bucket_size_kzt}:{max_price_kzt}"
    cached = _cache.get(cache_key)
    if cached is not None:
        return cached

    query = f"""
        WITH {_LATEST_PRICE_CTE}
        SELECT
            -- ::int только ПОСЛЕ LEAST: мусорная цена в триллионы тенге
            -- переполнила бы int при касте до усечения потолком
            LEAST(FLOOR(lp.price_kzt / $1::numeric), $2::numeric)::int AS bucket_idx,
            COUNT(*)::int AS count
        FROM listings l
        JOIN latest_price lp ON lp.listing_id = l.id
        WHERE l.is_active = TRUE
        GROUP BY bucket_idx
        ORDER BY bucket_idx
    """
    async with DBSession() as conn:
        rows = await conn.fetch(query, bucket_size_kzt, n_full_buckets)

    counts = {r["bucket_idx"]: r["count"] for r in rows}
    total = sum(counts.values())
    buckets = []
    for idx in range(n_full_buckets + 1):
        count = counts.get(idx, 0)
        is_overflow = idx == n_full_buckets
        buckets.append({
            "from_kzt": idx * bucket_size_kzt,
            "to_kzt": None if is_overflow else (idx + 1) * bucket_size_kzt,
            "count": count,
            "share_pct": round(count * 100.0 / total, 2) if total else 0.0,
        })

    payload = {
        "meta": {
            "bucket_size_kzt": bucket_size_kzt,
            "max_price_kzt": max_price_kzt,
            "total_listings": total,
            "method": (
                "latest price_history record per ACTIVE listing, bucketed by "
                "bucket_size_kzt; last bucket (to_kzt = null) collects everything "
                "above max_price_kzt"
            ),
        },
        "buckets": buckets,
    }
    _cache.set(cache_key, payload)
    return payload
