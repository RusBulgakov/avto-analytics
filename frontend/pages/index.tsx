// pages/index.tsx — Главный дашборд
import { useState } from 'react';
import useSWR from 'swr';
import Head from 'next/head';
import Header from '@/components/layout/Header';
import PriceChart from '@/components/charts/PriceChart';
import BoxPlot from '@/components/charts/BoxPlot';
import FilterPanel from '@/components/filters/FilterPanel';
import { analyticsApi } from '@/lib/api';
import styles from './index.module.css';

function StatCard({ label, value, sub, trend }: any) {
    return (
        <div className="card">
            <div className={styles.statLabel}>{label}</div>
            <div className={styles.statValue}>{value}</div>
            {sub && <div className={styles.statSub}>{sub}</div>}
            {trend !== undefined && (
                <span className={`badge ${trend >= 0 ? 'badge-green' : 'badge-red'}`}>
                    {trend >= 0 ? '▲' : '▼'} {Math.abs(trend)}%
                </span>
            )}
        </div>
    );
}

export default function Dashboard() {
    const [filters, setFilters] = useState<Record<string, any>>({ period_days: 90 });

    const { data: overview, isLoading: overviewLoading } = useSWR(
        ['market-overview', filters],
        () => analyticsApi.getMarketOverview(filters),
        { keepPreviousData: true }
    );
    const { data: summary, isLoading: summaryLoading } = useSWR(
        ['summary', filters],
        () => analyticsApi.getSummary(filters),
        { keepPreviousData: true }
    );
    const { data: priceHistory, isLoading: chartLoading } = useSWR(
        ['price-history', filters],
        () => analyticsApi.getPriceHistory(filters),
        { keepPreviousData: true }
    );

    const selectedBrandId = filters.brand_id?.length === 1 ? filters.brand_id[0] : null;
    const boxplotParams = {
        city: filters.city,
        source: filters.source,
        year: filters.year,
        ...(selectedBrandId ? { brand_id: selectedBrandId } : {}),
    };
    const { data: boxplotData, isLoading: boxplotLoading } = useSWR(
        ['price-boxplot', boxplotParams],
        () => analyticsApi.getPriceBoxplot(boxplotParams),
        { keepPreviousData: true }
    );

    const totalListings = summary?.active_listings ?? 0;
    const avgPrice = summary?.avg_price_kzt ?? null;

    const formatPrice = (n: number) =>
        n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)} млн ₸` : `${(n / 1_000).toFixed(0)} тыс ₸`;

    return (
        <>
            <Head>
                <title>Авто Аналитика Казахстана — Дашборд</title>
                <meta name="description" content="Аналитика авторынка Казахстана. Графики цен, рентабельность, статистика по маркам." />
                <meta name="viewport" content="width=device-width, initial-scale=1" />
            </Head>

            <div className={styles.page}>
                <Header />

                <main className="container">

                    {/* Hero */}
                    <section className={styles.hero}>
                        <h1 className={styles.heroTitle}>Авторынок Казахстана</h1>
                        <p className={styles.heroSub}>
                            Ежедневная аналитика цен с kolesa.kz, OLX, avtorynok и других площадок
                        </p>
                    </section>

                    {/* Stats row */}
                    <div className="grid-stats" style={{ marginBottom: 24 }}>
                        <StatCard
                            label="Активных объявлений"
                            value={summaryLoading ? '...' : totalListings.toLocaleString('ru-RU')}
                            sub="обновлено сегодня"
                        />
                        <StatCard
                            label="Ср. цена по рынку"
                            value={avgPrice ? formatPrice(avgPrice) : '...'}
                        />
                        <StatCard
                            label="Источников"
                            value={summaryLoading ? '...' : summary?.sources?.length ?? 0}
                            sub={summary?.sources ? summary.sources.slice(0, 3).map((s: any) => s.name).join(', ') : '...'}
                        />
                        <StatCard
                            label={filters.brand_id && filters.brand_id.length === 1 ? 'Моделей (в базе)' : 'Марок (в базе)'}
                            value={summaryLoading ? '...' : summary?.total_brands ?? '...'}
                        />
                    </div>

                    {/* Main content: Filters + Chart */}
                    <div className="grid-main">
                        {/* Left Column: Filters + Sources */}
                        <div>
                            <FilterPanel onChange={setFilters} />

                            <div className="card" style={{ marginTop: 20 }}>
                                <div style={{ fontSize: 13, fontWeight: 700, textTransform: 'uppercase', color: 'var(--color-text-muted)', marginBottom: 16 }}>
                                    Аналитика по площадкам
                                </div>
                                {summaryLoading ? (
                                    <div className="skeleton" style={{ height: 120 }} />
                                ) : (
                                    <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                                        {(summary?.sources || []).map((s: any) => {
                                            const max = summary?.active_listings || 1;
                                            const pct = Math.round((s.count / max) * 100);
                                            return (
                                                <div key={s.name}>
                                                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 13, marginBottom: 6 }}>
                                                        <span style={{ textTransform: 'capitalize', fontWeight: 500 }}>{s.name}</span>
                                                        <span style={{ color: 'var(--color-text-muted)' }}>
                                                            {s.count.toLocaleString('ru-RU')} <span style={{ fontSize: 11 }}>({pct}%)</span>
                                                        </span>
                                                    </div>
                                                    <div style={{ height: 6, background: 'var(--color-surface-2)', borderRadius: 3, overflow: 'hidden' }}>
                                                        <div style={{ height: '100%', width: `${pct}%`, background: 'var(--color-primary)', borderRadius: 3, transition: 'width 0.4s ease-out' }} />
                                                    </div>
                                                </div>
                                            )
                                        })}
                                        {summary?.sources?.length === 0 && (
                                            <div style={{ fontSize: 13, color: 'var(--color-text-muted)', textAlign: 'center', padding: '10px 0' }}>
                                                Нет данных
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        </div>

                        {/* Chart + Top brands */}
                        <div className={styles.rightCol}>
                            <div className="card" style={{ marginBottom: 20 }}>
                                <div className={styles.chartHeader}>
                                    <div>
                                        <h2 className={styles.chartTitle}>Динамика цен</h2>
                                        <p className={styles.chartSub}>Средняя и медианная цена за период</p>
                                    </div>
                                    <span className="badge badge-blue">PRO: прогноз</span>
                                </div>
                                <PriceChart data={priceHistory ?? []} loading={chartLoading} />
                            </div>

                            {/* Box plot — топ марок (без фильтра) или топ моделей (с маркой) */}
                            <div className="card" style={{ marginBottom: 20 }}>
                                <div className={styles.chartHeader}>
                                    <div>
                                        <h2 className={styles.chartTitle}>
                                            {selectedBrandId ? 'Распределение цен по моделям' : 'Распределение цен по маркам'}
                                        </h2>
                                        <p className={styles.chartSub}>
                                            {selectedBrandId ? 'Топ-10 моделей · медиана, квартили, разброс' : 'Топ-10 марок · медиана, квартили, разброс'}
                                        </p>
                                    </div>
                                </div>
                                <BoxPlot data={boxplotData ?? []} loading={boxplotLoading} />
                            </div>

                            {/* Top brands/models table */}
                            <div className="card">
                                <h2 className={styles.chartTitle} style={{ marginBottom: 16 }}>
                                    {filters.brand_id ? 'Топ моделей по объявлениям' : 'Топ марок по объявлениям'}
                                </h2>
                                {overviewLoading ? (
                                    <div className="skeleton" style={{ height: 200 }} />
                                ) : (
                                    <div className={styles.tableWrap}>
                                        <table className={styles.table}>
                                            <thead>
                                                <tr>
                                                    <th>{filters.brand_id ? 'Модель' : 'Марка'}</th>
                                                    <th>Объявлений</th>
                                                    <th>Ср. цена</th>
                                                    <th>Мин / Макс</th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {(overview ?? []).slice(0, 10).map((b: any) => (
                                                    <tr key={b.brand} id={`brand-row-${b.brand.toLowerCase()}`}>
                                                        <td><strong>{b.brand}</strong></td>
                                                        <td>{b.active_listings.toLocaleString('ru-RU')}</td>
                                                        <td>{formatPrice(b.avg_price_kzt)}</td>
                                                        <td style={{ color: '#7b8899', fontSize: 12 }}>
                                                            {formatPrice(b.min_price_kzt)} — {formatPrice(b.max_price_kzt)}
                                                        </td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                )}
                            </div>
                        </div>
                    </div>
                </main>
            </div>
        </>
    );
}
