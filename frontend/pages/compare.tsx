// pages/compare.tsx — сравнение 2–3 моделей бок-о-бок (t-0012).
// Вход через query-string: /compare?items=toyota:camry,kia:k5
// (совместимо с output: 'export' — без [param]-роутов, все данные client-side).
// Slug-конвенция та же, что у /model?brand=..&model=..: матчим по slug ИЛИ name
// (case-insensitive) из /analytics/brands и /analytics/models.
import { useMemo, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import useSWR from 'swr';

import Seo from '@/components/Seo';
import Topbar from '@/components/layout/Topbar';
import Badge from '@/components/ui/Badge';
import PriceChart from '@/components/charts/PriceChart';
import { analyticsApi } from '@/lib/api';
import { fmt } from '@/lib/format';

type Period = 30 | 90 | 180 | 365;
const PERIODS: Period[] = [30, 90, 180, 365];
const MAX_ITEMS = 3;

interface CompareItem {
    brand: string;
    model: string;
}

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
interface LiquidityBucket {
    bucket: string;
    count: number;
    pct: number;
}

function slugEq(a: string | null | undefined, b: string | null | undefined): boolean {
    if (!a || !b) return false;
    return a.toLowerCase() === b.toLowerCase();
}

/** slug для URL — тот же fallback, что использует model.tsx в breadcrumb'ах */
function toSlug(row: { slug: string | null; name: string }): string {
    return (row.slug ?? row.name).toLowerCase();
}

function itemKey(it: CompareItem): string {
    return `${it.brand.toLowerCase()}:${it.model.toLowerCase()}`;
}

/** Парсит ?items=toyota:camry,kia:k5 → максимум 3 уникальных пары */
function parseItems(raw: unknown): CompareItem[] {
    if (typeof raw !== 'string' || !raw.trim()) return [];
    const seen = new Set<string>();
    const out: CompareItem[] = [];
    for (const chunk of raw.split(',')) {
        const idx = chunk.indexOf(':');
        if (idx <= 0) continue;
        const brand = chunk.slice(0, idx).trim();
        const model = chunk.slice(idx + 1).trim();
        if (!brand || !model) continue;
        const key = `${brand.toLowerCase()}:${model.toLowerCase()}`;
        if (seen.has(key)) continue;
        seen.add(key);
        out.push({ brand, model });
        if (out.length >= MAX_ITEMS) break; // >3 → берём первые 3
    }
    return out;
}

function serializeItems(items: CompareItem[]): string {
    return items.map(it => `${it.brand}:${it.model}`).join(',');
}

// ── Метрики одной модели (все — из уже существующих endpoint'ов) ────────────
interface ColumnStats {
    medianPrice: number | null;   // price-history: среднее по median_price_kzt
    delta: number | null;         // price-history: % изменение avg за период
    count: number | null;         // price-history last listing_count → models.listings_count
    medianDaysBucket: string | null; // liquidity: бакет, где накопленный % ≥ 50
    fastSharePct: number | null;  // liquidity: доля закрытых за ≤14 дней
    soldTotal: number | null;     // liquidity: всего закрытых за 180 дней
}

function computeStats(
    points: PricePoint[] | undefined,
    liquidity: LiquidityBucket[] | undefined,
    model: ModelRow | null
): ColumnStats {
    let medianPrice: number | null = null;
    let delta: number | null = null;
    let count: number | null = null;

    if (points && points.length) {
        const meds = points.map(p => p.median_price_kzt).filter(n => n > 0);
        if (meds.length) medianPrice = Math.round(meds.reduce((a, b) => a + b, 0) / meds.length);
        const first = points[0].avg_price_kzt;
        const last = points[points.length - 1].avg_price_kzt;
        if (points.length >= 2 && first > 0) delta = ((last - first) / first) * 100;
        count = points[points.length - 1].listing_count;
    }
    if (count == null && model) count = model.listings_count;

    let medianDaysBucket: string | null = null;
    let fastSharePct: number | null = null;
    let soldTotal: number | null = null;
    if (liquidity && liquidity.length) {
        soldTotal = liquidity.reduce((s, b) => s + b.count, 0);
        if (soldTotal > 0) {
            let cum = 0;
            for (const b of liquidity) {
                cum += b.pct;
                if (cum >= 50) { medianDaysBucket = b.bucket; break; }
            }
            fastSharePct = liquidity
                .filter(b => ['0-3', '4-7', '8-14'].includes(b.bucket))
                .reduce((s, b) => s + b.pct, 0);
        }
    }

    return { medianPrice, delta, count, medianDaysBucket, fastSharePct, soldTotal };
}

// ── Одна колонка сравнения ──────────────────────────────────────────────────
function StatRow({ label, children }: { label: string; children: React.ReactNode }) {
    return (
        <div style={{
            display: 'flex', justifyContent: 'space-between', alignItems: 'baseline',
            gap: 8, padding: '7px 0', borderBottom: '1px solid var(--border)',
        }}>
            <span className="uppercase" style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>{label}</span>
            <span className="mono tnum" style={{ fontSize: 13 }}>{children}</span>
        </div>
    );
}

function CompareColumn({
    item, brands, brandsLoading, period, onRemove,
}: {
    item: CompareItem;
    brands: BrandRow[] | undefined;
    brandsLoading: boolean;
    period: Period;
    onRemove: () => void;
}) {
    const brand = useMemo(() => {
        if (!brands) return null;
        return brands.find(b => slugEq(b.slug, item.brand) || slugEq(b.name, item.brand)) || null;
    }, [brands, item.brand]);

    const { data: models, isLoading: modelsLoading } = useSWR<ModelRow[]>(
        brand ? ['models', brand.id] : null,
        () => analyticsApi.getModels(brand!.id),
        { revalidateOnFocus: false }
    );

    const model = useMemo(() => {
        if (!models) return null;
        return models.find(m => slugEq(m.slug, item.model) || slugEq(m.name, item.model)) || null;
    }, [models, item.model]);

    const historyParams = brand && model
        ? { brand_id: brand.id, model_id: model.id, period_days: period }
        : null;
    const { data: historyData, isLoading: historyLoading } = useSWR<{
        granularity: 'day' | 'week' | 'month';
        points: PricePoint[];
    }>(
        historyParams ? ['cmp-price-history', historyParams] : null,
        () => analyticsApi.getPriceHistory(historyParams!),
        { keepPreviousData: true }
    );

    const { data: liquidity } = useSWR<LiquidityBucket[]>(
        brand && model ? ['cmp-liquidity', brand.id, model.id] : null,
        () => analyticsApi.getLiquidity({ brand_id: brand!.id, model_id: model!.id }),
        { revalidateOnFocus: false }
    );

    const stats = useMemo(
        () => computeStats(historyData?.points, liquidity, model),
        [historyData, liquidity, model]
    );

    const resolving = brandsLoading || (brand != null && modelsLoading);
    const notFound = !resolving && brands != null && (!brand || (models != null && !model));

    const removeBtn = (
        <button
            type="button"
            onClick={onRemove}
            aria-label={`Убрать ${item.brand} ${item.model} из сравнения`}
            className="btn btn-ghost"
            style={{ padding: '2px 8px', fontSize: 14, lineHeight: 1 }}
        >
            ×
        </button>
    );

    if (resolving) {
        return (
            <div className="card" style={{ padding: 16 }}>
                <div className="skeleton" style={{ height: 260, borderRadius: 10 }} />
            </div>
        );
    }

    if (notFound) {
        return (
            <div className="card" style={{ padding: 16 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                    <div style={{ fontWeight: 600 }}>{item.brand} / {item.model}</div>
                    {removeBtn}
                </div>
                <div style={{ color: 'var(--text-muted)', fontSize: 12.5, marginTop: 10 }}>
                    Не найдено в базе. Проверьте slug'и в URL — формат
                    {' '}<code>марка:модель</code> (как в адресе страницы модели).
                </div>
            </div>
        );
    }

    if (!brand || !model) return null; // ещё резолвится / нет данных

    const title = `${brand.name} ${model.name}`;
    return (
        <div className="card" style={{ display: 'flex', flexDirection: 'column' }}>
            <div className="card-h">
                <div>
                    <div className="card-title">{title}</div>
                    <div className="card-sub">
                        <Link
                            href={{ pathname: '/model', query: { brand: toSlug(brand), model: toSlug(model) } }}
                            style={{ color: 'var(--text-muted)' }}
                        >
                            страница модели →
                        </Link>
                    </div>
                </div>
                {removeBtn}
            </div>
            <div className="card-b" style={{ flex: 1 }}>
                <div style={{ marginBottom: 10 }}>
                    <div className="uppercase">медианная цена</div>
                    <div className="big-price tnum" style={{ fontSize: 26 }}>
                        {stats.medianPrice != null ? (stats.medianPrice / 1_000_000).toFixed(1) : '—'}
                        <span className="unit">млн ₸</span>
                    </div>
                    <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
                        {stats.delta != null && (
                            <Badge variant={stats.delta >= 0 ? 'up' : 'down'}>
                                {stats.delta >= 0 ? '▲' : '▼'} {Math.abs(stats.delta).toFixed(1)}% · {period}д
                            </Badge>
                        )}
                        {stats.count != null && <Badge variant="neutral">n = {fmt.int(stats.count)}</Badge>}
                    </div>
                </div>

                <StatRow label="медиана">
                    {stats.medianPrice != null ? `${fmt.price(stats.medianPrice)} ₸` : '—'}
                </StatRow>
                <StatRow label={`тренд · ${period}д`}>
                    {stats.delta != null
                        ? <span style={{ color: stats.delta >= 0 ? 'var(--up)' : 'var(--down)' }}>{fmt.pct(stats.delta)}</span>
                        : '—'}
                </StatRow>
                <StatRow label="дней до продажи (медиана)">
                    {stats.medianDaysBucket ?? '—'}
                </StatRow>
                <StatRow label="ликвидность · продано ≤14д">
                    {stats.fastSharePct != null ? `${stats.fastSharePct.toFixed(0)}%` : '—'}
                </StatRow>
                <StatRow label="продаж за 180д">
                    {stats.soldTotal != null ? fmt.int(stats.soldTotal) : '—'}
                </StatRow>
                <StatRow label="активных объявлений">
                    {stats.count != null ? fmt.int(stats.count) : '—'}
                </StatRow>

                <div style={{ marginTop: 12 }}>
                    <PriceChart
                        data={historyData?.points ?? []}
                        loading={historyLoading && !historyData}
                        granularity={historyData?.granularity ?? 'day'}
                    />
                </div>
            </div>
        </div>
    );
}

// ── Пикер «добавить модель» (переиспользует /brands и /models hooks) ────────
function AddModelPicker({
    brands, onAdd,
}: {
    brands: BrandRow[] | undefined;
    onAdd: (item: CompareItem) => void;
}) {
    const [brandId, setBrandId] = useState<string>('');
    const [modelId, setModelId] = useState<string>('');

    const brand = useMemo(
        () => (brands ?? []).find(b => String(b.id) === brandId) || null,
        [brands, brandId]
    );
    const { data: models, isLoading: modelsLoading } = useSWR<ModelRow[]>(
        brand ? ['models', brand.id] : null,
        () => analyticsApi.getModels(brand!.id),
        { revalidateOnFocus: false }
    );
    const model = useMemo(
        () => (models ?? []).find(m => String(m.id) === modelId) || null,
        [models, modelId]
    );

    const selStyle: React.CSSProperties = { width: '100%', height: 32 };

    return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <select
                className="filter-input"
                style={selStyle}
                value={brandId}
                onChange={e => { setBrandId(e.target.value); setModelId(''); }}
                aria-label="Марка"
            >
                <option value="">Марка…</option>
                {(brands ?? []).map(b => (
                    <option key={b.id} value={b.id}>{b.name}</option>
                ))}
            </select>
            <select
                className="filter-input"
                style={selStyle}
                value={modelId}
                onChange={e => setModelId(e.target.value)}
                disabled={!brand || modelsLoading}
                aria-label="Модель"
            >
                <option value="">{modelsLoading ? 'загрузка…' : 'Модель…'}</option>
                {(models ?? []).map(m => (
                    <option key={m.id} value={m.id}>{m.name} · {fmt.int(m.listings_count)}</option>
                ))}
            </select>
            <button
                type="button"
                className="btn btn-primary"
                disabled={!brand || !model}
                onClick={() => {
                    if (!brand || !model) return;
                    onAdd({ brand: toSlug(brand), model: toSlug(model) });
                    setModelId('');
                }}
            >
                Добавить к сравнению
            </button>
        </div>
    );
}

// ── Страница ────────────────────────────────────────────────────────────────
export default function ComparePage() {
    const router = useRouter();
    const [period, setPeriod] = useState<Period>(90);

    const items = useMemo(() => parseItems(router.query.items), [router.query.items]);

    const { data: brands, isLoading: brandsLoading } = useSWR<BrandRow[]>(
        'brands',
        () => analyticsApi.getBrands(),
        { revalidateOnFocus: false }
    );

    // URL — единственный источник правды: shareable по определению
    const setItems = (next: CompareItem[]) => {
        router.replace(
            { pathname: '/compare', query: next.length ? { items: serializeItems(next) } : {} },
            undefined,
            { shallow: true }
        );
    };

    const addItem = (it: CompareItem) => {
        if (items.length >= MAX_ITEMS) return;
        if (items.some(x => itemKey(x) === itemKey(it))) return;
        setItems([...items, it]);
    };

    const removeAt = (idx: number) => setItems(items.filter((_, i) => i !== idx));

    return (
        <>
            <Seo
                title="Сравнение моделей авто — цены, тренд, ликвидность | Авто Аналитика KZ"
                description="Сравните 2–3 модели автомобилей бок-о-бок: медианная цена, динамика за период, скорость продажи и объём предложения на вторичном рынке Казахстана."
                path="/compare"
            />

            <div className="app">
                <Topbar />

                <main className="main">
                    <div className="breadcrumb">
                        <Link href="/">Дашборд</Link>
                        <span className="sep">/</span>
                        <span style={{ color: 'var(--text)' }}>Сравнение</span>
                    </div>

                    <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
                        <div>
                            <div className="page-title">Сравнение моделей</div>
                            <div className="page-sub">
                                до 3 моделей бок-о-бок · ссылка на страницу — shareable
                            </div>
                        </div>
                        <div className="model-period-seg" role="tablist" aria-label="Период">
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

                    {!router.isReady ? (
                        <div className="skeleton" style={{ height: 300, borderRadius: 14 }} />
                    ) : items.length === 0 ? (
                        /* Пустое состояние: подсказка формата + пикер */
                        <div className="card" style={{ maxWidth: 460, padding: 20 }}>
                            <div className="card-title" style={{ marginBottom: 6 }}>Выберите модели</div>
                            <div style={{ color: 'var(--text-muted)', fontSize: 12.5, marginBottom: 14 }}>
                                Добавьте 2–3 модели для сравнения. Или откройте ссылку вида{' '}
                                <code>/compare?items=toyota:camry,kia:k5</code>.
                            </div>
                            <AddModelPicker brands={brands} onAdd={addItem} />
                        </div>
                    ) : (
                        <>
                            <section
                                style={{
                                    display: 'grid',
                                    gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))',
                                    gap: 12,
                                    alignItems: 'stretch',
                                }}
                            >
                                {items.map((it, i) => (
                                    <CompareColumn
                                        key={itemKey(it)}
                                        item={it}
                                        brands={brands}
                                        brandsLoading={brandsLoading}
                                        period={period}
                                        onRemove={() => removeAt(i)}
                                    />
                                ))}
                                {items.length < MAX_ITEMS && (
                                    <div className="card" style={{ padding: 16, alignSelf: 'start' }}>
                                        <div className="card-title" style={{ marginBottom: 4 }}>
                                            {items.length === 1 ? 'Добавьте вторую модель' : 'Добавить модель'}
                                        </div>
                                        <div style={{ color: 'var(--text-muted)', fontSize: 12, marginBottom: 12 }}>
                                            {items.length === 1
                                                ? 'сравнение работает лучше от двух'
                                                : `ещё ${MAX_ITEMS - items.length} слот${MAX_ITEMS - items.length === 1 ? '' : 'а'}`}
                                        </div>
                                        <AddModelPicker brands={brands} onAdd={addItem} />
                                    </div>
                                )}
                            </section>
                        </>
                    )}
                </main>
            </div>
        </>
    );
}
