// components/charts/BoxPlot.tsx
// Рисует горизонтальные «ящики с усами» (box-and-whisker) для топ-10 марок
// Данные: { brand, q1, median, q3, whisker_low, whisker_high, count }

import { useMemo } from 'react';
import { fmt as sharedFmt } from '@/lib/format';

export interface BoxPlotItem {
    brand: string;
    count: number;
    min_price: number;
    q1: number;
    median: number;
    q3: number;
    max_price: number;
    whisker_low: number;
    whisker_high: number;
}

interface Props {
    data: BoxPlotItem[];
    loading?: boolean;
}

const BRAND_COLORS = [
    '#6366f1', '#22d3ee', '#f59e0b', '#10b981', '#f43f5e',
    '#8b5cf6', '#ec4899', '#14b8a6', '#f97316', '#06b6d4',
];

function fmt(n: number) {
    if (!n) return '—';
    if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}М`;
    if (n >= 1_000) return `${(n / 1_000).toFixed(0)}К`;
    return `${n}`;
}

export default function BoxPlot({ data, loading }: Props) {
    const ROW_H = 22;
    const LABEL_W = 88;
    const PAD_RIGHT = 20;
    const PAD_TOP = 10;
    const PAD_BOTTOM = 18;

    const sorted = useMemo(() =>
        [...(data ?? [])].sort((a, b) => a.median - b.median),
        [data]
    );

    const globalMin = useMemo(() => Math.min(...sorted.map(d => d.whisker_low)), [sorted]);
    const globalMax = useMemo(() => Math.max(...sorted.map(d => d.whisker_high)), [sorted]);

    // ticks on the x-axis
    const ticks = useMemo(() => {
        const range = globalMax - globalMin;
        const step = Math.pow(10, Math.floor(Math.log10(range / 5)));
        const nice = Math.ceil(range / step / 5) * step;
        const t: number[] = [];
        const start = Math.floor(globalMin / step) * step;
        for (let v = start; v <= globalMax + step; v += nice) t.push(v);
        return t.filter(v => v >= globalMin && v <= globalMax);
    }, [globalMin, globalMax]);

    if (loading) {
        return (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                {[...Array(5)].map((_, i) => (
                    <div key={i} className="skeleton" style={{ height: ROW_H - 8 }} />
                ))}
            </div>
        );
    }

    if (!sorted.length) {
        return (
            <div style={{ color: 'var(--color-text-muted)', fontSize: 13, textAlign: 'center', padding: '24px 0' }}>
                Нет данных для отображения
            </div>
        );
    }

    const svgH = sorted.length * ROW_H + PAD_TOP + PAD_BOTTOM;

    const toX = (v: number, chartW: number) =>
        LABEL_W + ((v - globalMin) / (globalMax - globalMin)) * chartW;

    return (
        <div style={{ width: '100%', maxWidth: 820, margin: '0 auto', overflowX: 'auto' }}>
            <svg
                width="100%"
                height={svgH}
                viewBox={`0 0 800 ${svgH}`}
                preserveAspectRatio="xMidYMid meet"
                style={{ display: 'block', fontFamily: 'inherit' }}
            >
                {/* Grid lines + x-axis ticks */}
                {ticks.map(t => {
                    const x = toX(t, 800 - LABEL_W - PAD_RIGHT);
                    return (
                        <g key={t}>
                            <line
                                x1={x} y1={PAD_TOP}
                                x2={x} y2={svgH - PAD_BOTTOM}
                                stroke="var(--color-border, #2a2e3a)"
                                strokeWidth={1}
                                strokeDasharray="4 4"
                            />
                            <text
                                x={x} y={svgH - PAD_BOTTOM + 16}
                                textAnchor="middle"
                                fontSize={11}
                                fill="var(--color-text-muted, #7b8899)"
                            >
                                {fmt(t)}
                            </text>
                        </g>
                    );
                })}

                {sorted.map((d, i) => {
                    const cy = PAD_TOP + i * ROW_H + ROW_H / 2;
                    const chartW = 800 - LABEL_W - PAD_RIGHT;
                    const x_wl = toX(d.whisker_low, chartW);
                    const x_q1 = toX(d.q1, chartW);
                    const x_med = toX(d.median, chartW);
                    const x_q3 = toX(d.q3, chartW);
                    const x_wh = toX(d.whisker_high, chartW);
                    const color = BRAND_COLORS[i % BRAND_COLORS.length];
                    const boxH = 10;

                    return (
                        <g key={d.brand}>
                            {/* Brand label */}
                            <text
                                x={LABEL_W - 10} y={cy + 4}
                                textAnchor="end"
                                fontSize={12}
                                fontWeight={600}
                                fill="var(--color-text, #e6eaf1)"
                            >
                                {sharedFmt.brandName(d.brand)}
                            </text>

                            {/* Whisker line */}
                            <line
                                x1={x_wl} y1={cy} x2={x_wh} y2={cy}
                                stroke={color} strokeWidth={1.5} opacity={0.6}
                            />

                            {/* Whisker caps */}
                            <line x1={x_wl} y1={cy - 7} x2={x_wl} y2={cy + 7} stroke={color} strokeWidth={1.5} />
                            <line x1={x_wh} y1={cy - 7} x2={x_wh} y2={cy + 7} stroke={color} strokeWidth={1.5} />

                            {/* IQR box */}
                            <rect
                                x={x_q1} y={cy - boxH / 2}
                                width={Math.max(x_q3 - x_q1, 2)} height={boxH}
                                fill={color} fillOpacity={0.18}
                                stroke={color} strokeWidth={1.5}
                                rx={3}
                            />

                            {/* Median line */}
                            <line
                                x1={x_med} y1={cy - boxH / 2}
                                x2={x_med} y2={cy + boxH / 2}
                                stroke={color} strokeWidth={2.5}
                            />

                            {/* Median value tooltip */}
                            <text
                                x={x_med} y={cy - boxH / 2 - 4}
                                textAnchor="middle"
                                fontSize={10}
                                fill={color}
                                fontWeight={700}
                            >
                                {fmt(d.median)}
                            </text>

                            {/* Count badge. У правого края переносим подпись влево от уса,
                                иначе она обрезается краем viewBox («15 78.») */}
                            {(() => {
                                const countLabel = d.count.toLocaleString('ru-RU');
                                const estWidth = countLabel.length * 6.5;
                                const flip = x_wh + 6 + estWidth > 800 - 4;
                                return (
                                    <text
                                        x={flip ? x_wh - 6 : x_wh + 6} y={cy + 4}
                                        fontSize={10}
                                        textAnchor={flip ? 'end' : 'start'}
                                        fill="var(--color-text-muted, #7b8899)"
                                    >
                                        {countLabel}
                                    </text>
                                );
                            })()}
                        </g>
                    );
                })}
            </svg>

            {/* Legend */}
            <div style={{ display: 'flex', gap: 20, justifyContent: 'center', marginTop: 8, flexWrap: 'wrap', fontSize: 11, color: 'var(--color-text-muted)' }}>
                <span>▏— усы (1.5×IQR)</span>
                <span>■ — межквартильный диапазон (Q1–Q3)</span>
                <span>| — медиана</span>
            </div>
        </div>
    );
}
