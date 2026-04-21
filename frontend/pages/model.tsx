// pages/model.tsx — Model detail page (trading-terminal redesign).
// Resolves brand/model via ?brand=<slug>&model=<slug> query params.
// Plain static page → compatible with `output: 'export'`. All data fetching client-side.
import { useMemo, useState } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import { useRouter } from 'next/router';
import useSWR from 'swr';

import Topbar from '@/components/layout/Topbar';
import Badge from '@/components/ui/Badge';
import PriceChart from '@/components/charts/PriceChart';
import Heatmap, { type HeatmapCell } from '@/components/charts/Heatmap';
import BoxPlot from '@/components/charts/BoxPlot';
import RecentFeed, { type RecentItem } from '@/components/feed/RecentFeed';

import { analyticsApi } from '@/lib/api';
import { fmt } from '@/lib/format';

type Period = 7 | 30 | 90 | 180 | 365;
const PERIODS: Period[] = [7, 30, 90, 180, 365];

interface BrandRow {
    id: number;
    name: string;
    slug: string | null;
    listings_count: number;
}
interface ModelRow {
    id: number;
    name: string;
    slug: string | null;
    listings_count: number;
}
interface PricePoint {
    date: string;
    avg_price_kzt: number;
    median_price_kzt: number;
    listing_count: number;
}
interface OverviewRow {
    brand: string;
    active_listings: number;
    avg_price_kzt: number;
    min_price_kzt: number;
    max_price_kzt: number;
}

function slugEq(a: string | null | undefined, b: string | null | undefined): boolean {
    if (!a || !b) return false;
    return a.toLowerCase() === b.toLowerCase();
}

function median(values: number[]): number | null {
    if (!values.length) return null;
    const sorted = [...values].sort((a, b) => a - b);
    const mid = Math.floor(sorted.length / 2);
    return sorted.length % 2
        ? sorted[mid]
        : Math.round((sorted[mid - 1] + sorted[mid]) / 2);
}

function averageRound(values: number[]): number | null {
    if (!values.length) return null;
    return Math.round(values.reduce((s, v) => s + v, 0) / values.length);
}

function NotFound({ brandSlug, modelSlug }: { brandSlug?: string; modelSlug?: string }) {
    return (
        <div className="app">
            <Topbar />
            <main className="main">
                <div className="breadcrumb">
                    <Link href="/">Дашборд</Link>
                    <span className="sep">/</span>
                    <span style={{ color: 'var(--text)' }}>не найдено</span>
                </div>
                <div className="card">
                    <div className="model-notfound">
                        <div className="title">Не найдено</div>
                        <div>
                            Марка &laquo;{brandSlug || '—'}&raquo;
                            {modelSlug ? <> / модель &laquo;{modelSlug}&raquo;</> : null}
                            {' '}
                            не существует в нашей базе.
                        </div>
                        <div style={{ marginTop: 16 }}>
                            <Link href="/" className="btn btn-primary">На главную</Link>
                        </div>
                    </div>
                </div>
            </main>
        </div>
    );
}

