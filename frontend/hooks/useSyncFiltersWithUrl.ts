// hooks/useSyncFiltersWithUrl.ts — two-way sync between useFilters store and URL
import { useEffect, useRef } from 'react';
import { useRouter } from 'next/router';
import {
    useFilters,
    filtersToQuery,
    selectFilterState,
} from '@/store/filters';

/**
 * Mount this once (e.g. in _app.tsx) to:
 *   1. On first client mount, hydrate store from window.location.search.
 *   2. After hydration, push any store change back to the URL via
 *      router.replace({ query }, undefined, { shallow: true }).
 *
 * Values that are "empty" (empty arrays, null ranges, default period 90)
 * are never written to the URL.
 */
export function useSyncFiltersWithUrl() {
    const router = useRouter();
    const syncFromUrl = useFilters((s) => s.syncFromUrl);
    const state = useFilters(selectFilterState);
    const hydrated = useRef(false);

    // 1) Hydrate store once on first client render.
    useEffect(() => {
        if (typeof window === 'undefined') return;
        if (hydrated.current) return;
        syncFromUrl(window.location.search);
        hydrated.current = true;
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // 2) Push store → URL whenever state changes (after hydration).
    useEffect(() => {
        if (!hydrated.current) return;
        if (!router.isReady) return;

        const query = filtersToQuery(state);
        // Avoid redundant replaces (would reset scroll / cause re-renders).
        const currentSearch = typeof window !== 'undefined' ? window.location.search.replace(/^\?/, '') : '';
        const nextSearch = new URLSearchParams(query).toString();
        if (currentSearch === nextSearch) return;

        router.replace(
            { pathname: router.pathname, query },
            undefined,
            { shallow: true, scroll: false },
        );
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [
        state.brand_id,
        state.model_id,
        state.city,
        state.year,
        state.price,
        state.mileage,
        state.period,
        state.source,
        router.isReady,
    ]);
}
