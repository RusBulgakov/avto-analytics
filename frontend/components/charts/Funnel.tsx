// components/charts/Funnel.tsx — days-on-market distribution bars
import React from 'react';
import { fmt } from '@/lib/format';

export interface FunnelBucket {
    bucket: string; // '0-3' | '4-7' | ...
    count: number;
    pct: number;
}

interface Props {
    data: FunnelBucket[];
    loading?: boolean;
}

// Fast sale → slow sale color progression (mirrors handoff data.js FUNNEL colors)
const COLORS: Record<string, string> = {
    '0-3':   'var(--up)',
    '4-7':   '#5fd99a',
    '8-14':  '#a3d06a',
    '15-30': 'var(--accent)',
    '31-60': '#e89050',
    '61-90': '#e06872',
    '90+':   'var(--down)',
};

const LABELS: Record<string, string> = {
    '0-3':   '0–3 дня',
    '4-7':   '4–7 дней',
    '8-14':  '8–14 дней',
    '15-30': '15–30 дней',
    '31-60': '31–60 дней',
    '61-90': '61–90 дней',
    '90+':   '90+ дней',
};

export default function Funnel({ data, loading }: Props) {
    if (loading) {
        return <div className="skeleton" style={{ height: 240 }} />;
    }

    const max = Math.max(1, ...data.map(d => d.count));

    return (
        <div>
            {data.map(d => {
                const widthPct = max > 0 ? (d.count / max) * 100 : 0;
                return (
                    <div className="funnel-row" key={d.bucket}>
                        <div className="funnel-label">{LABELS[d.bucket] ?? d.bucket}</div>
                        <div className="funnel-bar-wrap">
                            <div
                                className="funnel-bar"
                                style={{
                                    width: `${widthPct}%`,
                                    background: COLORS[d.bucket] ?? 'var(--info)',
                                }}
                            />
                        </div>
                        <div className="funnel-count tnum">{fmt.int(d.count)}</div>
                        <div className="funnel-pct tnum">{d.pct.toFixed(1)}%</div>
                    </div>
                );
            })}
        </div>
    );
}
