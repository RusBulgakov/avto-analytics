// pages/forecast.tsx — реальный прогноз цен (OLS regression на price_history)
import { useMemo, useState } from 'react';
import Head from 'next/head';
import useSWR from 'swr';
import {
    ResponsiveContainer, ComposedChart, Area, Line, XAxis, YAxis,
    CartesianGrid, Tooltip, Legend,
} from 'recharts';
import { format } from 'date-fns';
import { ru } from 'date-fns/locale';

import Topbar from '@/components/layout/Topbar';
import Badge from '@/components/ui/Badge';
import { analyticsApi } from '@/lib/api';
import { fmt } from '@/lib/format';

interface BrandItem { id: number; name: string; slug: string; listings_count: number }
interface ModelItem { id: number; name: string; slug: string; listings_count: number }

interface ForecastResp {
    historical: {
        date: string;
        median_kzt: number;
        median_usd: number;
        fx_rate: number;
        count: number;
    }[];
    forecast: {
        date: string;
        median_kzt: number;
        median_usd: number;
        low: number;
        high: number;
    }[];
    trend_pct_per_month_kzt: number | null;
    trend_pct_per_month_usd: number | null;
    fx_impact_pct: number | null;
    r2_kzt: number | null;
    r2_usd: number | null;
    residual_std_pct_kzt: number | null;
    sample_size: number;
    horizon_weeks?: number;
    current_fx_rate: number | null;
    error?: string;
}

const CURRENT_YEAR = new Date().getFullYear();
const HORIZON_OPTIONS = [
    { id: 14,  label: '2 нед' },
    { id: 30,  label: '1 мес' },
    { id: 60,  label: '2 мес' },
    { id: 90,  label: '3 мес' },
];

