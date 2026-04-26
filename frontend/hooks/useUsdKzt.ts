// hooks/useUsdKzt.ts — fetches USD/KZT from our backend /fx-current endpoint
// (single source of truth: NBK daily rates stored in fx_history table).
//
// Замена прежней реализации с open.er-api.com + localStorage-snapshot
// которая давала фантомное delta=0% после первого daily-обновления.
// Теперь delta считается server-side через сравнение с записями
// fx_history за 1/7/30 дней назад — реальные NBK rates.
import useSWR from 'swr';
import { analyticsApi } from '@/lib/api';

interface FxCurrentResp {
    rate: number;
    rate_date: string;
    delta_1d_pct: number | null;
    delta_7d_pct: number | null;
    delta_30d_pct: number | null;
    eur_kzt: number | null;
    rub_kzt: number | null;
    cny_kzt: number | null;
    error?: string;
}

interface UsdKzt {
    rate: number;
    /** 1-day delta — может быть 0% по выходным, когда NBK не публикует. */
    delta: number | null;
    /** 7-day delta — стабильнее, для tooltip / индикатора движения. */
    delta7d: number | null;
    /** 30-day delta — для долгосрочного контекста. */
    delta30d: number | null;
    /** Курс EUR/KZT — для будущих UI. */
    eurKzt: number | null;
    updatedAt: Date;
}

export function useUsdKzt(): { data: UsdKzt | null; isLoading: boolean } {
    const { data, isLoading } = useSWR<FxCurrentResp>(
        'fx-current',
        () => analyticsApi.getFxCurrent(),
        {
            refreshInterval: 60 * 60 * 1000,  // 1 hour — NBK обновляется раз в день, чаще не нужно
            revalidateOnFocus: false,
            dedupingInterval: 5 * 60 * 1000,
        },
    );

    if (!data || data.error || !data.rate) {
        return { data: null, isLoading };
    }

    return {
        data: {
            rate: data.rate,
            delta: data.delta_1d_pct,
            delta7d: data.delta_7d_pct,
            delta30d: data.delta_30d_pct,
            eurKzt: data.eur_kzt,
            updatedAt: new Date(data.rate_date),
        },
        isLoading: false,
    };
}
