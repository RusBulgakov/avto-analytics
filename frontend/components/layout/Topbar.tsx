// components/layout/Topbar.tsx — sticky top bar with brand, nav, live ticker and tweaks
import React, { useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import useSWR from 'swr';
import { analyticsApi } from '@/lib/api';
import { fmt } from '@/lib/format';
import { useUsdKzt } from '@/hooks/useUsdKzt';
import Tweaks from './Tweaks';

interface SummaryResponse {
    active_listings?: number;
    total_brands?: number;
    avg_price_kzt?: number;
}

const NAV = [
    { href: '/', label: 'Дашборд', match: (p: string) => p === '/' },
    { href: '/brands', label: 'Марки', match: (p: string) => p.startsWith('/brand') || p.startsWith('/model') },
    { href: '/profitability', label: 'Рентабельность', match: (p: string) => p.startsWith('/profit') },
    { href: '/forecast', label: 'Прогноз', match: (p: string) => p.startsWith('/forecast') },
];

export default function Topbar() {
    const router = useRouter();
    const [tweaksOpen, setTweaksOpen] = useState(false);

    // Live ticker: total active listings — polls every 30s
    const { data: summary } = useSWR<SummaryResponse>(
        'summary-ticker',
        () => analyticsApi.getSummary(),
        { refreshInterval: 30_000, revalidateOnFocus: false }
    );

    const { data: fx } = useUsdKzt();

    const total = summary?.active_listings;
    const avgPrice = summary?.avg_price_kzt;

    // TEMP: index = avg price (млн) normalized. Replace with /analytics/price-index endpoint.
    const indexValue = avgPrice ? avgPrice / 1_000_000 : null;

    return (
        <>
            <header className="topbar">
                <Link href="/" className="brand">
                    <span className="brand-dot" />
                    <span>
                        <div>Авто Аналитика</div>
                        <div className="brand-meta">KZ · V1</div>
                    </span>
                </Link>

                <nav className="nav" aria-label="Разделы">
                    {NAV.map(item => (
                        <Link
                            key={item.href}
                            href={item.href}
                            className={item.match(router.pathname) ? 'active' : ''}
                        >
                            {item.label}
                        </Link>
                    ))}
                </nav>

                <div className="topbar-spacer" />

                <div className="ticker" aria-label="Live статистика">
                    <span className="ticker-item">
                        <span className="live-dot" aria-hidden />
                        <span className="ticker-label">LIVE</span>
                        <span className="mono tnum">
                            {total != null ? fmt.int(total) : '—'}
                        </span>
                        <span className="ticker-label">объявл.</span>
                    </span>

                    {indexValue != null && (
                        <span className="ticker-item">
                            <span className="ticker-label">INDEX</span>
                            <span className="mono tnum">{indexValue.toFixed(2)}</span>
                            <span className="ticker-label">млн ₸ ср.</span>
                        </span>
                    )}

                    {fx && (
                        <span className="ticker-item">
                            <span className="ticker-label">USD/KZT</span>
                            <span className="mono tnum">{fx.rate.toFixed(2)}</span>
                            {fx.delta != null && (
                                <span className={`mono ${fx.delta >= 0 ? 'up' : 'down'}`}>
                                    {fx.delta >= 0 ? '▲' : '▼'} {Math.abs(fx.delta).toFixed(2)}%
                                </span>
                            )}
                        </span>
                    )}
                </div>

                <button className="topbar-btn" type="button" aria-label="Поиск (не реализовано)">
                    <span>⌕</span>
                    <span>Поиск</span>
                    <span className="kbd">⌘K</span>
                </button>

                <button
                    className="topbar-btn"
                    type="button"
                    onClick={() => setTweaksOpen(v => !v)}
                    aria-label="Настройки"
                    aria-expanded={tweaksOpen}
                >
                    <span>⚙</span>
                </button>
            </header>

            <Tweaks open={tweaksOpen} onClose={() => setTweaksOpen(false)} />
        </>
    );
}
