// components/layout/FilterBar.tsx — chip row with real dropdowns + period toggle + updated-at
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import useSWR from 'swr';

import type { FilterState, Period } from '@/types/analytics';
import { analyticsApi } from '@/lib/api';
import { fmt } from '@/lib/format';
import FilterDropdown from '@/components/ui/FilterDropdown';

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

type ChipKey = 'brand' | 'model' | 'city' | 'year' | 'price' | 'mileage';

const CURRENT_YEAR = new Date().getFullYear();
const MIN_YEAR = 2000;
const MIN_PRICE_MIL = 0;
const MAX_PRICE_MIL = 200;
const MIN_MILEAGE_K = 0;
const MAX_MILEAGE_K = 500;

/* ─── small helpers ─── */
function formatRange(r: [number, number] | null, unit = '') {
    if (!r) return null;
    const [a, b] = r;
    return unit ? `${a}–${b} ${unit}` : `${a}–${b}`;
}

function capitalize(s: string): string {
    if (!s) return s;
    return s.charAt(0).toUpperCase() + s.slice(1);
}

function cityLabel(slug: string): string {
    // DB stores slugs like `ust-kamenogorsk`; split on `-`, capitalize each.
    return slug
        .split('-')
        .map(capitalize)
        .join('-');
}

/* ─── Brand/Model/City list items from backend ─── */
interface BrandItem { id: number; name: string; slug: string; listings_count: number }
interface ModelItem { id: number; name: string; slug: string; listings_count: number }
interface CityItem { name: string; listings_count: number }

/* ────────────────── Dropdown bodies ───────────────── */

function MultiIdDropdown({
    items, selected, onToggle, loading, labelFor,
}: {
    items: { id: number; name: string; listings_count: number }[] | undefined;
    selected: number[];
    onToggle: (id: number) => void;
    loading: boolean;
    labelFor?: (it: { id: number; name: string; listings_count: number }) => string;
}) {
    if (loading) {
        return <div className="filter-empty">загрузка…</div>;
    }
    if (!items || items.length === 0) {
        return <div className="filter-empty">нет данных</div>;
    }
    return (
        <div className="filter-list" role="listbox">
            {items.map((it) => {
                const on = selected.includes(it.id);
                const label = labelFor ? labelFor(it) : it.name;
                return (
                    <button
                        key={it.id}
                        type="button"
                        role="option"
                        aria-selected={on}
                        className={`filter-option ${on ? 'selected' : ''}`}
                        onClick={() => onToggle(it.id)}
                    >
                        <span className="filter-check" aria-hidden>{on ? '✓' : ''}</span>
                        <span className="filter-option-label">{label}</span>
                        <span className="filter-option-count">{fmt.int(it.listings_count)}</span>
                    </button>
                );
            })}
        </div>
    );
}

function CityDropdown({
    cities, selected, onToggle, loading,
}: {
    cities: CityItem[] | undefined;
    selected: string[];
    onToggle: (slug: string) => void;
    loading: boolean;
}) {
    if (loading) {
        return <div className="filter-empty">загрузка…</div>;
    }
    if (!cities || cities.length === 0) {
        return <div className="filter-empty">нет данных</div>;
    }
    return (
        <div className="filter-list" role="listbox">
            {cities.map((c) => {
                const on = selected.includes(c.name);
                return (
                    <button
                        key={c.name}
                        type="button"
                        role="option"
                        aria-selected={on}
                        className={`filter-option ${on ? 'selected' : ''}`}
                        onClick={() => onToggle(c.name)}
                    >
                        <span className="filter-check" aria-hidden>{on ? '✓' : ''}</span>
                        <span className="filter-option-label">{cityLabel(c.name)}</span>
                        <span className="filter-option-count">{fmt.int(c.listings_count)}</span>
                    </button>
                );
            })}
        </div>
    );
}

