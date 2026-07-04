// pages/forecast.tsx — реальный прогноз цен (OLS regression на price_history)
import { useMemo, useState } from 'react';
import useSWR from 'swr';

import Seo from '@/components/Seo';
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
        median_mileage_km: number | null;
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
    // V3 fields
    mileage_coverage_weeks: number;
    mileage_coef_usd_per_10k_km: number | null;
    multivariate_r2_usd: number | null;
    holiday_effect_pct: number | null;
    model_features: string[];
    error?: string;
}

interface BacktestResp {
    params: { period_days: number; discount_threshold: number; hold_days: number };
    total_signals: number;
    hits: number;
    misses: number;
    win_rate: number | null;
    avg_signal_discount: number | null;
    // V2 (primary): arb-margin = group p25 at close / first_price - 1
    avg_arb_margin: number | null;
    median_arb_margin: number | null;
    // V1 (legacy): listing-margin = last_price / first_price - 1
    avg_listing_margin: number | null;
    median_listing_margin: number | null;
    median_days_to_sell: number | null;
    top_winners: {
        brand: string; model: string; year: number;
        // V3 fields (new)
        entry_price: number;             // = buy_price legacy
        market_p25_at_entry: number | null;  // p25 группы когда listing появился
        market_p25_at_close: number | null;  // p25 группы когда listing закрылся
        entry_discount: number | null;       // (p25_entry - entry) / entry → насколько ниже p25 был entry
        market_movement: number | null;      // (p25_close - p25_entry) / p25_entry → движение рынка
        arb_margin: number | null;           // total = (1 + entry_discount) × (1 + market_movement) - 1
        // legacy
        buy_price: number;
        sell_price: number;
        listing_margin: number | null;
        days: number;
        url: string;
    }[];
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

