// hooks/useUsdKzt.ts — fetch USD/KZT rate from free public API (CORS-enabled, no key)
// Source: open.er-api.com (refreshed daily). Falls back to a sane default if offline.
import useSWR from 'swr';

interface UsdKztResponse {
    result: string;
    rates: Record<string, number>;
    time_last_update_unix: number;
}

interface UsdKzt {
    rate: number;        // current USD→KZT rate
    delta: number | null;// % change vs previous observation stored locally
    updatedAt: Date;
}

const fetcher = async (url: string): Promise<UsdKztResponse> => {
    const r = await fetch(url);
    if (!r.ok) throw new Error('fx fetch failed');
    return r.json();
};

const FX_URL = 'https://open.er-api.com/v6/latest/USD';

export function useUsdKzt(): { data: UsdKzt | null; isLoading: boolean } {
    const { data, isLoading } = useSWR<UsdKztResponse>(FX_URL, fetcher, {
        refreshInterval: 30 * 60 * 1000, // 30 min
        revalidateOnFocus: false,
        dedupingInterval: 5 * 60 * 1000,
    });

    if (!data || !data.rates?.KZT) {
        return { data: null, isLoading };
    }

    const rate = data.rates.KZT;
    const updatedAt = new Date(data.time_last_update_unix * 1000);

    // Track previous rate in localStorage to derive a delta %
    let delta: number | null = null;
    if (typeof window !== 'undefined') {
        try {
            const prevRaw = localStorage.getItem('usdkzt:prev');
            if (prevRaw) {
                const prev = Number(prevRaw);
                if (!Number.isNaN(prev) && prev > 0) {
                    delta = ((rate - prev) / prev) * 100;
                }
            }
            // Update snapshot once per hour to avoid noise
            const stampRaw = localStorage.getItem('usdkzt:stamp');
            const stamp = stampRaw ? Number(stampRaw) : 0;
            const hoursSince = (Date.now() - stamp) / 36e5;
            if (hoursSince > 24) {
                localStorage.setItem('usdkzt:prev', String(rate));
                localStorage.setItem('usdkzt:stamp', String(Date.now()));
            }
        } catch {
            /* noop */
        }
    }

    return { data: { rate, delta, updatedAt }, isLoading: false };
}
