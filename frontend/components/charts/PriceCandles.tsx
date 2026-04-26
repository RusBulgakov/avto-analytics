// components/charts/PriceCandles.tsx — distribution-style candlesticks of prices over time.
// Each candle aggregates price_history entries inside a time bucket (day/week/month):
//   • vertical whisker  = P5 → P95
//   • box body          = Q1 (p25) → Q3 (p75)
//   • median            = horizontal tick inside the box
//   • color             = direction of median vs. previous bucket (up/down)
'use client';
import { useMemo, useState } from 'react';
import { format } from 'date-fns';
import { ru } from 'date-fns/locale';

export type Granularity = 'day' | 'week' | 'month';

export interface Candle {
    date: string;          // ISO start of bucket
    count: number;
    whisker_low: number;
    p25: number;
    median: number;
    p75: number;
    whisker_high: number;
}

interface Props {
    data: Candle[];
    granularity: Granularity;
    loading?: boolean;
}

const W = 800;
const H = 320;
const PAD_L = 64;
const PAD_R = 16;
const PAD_T = 16;
const PAD_B = 36;

function fmtPrice(v: number) {
    if (v >= 1_000_000) return `${(v / 1_000_000).toFixed(1)} млн`;
    if (v >= 1_000) return `${Math.round(v / 1_000)}к`;
    return `${v}`;
}

function fmtBucketLabel(d: string, g: Granularity) {
    if (g === 'month') return format(new Date(d), 'LLL', { locale: ru });
    return format(new Date(d), 'd MMM', { locale: ru });
}

function fmtBucketTooltip(d: string, g: Granularity) {
    if (g === 'month') return format(new Date(d), 'LLLL yyyy', { locale: ru });
    if (g === 'week') {
        const start = new Date(d);
        const end = new Date(start);
        end.setDate(start.getDate() + 6);
        return `${format(start, 'd MMM', { locale: ru })} – ${format(end, 'd MMM yyyy', { locale: ru })}`;
    }
    return format(new Date(d), 'd MMM yyyy', { locale: ru });
}

