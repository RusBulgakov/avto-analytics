// types/analytics.ts — shared types for API responses & UI state

export type Period = 7 | 30 | 90 | 180 | 365 | 'all';

export interface FilterState {
    brand_id: number[];
    model_id: number[];
    city: string[];
    year: [number, number] | null;
    price: [number, number] | null;
    mileage: [number, number] | null;
    period: Period;
    source: string[];
    /** false = только активные (default UI), true = + снятые (исторический режим) */
    include_inactive: boolean;
}

export const emptyFilters: FilterState = {
    brand_id: [],
    model_id: [],
    city: [],
    year: null,
    price: null,
    mileage: null,
    period: 90,
    source: [],
    include_inactive: false,
};

export interface Source {
    name: string;
    count: number;
}

export interface SummaryResponse {
    active_listings: number;
    total_brands: number;
    avg_price_kzt: number;
    sources: Source[];
}

export interface PricePoint {
    date: string;  // ISO
    avg_price_kzt: number;
    median_price_kzt?: number;
}

export interface BrandOverview {
    brand: string;
    active_listings: number;
    avg_price_kzt: number;
    min_price_kzt: number;
    max_price_kzt: number;
}
