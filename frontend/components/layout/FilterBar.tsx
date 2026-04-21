// components/layout/FilterBar.tsx — chip row + period toggle + updated-at stamp
import React, { useState, useEffect } from 'react';
import type { FilterState, Period } from '@/types/analytics';
import { fmt } from '@/lib/format';

interface Props {
    filters: FilterState;
    onChange: (next: FilterState) => void;
}

const PERIODS: { id: Period; label: string }[] = [
    { id: 7,     label: '7Д' },
    { id: 30,    label: '1М' },
    { id: 90,    label: '3М' },
    { id: 180,   label: '6М' },
    { id: 365,   label: '1Г' },
    { id: 'all', label: 'Все' },
];

function formatRange(r: [number, number] | null, unit = '') {
    if (!r) return null;
    const [a, b] = r;
    return unit ? `${a}–${b} ${unit}` : `${a}–${b}`;
}

export default function FilterBar({ filters, onChange }: Props) {
    // Tick the "обновлено" label every minute
    const [now, setNow] = useState<Date>(new Date());
    useEffect(() => {
        const i = setInterval(() => setNow(new Date()), 60_000);
        return () => clearInterval(i);
    }, []);

    const chips: { key: string; label: string; val: string | null }[] = [
        {
            key: 'brand',
            label: 'Марка',
            val: filters.brand_id.length ? `${filters.brand_id.length}` : null,
        },
        {
            key: 'model',
            label: 'Модель',
            val: filters.model_id.length ? `${filters.model_id.length}` : null,
        },
        {
            key: 'city',
            label: 'Город',
            val: filters.city.length ? filters.city.join(', ') : null,
        },
        { key: 'year',    label: 'Год',    val: formatRange(filters.year) },
        { key: 'price',   label: 'Цена',   val: formatRange(filters.price) },
        { key: 'mileage', label: 'Пробег', val: formatRange(filters.mileage, 'тыс') },
    ];

    const setPeriod = (period: Period) => onChange({ ...filters, period });

    return (
        <div className="filterbar" role="toolbar" aria-label="Фильтры">
            <span className="uppercase" style={{ marginRight: 4 }}>фильтры</span>

            {chips.map(c => {
                const active = c.val != null;
                return (
                    <button
                        key={c.key}
                        type="button"
                        className={`chip ${active ? 'active' : ''}`}
                        /* Wiring: real dropdowns come in step 4 — for now chip is a placeholder */
                    >
                        <span className="chip-label">{c.label}:</span>
                        <span className="chip-val">{active ? c.val : 'Все'}</span>
                        <span className="chip-x" aria-hidden>{active ? '×' : '+'}</span>
                    </button>
                );
            })}

            <div className="filterbar-sep" aria-hidden />

            <div className="period-group" role="group" aria-label="Период">
                {PERIODS.map(p => (
                    <button
                        key={String(p.id)}
                        type="button"
                        className={`period-btn ${filters.period === p.id ? 'active' : ''}`}
                        onClick={() => setPeriod(p.id)}
                    >
                        {p.label}
                    </button>
                ))}
            </div>

            <div className="filterbar-sep" aria-hidden />

            <span
                className="uppercase dim"
                style={{ fontFamily: 'var(--mono)', marginLeft: 'auto' }}
            >
                обновлено {fmt.hhmm(now)}
            </span>
        </div>
    );
}
