// components/ui/KPI.tsx — single KPI tile (used in kpi-grid container)
import React from 'react';
import Sparkline from './Sparkline';

interface Props {
    label: string;
    value: React.ReactNode;
    unit?: string;
    /** Delta as percent (positive or negative). Null → hide delta row. */
    delta?: number | null;
    /** When true, negative delta is treated as "good" (e.g. liquidity = faster = better). */
    inverted?: boolean;
    foot?: React.ReactNode;
    sparkData?: { value: number }[];
    sparkColor?: string;
    /** Period the delta refers to, used in caption (default "за 30 дн"). */
    deltaCaption?: string;
}

export default function KPI({
    label,
    value,
    unit,
    delta,
    inverted,
    foot,
    sparkData,
    sparkColor,
    deltaCaption = 'за 30 дн',
}: Props) {
    const hasDelta = delta != null && !Number.isNaN(delta);
    const isUp = hasDelta && (delta as number) >= 0;
    const good = inverted ? !isUp : isUp;

    return (
        <div className="kpi">
            <div className="kpi-label">{label}</div>
            <div className="kpi-value tnum">
                {value}
                {unit && <span className="unit">{unit}</span>}
            </div>
            {hasDelta && (
                <div className={`kpi-delta ${good ? 'up' : 'down'}`}>
                    <span className="kpi-arrow">{isUp ? '▲' : '▼'}</span>
                    {/* Знак задаёт стрелка — число без знака, иначе выходило «▼ +0.5%» */}
                    {Math.abs(delta as number).toFixed(1)}%
                    <span className="dim" style={{ marginLeft: 4 }}>{deltaCaption}</span>
                </div>
            )}
            {foot && <div className="kpi-foot">{foot}</div>}
            {sparkData && sparkData.length > 1 && (
                <div className="kpi-spark">
                    <Sparkline data={sparkData} color={sparkColor ?? (good ? 'var(--up)' : 'var(--info)')} />
                </div>
            )}
        </div>
    );
}
