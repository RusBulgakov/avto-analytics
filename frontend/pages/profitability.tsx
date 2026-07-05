// pages/profitability.tsx — рейтинг моделей по потенциалу маржи перепродажи
import { useMemo, useState } from 'react';
import useSWR from 'swr';

import Seo from '@/components/Seo';
import Topbar from '@/components/layout/Topbar';
import Badge from '@/components/ui/Badge';
import { analyticsApi } from '@/lib/api';
import { downloadCsv, sanitizeFilenamePart, toCsv } from '@/lib/csv';
import { fmt } from '@/lib/format';

interface ProfitRow {
    brand: string;
    model: string;
    year: number | null;
    volume: number;
    buy_price: number | null;
    sell_price: number | null;
    high_price: number | null;
    margin_pct: number | null;
    median_days_to_sell: number | null;
    risk: 'low' | 'medium' | 'high';
}

interface BrandItem { id: number; name: string; slug: string; listings_count: number }
interface ModelItem { id: number; name: string; slug: string; listings_count: number }
interface CityItem { name: string; listings_count: number }

type SortField = 'margin_pct' | 'volume' | 'median_days_to_sell' | 'year' | 'buy_price' | 'sell_price';
type SortDir = 'asc' | 'desc';

const MIN_VOLUME_OPTIONS = [10, 20, 40, 80];
const LIMIT_OPTIONS = [20, 50, 100];
const CURRENT_YEAR = new Date().getFullYear();
const YEAR_OPTIONS = Array.from({ length: CURRENT_YEAR - 1999 }, (_, i) => CURRENT_YEAR - i); // 2026..2000

function riskBadge(risk: 'low' | 'medium' | 'high') {
    if (risk === 'low') return <Badge variant="up">низкий</Badge>;
    if (risk === 'medium') return <Badge variant="accent">средний</Badge>;
    return <Badge variant="down">высокий</Badge>;
}

