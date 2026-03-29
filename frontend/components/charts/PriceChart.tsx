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

interface PriceChartProps {
    data: DataPoint[];
    loading?: boolean;
}

function formatPrice(val: number) {
    if (val >= 1_000_000) return `${(val / 1_000_000).toFixed(1)} млн ₸`;
    if (val >= 1_000) return `${(val / 1_000).toFixed(0)} тыс ₸`;
    return `${val} ₸`;
}

const CustomTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null;
    return (
        <div style={{
            background: '#1d2535', border: '1px solid rgba(255,255,255,0.1)',
            borderRadius: 12, padding: '12px 16px', fontSize: 13,
        }}>
            <div style={{ color: '#7b8899', marginBottom: 8 }}>
                {format(new Date(label), 'd MMM yyyy', { locale: ru })}
            </div>
            {payload.map((p: any) => (
                <div key={p.name} style={{ color: p.color, marginBottom: 4 }}>
                    {p.name}: <strong>{formatPrice(p.value)}</strong>
                </div>
            ))}
        </div>
    );
};

export default function PriceChart({ data, loading }: PriceChartProps) {
    if (loading) {
        return <div className="skeleton" style={{ height: 300, borderRadius: 14 }} />;
    }
    if (!data?.length) {
        return (
            <div style={{ height: 300, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#7b8899' }}>
                Нет данных для выбранных фильтров
            </div>
        );
    }
    return (
        <ResponsiveContainer width="100%" height={300}>
            <AreaChart data={data} margin={{ top: 10, right: 10, left: 10, bottom: 0 }}>
                <defs>
                    <linearGradient id="avgGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#3d7fff" stopOpacity={0.3} />
                        <stop offset="95%" stopColor="#3d7fff" stopOpacity={0} />
                    </linearGradient>
                    <linearGradient id="medGrad" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#22d3a3" stopOpacity={0.25} />
                        <stop offset="95%" stopColor="#22d3a3" stopOpacity={0} />
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
                    tickFormatter={formatPrice}
                    tick={{ fill: '#7b8899', fontSize: 11 }}
                    axisLine={false} tickLine={false} width={80}
                />
                <Tooltip content={<CustomTooltip />} />
                <Legend
                    wrapperStyle={{ paddingTop: 16, fontSize: 13, color: '#7b8899' }}
                />
                <Area
                    type="monotone" dataKey="avg_price_kzt"
                    name="Средняя цена" stroke="#3d7fff" strokeWidth={2}
                    fill="url(#avgGrad)" dot={false} activeDot={{ r: 5 }}
                />
                <Area
                    type="monotone" dataKey="median_price_kzt"
                    name="Медиана" stroke="#22d3a3" strokeWidth={2}
                    fill="url(#medGrad)" dot={false} activeDot={{ r: 5 }}
                />
            </AreaChart>
        </ResponsiveContainer>
    );
}
