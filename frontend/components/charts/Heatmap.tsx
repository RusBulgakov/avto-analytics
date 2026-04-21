// components/charts/Heatmap.tsx — year × mileage grid, toggles Price/Volume
import React, { useMemo, useState } from 'react';
import { fmt } from '@/lib/format';

export interface HeatmapCell {
    year: number;
    mileage_bucket: string;
    avg_price_kzt: number;
    volume: number;
}

interface Props {
    data: HeatmapCell[];
    loading?: boolean;
}

const BUCKETS = ['0-20', '20-50', '50-100', '100-150', '150-200', '200+'];
const MIN_YEAR = 2010;
const MAX_YEAR = new Date().getFullYear();

type Mode = 'price' | 'volume';

function colorFor(mode: Mode, t: number /* 0..1 */): string {
    // Two gradients matching design: surface-2 → accent → up (price), surface-2 → info (volume)
    const clamp = Math.max(0, Math.min(1, t));
    if (mode === 'price') {
        // Three-stop mix: surface-2 (cold) → accent (warm) → up (hot)
        if (clamp < 0.5) {
            const p = Math.round(clamp * 2 * 100);
            return `color-mix(in oklab, var(--surface-2) ${100 - p}%, var(--accent) ${p}%)`;
        }
        const p = Math.round((clamp - 0.5) * 2 * 100);
        return `color-mix(in oklab, var(--accent) ${100 - p}%, var(--up) ${p}%)`;
    }
    // volume: single hue
    const p = Math.round(clamp * 100);
    return `color-mix(in oklab, var(--surface-2) ${100 - p}%, var(--info) ${p}%)`;
}

export default function Heatmap({ data, loading }: Props) {
    const [mode, setMode] = useState<Mode>('price');
    const [hover, setHover] = useState<HeatmapCell | null>(null);

    // Build lookup and min/max per mode
    const { lookup, min, max, years } = useMemo(() => {
        const lookup = new Map<string, HeatmapCell>();
        let lo = Infinity;
        let hi = -Infinity;
        const yearSet = new Set<number>();
        for (const c of data) {
            lookup.set(`${c.year}|${c.mileage_bucket}`, c);
            const v = mode === 'price' ? c.avg_price_kzt : c.volume;
            if (v < lo) lo = v;
            if (v > hi) hi = v;
            yearSet.add(c.year);
        }
        // Full year grid — add missing years between min..max of data
        const yearsArr = Array.from(yearSet).sort((a, b) => b - a);
        if (yearsArr.length === 0) {
            for (let y = MAX_YEAR; y >= MIN_YEAR; y--) yearsArr.push(y);
        }
        return { lookup, min: Number.isFinite(lo) ? lo : 0, max: Number.isFinite(hi) ? hi : 1, years: yearsArr };
    }, [data, mode]);

    if (loading) {
        return <div className="skeleton" style={{ height: 420 }} />;
    }

    return (
        <div>
            {/* Caption + mode toggle */}
            <div
                style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginBottom: 10,
                    minHeight: 22,
                }}
            >
                <div className="mono" style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                    {hover ? (
                        <>
                            <span style={{ color: 'var(--text)' }}>{hover.year}</span>
                            <span style={{ margin: '0 6px' }}>·</span>
                            {hover.mileage_bucket} тыс.км
                            <span style={{ margin: '0 6px' }}>·</span>
                            <span style={{ color: 'var(--text)' }}>
                                {fmt.price(hover.avg_price_kzt)} ₸
                            </span>
                            <span style={{ margin: '0 6px' }}>·</span>
                            {fmt.int(hover.volume)} объявл.
                        </>
                    ) : (
                        <span>год × пробег · наведите на ячейку</span>
                    )}
                </div>
                <div className="tweak-seg" style={{ width: 160 }}>
                    <button
                        className={mode === 'price' ? 'active' : ''}
                        onClick={() => setMode('price')}
                    >
                        Цена
                    </button>
                    <button
                        className={mode === 'volume' ? 'active' : ''}
                        onClick={() => setMode('volume')}
                    >
                        Объём
                    </button>
                </div>
            </div>

            {/* Column labels */}
            <div
                className="heatmap-row"
                style={{ gridTemplateColumns: `36px repeat(${BUCKETS.length}, 1fr)` }}
            >
                <div />
                {BUCKETS.map(b => (
                    <div key={b} className="hm-col-label">
                        {b}
                    </div>
                ))}
            </div>

            {/* Data rows */}
            <div className="heatmap">
                {years.map(year => (
                    <div
                        className="heatmap-row"
                        key={year}
                        style={{ gridTemplateColumns: `36px repeat(${BUCKETS.length}, 1fr)` }}
                    >
                        <div className="hm-label">{year}</div>
                        {BUCKETS.map(bucket => {
                            const c = lookup.get(`${year}|${bucket}`);
                            if (!c) {
                                return (
                                    <div
                                        key={bucket}
                                        className="hm-cell hm-empty"
                                    >
                                        —
                                    </div>
                                );
                            }
                            const v = mode === 'price' ? c.avg_price_kzt : c.volume;
                            const t = max > min ? (v - min) / (max - min) : 0.5;
                            const label = mode === 'price' ? fmt.price(v) : fmt.int(v);
                            return (
                                <div
                                    key={bucket}
                                    className="hm-cell"
                                    style={{ background: colorFor(mode, t) }}
                                    onMouseEnter={() => setHover(c)}
                                    onMouseLeave={() => setHover(null)}
                                >
                                    {label}
                                </div>
                            );
                        })}
                    </div>
                ))}
            </div>
        </div>
    );
}