function fmtPriceLabel(v: number) {
    if (!v) return '—';
    if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)} млн ₸`;
    if (v >= 1_000) return `${(v / 1_000).toFixed(0)} тыс ₸`;
    return `${v} ₸`;
}

function ForecastTooltip({ active, payload, label }: any) {
    if (!active || !payload?.length) return null;
    const isForecast = payload.find((p: any) => p.dataKey === 'forecast') != null;
    return (
        <div style={{
            background: 'var(--surface-2)',
            border: '1px solid var(--border-strong)',
            borderRadius: 6, padding: '10px 14px', fontSize: 12.5,
            fontFamily: 'var(--mono)',
        }}>
            <div style={{ color: 'var(--text-muted)', marginBottom: 8 }}>
                {format(new Date(label), 'd MMM yyyy', { locale: ru })}
                {isForecast && <span style={{ color: 'var(--accent)', marginLeft: 6 }}>(прогноз)</span>}
            </div>
            {payload.map((p: any) => {
                if (p.dataKey === 'ci_low' || p.dataKey === 'ci_high') return null;
                return (
                    <div key={p.dataKey} style={{ color: p.color, marginBottom: 4 }}>
                        {p.name}: <strong>{fmtPriceLabel(p.value)}</strong>
                    </div>
                );
            })}
        </div>
    );
}

export default function ForecastPage() {
    const [brandId, setBrandId] = useState<number | null>(null);
    const [modelId, setModelId] = useState<number | null>(null);
    const [yearFrom, setYearFrom] = useState<number | null>(null);
    const [yearTo, setYearTo] = useState<number | null>(null);
    const [horizonDays, setHorizonDays] = useState(30);

    const { data: brands } = useSWR<BrandItem[]>(
        'brands-forecast',
        () => analyticsApi.getBrands(),
        { revalidateOnFocus: false }
    );

    const { data: models } = useSWR<ModelItem[]>(
        brandId ? ['models-forecast', brandId] : null,
        () => analyticsApi.getModels(brandId!),
        { revalidateOnFocus: false }
    );

    const { data: forecast, isLoading } = useSWR<ForecastResp>(
        brandId ? ['forecast', brandId, modelId, yearFrom, yearTo, horizonDays] : null,
        () => analyticsApi.getForecast({
            brand_id: brandId!,
            ...(modelId ? { model_id: modelId } : {}),
            ...(yearFrom ? { year_from: yearFrom } : {}),
            ...(yearTo ? { year_to: yearTo } : {}),
            horizon_days: horizonDays,
            history_days: 90,
        }),
        { keepPreviousData: true }
    );

    const chartData = useMemo(() => {
        if (!forecast) return [];
        const hist = forecast.historical.map(p => ({
            date: p.date,
            actual: p.median_kzt,
            count: p.count,
        }));
        const fc = forecast.forecast.map(p => ({
            date: p.date,
            forecast: p.median_kzt,
            ci_low: p.low,
            ci_high: p.high,
        }));
        return [...hist, ...fc];
    }, [forecast]);

    const showChart = !!forecast && !forecast.error && forecast.sample_size >= 4;
    const trendKztUp = (forecast?.trend_pct_per_month_kzt ?? 0) > 0;
    const trendUsdUp = (forecast?.trend_pct_per_month_usd ?? 0) > 0;
    const fxNegative = (forecast?.fx_impact_pct ?? 0) < 0;

    return (
        <>
            <Head>
                <title>Прогноз — Авто Аналитика KZ</title>
            </Head>

            <div className="app">
                <Topbar />

                <main className="main">
                    <div style={{ maxWidth: 1100, margin: '0 auto', width: '100%' }}>
                        <div style={{ marginBottom: 6 }}>
                            <Badge variant="info">MVP · OLS regression</Badge>
                        </div>
                        <div className="page-title">Прогноз медианной цены</div>
                        <div className="page-sub" style={{ marginTop: 6 }}>
                            Linear regression на недельных бакетах price_history. Junk-объявления (битые / не растаможенные) исключены.
                        </div>

                        <section className="card" style={{ marginTop: 20, padding: 14 }}>
                            <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'flex-end' }}>
                                <label style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 180 }}>
                                    <span className="uppercase" style={{ fontSize: 11, color: 'var(--text-muted)' }}>Марка</span>
                                    <select
                                        className="filter-input"
                                        value={brandId ?? ''}
                                        onChange={e => {
                                            setBrandId(e.target.value ? +e.target.value : null);
                                            setModelId(null);
                                        }}
                                        style={{ height: 32 }}
                                    >
                                        <option value="">— выберите —</option>
                                        {brands?.map(b => (
                                            <option key={b.id} value={b.id}>
                                                {b.name} ({fmt.int(b.listings_count)})
                                            </option>
                                        ))}
                                    </select>
                                </label>

                                <label style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 180 }}>
                                    <span className="uppercase" style={{ fontSize: 11, color: 'var(--text-muted)' }}>Модель</span>
                                    <select
                                        className="filter-input"
                                        value={modelId ?? ''}
                                        onChange={e => setModelId(e.target.value ? +e.target.value : null)}
                                        disabled={!brandId}
                                        style={{ height: 32 }}
                                    >
                                        <option value="">все модели марки</option>
                                        {models?.map(m => (
                                            <option key={m.id} value={m.id}>
                                                {m.name} ({fmt.int(m.listings_count)})
                                            </option>
                                        ))}
                                    </select>
                                </label>

                                <label style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 100 }}>
                                    <span className="uppercase" style={{ fontSize: 11, color: 'var(--text-muted)' }}>Год от</span>
                                    <select
                                        className="filter-input"
                                        value={yearFrom ?? ''}
                                        onChange={e => setYearFrom(e.target.value ? +e.target.value : null)}
                                        style={{ height: 32 }}
                                        title="Например, поколение Camry XV50: от=2011 до=2018"
                                    >
                                        <option value="">любой</option>
                                        {Array.from({ length: 27 }, (_, i) => CURRENT_YEAR - i).map(y => (
                                            <option key={y} value={y}>{y}</option>
                                        ))}
                                    </select>
                                </label>

                                <label style={{ display: 'flex', flexDirection: 'column', gap: 4, minWidth: 100 }}>
                                    <span className="uppercase" style={{ fontSize: 11, color: 'var(--text-muted)' }}>Год до</span>
                                    <select
                                        className="filter-input"
                                        value={yearTo ?? ''}
                                        onChange={e => setYearTo(e.target.value ? +e.target.value : null)}
                                        style={{ height: 32 }}
                                    >
                                        <option value="">любой</option>
                                        {Array.from({ length: 27 }, (_, i) => CURRENT_YEAR - i).map(y => (
                                            <option key={y} value={y}>{y}</option>
                                        ))}
                                    </select>
                                </label>

                                <label style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                                    <span className="uppercase" style={{ fontSize: 11, color: 'var(--text-muted)' }}>Горизонт</span>
                                    <div className="period-group">
                                        {HORIZON_OPTIONS.map(h => (
                                            <button
                                                key={h.id}
                                                type="button"
                                                className={`period-btn ${horizonDays === h.id ? 'active' : ''}`}
                                                onClick={() => setHorizonDays(h.id)}
                                            >
                                                {h.label}
                                            </button>
                                        ))}
                                    </div>
                                </label>
                            </div>
                        </section>

                        {forecast && !forecast.error && (
                            <section
                                style={{
                                    display: 'grid',
                                    gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))',
                                    gap: 1, marginTop: 14,
                                    background: 'var(--border)',
                                    border: '1px solid var(--border)',
                                    borderRadius: 'var(--radius-lg)',
                                    overflow: 'hidden',
                                }}
                            >
                                <div className="kpi" style={{ minHeight: 100 }}>
                                    <div className="uppercase" style={{ fontSize: 11, color: 'var(--text-muted)' }}>Тренд KZT</div>
                                    <div
                                        style={{
                                            fontSize: 26, fontWeight: 600, fontFamily: 'var(--display)',
                                            color: forecast.trend_pct_per_month_kzt == null
                                                ? 'var(--text-muted)'
                                                : trendKztUp ? 'var(--up)' : 'var(--down)',
                                            marginTop: 4,
                                        }}
                                    >
                                        {forecast.trend_pct_per_month_kzt != null
                                            ? `${trendKztUp ? '▲' : '▼'} ${Math.abs(forecast.trend_pct_per_month_kzt).toFixed(1)}%`
                                            : '—'}
                                    </div>
                                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>в месяц · в тенге</div>
                                </div>
                                <div className="kpi" style={{ minHeight: 100 }}>
                                    <div className="uppercase" style={{ fontSize: 11, color: 'var(--text-muted)' }}>Тренд USD</div>
                                    <div
                                        style={{
                                            fontSize: 26, fontWeight: 600, fontFamily: 'var(--display)',
                                            color: forecast.trend_pct_per_month_usd == null
                                                ? 'var(--text-muted)'
                                                : trendUsdUp ? 'var(--up)' : 'var(--down)',
                                            marginTop: 4,
                                        }}
                                    >
                                        {forecast.trend_pct_per_month_usd != null
                                            ? `${trendUsdUp ? '▲' : '▼'} ${Math.abs(forecast.trend_pct_per_month_usd).toFixed(1)}%`
                                            : '—'}
                                    </div>
                                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>истинный тренд (без FX)</div>
                                </div>
                                <div className="kpi" style={{ minHeight: 100 }}>
                                    <div className="uppercase" style={{ fontSize: 11, color: 'var(--text-muted)' }}>FX вклад</div>
                                    <div
                                        style={{
                                            fontSize: 26, fontWeight: 600, fontFamily: 'var(--display)',
                                            color: forecast.fx_impact_pct == null
                                                ? 'var(--text-muted)'
                                                : fxNegative ? 'var(--info)' : 'var(--accent)',
                                            marginTop: 4,
                                        }}
                                        title="Сколько из тренда KZT-цен объясняется курсом тенге, а сколько — реальным движением рынка"
                                    >
                                        {forecast.fx_impact_pct != null
                                            ? `${forecast.fx_impact_pct > 0 ? '+' : ''}${forecast.fx_impact_pct.toFixed(1)}%`
                                            : '—'}
                                    </div>
                                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                                        {forecast.fx_impact_pct == null ? '—' :
                                         forecast.fx_impact_pct > 0.5 ? 'тенге слабеет → KZT цены растут быстрее' :
                                         forecast.fx_impact_pct < -0.5 ? 'тенге крепнет → KZT цены растут медленнее' :
                                         'FX почти не влияет'}
                                    </div>
                                </div>
                                <div className="kpi" style={{ minHeight: 100 }}>
                                    <div className="uppercase" style={{ fontSize: 11, color: 'var(--text-muted)' }}>R² (USD)</div>
                                    <div style={{ fontSize: 26, fontWeight: 600, fontFamily: 'var(--display)', marginTop: 4 }}>
                                        {forecast.r2_usd != null ? forecast.r2_usd.toFixed(2) : '—'}
                                    </div>
                                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                                        {forecast.r2_usd == null ? '—' :
                                         forecast.r2_usd > 0.5 ? 'надёжная' :
                                         forecast.r2_usd > 0.2 ? 'умеренная' : 'шумная'}
                                    </div>
                                </div>
                                <div className="kpi" style={{ minHeight: 100 }}>
                                    <div className="uppercase" style={{ fontSize: 11, color: 'var(--text-muted)' }}>Выборка</div>
                                    <div style={{ fontSize: 26, fontWeight: 600, fontFamily: 'var(--display)', marginTop: 4 }}>
                                        {forecast.sample_size}
                                    </div>
                                    <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                                        недель · USD = {forecast.current_fx_rate ?? '—'}
                                    </div>
                                </div>
                            </section>
                        )}

                        <section className="card" style={{ marginTop: 14 }}>
                            <div className="card-h">
                                <div>
                                    <div className="card-title">График прогноза</div>
                                    <div className="card-sub">
                                        факт · прогноз {forecast?.horizon_weeks ?? Math.ceil(horizonDays / 7)} нед. · 95% доверительный интервал
                                    </div>
                                </div>
                            </div>
                            <div className="card-b">
                                {!brandId ? (
                                    <div style={{ height: 360, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
                                        Выберите марку чтобы построить прогноз
                                    </div>
                                ) : isLoading && !forecast ? (
                                    <div className="skeleton" style={{ height: 360, borderRadius: 8 }} />
                                ) : forecast?.error ? (
                                    <div style={{ height: 360, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--down)', fontSize: 13 }}>
                                        {forecast.error}
                                    </div>
                                ) : showChart ? (
                                    <ResponsiveContainer width="100%" height={380}>
                                        <ComposedChart data={chartData} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
                                            <defs>
                                                <linearGradient id="ciGrad" x1="0" y1="0" x2="0" y2="1">
                                                    <stop offset="5%" stopColor="#f4b84a" stopOpacity={0.30} />
                                                    <stop offset="95%" stopColor="#f4b84a" stopOpacity={0.05} />
                                                </linearGradient>
                                            </defs>
                                            <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.04)" />
                                            <XAxis
                                                dataKey="date"
                                                tickFormatter={(d) => format(new Date(d), 'd MMM', { locale: ru })}
                                                tick={{ fill: '#7b8899', fontSize: 11 }}
                                                axisLine={false} tickLine={false}
                                            />
                                            <YAxis
                                                tickFormatter={fmtPriceLabel}
                                                tick={{ fill: '#7b8899', fontSize: 11 }}
                                                axisLine={false} tickLine={false} width={90}
                                            />
                                            <Tooltip content={<ForecastTooltip />} />
                                            <Legend wrapperStyle={{ paddingTop: 12, fontSize: 12 }} />
                                            <Area
                                                type="monotone" dataKey="ci_high"
                                                stroke="none" fill="url(#ciGrad)"
                                                name="" legendType="none"
                                            />
                                            <Area
                                                type="monotone" dataKey="ci_low"
                                                stroke="none" fill="var(--bg)"
                                                name="" legendType="none"
                                            />
                                            <Line
                                                type="monotone" dataKey="actual"
                                                name="Факт" stroke="#6ea8ff" strokeWidth={2}
                                                dot={{ r: 4 }} activeDot={{ r: 6 }}
                                            />
                                            <Line
                                                type="monotone" dataKey="forecast"
                                                name="Прогноз" stroke="#f4b84a" strokeWidth={2}
                                                strokeDasharray="6 4"
                                                dot={{ r: 4 }} activeDot={{ r: 6 }}
                                            />
                                        </ComposedChart>
                                    </ResponsiveContainer>
                                ) : (
                                    <div style={{ height: 360, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
                                        Недостаточно данных для прогноза (минимум 4 недели)
                                    </div>
                                )}
                            </div>
                        </section>

                        <div
                            className="card"
                            style={{ marginTop: 14, padding: 14, fontSize: 12, color: 'var(--text-2)' }}
                        >
                            <div className="uppercase" style={{ color: 'var(--text-muted)', marginBottom: 6, fontSize: 11 }}>
                                методология MVP
                            </div>
                            <div>
                                Простая <strong>OLS regression</strong> на недельных медианах цены за последние 90 дней.
                                Не учитывает сезонность, курс KZT/USD, выпуск новых поколений — это запланировано в следующих итерациях.
                                R² ниже 0.3 значит данные шумные для линейной модели — попробуйте сузить группу (конкретный год / модель).
                                Junk-листинги (битые / не растаможенные / не на ходу) автоматически исключены.
                            </div>
                        </div>
                    </div>
                </main>
            </div>
        </>
    );
}