export default function ModelPage() {
    const router = useRouter();
    // useRouter().query is {} until hydration; coerce to string | undefined
    const rawBrand = router.query.brand;
    const rawModel = router.query.model;
    const brandSlug = typeof rawBrand === 'string' ? rawBrand : undefined;
    const modelSlug = typeof rawModel === 'string' ? rawModel : undefined;

    const [period, setPeriod] = useState<Period>(90);

    // Step 1: brands list (cached globally)
    const { data: brands, isLoading: brandsLoading } = useSWR<BrandRow[]>(
        'brands',
        () => analyticsApi.getBrands(),
        { revalidateOnFocus: false }
    );

    const brand = useMemo(() => {
        if (!brands || !brandSlug) return null;
        return brands.find(b => slugEq(b.slug, brandSlug) || slugEq(b.name, brandSlug)) || null;
    }, [brands, brandSlug]);

    // Step 2: models for resolved brand
    const { data: models, isLoading: modelsLoading } = useSWR<ModelRow[]>(
        brand ? ['models', brand.id] : null,
        () => analyticsApi.getModels(brand!.id),
        { revalidateOnFocus: false }
    );

    const model = useMemo(() => {
        if (!models || !modelSlug) return null;
        return models.find(m => slugEq(m.slug, modelSlug) || slugEq(m.name, modelSlug)) || null;
    }, [models, modelSlug]);

    const ready = router.isReady;
    const resolving = brandsLoading || (brand && modelsLoading);

    // Price history (chart)
    const historyParams = brand && model
        ? { brand_id: brand.id, model_id: model.id, period_days: period }
        : null;
    const { data: priceHistory, isLoading: chartLoading } = useSWR<PricePoint[]>(
        historyParams ? ['price-history', historyParams] : null,
        () => analyticsApi.getPriceHistory(historyParams!),
        { keepPreviousData: true }
    );

    // Recent listings (right column, top 10) — scoped by brand (API doesn't accept model_id)
    const recentParams = brand ? { brand_id: brand.id, limit: 10 } : null;
    const { data: recent, isLoading: recentLoading } = useSWR<RecentItem[]>(
        recentParams ? ['recent', recentParams] : null,
        () => analyticsApi.getRecent(recentParams!),
        { keepPreviousData: true, refreshInterval: 30_000 }
    );

    // Bigger recent sample for city grouping / mileage-year stats (50 rows)
    const statsParams = brand ? { brand_id: brand.id, limit: 50 } : null;
    const { data: recentSample } = useSWR<RecentItem[]>(
        statsParams ? ['recent-stats', statsParams] : null,
        () => analyticsApi.getRecent(statsParams!),
        { keepPreviousData: true }
    );

    // Heatmap — scoped by brand (endpoint treats brand_id single value)
    const heatmapParams = brand ? { brand_id: brand.id } : null;
    const { data: heatmap, isLoading: heatmapLoading } = useSWR<HeatmapCell[]>(
        heatmapParams ? ['heatmap', heatmapParams] : null,
        () => analyticsApi.getHeatmap(heatmapParams!),
        { keepPreviousData: true }
    );

    // Boxplot — brand_id makes endpoint return top-10 models of that brand
    const boxplotParams = brand ? { brand_id: brand.id } : null;
    const { data: boxplotData, isLoading: boxplotLoading } = useSWR(
        boxplotParams ? ['price-boxplot', boxplotParams] : null,
        () => analyticsApi.getPriceBoxplot(boxplotParams!),
        { keepPreviousData: true }
    );

    // Overview of all brands (for competitor-band card)
    const { data: overview } = useSWR<OverviewRow[]>(
        'market-overview-all',
        () => analyticsApi.getMarketOverview(),
        { revalidateOnFocus: false }
    );

    // Derived stats
    const derived = useMemo(() => {
        const sample = recentSample ?? [];
        const ourRows = sample.filter(
            r => r.model && r.model.toLowerCase() === (model?.name ?? '').toLowerCase()
        );
        const prices = ourRows.map(r => r.price_kzt).filter((x): x is number => x != null && x > 0);
        const mileagesTysKm = ourRows
            .map(r => r.mileage_km)
            .filter((x): x is number => x != null && x > 0)
            .map(km => Math.round(km / 1000));
        const years = ourRows.map(r => r.year).filter((x): x is number => x != null && x > 0);

        let medianPrice: number | null = null;
        if (priceHistory && priceHistory.length) {
            // Average of per-day medians from history is a good quick stat
            const meds = priceHistory.map(p => p.median_price_kzt).filter(n => n > 0);
            if (meds.length) medianPrice = Math.round(meds.reduce((a, b) => a + b, 0) / meds.length);
        }
        if (medianPrice == null) medianPrice = median(prices);

        const minPrice = prices.length ? Math.min(...prices) : null;
        const maxPrice = prices.length ? Math.max(...prices) : null;
        const avgMileage = averageRound(mileagesTysKm);
        const avgYear = years.length
            ? (years.reduce((a, b) => a + b, 0) / years.length).toFixed(1)
            : null;

        // Active listing count
        let count = priceHistory && priceHistory.length
            ? priceHistory[priceHistory.length - 1].listing_count
            : null;
        if (count == null && models && model) {
            const hit = models.find(m => m.id === model.id);
            if (hit) count = hit.listings_count;
        }

        // City breakdown
        const cityMap = new Map<string, number>();
        for (const r of ourRows) {
            const c = r.city || 'Другие';
            cityMap.set(c, (cityMap.get(c) ?? 0) + 1);
        }
        const cities = Array.from(cityMap.entries())
            .sort((a, b) => b[1] - a[1])
            .slice(0, 5)
            .map(([city, n]) => ({ city, n }));

        // Year range — infer from sample
        const minYear = years.length ? Math.min(...years) : null;
        const maxYear = years.length ? Math.max(...years) : null;

        // 30-day delta
        let delta30: number | null = null;
        if (priceHistory && priceHistory.length >= 2) {
            const last = priceHistory[priceHistory.length - 1].avg_price_kzt;
            const first = priceHistory[0].avg_price_kzt;
            if (first > 0) delta30 = ((last - first) / first) * 100;
        }

        return {
            medianPrice, minPrice, maxPrice, avgMileage, avgYear, count,
            cities, minYear, maxYear, delta30,
        };
    }, [recentSample, priceHistory, model, models]);

    // Competitors: brands in same price band (±25% around median)
    const competitors = useMemo(() => {
        if (!overview || !derived.medianPrice) return [];
        const mid = derived.medianPrice;
        const lo = mid * 0.75;
        const hi = mid * 1.25;
        return overview
            .filter(o => o.avg_price_kzt && o.avg_price_kzt >= lo && o.avg_price_kzt <= hi)
            .filter(o => !brand || o.brand.toLowerCase() !== brand.name.toLowerCase())
            .sort((a, b) =>
                Math.abs(a.avg_price_kzt - mid) - Math.abs(b.avg_price_kzt - mid)
            )
            .slice(0, 5);
    }, [overview, derived.medianPrice, brand]);

    // ── Render guards ────────────────────────────────────────
    if (!ready) {
        return (
            <div className="app">
                <Topbar />
                <main className="main">
                    <div className="skeleton" style={{ height: 200, borderRadius: 14 }} />
                </main>
            </div>
        );
    }

    if (!brandSlug || !modelSlug) {
        return <NotFound brandSlug={brandSlug} modelSlug={modelSlug} />;
    }

    if (resolving) {
        return (
            <div className="app">
                <Topbar />
                <main className="main">
                    <div className="skeleton" style={{ height: 200, borderRadius: 14 }} />
                </main>
            </div>
        );
    }

    if (!brand || !model) {
        return <NotFound brandSlug={brandSlug} modelSlug={modelSlug} />;
    }

    const title = `${brand.name} ${model.name}`;
    const yearRange =
        derived.minYear && derived.maxYear && derived.minYear !== derived.maxYear
            ? `${derived.minYear}–${derived.maxYear}`
            : derived.minYear
                ? `${derived.minYear}`
                : null;

    return (
        <>
            <Head>
                <title>{title} — Авто Аналитика KZ</title>
                <meta name="description" content={`Аналитика ${title}: цены, объявления, прогноз.`} />
            </Head>

            <div className="app">
                <Topbar />

                <main className="main">
                    {/* Breadcrumb */}
                    <div className="breadcrumb">
                        <Link href="/">Дашборд</Link>
                        <span className="sep">/</span>
                        <Link href={{ pathname: '/', query: { brand_id: brand.id } }}>
                            Марки
                        </Link>
                        <span className="sep">/</span>
                        <Link href={{ pathname: '/model', query: { brand: brand.slug ?? brandSlug } }}>
                            {brand.name}
                        </Link>
                        <span className="sep">/</span>
                        <span style={{ color: 'var(--text)' }}>{model.name}</span>
                    </div>

                    {/* Hero */}
                    <div className="card">
                        <div className="detail-hero">
                            <div>
                                <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8, flexWrap: 'wrap' }}>
                                    <span className="page-title" style={{ fontSize: 26 }}>{title}</span>
                                    {yearRange && <Badge variant="neutral">{yearRange}</Badge>}
                                    {derived.count != null && derived.count > 0 && (
                                        <Badge variant="up">● Ликвидная</Badge>
                                    )}
                                </div>
                                <div style={{ color: 'var(--text-muted)', fontSize: 13, maxWidth: 640 }}>
                                    {derived.count != null
                                        ? <>{fmt.int(derived.count)} активных объявлений в Казахстане · аналитика цен, ликвидности и распределения.</>
                                        : <>Аналитика по модели {title}: цены, города, динамика.</>}
                                </div>
                            </div>
                            <div style={{ textAlign: 'right' }}>
                                <div className="uppercase">медианная цена</div>
                                <div className="big-price tnum">
                                    {derived.medianPrice != null
                                        ? (derived.medianPrice / 1_000_000).toFixed(1)
                                        : '—'}
                                    <span className="unit">млн ₸</span>
                                </div>
                                <div style={{ marginTop: 6, display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                                    {derived.delta30 != null && (
                                        <Badge variant={derived.delta30 >= 0 ? 'up' : 'down'}>
                                            {derived.delta30 >= 0 ? '▲' : '▼'} {Math.abs(derived.delta30).toFixed(1)}% · {period}д
                                        </Badge>
                                    )}
                                    {derived.count != null && (
                                        <Badge variant="neutral">n = {fmt.int(derived.count)}</Badge>
                                    )}
                                </div>
                            </div>
                        </div>
                        <div className="card-b">
                            <div className="stat-inline">
                                <div className="si">
                                    <div className="si-l">медиана</div>
                                    <div className="si-v">
                                        {derived.medianPrice != null ? fmt.price(derived.medianPrice) + ' ₸' : '—'}
                                    </div>
                                </div>
                                <div className="si">
                                    <div className="si-l">мин / макс</div>
                                    <div className="si-v">
                                        {derived.minPrice != null && derived.maxPrice != null
                                            ? `${fmt.price(derived.minPrice)} / ${fmt.price(derived.maxPrice)}`
                                            : '—'}
                                    </div>
                                </div>
                                <div className="si">
                                    <div className="si-l">ср. пробег</div>
                                    <div className="si-v">
                                        {derived.avgMileage != null ? fmt.km(derived.avgMileage) : '—'}
                                    </div>
                                </div>
                                <div className="si">
                                    <div className="si-l">ср. год</div>
                                    <div className="si-v">{derived.avgYear ?? '—'}</div>
                                </div>
                                <div className="si">
                                    <div className="si-l">объявлений</div>
                                    <div className="si-v">
                                        {derived.count != null ? fmt.int(derived.count) : '—'}
                                    </div>
                                </div>
                                <div className="si">
                                    <div className="si-l">дней на продажу</div>
                                    <div className="si-v">—</div>
                                </div>
                                <div className="si">
                                    <div className="si-l">прогноз</div>
                                    <div className="si-v accent">
                                        — <Badge variant="info">PRO</Badge>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* Chart + active listings */}
                    <section className="grid-2-1">
                        <div className="card">
                            <div className="card-h">
                                <div>
                                    <div className="card-title">Динамика цены · {period} дней</div>
                                    <div className="card-sub">Средняя и медиана</div>
                                </div>
                                <div className="model-period-seg" role="tablist">
                                    {PERIODS.map(p => (
                                        <button
                                            key={p}
                                            type="button"
                                            className={p === period ? 'active' : ''}
                                            onClick={() => setPeriod(p)}
                                        >
                                            {p}д
                                        </button>
                                    ))}
                                </div>
                            </div>
                            <div className="card-b">
                                <PriceChart data={priceHistory ?? []} loading={chartLoading} />
                            </div>
                        </div>
                        <div className="card">
                            <div className="card-h">
                                <div>
                                    <div className="card-title">Активные объявления</div>
                                    <div className="card-sub">
                                        {recentLoading && !recent ? 'загрузка…' : `${recent?.length ?? 0} шт. · ${brand.name}`}
                                    </div>
                                </div>
                                <span className="live-dot" aria-hidden />
                            </div>
                            <div className="card-b flush">
                                <RecentFeed data={recent ?? []} loading={recentLoading} />
                            </div>
                        </div>
                    </section>

                    {/* Heatmap */}
                    <section className="card">
                        <div className="card-h">
                            <div>
                                <div className="card-title">Матрица: год × пробег — {title}</div>
                                <div className="card-sub">Целевая цена покупки по возрасту и пробегу</div>
                            </div>
                        </div>
                        <div className="card-b">
                            <Heatmap data={heatmap ?? []} loading={heatmapLoading} />
                        </div>
                    </section>

                    {/* Three small cards */}
                    <section className="grid-1-1-1">
                        <div className="card">
                            <div className="card-h">
                                <div>
                                    <div className="card-title">По городам</div>
                                    <div className="card-sub">топ-5 по объявлениям</div>
                                </div>
                            </div>
                            <div className="card-b">
                                {derived.cities.length === 0 ? (
                                    <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: 8 }}>
                                        Нет данных
                                    </div>
                                ) : (
                                    derived.cities.map((r, i) => {
                                        const maxN = derived.cities[0].n || 1;
                                        const pct = Math.round((r.n / maxN) * 100);
                                        return (
                                            <div key={i} className="model-row">
                                                <div>
                                                    {r.city}
                                                    <span className="dim mono" style={{ fontSize: 10.5, marginLeft: 6 }}>
                                                        · {r.n}
                                                    </span>
                                                </div>
                                                <div className="src-bar" style={{ width: 80 }}>
                                                    <div className="src-bar-fill" style={{ width: `${pct}%` }} />
                                                </div>
                                                <span className="mono tnum dim" style={{ fontSize: 11 }}>
                                                    {pct}%
                                                </span>
                                            </div>
                                        );
                                    })
                                )}
                            </div>
                        </div>

                        <div className="card">
                            <div className="card-h">
                                <div>
                                    <div className="card-title">Распределение цен</div>
                                    <div className="card-sub">топ-10 моделей {brand.name}</div>
                                </div>
                            </div>
                            <div className="card-b">
                                <BoxPlot data={boxplotData ?? []} loading={boxplotLoading} />
                            </div>
                        </div>

                        <div className="card">
                            <div className="card-h">
                                <div>
                                    <div className="card-title">Сравнение конкурентов</div>
                                    <div className="card-sub">марки в той же ценовой зоне (±25%)</div>
                                </div>
                            </div>
                            <div className="card-b">
                                {competitors.length === 0 ? (
                                    <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: 8 }}>
                                        Нет подходящих конкурентов
                                    </div>
                                ) : (
                                    competitors.map((c, i) => {
                                        const diff = derived.medianPrice
                                            ? ((c.avg_price_kzt - derived.medianPrice) / derived.medianPrice) * 100
                                            : 0;
                                        return (
                                            <div key={i} className="model-row">
                                                <div style={{ fontWeight: 500 }}>{c.brand}</div>
                                                <div className="mono tnum" style={{ fontSize: 12 }}>
                                                    {fmt.price(c.avg_price_kzt)}
                                                </div>
                                                <span
                                                    className={`badge ${diff >= 0 ? 'down' : 'up'}`}
                                                    style={{ minWidth: 56, justifyContent: 'center' }}
                                                >
                                                    {diff >= 0 ? '+' : ''}{diff.toFixed(1)}%
                                                </span>
                                            </div>
                                        );
                                    })
                                )}
                            </div>
                        </div>
                    </section>
                </main>
            </div>
        </>
    );
}
