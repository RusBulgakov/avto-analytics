// pages/index.tsx — Dashboard (trading terminal redesign, steps 1–6)
import { useState } from 'react';
import Link from 'next/link';
import useSWR from 'swr';

import Seo from '@/components/Seo';

import Topbar from '@/components/layout/Topbar';
import FilterBar from '@/components/layout/FilterBar';
import KPI from '@/components/ui/KPI';
import Badge from '@/components/ui/Badge';
import PriceChart from '@/components/charts/PriceChart';
import PriceCandles, { type Candle, type Granularity } from '@/components/charts/PriceCandles';
import BoxPlot from '@/components/charts/BoxPlot';
import Heatmap, { type HeatmapCell } from '@/components/charts/Heatmap';
import Funnel, { type FunnelBucket } from '@/components/charts/Funnel';
import KZMap from '@/components/charts/KZMap';
import RecentFeed, { type RecentItem } from '@/components/feed/RecentFeed';

import { analyticsApi } from '@/lib/api';
import { fmt } from '@/lib/format';
import { useUsdKzt } from '@/hooks/useUsdKzt';
import { useSyncFiltersWithUrl } from '@/hooks/useSyncFiltersWithUrl';
import { useFilters, selectFilterState } from '@/store/filters';
import {
    type FilterState,
    type SummaryResponse,
    type BrandOverview,
} from '@/types/analytics';

function buildApiFilters(filters: FilterState) {
    const params: Record<string, unknown> = {
        period_days: filters.period === 'all' ? undefined : filters.period,
    };
    if (filters.brand_id.length) params.brand_id = filters.brand_id;
    if (filters.model_id.length) params.model_id = filters.model_id;
    if (filters.city.length) params.city = filters.city;
    if (filters.source.length) params.source = filters.source;
    if (filters.include_inactive) params.include_inactive = true;
    return params;
}