export default function PriceCandles({ data, granularity, loading }: Props) {
    const [hoverIdx, setHoverIdx] = useState<number | null>(null);

    const { yMin, yMax, ticks } = useMemo(() => {
        if (!data.length) return { yMin: 0, yMax: 1, ticks: [] as number[] };
        const lo = Math.min(...data.map(c => c.whisker_low));
        const hi = Math.max(...data.map(c => c.whisker_high));
        const span = Math.max(1, hi - lo);
        const yMin = Math.max(0, lo - span * 0.05);
        const yMax = hi + span * 0.05;

        // ~5 evenly-spaced ticks
        const range = yMax - yMin;
        const step = Math.pow(10, Math.floor(Math.log10(range / 4)));
        const niceStep = Math.ceil(range / step / 4) * step;
        const ticks: number[] = [];
        const start = Math.ceil(yMin / niceStep) * niceStep;
        for (let v = start; v <= yMax; v += niceStep) ticks.push(v);
        return { yMin, yMax, ticks };
    }, [data]);

    if (loading) return <div className="skeleton" style={{ height: 320, borderRadius: 8 }} />;
    if (!data.length) {
        return (
            <div style={{
                height: 320, display: 'flex', alignItems: 'center', justifyContent: 'center',
                color: 'var(--text-muted)', fontSize: 12,
            }}>
                Нет данных за выбранный период
            </div>
        );
    }

    const innerW = W - PAD_L - PAD_R;
    const innerH = H - PAD_T - PAD_B;
    const slotW = innerW / data.length;
    const candleW = Math.max(4, Math.min(28, slotW * 0.55));

    const xCenter = (i: number) => PAD_L + slotW * (i + 0.5);
    const y = (v: number) => PAD_T + innerH * (1 - (v - yMin) / (yMax - yMin));

    const hovered = hoverIdx != null ? data[hoverIdx] : null;

    return (
        <div style={{ width: '100%', maxWidth: 920, margin: '0 auto' }}>
            <svg
                viewBox={`0 0 ${W} ${H}`}
                width="100%"
                height={H}
                style={{ display: 'block', fontFamily: 'inherit' }}
                onMouseLeave={() => setHoverIdx(null)}
            >
                {/* Y-axis grid */}
                {ticks.map(t => (
                    <g key={t}>
                        <line
                            x1={PAD_L} y1={y(t)} x2={W - PAD_R} y2={y(t)}
                            stroke="var(--border)" strokeWidth={1} strokeDasharray="3 4" opacity={0.4}
                        />
                        <text
                            x={PAD_L - 8} y={y(t) + 4}
                            textAnchor="end" fontSize={10}
                            fill="var(--text-muted)" fontFamily="var(--mono)"
                        >
                            {fmtPrice(t)}
                        </text>
                    </g>
                ))}

                {/* Candles */}
                {data.map((c, i) => {
                    const cx = xCenter(i);
                    const x0 = cx - candleW / 2;
                    const prev = i > 0 ? data[i - 1].median : c.median;
                    const isUp = c.median >= prev;
                    const stroke = isUp ? 'var(--up)' : 'var(--down)';
                    const fill = isUp ? 'var(--up-soft)' : 'var(--down-soft)';
                    const isHover = hoverIdx === i;

                    return (
                        <g
                            key={c.date}
                            onMouseEnter={() => setHoverIdx(i)}
                            style={{ cursor: 'default' }}
                        >
                            {/* invisible hit area = full slot */}
                            <rect
                                x={PAD_L + slotW * i} y={PAD_T}
                                width={slotW} height={innerH}
                                fill="transparent"
                            />
                            {/* whisker line P5-P95 */}
                            <line
                                x1={cx} y1={y(c.whisker_high)}
                                x2={cx} y2={y(c.whisker_low)}
                                stroke={stroke} strokeWidth={1.4} opacity={isHover ? 1 : 0.7}
                            />
                            {/* whisker caps */}
                            <line
                                x1={cx - 4} y1={y(c.whisker_high)}
                                x2={cx + 4} y2={y(c.whisker_high)}
                                stroke={stroke} strokeWidth={1.4}
                            />
                            <line
                                x1={cx - 4} y1={y(c.whisker_low)}
                                x2={cx + 4} y2={y(c.whisker_low)}
                                stroke={stroke} strokeWidth={1.4}
                            />
                            {/* IQR box Q1-Q3 */}
                            <rect
                                x={x0} y={y(c.p75)}
                                width={candleW} height={Math.max(2, y(c.p25) - y(c.p75))}
                                fill={fill} stroke={stroke} strokeWidth={1.5} rx={1.5}
                            />
                            {/* median tick */}
                            <line
                                x1={x0} y1={y(c.median)}
                                x2={x0 + candleW} y2={y(c.median)}
                                stroke={stroke} strokeWidth={2.2}
                            />
                        </g>
                    );
                })}

                {/* X-axis labels (every Nth so they don't crowd) */}
                {data.map((c, i) => {
                    const stride = Math.max(1, Math.ceil(data.length / 8));
                    if (i % stride !== 0 && i !== data.length - 1) return null;
                    return (
                        <text
                            key={`xl-${c.date}`}
                            x={xCenter(i)} y={H - PAD_B + 16}
                            textAnchor="middle" fontSize={10}
                            fill="var(--text-muted)" fontFamily="var(--mono)"
                        >
                            {fmtBucketLabel(c.date, granularity)}
                        </text>
                    );
                })}
            </svg>

            {/* Tooltip / status row */}
            <div
                className="mono"
                style={{
                    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
                    fontSize: 11, color: 'var(--text-muted)', padding: '4px 4px 0',
                    minHeight: 18,
                }}
            >
                {hovered ? (
                    <>
                        <span>
                            <span style={{ color: 'var(--text)' }}>{fmtBucketTooltip(hovered.date, granularity)}</span>
                            <span style={{ margin: '0 8px' }}>·</span>
                            P25 <span style={{ color: 'var(--text)' }}>{fmtPrice(hovered.p25)} ₸</span>
                            <span style={{ margin: '0 6px' }}>·</span>
                            <span style={{ color: 'var(--text)' }}>med {fmtPrice(hovered.median)} ₸</span>
                            <span style={{ margin: '0 6px' }}>·</span>
                            P75 <span style={{ color: 'var(--text)' }}>{fmtPrice(hovered.p75)} ₸</span>
                        </span>
                        <span>{hovered.count.toLocaleString('ru-RU')} объявл.</span>
                    </>
                ) : (
                    <>
                        <span>● тело = Q1–Q3 · усы = P5–P95 · цвет = направление медианы</span>
                        <span>{data.length} {granularity === 'month' ? 'мес.' : granularity === 'week' ? 'нед.' : 'дн.'}</span>
                    </>
                )}
            </div>
        </div>
    );
}
