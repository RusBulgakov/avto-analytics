// pages/listing.tsx — Listing detail (trading terminal redesign)
// Query-string routing because next.config.js has `output: 'export'`.
// URL: /listing?id=<uuid>
import { useMemo } from 'react';
import Head from 'next/head';
import Link from 'next/link';
import { useRouter } from 'next/router';
import useSWR from 'swr';
import {
    ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid,
} from 'recharts';

import Topbar from '@/components/layout/Topbar';
import Badge from '@/components/ui/Badge';

import { analyticsApi } from '@/lib/api';
import { fmt } from '@/lib/format';
import { useUsdKzt } from '@/hooks/useUsdKzt';

// ── Types (locally declared — lib/api.ts exports are untyped) ─────────
interface PricePoint {
    date: string;
    price_kzt: number;
}

interface ListingDetail {
    id: string;
    external_id: string;
    title: string;
    year: number | null;
    mileage_km: number | null;
    city: string | null;
    listing_url: string;
    first_seen_at: string;
    last_seen_at: string;
    is_active: boolean;
    brand_id: number | null;
    brand: string | null;
    model_id: number | null;
    model: string | null;
    source: string;
    price_history: PricePoint[];
}

interface Valuation {
    listing_id: string;
    current: number | null;
    fair_low: number | null;
    median: number | null;
    fair_high: number | null;
    sample_size: number;
    verdict: 'cheap' | 'fair' | 'expensive' | null;
    margin_if_resell_pct: number | null;
}

interface SimilarItem {
    id: string;
    brand: string | null;
    model: string | null;
    year: number | null;
    mileage_km: number | null;
    city: string | null;
    source: string;
    listing_url: string;
    price_kzt: number;
}

// ── Helpers ─────────────────────────────────────────────────────────────
function slugify(s: string | null | undefined): string {
    if (!s) return '';
    return encodeURIComponent(s.toLowerCase().trim());
}

function formatBigPrice(n: number | null | undefined): { head: string; unit: string } {
    if (n == null) return { head: '—', unit: '' };
    if (n >= 1_000_000) return { head: (n / 1_000_000).toFixed(1), unit: 'млн ₸' };
    if (n >= 1_000) return { head: (n / 1_000).toFixed(0), unit: 'тыс ₸' };
    return { head: String(n), unit: '₸' };
}

function formatDate(iso: string | null | undefined): string {
    if (!iso) return '—';
    try {
        const d = new Date(iso);
        return d.toLocaleDateString('ru-RU', { day: '2-digit', month: 'short', year: 'numeric' });
    } catch {
        return '—';
    }
}

function formatDateShort(iso: string): string {
    try {
        const d = new Date(iso);
        return d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' });
    } catch {
        return iso;
    }
}

// Count how many times the price decreased across history
function countPriceDrops(history: PricePoint[]): number {
    if (!history || history.length < 2) return 0;
    let drops = 0;
    for (let i = 1; i < history.length; i++) {
        if (history[i].price_kzt < history[i - 1].price_kzt) drops++;
    }
    return drops;
}

// Position % on the fair-price bar (0 = min, 100 = max). Clamps and returns 50 if unknown.
function pricePositionPct(
    current: number | null,
    fair_low: number | null,
    fair_high: number | null,
): number {
    if (current == null || fair_low == null || fair_high == null) return 50;
    // Bar spans ~20% below fair_low → ~20% above fair_high so extremes fall within range.
    const span = fair_high - fair_low;
    if (span <= 0) return 50;
    const min = fair_low - span * 0.5;
    const max = fair_high + span * 0.5;
    const raw = ((current - min) / (max - min)) * 100;
    return Math.max(2, Math.min(98, raw));
}

