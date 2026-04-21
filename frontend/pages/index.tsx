// pages/index.tsx — Dashboard (trading terminal redesign, steps 1–3)
import { useState } from 'react';
import Head from 'next/head';
import useSWR from 'swr';

import Topbar from '@/components/layout/Topbar';
import FilterBar from '@/components/layout/FilterBar';
import KPI from '@/components/ui/KPI';
import Badge from '@/components/ui/Badge';
import PriceChart from '@/components/charts/PriceChart';
import BoxPlot from '@/components/charts/BoxPlot';

import { analyticsApi } from '@/lib/api';
import { fmt } from '@/lib/format';
import { useUsdKzt } from '@/hooks/useUsdKzt';
import { emptyFilters, type FilterState, type SummaryResponse, type BrandOverview } from '@/types/analytics';

function buildApiFilters(filters: FilterState) {
    const params: Record<string, unknown> = {
        period_days: filters.period === 'all' ? undefined : filters.period,
    };
    if (filters.brand_id.length) params.brand_id = filters.brand_id;
    if (filters.model_id.length) params.model_id = filters.model_id;
    if (filters.city.length) params.city = filters.city;
    if (filters.source.length) params.source = filters.source;
    return params;
}

export default function Dashboard() {
    const [filters, setFilters] = useState<FilterState>(emptyFilters);
    const apiParams = buildApiFilters(filters);

    const { data: summary, isLoading: summaryLoading } = useSWR<SummaryResponse>(
        ['summary', apiParams],
        () => analyticsApi.getSummary(apiParams),
        { keepPreviousData: true, refreshInterval: 60_000 }
    );

    const { data: priceHistory, isLoading: chartLoading } = useSWR(
        ['price-history', apiParams],
        () => analyticsApi.getPriceHistory(apiParams),
        { keepPreviousData: true }
    );

    const { data: overview, isLoading: overviewLoading } = useSWR<BrandOverview[]>(
        ['market-overview', apiParams],
        () => analyticsApi.getMarketOverview(apiParams),
        { keepPreviousData: true }
    );

    const selectedBrandId = filters.brand_id.length === 1 ? filters.brand_id[0] : null;
    const boxplotParams = {
        city: filters.city.length ? filters.city : undefined,
        source: filters.source.length ? filters.source : undefined,
        ...(selectedBrandId ? { brand_id: selectedBrandId } : {}),
    };
    const { data: boxplotData, isLoading: boxplotLoading } = useSWR(
        ['price-boxplot', boxplotParams],
        () => analyticsApi.getPriceBoxplot(boxplotParams),
        { keepPreviousData: true }
    );

    const { data: fx } = useUsdKzt();

    const totalListings = summary?.active_listings;
    const totalBrands = summary?.total_brands;
    const avgPrice = summary?.avg_price_kzt;
    // Placeholder "index" = avg price in млн ₸ (reuse until /analytics/price-index endpoint lands)
    const indexValue = avgPrice ? (avgPrice / 1_000_000) : null;

    return (
        <>
            <Head>
                <title>Авто Аналитика KZ — Торговый терминал</title>
                <meta name="description" content="Аналитика авторынка Казахстана. Индекс цен, рентабельность, live-лента объявлений." />
                <meta name="viewport" content="width=device-width, initial-scale=1" />
            </Head>

            <div className="app">
                <Topbar />
                <FilterBar filters={filters} onChange={setFilters} />

                <main className="main">
                    {/* ── KPI row ─────────────────────────────────────── */}
                    <section className="kpi-grid" aria-label="Ключевые показатели">
                        <KPI
                            label="Индекс цен AA·IDX"
                            value={
                                summaryLoading && indexValue == null
                                    ? '…'
                                    : indexValue != null
                                        ? indexValue.toFixed(2)
                                        : '—'
                            }
                            unit="млн ₸"
                            foot={<span>средняя по активным объявлениям</span>}
                        />
                        <KPI
                            label="Активные объявления"
                            value={
                                summaryLoading && totalListings == null
                                    ? '…'
                                    : totalListings != null
                                        ? fmt.int(totalListings)
                                        : '—'
                            }
                            foot={
                                summary?.sources?.length
                                    ? <span>с {summary.sources.length} площадок</span>
                                    : null
                            }
                        />
                        <KPI
                            label="Марок в базе"
                            value={
                                summaryLoading && totalBrands == null
                                    ? '…'
                                    : totalBrands != null
                                        ? fmt.int(totalBrands)
                                        : '—'
                            }
                            foot={<span>{selectedBrandId ? 'выбрана 1 марка' : 'всего уникальных'}</span>}
                        />
                        <KPI
                            label="USD / KZT"
                            value={fx ? fx.rate.toFixed(2) : '…'}
                            delta={fx?.delta ?? null}
                            deltaCaption="за 24 ч"
                            foot={
                                fx
                                    ? <span>обновлено {fx.updatedAt.toLocaleDateString('ru-RU')}</span>
                                    : <span>open.er-api.com</span>
                            }
                        />
                    </section>

                    {/* ── Main chart + Sources ────────────────────────── */}
                    <section className="grid-2-1">
                        <div className="card">
                            <div className="card-h">
                                <div>
                                    <div className="card-title">Динамика цен</div>
                                    <div className="card-sub">
                                        Средняя и медиана · период {filters.period === 'all' ? 'весь' : `${filters.period}д`}
                                    </div>
                                </div>
                                <Badge variant="info">PRO: прогноз</Badge>
                            </div>
                            <div className="card-b">
                                <PriceChart data={priceHistory ?? []} loading={chartLoading} />
                            </div>
                        </div>

                        <div className="card">
                            <div className="card-h">
                                <div>
                                    <div className="card-title">Источники данных</div>
                                    <div className="card-sub">доля активных объявлений</div>
                                </div>
                            </div>
                            <div className="card-b">
                                {summaryLoading && !summary ? (
                                    <div className="skeleton" style={{ height: 120 }} />
                                ) : summary?.sources?.length ? (
                                    <div>
                                        {summary.sources.map(s => {
                                            const pct = summary.active_listings
                                                ? Math.round((s.count / summary.active_listings) * 100)
                                                : 0;
                                            return (
                                                <div className="src-row" key={s.name}>
                                                    <div className="src-name">{s.name}</div>
                                                    <div className="src-count">
                                                        {fmt.int(s.count)} <span className="dim">· {pct}%</span>
                                                    </div>
                                                    <div className="src-bar">
                                                        <div className="src-bar-fill" style={{ width: `${pct}%` }} />
                                                    </div>
                                                </div>
                                            );
                                        })}
                                    </div>
                                ) : (
                                    <div style={{ color: 'var(--text-muted)', padding: 12 }}>Нет данных</div>
                                )}
                            </div>
                        </div>
                    </section>

                    {/* ── Boxplot ─────────────────────────────────────── */}
                    <section className="card">
                        <div className="card-h">
                            <div>
                                <div className="card-title">
                                    {selectedBrandId ? 'Распределение цен по моделям' : 'Распределение цен по маркам'}
                                </div>
                                <div className="card-sub">
                                    {selectedBrandId ? 'Топ-10 моделей · медиана, квартили, разброс' : 'Топ-10 марок · медиана, квартили, разброс'}
                                </div>
                            </div>
                        </div>
                        <div className="card-b">
                            <BoxPlot data={boxplotData ?? []} loading={boxplotLoading} />
                        </div>
                    </section>

                    {/* ── Top table ───────────────────────────────────── */}
                    <section className="card">
                        <div className="card-h">
                            <div>
                                <div className="card-title">
                                    {selectedBrandId ? 'Топ моделей по объявлениям' : 'Топ марок по объявлениям'}
                                </div>
                                <div className="card-sub">отсортировано по количеству активных объявлений</div>
                            </div>
                        </div>
                        <div className="card-b flush">
                            {overviewLoading && !overview ? (
                                <div className="skeleton" style={{ height: 200, margin: 16 }} />
                            ) : (
                                <table className="tbl">
                                    <thead>
                                        <tr>
                                            <th style={{ width: 44 }}>#</th>
                                            <th>{selectedBrandId ? 'Модель' : 'Марка'}</th>
                                            <th className="right">Активных</th>
                                            <th className="right">Ср. цена</th>
                                            <th className="right">Мин — Макс</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {(overview ?? []).slice(0, 10).map((b, i) => (
                                            <tr key={b.brand}>
                                                <td><span className="rank">{i + 1}</span></td>
                                                <td><strong>{b.brand}</strong></td>
                                                <td className="num">{fmt.int(b.active_listings)}</td>
                                                <td className="num">{fmt.price(b.avg_price_kzt)}</td>
                                                <td className="num dim">
                                                    {fmt.price(b.min_price_kzt)} — {fmt.price(b.max_price_kzt)}
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            )}
                        </div>
                    </section>
                </main>
            </div>
        </>
    );
}
