// components/filters/FilterPanel.tsx
// Mobile-first панель фильтров с Select's
'use client';
import { useEffect, useState } from 'react';
import { analyticsApi } from '@/lib/api';
import styles from './FilterPanel.module.css';

interface Filters {
    brand_id?: number[];
    model_id?: number[];
    year?: number[];
    mileage_max?: number;
    city?: string[];
    source?: string[];
    period_days?: number;
}

interface FilterPanelProps {
    onChange: (filters: Filters) => void;
}

const SOURCES = ['kolesa', 'avtorynok', 'mycar', 'newauto', 'olx'];
const YEARS = Array.from({ length: 2026 - 1990 + 1 }, (_, i) => 2026 - i);
const PERIODS = [
    { label: '7 дней', value: 7 },
    { label: '30 дней', value: 30 },
    { label: '90 дней', value: 90 },
    { label: '180 дней', value: 180 },
    { label: '1 год', value: 365 },
];

function CheckboxGroup({ options, selected, onChange, labelKey = 'label', valueKey = 'value' }: any) {
    const handleToggle = (val: any) => {
        const current = selected || [];
        if (current.includes(val)) onChange(current.filter((item: any) => item !== val));
        else onChange([...current, val]);
    };
    return (
        <div className={styles.checkboxList}>
            {options.map((opt: any) => {
                const isObj = typeof opt === 'object';
                const val = isObj ? opt[valueKey] : opt;
                const label = isObj ? opt[labelKey] : opt;
                const display = isObj && opt.listings_count ? `${label} (${opt.listings_count})` : label;
                return (
                    <label key={val} className={styles.checkboxItem}>
                        <input type="checkbox" checked={(selected || []).includes(val)} onChange={() => handleToggle(val)} />
                        <span>{display}</span>
                    </label>
                );
            })}
        </div>
    );
}

export default function FilterPanel({ onChange }: FilterPanelProps) {
    const [brands, setBrands] = useState<any[]>([]);
    const [models, setModels] = useState<any[]>([]);
    const [filters, setFilters] = useState<Filters>({ period_days: 90 });

    useEffect(() => {
        analyticsApi.getBrands().then(setBrands);
    }, []);

    useEffect(() => {
        if (filters.brand_id && filters.brand_id.length === 1) {
            analyticsApi.getModels(filters.brand_id[0]).then(setModels);
        } else {
            setModels([]);
        }
    }, [filters.brand_id]);

    const update = (key: keyof Filters, value: any) => {
        const newFilters = { ...filters };
        if (key === 'period_days' || key === 'mileage_max') {
            newFilters[key] = value || undefined;
        } else {
            newFilters[key] = value && value.length > 0 ? value : undefined;
        }

        if (key === 'brand_id' && (!value || value.length !== 1)) {
            newFilters.model_id = undefined;
        }
        setFilters(newFilters);
        onChange(newFilters);
    };

    return (
        <div className={styles.panel}>
            <div className={styles.title}>Фильтры</div>

            <div className={styles.group}>
                <label className={styles.label}>Марка</label>
                <CheckboxGroup options={brands} selected={filters.brand_id} onChange={(v: any) => update('brand_id', v)} labelKey="name" valueKey="id" />
            </div>

            {models.length > 0 && (
                <div className={styles.group}>
                    <label className={styles.label}>Модель</label>
                    <CheckboxGroup options={models} selected={filters.model_id} onChange={(v: any) => update('model_id', v)} labelKey="name" valueKey="id" />
                </div>
            )}

            <div className={styles.group}>
                <label className={styles.label}>Год выпуска</label>
                <CheckboxGroup options={YEARS} selected={filters.year} onChange={(v: any) => update('year', v)} />
            </div>

            <div className={styles.group}>
                <label className={styles.label}>Макс. пробег (км)</label>
                <input id="filter-mileage" type="number" className={styles.input}
                    placeholder="Напр. 100000"
                    onChange={(e) => update('mileage_max', e.target.value ? +e.target.value : undefined)} />
            </div>

            <div className={styles.group}>
                <label className={styles.label}>Город</label>
                <input id="filter-city" type="text" className={styles.input}
                    placeholder="Алматы, Астана (через запятую)"
                    onChange={(e) => update('city', e.target.value ? e.target.value.split(',').map(s => s.trim()).filter(Boolean) : undefined)} />
            </div>

            <div className={styles.group}>
                <label className={styles.label}>Источник</label>
                <CheckboxGroup options={SOURCES} selected={filters.source} onChange={(v: any) => update('source', v)} />
            </div>

            <div className={styles.group}>
                <label className={styles.label}>Период</label>
                <div className={styles.pills}>
                    {PERIODS.map(p => (
                        <button key={p.value} id={`period-${p.value}`}
                            className={`${styles.pill} ${filters.period_days === p.value ? styles.pillActive : ''}`}
                            onClick={() => update('period_days', p.value)}>
                            {p.label}
                        </button>
                    ))}
                </div>
            </div>
        </div>
    );
}
