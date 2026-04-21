// store/filters.ts — zustand store for dashboard FilterState, with URL sync helpers
import { create } from 'zustand';
import { emptyFilters, type FilterState, type Period } from '@/types/analytics';

type NumberTuple = [number, number];

export interface FiltersStore extends FilterState {
    setBrandId: (ids: number[]) => void;
    setModelId: (ids: number[]) => void;
    setCity: (cities: string[]) => void;
    setYear: (year: NumberTuple | null) => void;
    setPrice: (price: NumberTuple | null) => void;
    setMileage: (mileage: NumberTuple | null) => void;
    setPeriod: (period: Period) => void;
    setSource: (source: string[]) => void;
    setAll: (next: Partial<FilterState>) => void;
    reset: () => void;
    syncFromUrl: (search: string) => void;
}

/* ───────────────── URL helpers (exported for hook) ──────────────── */

export function filtersToQuery(f: FilterState): Record<string, string> {
    const q: Record<string, string> = {};
    if (f.brand_id.length) q.brand_id = f.brand_id.join(',');
    if (f.model_id.length) q.model_id = f.model_id.join(',');
    if (f.city.length) q.city = f.city.join(',');
    if (f.year) q.year = `${f.year[0]}-${f.year[1]}`;
    if (f.price) q.price = `${f.price[0]}-${f.price[1]}`;
    if (f.mileage) q.mileage = `${f.mileage[0]}-${f.mileage[1]}`;
    // period: skip default (90); 'all' encoded as "all"
    if (f.period !== 90) q.period = String(f.period);
    if (f.source.length) q.source = f.source.join(',');
    return q;
}

function parseIntList(raw: string | null): number[] {
    if (!raw) return [];
    return raw
        .split(',')
        .map(s => parseInt(s.trim(), 10))
        .filter(n => Number.isFinite(n));
}

function parseStrList(raw: string | null): string[] {
    if (!raw) return [];
    return raw.split(',').map(s => s.trim()).filter(Boolean);
}

function parseRange(raw: string | null): NumberTuple | null {
    if (!raw) return null;
    const parts = raw.split('-').map(s => Number(s.trim()));
    if (parts.length !== 2 || parts.some(n => !Number.isFinite(n))) return null;
    return [parts[0], parts[1]];
}

function parsePeriod(raw: string | null): Period {
    if (!raw) return 90;
    if (raw === 'all') return 'all';
    const n = parseInt(raw, 10);
    if (n === 7 || n === 30 || n === 90 || n === 180 || n === 365) return n;
    return 90;
}

export function queryToFilters(search: string): FilterState {
    const sp = new URLSearchParams(search);
    return {
        brand_id: parseIntList(sp.get('brand_id')),
        model_id: parseIntList(sp.get('model_id')),
        city: parseStrList(sp.get('city')),
        year: parseRange(sp.get('year')),
        price: parseRange(sp.get('price')),
        mileage: parseRange(sp.get('mileage')),
        period: parsePeriod(sp.get('period')),
        source: parseStrList(sp.get('source')),
    };
}

/* ───────────────── Store ───────────────── */

export const useFilters = create<FiltersStore>((set) => ({
    ...emptyFilters,
    setBrandId: (ids) => set({ brand_id: ids, model_id: [] }),
    setModelId: (ids) => set({ model_id: ids }),
    setCity: (cities) => set({ city: cities }),
    setYear: (year) => set({ year }),
    setPrice: (price) => set({ price }),
    setMileage: (mileage) => set({ mileage }),
    setPeriod: (period) => set({ period }),
    setSource: (source) => set({ source }),
    setAll: (next) => set(next as Partial<FiltersStore>),
    reset: () => set({ ...emptyFilters }),
    syncFromUrl: (search) => {
        const parsed = queryToFilters(search);
        set({ ...parsed });
    },
}));

/** Convenience selector: plain FilterState without actions. */
export function selectFilterState(s: FiltersStore): FilterState {
    return {
        brand_id: s.brand_id,
        model_id: s.model_id,
        city: s.city,
        year: s.year,
        price: s.price,
        mileage: s.mileage,
        period: s.period,
        source: s.source,
    };
}
