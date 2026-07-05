// components/layout/Topbar.tsx — sticky top bar with brand, nav, live ticker and tweaks
import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { useRouter } from 'next/router';
import useSWR from 'swr';
import { analyticsApi, authApi } from '@/lib/api';
import { fmt } from '@/lib/format';
import { useUsdKzt } from '@/hooks/useUsdKzt';
import { useTheme } from '@/hooks/useTheme';
import Tweaks from './Tweaks';
import SearchPalette from './SearchPalette';

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
    const [theme, setTheme] = useTheme();
    const toggleTheme = () => setTheme(theme === 'dark' ? 'light' : 'dark');
    const [searchOpen, setSearchOpen] = useState(false);
    const [userMenuOpen, setUserMenuOpen] = useState(false);

    // Auth: токен читаем после mount (SSR/static HTML его не знает)
    const [token, setToken] = useState<string | null>(null);
    useEffect(() => {
        setToken(localStorage.getItem('access_token'));
    }, []);
    const { data: me } = useSWR(
        token ? ['auth-me', token] : null,
        () => authApi.me(),
        { revalidateOnFocus: false, shouldRetryOnError: false }
    );

    const logout = () => {
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        setToken(null);
        setUserMenuOpen(false);
    };

    // Глобальный хоткей ⌘K / Ctrl+K → поиск
    useEffect(() => {
        const onKey = (e: KeyboardEvent) => {
            if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
                e.preventDefault();
                setSearchOpen(v => !v);
            }
        };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, []);

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

                <button
                    className="topbar-btn"
                    type="button"
                    aria-label="Поиск по маркам и моделям"
                    onClick={() => setSearchOpen(true)}
                >
                    <span>⌕</span>
                    <span>Поиск</span>
                    <span className="kbd">⌘K</span>
                </button>

                {/* Тема: ☾ в тёмной (клик → светлая), ☀ в светлой (клик → тёмная).
                    useTheme до mount отдаёт 'dark' — иконка совпадает с SSG-HTML,
                    hydration mismatch нет. */}
                <button
                    className="topbar-btn"
                    type="button"
                    onClick={toggleTheme}
                    aria-label={theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему'}
                    title="Переключить тему"
                >
                    <span aria-hidden>{theme === 'dark' ? '☾' : '☀'}</span>
                </button>

                {token ? (
                    <button
                        className="topbar-btn"
                        type="button"
                        onClick={() => setUserMenuOpen(v => !v)}
                        aria-expanded={userMenuOpen}
                        aria-label="Меню пользователя"
                        title={me?.email ?? 'Профиль'}
                    >
                        <span>👤</span>
                        <span>{me?.email ? me.email.split('@')[0] : 'Профиль'}</span>
                    </button>
                ) : (
                    <Link href="/auth/login" className="topbar-btn" aria-label="Войти">
                        <span>Войти</span>
                    </Link>
                )}

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

                    {/* Переключатель темы в мобильном меню — .topbar-btn на <640 скрыт */}
                    <button
                        className="mobile-theme-btn"
                        type="button"
                        onClick={toggleTheme}
                        aria-label={theme === 'dark' ? 'Включить светлую тему' : 'Включить тёмную тему'}
                    >
                        <span aria-hidden>{theme === 'dark' ? '☾' : '☀'}</span>
                        <span>Тема: {theme === 'dark' ? 'тёмная' : 'светлая'}</span>
                    </button>
                </div>
            )}

            {userMenuOpen && token && (
                <div className="user-menu" role="menu">
                    <div className="user-menu-email">{me?.email ?? '…'}</div>
                    <div className="user-menu-plan">
                        {me?.subscription?.display_name ?? 'Бесплатный план'}
                    </div>
                    <button type="button" className="user-menu-btn" onClick={logout}>
                        Выйти
                    </button>
                </div>
            )}

            <SearchPalette open={searchOpen} onClose={() => setSearchOpen(false)} />
            <Tweaks open={tweaksOpen} onClose={() => setTweaksOpen(false)} />
        </>
    );
}