// ── Page ────────────────────────────────────────────────────────────────
export default function ListingPage() {
    const router = useRouter();
    const id = typeof router.query.id === 'string' ? router.query.id : undefined;

    const { data: listing, error: listingErr, isLoading: listingLoading } = useSWR<ListingDetail | null>(
        id ? ['listing', id] : null,
        () => analyticsApi.getListing(id as string),
        { keepPreviousData: false, shouldRetryOnError: false }
    );

    const { data: valuation, isLoading: valLoading } = useSWR<Valuation>(
        id ? ['valuation', id] : null,
        () => analyticsApi.getValuation(id as string),
        { keepPreviousData: false, shouldRetryOnError: false }
    );

    const { data: similar, isLoading: simLoading } = useSWR<SimilarItem[]>(
        id ? ['similar', id] : null,
        () => analyticsApi.getSimilar(id as string, 10),
        { keepPreviousData: false, shouldRetryOnError: false }
    );

    const { data: fx } = useUsdKzt();

    const history = listing?.price_history ?? [];
    const priceDrops = useMemo(() => countPriceDrops(history), [history]);
    const chartData = useMemo(
        () => history.map(p => ({ date: p.date, value: p.price_kzt })),
        [history]
    );

    // Render the "price changes" list: for each row show date, price, delta vs previous
    const priceHistoryRows = useMemo(() => {
        if (!history.length) return [] as { date: string; price: number; delta: number }[];
        const sorted = [...history].sort(
            (a, b) => new Date(b.date).getTime() - new Date(a.date).getTime()
        );
        return sorted.map((p, i) => {
            const prev = sorted[i + 1];
            const delta = prev ? p.price_kzt - prev.price_kzt : 0;
            return { date: p.date, price: p.price_kzt, delta };
        });
    }, [history]);

    // ── Loading & error states ─────────────────────────────────────
    if (!id) {
        return (
            <>
                <Head><title>Объявление — Авто Аналитика KZ</title></Head>
                <div className="app">
                    <Topbar />
                    <main className="main">
                        <div className="card">
                            <div className="card-b" style={{ color: 'var(--text-muted)' }}>
                                Загрузка…
                            </div>
                        </div>
                    </main>
                </div>
            </>
        );
    }

    const notFound =
        (!listingLoading && !listing) ||
        Boolean(listingErr && (listingErr as any)?.response?.status === 404);

    if (notFound) {
        return (
            <>
                <Head><title>Объявление не найдено — Авто Аналитика KZ</title></Head>
                <div className="app">
                    <Topbar />
                    <main className="main">
                        <div className="card">
                            <div className="card-b">
                                <div className="page-title">Объявление не найдено</div>
                                <div className="page-sub" style={{ marginTop: 8 }}>
                                    Возможно, оно было снято с публикации или ID указан неверно.
                                </div>
                                <div style={{ marginTop: 16 }}>
                                    <Link href="/" className="btn btn-ghost">← На дашборд</Link>
                                </div>
                            </div>
                        </div>
                    </main>
                </div>
            </>
        );
    }

    // ── Derived display values ─────────────────────────────────────
    const title = listing
        ? [listing.brand, listing.model].filter(Boolean).join(' ') || listing.title || 'Объявление'
        : '';
    const year = listing?.year ?? null;
    const currentPrice = valuation?.current ?? null;
    const big = formatBigPrice(currentPrice);
    const usd = currentPrice && fx ? Math.round(currentPrice / fx.rate) : null;

    const brandSlug = slugify(listing?.brand);
    const modelSlug = slugify(listing?.model);

    const pricePosPct = pricePositionPct(
        currentPrice,
        valuation?.fair_low ?? null,
        valuation?.fair_high ?? null
    );

    // Sentence for the callout
    let verdictClass: 'up' | 'down' | 'accent' = 'accent';
    let verdictLabel = 'Честная цена';
    if (valuation?.verdict === 'cheap') { verdictClass = 'up'; verdictLabel = 'Дёшево'; }
    else if (valuation?.verdict === 'expensive') { verdictClass = 'down'; verdictLabel = 'Дорого'; }

    let deltaPctVsMedian: number | null = null;
    if (currentPrice != null && valuation?.median != null && valuation.median > 0) {
        deltaPctVsMedian = ((currentPrice - valuation.median) / valuation.median) * 100;
    }

    const calloutText = (() => {
        if (!valuation || valuation.verdict == null) {
            return 'Недостаточно данных для оценки (≤10 похожих объявлений).';
        }
        const brand = listing?.brand ?? '';
        const model = listing?.model ?? '';
        const yr = year ?? '';
        const mileageThous = listing?.mileage_km != null ? Math.round(listing.mileage_km / 1000) : null;
        const direction = deltaPctVsMedian != null && deltaPctVsMedian < 0 ? 'ниже' : 'выше';
        const absPct = deltaPctVsMedian != null ? Math.abs(deltaPctVsMedian).toFixed(1) : '—';
        const margin = valuation.margin_if_resell_pct;
        const baseSentence =
            `Цена на ${absPct}% ${direction} медианы для ${brand} ${model} ${yr}` +
            (mileageThous != null ? ` с пробегом ~${mileageThous} тыс.км` : '') + '.';
        const marginSentence = margin != null
            ? ` При быстрой перепродаже за 14 дней — маржа ${margin >= 0 ? '+' : ''}${margin.toFixed(1)}%.`
            : '';
        return baseSentence + marginSentence;
    })();

    // Callout colors
    const calloutBg =
        verdictClass === 'up' ? 'var(--up-soft)'
            : verdictClass === 'down' ? 'var(--down-soft)'
                : 'var(--accent-soft)';
    const calloutBorder =
        verdictClass === 'up' ? 'var(--up)'
            : verdictClass === 'down' ? 'var(--down)'
                : 'var(--accent)';
    const calloutFg =
        verdictClass === 'up' ? 'var(--up)'
            : verdictClass === 'down' ? 'var(--down)'
                : 'var(--accent)';

    // Breadcrumb link targets (skip when brand/model missing)
    const brandHref = brandSlug ? `/model?brand=${brandSlug}` : null;
    const modelHref =
        brandSlug && modelSlug
            ? `/model?brand=${brandSlug}&model=${modelSlug}`
            : null;

    const activeBadge = listing?.is_active
        ? <Badge variant="up">● активно</Badge>
        : <Badge variant="neutral">архив</Badge>;

    return (
        <>
            <Head>
                <title>
                    {listing ? `${title}${year ? ' ' + year : ''} — Авто Аналитика KZ` : 'Объявление'}
                </title>
                <meta name="viewport" content="width=device-width, initial-scale=1" />
            </Head>

            <div className="app">
                <Topbar />

                <main className="main">
                    {/* ── Breadcrumb ─────────────────────────────────────── */}
                    <div className="breadcrumb">
                        <Link href="/">Дашборд</Link>
                        <span className="sep">/</span>
                        {brandHref ? (
                            <Link href={brandHref}>{listing?.brand ?? '—'}</Link>
                        ) : (
                            <span>{listing?.brand ?? '—'}</span>
                        )}
                        <span className="sep">/</span>
                        {modelHref ? (
                            <Link href={modelHref}>{listing?.model ?? '—'}</Link>
                        ) : (
                            <span>{listing?.model ?? '—'}</span>
                        )}
                        <span className="sep">/</span>
                        <span style={{ color: 'var(--text)' }}>Объявление</span>
                    </div>

                    {/* ── Hero ───────────────────────────────────────────── */}
                    <div className="card">
                        <div className="detail-hero">
                            <div>
                                <div
                                    style={{
                                        display: 'flex',
                                        alignItems: 'center',
                                        gap: 10,
                                        flexWrap: 'wrap',
                                        marginBottom: 8,
                                    }}
                                >
                                    <span className="page-title" style={{ fontSize: 24 }}>
                                        {listingLoading ? (
                                            <span className="skeleton" style={{ display: 'inline-block', width: 220, height: 24 }} />
                                        ) : (
                                            <>
                                                {title} {year && <span className="mono dim">{year}</span>}
                                            </>
                                        )}
                                    </span>
                                    {listing && (
                                        <>
                                            <Badge variant="neutral">{listing.source}</Badge>
                                            {activeBadge}
                                            {priceDrops > 0 && (
                                                <Badge variant="accent">
                                                    цена снижена {priceDrops} {priceDrops === 1 ? 'раз' : 'раза'}
                                                </Badge>
                                            )}
                                        </>
                                    )}
                                </div>
                                {listing && (
                                    <div style={{ color: 'var(--text-muted)', fontSize: 13 }}>
                                        {listing.city ?? '—'}
                                        {listing.mileage_km != null && (
                                            <>
                                                <span style={{ margin: '0 8px' }}>·</span>
                                                {Math.round(listing.mileage_km / 1000)} тыс км
                                            </>
                                        )}
                                        <span style={{ margin: '0 8px' }}>·</span>
                                        ID <span className="mono">{listing.external_id}</span>
                                    </div>
                                )}
                            </div>
                            <div style={{ textAlign: 'right' }}>
                                <div className="uppercase">текущая цена</div>
                                <div className="big-price tnum">
                                    {big.head}
                                    {big.unit && <span className="unit">{big.unit}</span>}
                                </div>
                                <div
                                    style={{
                                        marginTop: 6,
                                        display: 'flex',
                                        gap: 8,
                                        justifyContent: 'flex-end',
                                        alignItems: 'center',
                                        flexWrap: 'wrap',
                                    }}
                                >
                                    {usd != null && (
                                        <span className="mono dim" style={{ fontSize: 11 }}>
                                            ≈ {usd.toLocaleString('ru-RU')} USD
                                        </span>
                                    )}
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* ── Photo + specs + valuation ──────────────────────── */}
                    <div className="listing-grid">
                        {/* ── Left column ──────────────────────────────── */}
                        <div>
                            <div className="photo-ph">НЕТ ФОТО</div>
                            <div className="photo-strip">
                                <div className="photo-ph">01</div>
                                <div className="photo-ph">02</div>
                                <div className="photo-ph">03</div>
                                <div className="photo-ph">04</div>
                            </div>

                            <div className="card" style={{ marginTop: 14 }}>
                                <div className="card-h">
                                    <div className="card-title">Характеристики</div>
                                </div>
                                <div className="card-b">
                                    {listingLoading && !listing ? (
                                        <div className="skeleton" style={{ height: 360 }} />
                                    ) : listing ? (
                                        <table className="spec-tbl">
                                            <tbody>
                                                <tr>
                                                    <td>Источник</td>
                                                    <td>{listing.source}</td>
                                                </tr>
                                                <tr>
                                                    <td>Марка</td>
                                                    <td>{listing.brand ?? '—'}</td>
                                                </tr>
                                                <tr>
                                                    <td>Модель</td>
                                                    <td>{listing.model ?? '—'}</td>
                                                </tr>
                                                <tr>
                                                    <td>Год</td>
                                                    <td>{listing.year ?? '—'}</td>
                                                </tr>
                                                <tr>
                                                    <td>Пробег</td>
                                                    <td>
                                                        {listing.mileage_km != null
                                                            ? `${fmt.int(listing.mileage_km)} км`
                                                            : '—'}
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td>Город</td>
                                                    <td>{listing.city ?? '—'}</td>
                                                </tr>
                                                <tr>
                                                    <td>Внешний ID</td>
                                                    <td>{listing.external_id || '—'}</td>
                                                </tr>
                                                <tr>
                                                    <td>Первое появление</td>
                                                    <td>{formatDate(listing.first_seen_at)}</td>
                                                </tr>
                                                <tr>
                                                    <td>Последнее обновление</td>
                                                    <td>{formatDate(listing.last_seen_at)}</td>
                                                </tr>
                                                <tr>
                                                    <td>Статус</td>
                                                    <td>
                                                        <span
                                                            className={listing.is_active ? 'up' : 'down'}
                                                        >
                                                            {listing.is_active ? 'активно' : 'снято'}
                                                        </span>
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td>Заголовок</td>
                                                    <td style={{ maxWidth: 280, overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                                        {listing.title || '—'}
                                                    </td>
                                                </tr>
                                                <tr>
                                                    <td>Ссылка</td>
                                                    <td>
                                                        <a
                                                            href={listing.listing_url}
                                                            target="_blank"
                                                            rel="noopener noreferrer"
                                                            style={{ color: 'var(--info)' }}
                                                        >
                                                            открыть →
                                                        </a>
                                                    </td>
                                                </tr>
                                            </tbody>
                                        </table>
                                    ) : null}
                                </div>
                            </div>
                        </div>

                        {/* ── Right column ─────────────────────────────── */}
                        <div>
                            {/* Valuation */}
                            <div className="card">
                                <div className="card-h">
                                    <div>
                                        <div className="card-title">Справедливая цена</div>
                                        <div className="card-sub">
                                            {valuation
                                                ? `Модель оценки на основе ${fmt.int(valuation.sample_size)} объявлений`
                                                : valLoading
                                                    ? 'загрузка…'
                                                    : '—'}
                                        </div>
                                    </div>
                                </div>
                                <div className="card-b">
                                    {valLoading && !valuation ? (
                                        <div className="skeleton" style={{ height: 220 }} />
                                    ) : valuation && valuation.verdict != null ? (
                                        <>
                                            {/* Gauge */}
                                            <div className="listing-gauge">
                                                <div className="listing-gauge-bar" />
                                                <div
                                                    className="listing-gauge-pointer"
                                                    style={{ left: `${pricePosPct}%` }}
                                                />
                                                <div
                                                    className="listing-gauge-label"
                                                    style={{ left: `${pricePosPct}%` }}
                                                >
                                                    ЭТА ЦЕНА · {fmt.price(currentPrice)}
                                                </div>
                                                <div className="listing-gauge-scale">
                                                    <span>дёшево</span>
                                                    <span>рынок</span>
                                                    <span>дорого</span>
                                                </div>
                                            </div>

                                            {/* Three columns */}
                                            <div className="listing-val-cols">
                                                <div className={verdictClass === 'up' ? 'listing-val-col active' : 'listing-val-col'}>
                                                    <div className="uppercase">Дёшево</div>
                                                    <div
                                                        className="mono tnum"
                                                        style={{ fontSize: 15, marginTop: 4, color: 'var(--up)' }}
                                                    >
                                                        &lt; {fmt.price(valuation.fair_low)}
                                                    </div>
                                                </div>
                                                <div className={verdictClass === 'accent' ? 'listing-val-col active' : 'listing-val-col'}>
                                                    <div className="uppercase">Честная</div>
                                                    <div className="mono tnum" style={{ fontSize: 15, marginTop: 4 }}>
                                                        {fmt.price(valuation.fair_low)} – {fmt.price(valuation.fair_high)}
                                                    </div>
                                                </div>
                                                <div className={verdictClass === 'down' ? 'listing-val-col active' : 'listing-val-col'}>
                                                    <div className="uppercase">Дорого</div>
                                                    <div
                                                        className="mono tnum"
                                                        style={{ fontSize: 15, marginTop: 4, color: 'var(--down)' }}
                                                    >
                                                        &gt; {fmt.price(valuation.fair_high)}
                                                    </div>
                                                </div>
                                            </div>

                                            {/* Callout */}
                                            <div
                                                className="listing-callout"
                                                style={{
                                                    background: calloutBg,
                                                    borderLeft: `2px solid ${calloutBorder}`,
                                                }}
                                            >
                                                <div
                                                    className="mono"
                                                    style={{
                                                        fontSize: 11,
                                                        color: calloutFg,
                                                        letterSpacing: '0.05em',
                                                        textTransform: 'uppercase',
                                                        fontWeight: 600,
                                                        marginBottom: 4,
                                                    }}
                                                >
                                                    Вывод модели · {verdictLabel}
                                                </div>
                                                <div style={{ fontSize: 13, lineHeight: 1.5 }}>
                                                    {calloutText}
                                                </div>
                                            </div>
                                        </>
                                    ) : (
                                        <div
                                            className="listing-callout"
                                            style={{
                                                background: 'var(--surface-2)',
                                                borderLeft: '2px solid var(--border-strong)',
                                            }}
                                        >
                                            <div style={{ fontSize: 13, lineHeight: 1.5, color: 'var(--text-muted)' }}>
                                                Недостаточно данных для оценки (≤10 похожих объявлений).
                                            </div>
                                        </div>
                                    )}
                                </div>
                            </div>

                            {/* Price history */}
                            <div className="card" style={{ marginTop: 14 }}>
                                <div className="card-h">
                                    <div>
                                        <div className="card-title">История цены</div>
                                        <div className="card-sub">
                                            {history.length > 1
                                                ? `${history.length} точек · ${history.length > 1 ? formatDateShort(history[0].date) + ' – ' + formatDateShort(history[history.length - 1].date) : ''}`
                                                : 'без изменений'}
                                        </div>
                                    </div>
                                    {history.length > 1 && (() => {
                                        const first = history[0].price_kzt;
                                        const last = history[history.length - 1].price_kzt;
                                        const diffPct = first ? ((last - first) / first) * 100 : 0;
                                        const variant = diffPct < 0 ? 'down' : diffPct > 0 ? 'up' : 'neutral';
                                        return (
                                            <Badge variant={variant}>
                                                {diffPct === 0 ? '—' : diffPct < 0 ? '▼' : '▲'}{' '}
                                                {Math.abs(diffPct).toFixed(1)}%
                                            </Badge>
                                        );
                                    })()}
                                </div>
                                <div className="card-b">
                                    {chartData.length >= 2 ? (
                                        <ResponsiveContainer width="100%" height={140}>
                                            <LineChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
                                                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                                                <XAxis
                                                    dataKey="date"
                                                    tickFormatter={(d) => formatDateShort(d)}
                                                    tick={{ fill: '#7b8899', fontSize: 10 }}
                                                    axisLine={false}
                                                    tickLine={false}
                                                />
                                                <YAxis
                                                    tickFormatter={(v) => (v / 1_000_000).toFixed(1) + 'М'}
                                                    tick={{ fill: '#7b8899', fontSize: 10 }}
                                                    axisLine={false}
                                                    tickLine={false}
                                                    width={40}
                                                />
                                                <Tooltip
                                                    contentStyle={{
                                                        background: 'var(--surface-2)',
                                                        border: '1px solid var(--border-strong)',
                                                        borderRadius: 6,
                                                        fontSize: 12,
                                                        fontFamily: 'var(--mono)',
                                                    }}
                                                    labelFormatter={(d) => formatDateShort(String(d))}
                                                    formatter={(v: number) => [fmt.priceFull(v), 'Цена']}
                                                />
                                                <Line
                                                    type="monotone"
                                                    dataKey="value"
                                                    stroke="var(--info)"
                                                    strokeWidth={2}
                                                    dot={false}
                                                    activeDot={{ r: 4 }}
                                                />
                                            </LineChart>
                                        </ResponsiveContainer>
                                    ) : (
                                        <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: '8px 0' }}>
                                            История цены пока пуста.
                                        </div>
                                    )}
                                    <div style={{ marginTop: 8 }}>
                                        {priceHistoryRows.map((h, i) => (
                                            <div key={i} className="price-history-mini">
                                                <div className="ph-date">{formatDateShort(h.date)}</div>
                                                <div className="ph-price tnum">{fmt.priceFull(h.price)}</div>
                                                <div
                                                    className={`ph-change ${h.delta < 0 ? 'down' : h.delta > 0 ? 'up' : 'dim'}`}
                                                >
                                                    {h.delta === 0 ? '—' : (h.delta < 0 ? '▼ ' : '▲ ') + fmt.priceFull(Math.abs(h.delta))}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                </div>
                            </div>

                            {/* Actions */}
                            <div
                                style={{
                                    display: 'grid',
                                    gridTemplateColumns: '1fr 1fr',
                                    gap: 10,
                                    marginTop: 14,
                                }}
                            >
                                <a
                                    href={listing?.listing_url || '#'}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    className="topbar-btn"
                                    style={{ justifyContent: 'center', height: 42, fontSize: 13 }}
                                >
                                    Открыть на {listing?.source ?? 'источнике'} →
                                </a>
                                <button
                                    type="button"
                                    className="topbar-btn listing-fav"
                                    aria-label="В избранное"
                                    style={{ justifyContent: 'center', height: 42, fontSize: 13 }}
                                >
                                    ★ В избранное
                                </button>
                            </div>
                        </div>
                    </div>

                    {/* ── Similar listings ───────────────────────────────── */}
                    <div className="card">
                        <div className="card-h">
                            <div>
                                <div className="card-title">Похожие объявления</div>
                                <div className="card-sub">
                                    {listing?.brand} {listing?.model}
                                    {year ? ` · ${year - 1}–${year + 1}` : ''}
                                    {listing?.city ? ` · ${listing.city}` : ''}
                                </div>
                            </div>
                            {similar && (
                                <Badge variant="neutral">{similar.length} совпадений</Badge>
                            )}
                        </div>
                        <div className="card-b flush">
                            {simLoading && !similar ? (
                                <div className="skeleton" style={{ height: 180, margin: 16 }} />
                            ) : similar && similar.length > 0 ? (
                                <table className="tbl">
                                    <thead>
                                        <tr>
                                            <th>Авто</th>
                                            <th className="right">Год</th>
                                            <th className="right">Пробег</th>
                                            <th className="right">Цена</th>
                                            <th className="right">Vs. это</th>
                                            <th>Город</th>
                                            <th>Источник</th>
                                            <th></th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {similar.map(s => {
                                            const diff =
                                                currentPrice && currentPrice > 0
                                                    ? ((s.price_kzt - currentPrice) / currentPrice) * 100
                                                    : 0;
                                            const diffVariant = diff <= 0 ? 'up' : 'down';
                                            return (
                                                <tr key={s.id}>
                                                    <td>
                                                        <strong>
                                                            {[s.brand, s.model].filter(Boolean).join(' ') || '—'}
                                                        </strong>
                                                    </td>
                                                    <td className="num tnum">{s.year ?? '—'}</td>
                                                    <td className="num tnum">
                                                        {s.mileage_km != null
                                                            ? `${Math.round(s.mileage_km / 1000)} тыс`
                                                            : '—'}
                                                    </td>
                                                    <td className="num tnum">
                                                        <strong>{fmt.priceFull(s.price_kzt)}</strong>
                                                    </td>
                                                    <td className="num">
                                                        {currentPrice ? (
                                                            <Badge variant={diffVariant}>
                                                                {diff <= 0 ? '▼' : '▲'} {Math.abs(diff).toFixed(1)}%
                                                            </Badge>
                                                        ) : (
                                                            <span className="dim">—</span>
                                                        )}
                                                    </td>
                                                    <td>{s.city ?? '—'}</td>
                                                    <td>
                                                        <span className="dim">{s.source}</span>
                                                    </td>
                                                    <td>
                                                        <Link
                                                            href={`/listing?id=${encodeURIComponent(s.id)}`}
                                                            className="topbar-btn"
                                                            style={{ fontSize: 11, height: 24, padding: '0 8px' }}
                                                        >
                                                            →
                                                        </Link>
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            ) : (
                                <div style={{ color: 'var(--text-muted)', padding: 16 }}>
                                    Похожих объявлений не найдено.
                                </div>
                            )}
                        </div>
                    </div>
                </main>
            </div>
        </>
    );
}