    const { data: backtest, isLoading: backtestLoading } = useSWR<BacktestResp>(
        brandId ? ['backtest', brandId, modelId, yearFrom, yearTo] : null,
        () => analyticsApi.getBacktest({
            ...(brandId ? { brand_id: brandId } : {}),
            ...(modelId ? { model_id: modelId } : {}),
            ...(yearFrom ? { year_from: yearFrom } : {}),
            ...(yearTo ? { year_to: yearTo } : {}),
            period_days: 60,
            discount_threshold: 0.15,
            hold_days: 45,
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
            <Seo
                title="Прогноз цен на авто в Казахстане | Авто Аналитика KZ"
                description="Прогноз медианной цены автомобилей в Казахстане: OLS-регрессия по истории цен, тренд в тенге и долларах, доверительный интервал."
                path="/forecast"
            />

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
                                {forecast.mileage_coef_usd_per_10k_km != null && (
                                    <div className="kpi" style={{ minHeight: 100 }}>
                                        <div className="uppercase" style={{ fontSize: 11, color: 'var(--text-muted)' }}>Mileage</div>
                                        <div style={{ fontSize: 22, fontWeight: 600, fontFamily: 'var(--display)', marginTop: 4, color: 'var(--down)' }}>
                                            {forecast.mileage_coef_usd_per_10k_km < 0 ? '−' : '+'}${Math.abs(forecast.mileage_coef_usd_per_10k_km).toFixed(0)}
                                        </div>
                                        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                                            на каждые 10к км · R² {forecast.multivariate_r2_usd?.toFixed(2) ?? '—'}
                                        </div>
                                    </div>
                                )}
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

                        {/* === BACKTEST SECTION === */}
                        {brandId && backtest && !backtest.error && backtest.total_signals > 0 && (
                            <section className="card" style={{ marginTop: 14 }}>
                                <div className="card-h">
                                    <div>
                                        <div className="card-title">Ретро-тест стратегии «купить дешевое»</div>
                                        <div className="card-sub">
                                            период 60 дней · discount −15% от p25 группы · holding window 45 дней
                                        </div>
                                    </div>
                                    <Badge variant="accent">MVP</Badge>
                                </div>
                                <div className="card-b">
                                    {/* KPI row */}
                                    <div
                                        style={{
                                            display: 'grid',
                                            gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
                                            gap: 1,
                                            background: 'var(--border)',
                                            border: '1px solid var(--border)',
                                            borderRadius: 'var(--radius)',
                                            overflow: 'hidden',
                                            marginBottom: 14,
                                        }}
                                    >
                                        <div className="kpi" style={{ minHeight: 88 }}>
                                            <div className="uppercase" style={{ fontSize: 11, color: 'var(--text-muted)' }}>Сигналы</div>
                                            <div style={{ fontSize: 22, fontWeight: 600, fontFamily: 'var(--display)', marginTop: 4 }}>
                                                {fmt.int(backtest.total_signals)}
                                            </div>
                                            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>buy-сигналов за 60д</div>
                                        </div>
                                        <div className="kpi" style={{ minHeight: 88 }}>
                                            <div className="uppercase" style={{ fontSize: 11, color: 'var(--text-muted)' }}>Win rate</div>
                                            <div
                                                style={{
                                                    fontSize: 22, fontWeight: 600, fontFamily: 'var(--display)', marginTop: 4,
                                                    color: backtest.win_rate != null && backtest.win_rate >= 0.6 ? 'var(--up)' : 'var(--text)',
                                                }}
                                            >
                                                {backtest.win_rate != null ? `${(backtest.win_rate * 100).toFixed(0)}%` : '—'}
                                            </div>
                                            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{backtest.hits}/{backtest.total_signals} закрылись</div>
                                        </div>
                                        <div
                                            className="kpi"
                                            style={{ minHeight: 88 }}
                                            title="V2: средняя маржа арбитража = (p25 группы на момент закрытия / first_price - 1). Сравнивает с текущим рынком."
                                        >
                                            <div className="uppercase" style={{ fontSize: 11, color: 'var(--text-muted)' }}>Arb margin</div>
                                            <div
                                                style={{
                                                    fontSize: 22, fontWeight: 600, fontFamily: 'var(--display)', marginTop: 4,
                                                    color: backtest.median_arb_margin != null && backtest.median_arb_margin > 0
                                                        ? 'var(--up)' : backtest.median_arb_margin != null && backtest.median_arb_margin < 0
                                                        ? 'var(--down)' : 'var(--text)',
                                                }}
                                            >
                                                {backtest.median_arb_margin != null
                                                    ? `${backtest.median_arb_margin > 0 ? '+' : ''}${(backtest.median_arb_margin * 100).toFixed(1)}%`
                                                    : '—'}
                                            </div>
                                            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                                                median · vs market p25 на close
                                            </div>
                                        </div>
                                        <div className="kpi" style={{ minHeight: 88 }}>
                                            <div className="uppercase" style={{ fontSize: 11, color: 'var(--text-muted)' }}>Median days</div>
                                            <div style={{ fontSize: 22, fontWeight: 600, fontFamily: 'var(--display)', marginTop: 4 }}>
                                                {backtest.median_days_to_sell != null ? backtest.median_days_to_sell.toFixed(0) : '—'}
                                            </div>
                                            <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>дней до закрытия</div>
                                        </div>
                                    </div>

                                    {/* Top winners */}
                                    {backtest.top_winners.length > 0 ? (
                                        <>
                                            <div className="uppercase" style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 8 }}>
                                                топ-{backtest.top_winners.length} успешных сделок
                                            </div>
                                            <table className="tbl">
                                                <thead>
                                                    <tr>
                                                        <th>Авто</th>
                                                        <th className="right" title="Первая цена в объявлении (не реальная сделка)">Цена входа</th>
                                                        <th className="right" title="p25 группы когда listing появился">p25 входа</th>
                                                        <th className="right" title="p25 группы когда listing закрылся">p25 выхода</th>
                                                        <th
                                                            className="right"
                                                            title="(p25_close − p25_entry) / p25_entry — насколько рынок сам двинулся за время"
                                                        >
                                                            Δ рынка
                                                        </th>
                                                        <th
                                                            className="right"
                                                            title="(p25_close / entry − 1) — сколько мог бы заработать если купил по entry и продал по market"
                                                        >
                                                            Total arb
                                                        </th>
                                                        <th className="right">Дней</th>
                                                    </tr>
                                                </thead>
                                                <tbody>
                                                    {backtest.top_winners.map((w, i) => (
                                                        <tr key={i}>
                                                            <td>
                                                                <a href={w.url} target="_blank" rel="noopener noreferrer" style={{ color: 'var(--info)' }}>
                                                                    <strong>{w.brand}</strong>{' '}
                                                                    <span className="dim">{w.model}</span>{' '}
                                                                    <span className="mono dim">{w.year}</span>
                                                                </a>
                                                            </td>
                                                            <td className="num">{fmt.price(w.entry_price ?? w.buy_price)}</td>
                                                            <td className="num">
                                                                {w.market_p25_at_entry != null ? fmt.price(w.market_p25_at_entry) : '—'}
                                                            </td>
                                                            <td className="num">
                                                                {w.market_p25_at_close != null ? fmt.price(w.market_p25_at_close) : '—'}
                                                            </td>
                                                            <td className="num">
                                                                {w.market_movement != null ? (
                                                                    <span style={{ color: w.market_movement > 0.05 ? 'var(--up)' : w.market_movement < -0.05 ? 'var(--down)' : 'var(--text-muted)' }}>
                                                                        {w.market_movement > 0 ? '+' : ''}{(w.market_movement * 100).toFixed(1)}%
                                                                    </span>
                                                                ) : '—'}
                                                            </td>
                                                            <td className="num">
                                                                {w.arb_margin != null ? (
                                                                    <Badge variant={w.arb_margin > 0.20 ? 'up' : w.arb_margin > 0.05 ? 'accent' : 'neutral'}>
                                                                        {w.arb_margin > 0 ? '+' : ''}{(w.arb_margin * 100).toFixed(0)}%
                                                                    </Badge>
                                                                ) : '—'}
                                                            </td>
                                                            <td className="num">{w.days.toFixed(0)}д</td>
                                                        </tr>
                                                    ))}
                                                </tbody>
                                            </table>
                                        </>
                                    ) : (
                                        <div style={{ padding: 12, color: 'var(--text-muted)', fontSize: 12 }}>
                                            Нет успешно-закрывшихся сделок в выборке.
                                        </div>
                                    )}
                                </div>
                            </section>
                        )}

                        {brandId && !backtestLoading && backtest?.error && (
                            <div
                                className="card"
                                style={{ marginTop: 14, padding: 14, color: 'var(--text-muted)', fontSize: 13 }}
                            >
                                Backtest: {backtest.error}
                            </div>
                        )}

                        <div
                            className="card"
                            style={{ marginTop: 14, padding: 14, fontSize: 12, color: 'var(--text-2)' }}
                        >
                            <div className="uppercase" style={{ color: 'var(--text-muted)', marginBottom: 6, fontSize: 11 }}>
                                методология
                            </div>
                            <div>
                                <strong>Forecast V2</strong> — OLS regression на двух осях: KZT и USD. Курс берётся из <code>fx_history</code> (NBK API daily).
                                FX-вклад показывает сколько из тренда KZT-цен объясняется движением тенге, а сколько — реальным движением рынка.
                                <br /><br />
                                <strong>Backtest — это симуляция, не история сделок.</strong> У нас нет данных о реальных транзакциях. "Цена входа" = первая запись price_history (то что продавец указал при создании объявления). Метрики измеряют "что бы получилось если бы трейдер мог купить листинг по выставленной цене и потом перепродать по текущей рыночной p25 группы". В реальности продавец может не согласиться на listed price, и продажа на market p25 требует своих усилий и времени.
                                <ul style={{ marginTop: 6, marginBottom: 0, paddingLeft: 18 }}>
                                    <li><strong>Δ рынка</strong> = (p25 на выходе − p25 на входе) / p25 на входе. Это <em>реальный</em> drift — насколько группа двигалась без участия конкретного listing.</li>
                                    <li><strong>Total arb</strong> = (p25_close − entry) / entry. Это сумма entry-дисконта + market drift — сколько максимум мог бы заработать.</li>
                                </ul>
                                <br />
                                Junk-листинги (битые / не растаможенные / на заказ) исключены. R² ниже 0.3 = данные шумные → попробуйте сузить группу (конкретный год / модель).
                            </div>
                        </div>
                    </div>
                </main>
            </div>
        </>
    );
}
