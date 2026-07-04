// components/charts/PriceChart.tsx
// Интерактивный график изменения цен по времени (Recharts)
'use client';
import {
    ResponsiveContainer, AreaChart, Area, XAxis, YAxis,
    CartesianGrid, Tooltip, Legend,
} from 'recharts';
import { format } from 'date-fns';
import { ru } from 'date-fns/locale';

interface DataPoint {
    date: string;
    avg_price_kzt: number;
    median_price_kzt: number;
    listing_count: number;
}

type Granularity = 'day' | 'week' | 'month';

interface PriceChartProps {
    data: DataPoint[];
    loading?: boolean;
    granularity?: Granularity;
}

function formatPrice(val: number) {
    if (val >= 1_000_000) return `${(val / 1_000_000).toFixed(1)} млн ₸`;
    if (val >= 1_000) return `${(val / 1_000).toFixed(0)} тыс ₸`;
    return `${val} ₸`;
}

function tooltipDateFormat(d: string, g: Granularity) {
    if (g === 'month') return format(new Date(d), 'LLLL yyyy', { locale: ru });
    if (g === 'week') {
        const start = new Date(d);
        const end = new Date(start);
        end.setDate(start.getDate() + 6);
        return `${format(start, 'd MMM', { locale: ru })} – ${format(end, 'd MMM yyyy', { locale: ru })}`;
    }
    return format(new Date(d), 'd MMM yyyy', { locale: ru });
}

function tickDateFormat(d: string, g: Granularity) {
    if (g === 'month') return format(new Date(d), 'LLL', { locale: ru });
    return format(new Date(d), 'd MMM', { locale: ru });
}

export default function PriceChart({ data, loading, granularity = 'day' }: PriceChartProps) {
    const CustomTooltip = ({ active, payload, label }: any) => {
        if (!active || !payload?.length) return null;
        return (
            <div style={{
                background: 'var(--surface-2)', border: '1px solid var(--border-strong)',
                borderRadius: 6, padding: '10px 14px', fontSize: 12.5, fontFamily: 'var(--mono)',
            }}>
                <div style={{ color: 'var(--text-muted)', marginBottom: 8 }}>
                    {tooltipDateFormat(label, granularity)}
                </div>
                {payload.map((p: any) => (
                    <div key={p.name} style={{ color: p.color, marginBottom: 4 }}>
                        {p.name}: <strong>{formatPrice(p.value)}</strong>
                    </div>
                ))}
            </div>
        );
    };

    if (loading) {
        return <div className="skeleton" style={{ height: 300, borderRadius: 14 }} />;
    }
    if (!data?.length) {
        return (
            <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)' }}>
                Нет данных для выбранных фильтров
            </div>
        );
    }
    return (
        <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={data} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
                <defs>
                    <linearGradient id="avgGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" style={{ stopColor: 'var(--info)' }} stopOpacity={0.3} />
                        <stop offset="95%" style={{ stopColor: 'var(--info)' }} stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="medGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" style={{ stopColor: 'var(--up)' }} stopOpacity={0.25} />
                        <stop offset="95%" style={{ stopColor: 'var(--up)' }} stopOpacity={0} />
                    </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--grid-line)" />
                <XAxis
                    dataKey="date"
                    tickFormatter={(d) => tickDateFormat(d, granularity)}
                    tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                    axisLine={false} tickLine={false}
                />
                <YAxis
                    tickFormatter={formatPrice}
                    tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                    axisLine={false} tickLine={false} width={80}
                />
                <Tooltip content={<CustomTooltip />} />
                <Legend
                    wrapperStyle={{ paddingTop: 16, fontSize: 13, color: 'var(--text-muted)' }}
                />
                <Area
                    type="monotone" dataKey="avg_price_kzt"
                    name="Средняя цена" stroke="var(--info)" strokeWidth={2}
                    fill="url(#avgGrad)" dot={false} activeDot={{ r: 5 }}
                />
                <Area
                    type="monotone" dataKey="median_price_kzt"
                    name="Медиана" stroke="var(--up)" strokeWidth={2}
                    fill="url(#medGrad)" dot={false} activeDot={{ r: 5 }}
                />
            </AreaChart>
        </ResponsiveContainer>
    );
}
