// components/layout/Topbar.tsx — sticky top bar with brand, nav, live ticker and tweaks
import React, { useEffect, useState } from 'react';
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
    { href: '/articles', label: 'Статьи', match: (p: string) => p.startsWith('/articles') },
];

export default function Topbar() {
    const router = useRouter();
    const [tweaksOpen, setTweaksOpen] = useState(false);
    const [mobileNavOpen, setMobileNavOpen] = useState(false);

    // Закрываем mobile-меню при смене страницы
    useEffect(() => {
        const close = () => setMobileNavOpen(false);
        router.events.on('routeChangeStart', close);
        return () => router.events.off('routeChangeStart', close);
    }, [router.events]);

    // Блокируем body-scroll когда menu open (UX best practice)
    useEffect(() => {
        if (mobileNavOpen) {
            document.body.style.overflow = 'hidden';
        } else {
            document.body.style.overflow = '';
        }
        return () => {
            document.body.style.overflow = '';
        };
    }, [mobileNavOpen]);

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

                    {fx && (() => {
                        // Primary delta: prefer 1d если оно ≠ 0, иначе 7d (weekend
                        // часто даёт 1d=0 потому что NBK не публикует по сб/вс).
                        const primary = (fx.delta != null && Math.abs(fx.delta) >= 0.01)
                            ? { value: fx.delta, label: '1д' }
                            : (fx.delta7d != null
                                ? { value: fx.delta7d, label: '7д' }
                                : null);
                        const tooltip = [
                            fx.delta != null ? `1 день: ${fx.delta >= 0 ? '+' : ''}${fx.delta.toFixed(2)}%` : null,
                            fx.delta7d != null ? `7 дней: ${fx.delta7d >= 0 ? '+' : ''}${fx.delta7d.toFixed(2)}%` : null,
                            fx.delta30d != null ? `30 дней: ${fx.delta30d >= 0 ? '+' : ''}${fx.delta30d.toFixed(2)}%` : null,
                            `Курс NBK на ${fx.updatedAt.toLocaleDateString('ru-RU')}`,
                        ].filter(Boolean).join('\n');
                        return (
                            <span className="ticker-item" title={tooltip}>
                                <span className="ticker-label">USD/KZT</span>
                                <span className="mono tnum">{fx.rate.toFixed(2)}</span>
                                {primary && (
                                    <span className={`mono ${primary.value >= 0 ? 'up' : 'down'}`}>
                                        {primary.value >= 0 ? '▲' : '▼'}{' '}
                                        {Math.abs(primary.value).toFixed(2)}%
                                        <span style={{ color: 'var(--text-muted)', marginLeft: 4, fontSize: 9 }}>
                                            {primary.label}
                                        </span>
                                    </span>
                                )}
                            </span>
                        );
                    })()}
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

                {/* Mobile burger — visible only at <640. Same target as nav links. */}
                <button
                    className="topbar-burger"
                    type="button"
                    onClick={() => setMobileNavOpen(v => !v)}
                    aria-label="Меню"
                    aria-expanded={mobileNavOpen}
                >
                    {mobileNavOpen ? '✕' : '☰'}
                </button>
            </header>

            {/* Mobile nav overlay */}
            {mobileNavOpen && (
                <div
                    className="mobile-nav-overlay"
                    onClick={(e) => {
                        if (e.target === e.currentTarget) setMobileNavOpen(false);
                    }}
                >
                    <nav className="mobile-nav" aria-label="Разделы">
                        {NAV.map(item => (
                            <Link
                                key={item.href}
                                href={item.href}
                                className={item.match(router.pathname) ? 'active' : ''}
                                onClick={() => setMobileNavOpen(false)}
                            >
                                {item.label}
                            </Link>
                        ))}
                    </nav>
                </div>
            )}

            <Tweaks open={tweaksOpen} onClose={() => setTweaksOpen(false)} />
        </>
    );
}