export default function ProfitabilityPage() {
    const [minVol, setMinVol] = useState(20);
    const [limit, setLimit] = useState(50);
    const [yearFrom, setYearFrom] = useState<number | null>(null);
    const [yearTo, setYearTo] = useState<number | null>(null);
    const [brandId, setBrandId] = useState<number | null>(null);
    const [modelId, setModelId] = useState<number | null>(null);
    const [city, setCity] = useState<string | null>(null);
    const [includeJunk, setIncludeJunk] = useState(false);
    // Client-side sort
    const [sortBy, setSortBy] = useState<SortField>('margin_pct');
    const [sortDir, setSortDir] = useState<SortDir>('desc');

    // Brands / models / cities for selectors
    const { data: brands } = useSWR<BrandItem[]>(
        'brands-profit',
        () => analyticsApi.getBrands(),
        { revalidateOnFocus: false }
    );
    const { data: models } = useSWR<ModelItem[]>(
        brandId ? ['models-profit', brandId] : null,
        () => analyticsApi.getModels(brandId!),
        { revalidateOnFocus: false }
    );
    const { data: cities } = useSWR<CityItem[]>(
        'cities-profit',
        () => analyticsApi.getCities(),
        { revalidateOnFocus: false }
    );

    const { data, isLoading } = useSWR<ProfitRow[]>(
        ['profit-ranking', minVol, limit, yearFrom, yearTo, brandId, modelId, city, includeJunk],
        () => analyticsApi.getProfitRanking({
            min_volume: minVol,
            limit,
            ...(yearFrom && { year_from: yearFrom }),
            ...(yearTo   && { year_to:   yearTo   }),
            ...(brandId  && { brand_id:  brandId  }),
            ...(modelId  && { model_id:  modelId  }),
            ...(city     && { city }),
            ...(includeJunk ? { include_junk: true } : {}),
        }),
        { keepPreviousData: true }
    );

    // Client-side sort
    const sortedData = useMemo(() => {
        if (!data) return [];
        const copy = [...data];
        copy.sort((a, b) => {
            const av = (a[sortBy] ?? -Infinity) as number;
            const bv = (b[sortBy] ?? -Infinity) as number;
            return sortDir === 'desc' ? bv - av : av - bv;
        });
        return copy;
    }, [data, sortBy, sortDir]);

    function toggleSort(field: SortField) {
        if (field === sortBy) {
            setSortDir(d => d === 'desc' ? 'asc' : 'desc');
        } else {
            setSortBy(field);
            setSortDir('desc');
        }
    }
    const sortIcon = (field: SortField) =>
        field === sortBy ? (sortDir === 'desc' ? ' ▼' : ' ▲') : '';

    // Экспорт текущей (отфильтрованной + отсортированной) таблицы в CSV.
    // Числа — сырые машиночитаемые значения (без ₸ и разделителей разрядов).
    function handleExportCsv() {
        if (!sortedData.length) return;
        const riskLabel = { low: 'низкий', medium: 'средний', high: 'высокий' } as const;
        const headers = [
            '#', 'Марка', 'Модель', 'Год',
            'Покупка (p25)', 'Продажа (медиана)', 'Маржа %',
            'Дней до продажи', 'Объём', 'Риск',
        ];
        const rows = sortedData.map((r, i) => [
            i + 1,
            r.brand,
            r.model,
            r.year,
            r.buy_price,
            r.sell_price,
            r.margin_pct != null ? Number(r.margin_pct.toFixed(1)) : null,
            r.median_days_to_sell != null ? Math.round(r.median_days_to_sell) : null,
            r.volume,
            riskLabel[r.risk],
        ]);

        // Имя файла: дата + активные фильтры (марка/модель/город/годы/выборка)
        // Локальная дата, не toISOString() — UTC может отставать на день от часового пояса пользователя
        const d = new Date();
        const date = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
        const yearPart =
            yearFrom && yearTo ? `${yearFrom}-${yearTo}`
            : yearFrom ? `от-${yearFrom}`
            : yearTo ? `до-${yearTo}`
            : null;
        const filterParts = [
            brandId ? brands?.find(b => b.id === brandId)?.name : null,
            modelId ? models?.find(m => m.id === modelId)?.name : null,
            city,
            yearPart,
            includeJunk ? 'все' : null,
        ]
            .filter((p): p is string => Boolean(p))
            .map(sanitizeFilenamePart)
            .filter(Boolean);
        const filename = ['profitability', date, ...filterParts].join('_') + '.csv';

        downloadCsv(filename, toCsv(headers, rows));
    }

    return (
        <>
            <Seo
                title="Рентабельность перепродажи авто — рейтинг моделей | Авто Аналитика KZ"
                description="Рейтинг моделей авто по потенциалу маржи перепродажи в Казахстане: цена входа, цена продажи, маржа, скорость продажи и риск."
                path="/profitability"
            />

            <div className="app">
                <Topbar />

                <main className="main">
                    <div
                        style={{
                            display: 'flex',
                            alignItems: 'flex-end',
                            justifyContent: 'space-between',
                            flexWrap: 'wrap',
                            gap: 16,
                        }}
                    >
                        <div>
                            <div className="page-title">Рейтинг рентабельности</div>
                            <div className="page-sub">
                                Оценка маржи = медиана − нижний квартиль цен по модели. Риск учитывает объём выборки.
                                {!includeJunk && (
                                    <>
                                        {' · '}
                                        <span style={{ color: 'var(--up)' }}>
                                            ★ исключены аварийные / не на ходу / не растаможенные / на запчасти + price-outliers
                                        </span>
                                    </>
                                )}
                            </div>
                            <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
                                <span
                                    className="uppercase"
                                    style={{ fontSize: 11, color: 'var(--text-muted)' }}
                                >
                                    выборка
                                </span>
                                <div className="period-group" role="group" aria-label="Junk-фильтр">
                                    <button
                                        type="button"
                                        className={`period-btn ${!includeJunk ? 'active' : ''}`}
                                        onClick={() => setIncludeJunk(false)}
                                        title="Только товарные: без битых/не на ходу/не растаможенных + outliers ниже 50% медианы"
                                    >
                                        Товарные
                                    </button>
                                    <button
                                        type="button"
                                        className={`period-btn ${includeJunk ? 'active' : ''}`}
                                        onClick={() => setIncludeJunk(true)}
                                        title="Без фильтра — raw данные включая аварийные, не на ходу, не растаможенные"
                                    >
                                        Все
                                    </button>
                                </div>
                            </div>
                        </div>

                        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                            {/* Brand */}
                            <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                                <span className="uppercase">марка</span>
                                <select
                                    value={brandId ?? ''}
                                    onChange={e => {
                                        setBrandId(e.target.value ? Number(e.target.value) : null);
                                        setModelId(null);
                                    }}
                                    style={{ fontSize: 13, padding: '4px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text)', cursor: 'pointer', minWidth: 130 }}
                                >
                                    <option value="">все</option>
                                    {brands?.filter(b => b.listings_count > 0).map(b => (
                                        <option key={b.id} value={b.id}>
                                            {fmt.brandName(b.name)} ({fmt.int(b.listings_count)})
                                        </option>
                                    ))}
                                </select>
                            </label>
                            {/* Model */}
                            <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                                <span className="uppercase">модель</span>
                                <select
                                    value={modelId ?? ''}
                                    onChange={e => setModelId(e.target.value ? Number(e.target.value) : null)}
                                    disabled={!brandId}
                                    style={{ fontSize: 13, padding: '4px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text)', cursor: 'pointer', minWidth: 130 }}
                                >
                                    <option value="">все</option>
                                    {models?.map(m => (
                                        <option key={m.id} value={m.id}>
                                            {m.name} ({fmt.int(m.listings_count)})
                                        </option>
                                    ))}
                                </select>
                            </label>
                            {/* City */}
                            <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                                <span className="uppercase">город</span>
                                <select
                                    value={city ?? ''}
                                    onChange={e => setCity(e.target.value || null)}
                                    style={{ fontSize: 13, padding: '4px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text)', cursor: 'pointer', minWidth: 130 }}
                                >
                                    <option value="">все</option>
                                    {cities?.slice(0, 25).map(c => (
                                        <option key={c.name} value={c.name}>
                                            {c.name} ({fmt.int(c.listings_count)})
                                        </option>
                                    ))}
                                </select>
                            </label>
                            {/* Год от */}
                            <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                                <span className="uppercase">год от</span>
                                <select
                                    value={yearFrom ?? ''}
                                    onChange={e => setYearFrom(e.target.value ? Number(e.target.value) : null)}
                                    style={{ fontSize: 13, padding: '4px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text)', cursor: 'pointer' }}
                                >
                                    <option value="">любой</option>
                                    {YEAR_OPTIONS.map(y => <option key={y} value={y}>{y}</option>)}
                                </select>
                            </label>
                            {/* Год до */}
                            <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                                <span className="uppercase">год до</span>
                                <select
                                    value={yearTo ?? ''}
                                    onChange={e => setYearTo(e.target.value ? Number(e.target.value) : null)}
                                    style={{ fontSize: 13, padding: '4px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text)', cursor: 'pointer' }}
                                >
                                    <option value="">любой</option>
                                    {YEAR_OPTIONS.map(y => <option key={y} value={y}>{y}</option>)}
                                </select>
                            </label>
                            <label
                                style={{
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: 4,
                                    fontSize: 11,
                                    color: 'var(--text-muted)',
                                }}
                            >
                                <span className="uppercase">мин. объявлений</span>
                                <div className="period-group">
                                    {MIN_VOLUME_OPTIONS.map(v => (
                                        <button
                                            key={v}
                                            type="button"
                                            className={`period-btn ${minVol === v ? 'active' : ''}`}
                                            onClick={() => setMinVol(v)}
                                        >
                                            {v}
                                        </button>
                                    ))}
                                </div>
                            </label>
                            <label
                                style={{
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: 4,
                                    fontSize: 11,
                                    color: 'var(--text-muted)',
                                }}
                            >
                                <span className="uppercase">показать</span>
                                <div className="period-group">
                                    {LIMIT_OPTIONS.map(v => (
                                        <button
                                            key={v}
                                            type="button"
                                            className={`period-btn ${limit === v ? 'active' : ''}`}
                                            onClick={() => setLimit(v)}
                                        >
                                            {v}
                                        </button>
                                    ))}
                                </div>
                            </label>
                            {/* Экспорт CSV */}
                            <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                                <span className="uppercase">экспорт</span>
                                <button
                                    type="button"
                                    onClick={handleExportCsv}
                                    disabled={!sortedData.length}
                                    title="Скачать текущую таблицу (с учётом фильтров и сортировки) в CSV"
                                    style={{
                                        fontSize: 13,
                                        padding: '4px 12px',
                                        borderRadius: 6,
                                        border: '1px solid var(--border)',
                                        background: 'var(--bg-card)',
                                        color: sortedData.length ? 'var(--text)' : 'var(--text-muted)',
                                        cursor: sortedData.length ? 'pointer' : 'not-allowed',
                                    }}
                                >
                                    ⬇ CSV
                                </button>
                            </label>
                        </div>
                    </div>

                    <section className="card">
                        <div className="card-b flush">
                            {isLoading && !data ? (
                                <div className="skeleton" style={{ height: 400, margin: 16 }} />
                            ) : data && data.length ? (
                                <table className="tbl">
                                    <thead>
                                        <tr>
                                            <th style={{ width: 44 }}>#</th>
                                            <th>Модель</th>
                                            <th
                                                className="right"
                                                style={{ cursor: 'pointer', userSelect: 'none' }}
                                                onClick={() => toggleSort('year')}
                                                title="Сортировка по году"
                                            >
                                                Год{sortIcon('year')}
                                            </th>
                                            <th
                                                className="right"
                                                style={{ cursor: 'pointer', userSelect: 'none' }}
                                                onClick={() => toggleSort('buy_price')}
                                            >
                                                Покупка (p25){sortIcon('buy_price')}
                                            </th>
                                            <th
                                                className="right"
                                                style={{ cursor: 'pointer', userSelect: 'none' }}
                                                onClick={() => toggleSort('sell_price')}
                                            >
                                                Продажа (медиана){sortIcon('sell_price')}
                                            </th>
                                            <th
                                                className="right"
                                                style={{ cursor: 'pointer', userSelect: 'none' }}
                                                onClick={() => toggleSort('margin_pct')}
                                            >
                                                Маржа{sortIcon('margin_pct')}
                                            </th>
                                            <th
                                                className="right"
                                                style={{ cursor: 'pointer', userSelect: 'none' }}
                                                onClick={() => toggleSort('median_days_to_sell')}
                                            >
                                                Дней{sortIcon('median_days_to_sell')}
                                            </th>
                                            <th
                                                className="right"
                                                style={{ cursor: 'pointer', userSelect: 'none' }}
                                                onClick={() => toggleSort('volume')}
                                            >
                                                Объём{sortIcon('volume')}
                                            </th>
                                            <th className="right">Риск</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {sortedData.map((r, i) => (
                                            <tr key={`${r.brand}|${r.model}|${r.year}`}>
                                                <td>
                                                    <span className="rank">{i + 1}</span>
                                                </td>
                                                <td>
                                                    <strong>{fmt.brandName(r.brand)}</strong>{' '}
                                                    <span className="dim">{r.model}</span>
                                                </td>
                                                <td className="num">
                                                    {r.year ?? '—'}
                                                </td>
                                                <td className="num">
                                                    {r.buy_price != null ? fmt.price(r.buy_price) : '—'}
                                                </td>
                                                <td className="num">
                                                    {r.sell_price != null ? fmt.price(r.sell_price) : '—'}
                                                </td>
                                                <td className="num">
                                                    {r.margin_pct != null ? (
                                                        <Badge variant={r.margin_pct >= 15 ? 'up' : r.margin_pct >= 5 ? 'accent' : 'neutral'}>
                                                            +{r.margin_pct.toFixed(1)}%
                                                        </Badge>
                                                    ) : (
                                                        '—'
                                                    )}
                                                </td>
                                                <td className="num">
                                                    {r.median_days_to_sell != null
                                                        ? `${r.median_days_to_sell.toFixed(0)}д`
                                                        : '—'}
                                                </td>
                                                <td className="num">{fmt.int(r.volume)}</td>
                                                <td className="right">{riskBadge(r.risk)}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            ) : (
                                <div style={{ padding: 24, color: 'var(--text-muted)' }}>
                                    Нет моделей с объёмом ≥ {minVol}
                                </div>
                            )}
                        </div>
                    </section>

                    <div
                        className="mono dim"
                        style={{ fontSize: 11, padding: '0 2px' }}
                    >
                        модель оценки упрощённая — без PRO сигналов (тренд цены, сезонность). При высоком разбросе цен
                        маржа может быть завышена. Объём ≥ {minVol} отсекает редкие модели.
                    </div>
                </main>
            </div>
        </>
    );
}