function RangeDropdown({
    initial, min, max, step = 1, unit, onApply, onReset,
}: {
    initial: [number, number] | null;
    min: number;
    max: number;
    step?: number;
    unit: string;
    onApply: (range: [number, number] | null) => void;
    onReset: () => void;
}) {
    const [from, setFrom] = useState<string>(initial ? String(initial[0]) : '');
    const [to, setTo] = useState<string>(initial ? String(initial[1]) : '');

    const parse = (s: string) => {
        const n = parseFloat(s.replace(',', '.'));
        return Number.isFinite(n) ? n : null;
    };

    const submit = () => {
        const a = parse(from);
        const b = parse(to);
        if (a == null && b == null) {
            onApply(null);
            return;
        }
        const lo = a != null ? Math.max(min, a) : min;
        const hi = b != null ? Math.min(max, b) : max;
        if (hi < lo) {
            onApply([hi, lo]);
        } else {
            onApply([lo, hi]);
        }
    };

    const reset = () => {
        setFrom('');
        setTo('');
        onReset();
    };

    return (
        <div className="filter-range">
            <div className="filter-range-row">
                <label className="filter-range-field">
                    <span className="filter-range-label">от</span>
                    <input
                        className="filter-input"
                        type="number"
                        min={min}
                        max={max}
                        step={step}
                        value={from}
                        inputMode="numeric"
                        placeholder={String(min)}
                        onChange={(e) => setFrom(e.target.value)}
                    />
                </label>
                <label className="filter-range-field">
                    <span className="filter-range-label">до</span>
                    <input
                        className="filter-input"
                        type="number"
                        min={min}
                        max={max}
                        step={step}
                        value={to}
                        inputMode="numeric"
                        placeholder={String(max)}
                        onChange={(e) => setTo(e.target.value)}
                    />
                </label>
                <span className="filter-range-unit">{unit}</span>
            </div>
            <div className="filter-range-actions">
                <button type="button" className="filter-btn filter-btn-ghost" onClick={reset}>Сбросить</button>
                <button type="button" className="filter-btn filter-btn-primary" onClick={submit}>Ок</button>
            </div>
        </div>
    );
}

/* ────────────────────── Main component ────────────────────── */