export default function Dashboard() {
    // Filters are kept in a zustand store that auto-syncs with the URL query.
    useSyncFiltersWithUrl();
    const filters = useFilters(selectFilterState);
    const setAll = useFilters(s => s.setAll);
    const setFilters = (next: FilterState) => setAll(next);
    const apiParams = buildApiFilters(filters);

    const { data: summary, isLoading: summaryLoading } = useSWR<SummaryResponse>(
        ['summary', apiParams],
        () => analyticsApi.getSummary(apiParams),
        { keepPreviousData: true, refreshInterval: 60_000 }
    );

    // Granularity: user override for chart's time bucket. 'auto' lets backend
    // pick (day for ≤14д, week for ≤180д, month for >180д). Backend echoes the
    // resolved granularity back so PriceChart formats ticks/tooltips correctly.
    const [chartGranularity, setChartGranularity] = useState<'auto' | Granularity>('auto');

    const priceHistoryParams = {
        ...apiParams,
        ...(chartGranularity !== 'auto' ? { granularity: chartGranularity } : {}),
    };
    const { data: priceHistoryData, isLoading: chartLoading } = useSWR<{
        granularity: Granularity;
        points: { date: string; avg_price_kzt: number; median_price_kzt: number; listing_count: number }[];
    }>(
        ['price-history', priceHistoryParams],
        () => analyticsApi.getPriceHistory(priceHistoryParams),
        { keepPreviousData: true }
    );
    const priceHistory = priceHistoryData?.points ?? [];
    const resolvedGranularity: Granularity = priceHistoryData?.granularity ?? 'day';

    // Свечи цен — отдельный widget с собственным granularity (по умолчанию = week
    // для 90д default period). Фильтры марки/города наследуем с дашборда.
    const [candlesGranularity, setCandlesGranularity] = useState<'auto' | Granularity>('auto');
    const candlesParams: Record<string, unknown> = {
        period_days: filters.period === 'all' ? 365 : filters.period,
        ...(candlesGranularity !== 'auto' ? { granularity: candlesGranularity } : {}),
    };
    if (filters.brand_id.length === 1) candlesParams.brand_id = filters.brand_id[0];
    if (filters.model_id.length === 1) candlesParams.model_id = filters.model_id[0];
    if (filters.city.length) candlesParams.city = filters.city;
    if (filters.source.length) candlesParams.source = filters.source;
    if (filters.include_inactive) candlesParams.include_inactive = true;

    const { data: candlesData, isLoading: candlesLoading } = useSWR<{
        granularity: Granularity;
        candles: Candle[];
    }>(
        ['price-candles', candlesParams],
        () => analyticsApi.getPriceCandles(candlesParams),
        { keepPreviousData: true }
    );

    const { data: overview, isLoading: overviewLoading } = useSWR<BrandOverview[]>(
        ['market-overview', apiParams],
        () => analyticsApi.getMarketOverview(apiParams),
        { keepPreviousData: true }
    );

    // Heatmap: supports single brand filter (pass first element)
    const singleBrand = filters.brand_id[0];
    const heatmapParams: Record<string, unknown> = {};
    if (singleBrand != null) heatmapParams.brand_id = singleBrand;
    if (filters.city.length) heatmapParams.city = filters.city;
    if (filters.source.length) heatmapParams.source = filters.source;
    if (filters.include_inactive) heatmapParams.include_inactive = true;

    const { data: heatmap, isLoading: heatmapLoading } = useSWR<HeatmapCell[]>(
        ['heatmap', heatmapParams],
        () => analyticsApi.getHeatmap(heatmapParams),
        { keepPreviousData: true }
    );

    const { data: liquidity, isLoading: liquidityLoading } = useSWR<FunnelBucket[]>(
        ['liquidity', heatmapParams],
        () => analyticsApi.getLiquidity(heatmapParams),
        { keepPreviousData: true }
    );

    const recentParams: Record<string, unknown> = { limit: 10 };
    if (singleBrand != null) recentParams.brand_id = singleBrand;
    if (filters.model_id.length === 1) recentParams.model_id = filters.model_id[0];
    if (filters.city.length) recentParams.city = filters.city;
    if (filters.source.length) recentParams.source = filters.source;

    const { data: recent, isLoading: recentLoading } = useSWR<RecentItem[]>(
        ['recent', recentParams],
        () => analyticsApi.getRecent(recentParams),
        { keepPreviousData: true, refreshInterval: 30_000 }
    );

    const selectedBrandId = filters.brand_id.length === 1 ? filters.brand_id[0] : null;
    // Слаг выбранной марки — для ссылок на /model из топ-таблицы моделей
    const { data: allBrands } = useSWR<{ id: number; name: string; slug: string | null; listings_count: number }[]>(
        'brands',
        () => analyticsApi.getBrands(),
        { revalidateOnFocus: false }
    );
    const selectedBrandSlug = selectedBrandId != null
        ? (allBrands?.find(b => b.id === selectedBrandId)?.slug ?? null)
        : null;
    const boxplotParams = {
        city: filters.city.length ? filters.city : undefined,
        source: filters.source.length ? filters.source : undefined,
        ...(selectedBrandId ? { brand_id: selectedBrandId } : {}),
        ...(filters.include_inactive ? { include_inactive: true } : {}),
    };
    const { data: boxplotData, isLoading: boxplotLoading } = useSWR(
        ['price-boxplot', boxplotParams],
        () => analyticsApi.getPriceBoxplot(boxplotParams),
        { keepPreviousData: true }
    );

    const geoParams: Record<string, unknown> = {};
    if (filters.include_inactive) geoParams.include_inactive = true;
    if (filters.brand_id.length) geoParams.brand_id = filters.brand_id;
    if (filters.model_id.length) geoParams.model_id = filters.model_id;
    const { data: geo, isLoading: geoLoading } = useSWR(
        ['geo', geoParams],
        () => analyticsApi.getGeo(geoParams),
        { keepPreviousData: true, refreshInterval: 300_000 }
    );

    const { data: fx } = useUsdKzt();

    const totalListings = summary?.active_listings;
    const totalBrands = summary?.total_brands;
    const avgPrice = summary?.avg_price_kzt;
    const indexValue = avgPrice ? avgPrice / 1_000_000 : null;

    // Fast-sale share = (0-3 + 4-7) / total — for liquidity KPI
    const fastShare = liquidity
        ? liquidity.filter(b => b.bucket === '0-3' || b.bucket === '4-7').reduce((s, b) => s + b.pct, 0)
        : null;

    return (
        <>
            <Seo
                title="Авто Аналитика KZ — Торговый терминал"
                description="Аналитика авторынка Казахстана. Индекс цен, рентабельность, live-лента объявлений."
                path="/"
            />

            <div className="app">
                <Topbar />
                <FilterBar filters={filters} onChange={setFilters} />

                <main className="main">
                    {/* ── KPI row ─────────────────────────────────────── */}
                    <section className="kpi-grid" aria-label="Ключевые показатели">
                        <KPI
                            label="Индекс цен AA·IDX"
                            value={
                                summaryLoading && indexValue == null
                                    ? '…'
                                    : indexValue != null
                                        ? indexValue.toFixed(2)
                                        : '—'
                            }
                            unit="млн ₸"
                            foot={<span>средняя по активным объявлениям</span>}
                        />
                        <KPI
                            label={filters.include_inactive ? 'Все объявления' : 'Активные объявления'}
                            value={
                                summaryLoading && totalListings == null
                                    ? '…'
                                    : totalListings != null
                                        ? fmt.int(totalListings)
                                        : '—'
                            }
                            foot={
                                summary?.sources?.length
                                    ? <span>с {summary.sources.length} площадок</span>
                                    : null
                            }
                        />
                        <KPI
                            label="Ликвидность"
                            value={fastShare != null ? fastShare.toFixed(0) : '…'}
                            unit="%"
                            inverted={false}
                            foot={<span>{'продано <7 дней'}</span>}
                        />
                        <KPI
                            label="USD / KZT"
                            value={fx ? fx.rate.toFixed(2) : '…'}
                            delta={fx?.delta ?? null}
                            deltaCaption="за 24 ч"
                            foot={
                                fx
                                    ? <span>обновлено {fx.updatedAt.toLocaleDateString('ru-RU')}</span>
                                    : <span>open.er-api.com</span>
                            }
                        />
                    </section>

                    {/* ── Main chart + Live feed ──────────────────────── */}
                    <section className="grid-2-1">
                        <div className="card">
                            <div className="card-h">
                                <div>
                                    <div className="card-title">Динамика цен</div>
                                    <div className="card-sub">
                                        Средняя и медиана · период {filters.period === 'all' ? 'весь' : `${filters.period}д`}
                                        {chartGranularity === 'auto' && priceHistoryData
                                            ? ` · бакет ${resolvedGranularity === 'day' ? 'день' : resolvedGranularity === 'week' ? 'неделя' : 'месяц'}`
                                            : null}
                                    </div>
                                </div>
                                <div className="period-group" role="group" aria-label="Шаг агрегации">
                                    {(['auto', 'day', 'week', 'month'] as const).map(g => (
                                        <button
                                            key={g}
                                            type="button"
                                            className={`period-btn ${chartGranularity === g ? 'active' : ''}`}
                                            onClick={() => setChartGranularity(g)}
                                        >
                                            {g === 'auto' ? 'авто' : g === 'day' ? '1д' : g === 'week' ? '1н' : '1м'}
                                        </button>
                                    ))}
                                </div>
                            </div>
                            <div className="card-b">
                                <PriceChart
                                    data={priceHistory}
                                    loading={chartLoading}
                                    granularity={resolvedGranularity}
                                />
                            </div>
                        </div>

                        <div className="card">
                            <div className="card-h">
                                <div>
                                    <div className="card-title">Лента new listings</div>
                                    <div className="card-sub">
                                        {recentLoading && !recent ? 'загрузка…' : `обновляется каждые 30с · ${recent?.length ?? 0} шт.`}
                                    </div>
                                </div>
                                <span className="live-dot" aria-hidden />
                            </div>
                            <div
                                className="card-b flush"
                                style={{ maxHeight: 360, overflowY: 'auto' }}
                            >
                                <RecentFeed data={recent ?? []} loading={recentLoading} />
                            </div>
                        </div>
                    </section>

                    {/* ── Heatmap + Funnel ────────────────────────────── */}
                    <section className="grid-2-1">
                        <div className="card">
                            <div className="card-h">
                                <div>
                                    <div className="card-title">Матрица год × пробег</div>
                                    <div className="card-sub">
                                        {selectedBrandId ? 'для выбранной марки' : 'весь рынок'} · средняя цена или объём
                                    </div>
                                </div>
                            </div>
                            <div className="card-b">
                                <Heatmap data={heatmap ?? []} loading={heatmapLoading} />
                            </div>
                        </div>

                        <div className="card">
                            <div className="card-h">
                                <div>
                                    <div className="card-title">Воронка ликвидности</div>
                                    <div className="card-sub">дней до закрытия · последние 180 дней</div>
                                </div>
                            </div>
                            <div className="card-b">
                                <Funnel data={liquidity ?? []} loading={liquidityLoading} />
                            </div>
                        </div>
                    </section>

                    {/* ── KZ Map + Sources ────────────────────────────── */}
                    <section className="grid-2-1">
                        <div className="card">
                            <div className="card-h">
                                <div>
                                    <div className="card-title">География KZ</div>
                                    <div className="card-sub">
                                        {filters.include_inactive ? 'все объявления' : 'активные объявления'} по городам · клик → фильтр
                                    </div>
                                </div>
                            </div>
                            <div className="card-b">
                                <KZMap data={geo ?? []} loading={geoLoading} />
                            </div>
                        </div>

                        <div className="card">
                            <div className="card-h">
                                <div>
                                    <div className="card-title">Источники данных</div>
                                    <div className="card-sub">доля активных объявлений</div>
                                </div>
                            </div>
                            <div className="card-b">
                                {summaryLoading && !summary ? (
                                    <div className="skeleton" style={{ height: 120 }} />
                                ) : summary?.sources?.length ? (
                                    <div>
                                        {summary.sources.map(s => {
                                            const pct = summary.active_listings
                                                ? Math.round((s.count / summary.active_listings) * 100)
                                                : 0;
                                            return (
                                                <div className="src-row" key={s.name}>
                                                    <div className="src-name">{s.name}</div>
                                                    <div className="src-count">
                                                        {fmt.int(s.count)} <span className="dim">· {pct}%</span>
                                                    </div>
                                                    <div className="src-bar">
                                                        <div className="src-bar-fill" style={{ width: `${pct}%` }} />
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                ) : (
                                    <div style={{ color: 'var(--text-muted)', padding: 12 }}>Нет данных</div>
                                )}
                            </div>
                        </div>
                    </section>

                    {/* ── Свечи распределения цен по времени ───────────── */}
                    <section className="card">
                        <div className="card-h">
                            <div>
                                <div className="card-title">Свечи цен — распределение по времени</div>
                                <div className="card-sub">
                                    {filters.brand_id.length === 1 && filters.model_id.length === 1
                                        ? 'выбранная модель'
                                        : filters.brand_id.length === 1
                                            ? 'выбранная марка'
                                            : 'весь рынок'}
                                    {' · '}тело Q1–Q3, усы P5–P95, медиана = тик
                                </div>
                            </div>
                            <div className="period-group" role="group" aria-label="Шаг бакета свечей">
                                {(['auto', 'day', 'week', 'month'] as const).map(g => (
                                    <button
                                        key={g}
                                        type="button"
                                        className={`period-btn ${candlesGranularity === g ? 'active' : ''}`}
                                        onClick={() => setCandlesGranularity(g)}
                                    >
                                        {g === 'auto' ? 'авто' : g === 'day' ? '1д' : g === 'week' ? '1н' : '1м'}
                                    </button>
                                ))}
                            </div>
                        </div>
                        <div className="card-b">
                            <PriceCandles
                                data={candlesData?.candles ?? []}
                                granularity={candlesData?.granularity ?? 'week'}
                                loading={candlesLoading}
                            />
                        </div>
                    </section>

                    {/* ── Boxplot (full width) ─────────────────────────── */}
                    <section className="card">
                        <div className="card-h">
                            <div>
                                <div className="card-title">
                                    {selectedBrandId ? 'Распределение цен по моделям' : 'Распределение цен по маркам'}
                                </div>
                                <div className="card-sub">Топ-10 · медиана, квартили, разброс</div>
                            </div>
                        </div>
                        <div className="card-b">
                            <BoxPlot data={boxplotData ?? []} loading={boxplotLoading} />
                        </div>
                    </section>

                    {/* ── Top table ───────────────────────────────────── */}
                    <section className="card">
                        <div className="card-h">
                            <div>
                                <div className="card-title">
                                    {selectedBrandId ? 'Топ моделей по объявлениям' : 'Топ марок по объявлениям'}
                                </div>
                                <div className="card-sub">отсортировано по количеству активных</div>
                            </div>
                        </div>
                        <div className="card-b flush">
                            {overviewLoading && !overview ? (
                                <div className="skeleton" style={{ height: 200, margin: 16 }} />
                            ) : (
                                <table className="tbl">
                                    <thead>
                                        <tr>
                                            <th style={{ width: 44 }}>#</th>
                                            <th>{selectedBrandId ? 'Модель' : 'Марка'}</th>
                                            <th className="right">Активных</th>
                                            <th className="right">Ср. цена</th>
                                            <th className="right">Мин — Макс</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {(overview ?? []).slice(0, 10).map((b, i) => (
                                            <tr key={b.brand}>
                                                <td><span className="rank">{i + 1}</span></td>
                                                <td>
                                                    {selectedBrandId && selectedBrandSlug && b.slug ? (
                                                        <Link
                                                            href={{ pathname: '/model', query: { brand: selectedBrandSlug, model: b.slug } }}
                                                            style={{ color: 'inherit' }}
                                                        >
                                                            <strong>{b.brand}</strong>
                                                        </Link>
                                                    ) : (
                                                        <strong>{selectedBrandId ? b.brand : fmt.brandName(b.brand)}</strong>
                                                    )}
                                                </td>
                                                <td className="num">{fmt.int(b.active_listings)}</td>
                                                <td className="num">{fmt.price(b.avg_price_kzt)}</td>
                                                <td className="num dim">
                                                    {fmt.price(b.min_price_kzt)} — {fmt.price(b.max_price_kzt)}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            )}
                        </div>
                    </section>
                </main>
            </div>
        </>
    );
}