export default function FilterBar({ filters, onChange }: Props) {
    // Tick "обновлено" every minute
    const [now, setNow] = useState<Date>(new Date());
    useEffect(() => {
        const i = setInterval(() => setNow(new Date()), 60_000);
        return () => clearInterval(i);
    }, []);

    // Open state + anchor rect for the portal dropdown
    const [open, setOpen] = useState<ChipKey | null>(null);
    const [anchor, setAnchor] = useState<DOMRect | null>(null);
    const chipRefs = useRef<Record<ChipKey, HTMLButtonElement | null>>({
        brand: null, model: null, city: null, year: null, price: null, mileage: null,
    });

    const openChip = (key: ChipKey) => {
        const el = chipRefs.current[key];
        if (!el) return;
        // Capture rect BEFORE any reflow.
        setAnchor(el.getBoundingClientRect());
        setOpen(key);
    };

    const toggleChip = (key: ChipKey) => {
        if (open === key) {
            setOpen(null);
            return;
        }
        openChip(key);
    };

    const close = useCallback(() => setOpen(null), []);

    // Re-measure anchor on scroll/resize while open.
    useEffect(() => {
        if (!open) return;
        const handler = () => {
            const el = chipRefs.current[open];
            if (el) setAnchor(el.getBoundingClientRect());
        };
        window.addEventListener('resize', handler);
        window.addEventListener('scroll', handler, true);
        return () => {
            window.removeEventListener('resize', handler);
            window.removeEventListener('scroll', handler, true);
        };
    }, [open]);

    /* ── Data ── */
    const { data: brands, isLoading: brandsLoading } = useSWR<BrandItem[]>(
        'brands',
        () => analyticsApi.getBrands(),
        { revalidateOnFocus: false }
    );

    const singleBrandId = filters.brand_id.length === 1 ? filters.brand_id[0] : null;
    const { data: models, isLoading: modelsLoading } = useSWR<ModelItem[]>(
        singleBrandId != null ? ['models', singleBrandId] : null,
        () => analyticsApi.getModels(singleBrandId as number),
        { revalidateOnFocus: false }
    );

    const { data: cities, isLoading: citiesLoading } = useSWR<CityItem[]>(
        'cities',
        () => analyticsApi.getCities(),
        { revalidateOnFocus: false }
    );

    /* ── Chip value summaries ── */
    const chips = useMemo((): { key: ChipKey; label: string; val: string | null; disabled?: boolean }[] => {
        let brandSummary: string | null = null;
        if (filters.brand_id.length === 1 && brands) {
            const b = brands.find((br) => br.id === filters.brand_id[0]);
            brandSummary = b ? b.name : '1';
        } else if (filters.brand_id.length > 1) {
            brandSummary = `${filters.brand_id.length}`;
        }

        let modelSummary: string | null = null;
        if (filters.model_id.length === 1 && models) {
            const m = models.find((mm) => mm.id === filters.model_id[0]);
            modelSummary = m ? m.name : '1';
        } else if (filters.model_id.length > 1) {
            modelSummary = `${filters.model_id.length}`;
        }

        const citySummary = filters.city.length === 0
            ? null
            : filters.city.length === 1
                ? cityLabel(filters.city[0])
                : `${filters.city.length}`;

        const priceForChip = filters.price
            ? ([Math.round((filters.price[0] / 1_000_000) * 10) / 10, Math.round((filters.price[1] / 1_000_000) * 10) / 10] as [number, number])
            : null;

        return [
            { key: 'brand', label: 'Марка', val: brandSummary },
            { key: 'model', label: 'Модель', val: modelSummary, disabled: singleBrandId == null },
            { key: 'city',  label: 'Город',  val: citySummary },
            { key: 'year',  label: 'Год',    val: formatRange(filters.year) },
            { key: 'price', label: 'Цена',   val: formatRange(priceForChip, 'млн ₸') },
            { key: 'mileage', label: 'Пробег', val: formatRange(filters.mileage, 'тыс') },
        ];
    }, [filters, brands, models, singleBrandId]);

    /* ── Toggle helpers ── */
    const toggleBrand = (id: number) => {
        const set = new Set(filters.brand_id);
        if (set.has(id)) set.delete(id); else set.add(id);
        // Clear models when brand selection changes.
        onChange({ ...filters, brand_id: Array.from(set), model_id: [] });
    };

    const toggleModel = (id: number) => {
        const set = new Set(filters.model_id);
        if (set.has(id)) set.delete(id); else set.add(id);
        onChange({ ...filters, model_id: Array.from(set) });
    };

    const toggleCity = (slug: string) => {
        const set = new Set(filters.city);
        if (set.has(slug)) set.delete(slug); else set.add(slug);
        onChange({ ...filters, city: Array.from(set) });
    };

    const setPeriod = (period: Period) => onChange({ ...filters, period });

    /* ── Clear a chip via the × marker ── */
    const clearChip = (key: ChipKey, e: React.MouseEvent) => {
        e.stopPropagation();
        switch (key) {
            case 'brand':   onChange({ ...filters, brand_id: [], model_id: [] }); break;
            case 'model':   onChange({ ...filters, model_id: [] }); break;
            case 'city':    onChange({ ...filters, city: [] }); break;
            case 'year':    onChange({ ...filters, year: null }); break;
            case 'price':   onChange({ ...filters, price: null }); break;
            case 'mileage': onChange({ ...filters, mileage: null }); break;
        }
    };

    /* ── Render active dropdown body ── */
    const dropdownBody = (() => {
        switch (open) {
            case 'brand':
                return (
                    <MultiIdDropdown
                        items={brands}
                        selected={filters.brand_id}
                        onToggle={toggleBrand}
                        loading={brandsLoading}
                        labelFor={(it) => `${it.name}`}
                    />
                );
            case 'model':
                if (singleBrandId == null) {
                    return <div className="filter-empty">выберите одну марку</div>;
                }
                return (
                    <MultiIdDropdown
                        items={models}
                        selected={filters.model_id}
                        onToggle={toggleModel}
                        loading={modelsLoading}
                    />
                );
            case 'city':
                return (
                    <CityDropdown
                        cities={cities}
                        selected={filters.city}
                        onToggle={toggleCity}
                        loading={citiesLoading}
                    />
                );
            case 'year':
                return (
                    <RangeDropdown
                        key={`year-${filters.year?.[0] ?? 'x'}-${filters.year?.[1] ?? 'y'}`}
                        initial={filters.year}
                        min={MIN_YEAR}
                        max={CURRENT_YEAR}
                        unit="г."
                        onApply={(r) => { onChange({ ...filters, year: r }); close(); }}
                        onReset={() => { onChange({ ...filters, year: null }); close(); }}
                    />
                );
            case 'price':
                return (
                    <RangeDropdown
                        key={`price-${filters.price?.[0] ?? 'x'}-${filters.price?.[1] ?? 'y'}`}
                        initial={filters.price ? [filters.price[0] / 1_000_000, filters.price[1] / 1_000_000] : null}
                        min={MIN_PRICE_MIL}
                        max={MAX_PRICE_MIL}
                        step={0.5}
                        unit="млн ₸"
                        onApply={(r) => {
                            if (r == null) {
                                onChange({ ...filters, price: null });
                            } else {
                                onChange({ ...filters, price: [Math.round(r[0] * 1_000_000), Math.round(r[1] * 1_000_000)] });
                            }
                            close();
                        }}
                        onReset={() => { onChange({ ...filters, price: null }); close(); }}
                    />
                );
            case 'mileage':
                return (
                    <RangeDropdown
                        key={`mileage-${filters.mileage?.[0] ?? 'x'}-${filters.mileage?.[1] ?? 'y'}`}
                        initial={filters.mileage}
                        min={MIN_MILEAGE_K}
                        max={MAX_MILEAGE_K}
                        unit="тыс. км"
                        onApply={(r) => { onChange({ ...filters, mileage: r }); close(); }}
                        onReset={() => { onChange({ ...filters, mileage: null }); close(); }}
                    />
                );
            default:
                return null;
        }
    })();

    return (
        <div className="filterbar" role="toolbar" aria-label="Фильтры">
            <span className="uppercase" style={{ marginRight: 4 }}>фильтры</span>

            {chips.map((c) => {
                const active = c.val != null;
                const disabled = c.disabled === true;
                return (
                    <button
                        key={c.key}
                        ref={(el) => { chipRefs.current[c.key] = el; }}
                        type="button"
                        disabled={disabled}
                        aria-haspopup="dialog"
                        aria-expanded={open === c.key}
                        className={`chip ${active ? 'active' : ''} ${disabled ? 'chip-disabled' : ''}`}
                        onClick={() => !disabled && toggleChip(c.key)}
                    >
                        <span className="chip-label">{c.label}:</span>
                        <span className="chip-val">{active ? c.val : 'Все'}</span>
                        {active ? (
                            <span
                                className="chip-x"
                                role="button"
                                aria-label={`Сбросить ${c.label}`}
                                onClick={(e) => clearChip(c.key, e)}
                            >×</span>
                        ) : (
                            <span className="chip-x" aria-hidden>+</span>
                        )}
                    </button>
                );
            })}

            <div className="filterbar-sep" aria-hidden />

            <div className="period-group" role="group" aria-label="Период">
                {PERIODS.map((p) => (
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

            <div
                className="period-group"
                role="group"
                aria-label="Режим"
                title="Активные = только сейчас на сайтах. Все = + снятые (исторический режим)"
            >
                <button
                    type="button"
                    className={`period-btn ${!filters.include_inactive ? 'active' : ''}`}
                    onClick={() => onChange({ ...filters, include_inactive: false })}
                >
                    Активные
                </button>
                <button
                    type="button"
                    className={`period-btn ${filters.include_inactive ? 'active' : ''}`}
                    onClick={() => onChange({ ...filters, include_inactive: true })}
                >
                    Все
                </button>
            </div>

            <div className="filterbar-sep" aria-hidden />

            <span
                className="uppercase dim"
                style={{ fontFamily: 'var(--mono)', marginLeft: 'auto' }}
            >
                обновлено {fmt.hhmm(now)}
            </span>

            <FilterDropdown
                open={open != null}
                anchorRect={anchor}
                onClose={close}
                minWidth={open === 'year' || open === 'price' || open === 'mileage' ? 260 : 260}
            >
                {dropdownBody}
            </FilterDropdown>
        </div>
    );
}
