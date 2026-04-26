// pages/profitability.tsx — рейтинг моделей по потенциалу маржи перепродажи
import { useState } from 'react';
import Head from 'next/head';
import useSWR from 'swr';

import Topbar from '@/components/layout/Topbar';
import Badge from '@/components/ui/Badge';
import { analyticsApi } from '@/lib/api';
import { fmt } from '@/lib/format';

interface ProfitRow {
    brand: string;
    model: string;
    year: number | null;
    volume: number;
    buy_price: number | null;
    sell_price: number | null;
    high_price: number | null;
    margin_pct: number | null;
    median_days_to_sell: number | null;
    risk: 'low' | 'medium' | 'high';
}

const MIN_VOLUME_OPTIONS = [10, 20, 40, 80];
const LIMIT_OPTIONS = [20, 50, 100];
const CURRENT_YEAR = new Date().getFullYear();
const YEAR_OPTIONS = Array.from({ length: CURRENT_YEAR - 1999 }, (_, i) => CURRENT_YEAR - i); // 2026..2000

function riskBadge(risk: 'low' | 'medium' | 'high') {
    if (risk === 'low') return <Badge variant="up">низкий</Badge>;
    if (risk === 'medium') return <Badge variant="accent">средний</Badge>;
    return <Badge variant="down">высокий</Badge>;
}

export default function ProfitabilityPage() {
    const [minVol, setMinVol] = useState(20);
    const [limit, setLimit] = useState(50);
    const [yearFrom, setYearFrom] = useState<number | null>(null);
    const [yearTo, setYearTo] = useState<number | null>(null);
    // Default false → не показываем аварийные / не на ходу / не растаможенные.
    // Пользователь может выбрать "Все" если хочет видеть raw-распределение.
    const [includeJunk, setIncludeJunk] = useState(false);

    const { data, isLoading } = useSWR<ProfitRow[]>(
        ['profit-ranking', minVol, limit, yearFrom, yearTo, includeJunk],
        () => analyticsApi.getProfitRanking({
            min_volume: minVol,
            limit,
            ...(yearFrom && { year_from: yearFrom }),
            ...(yearTo   && { year_to:   yearTo   }),
            ...(includeJunk ? { include_junk: true } : {}),
        }),
        { keepPreviousData: true }
    );

    return (
        <>
            <Head>
                <title>Рентабельность — Авто Аналитика KZ</title>
            </Head>

            <div className="app">
                <Topbar />

                <main className="main">
                    <div
                        style={{
                            display: 'flex',
                            alignItems: 'flex-end',
                            justifyContent: 'space-between',
                            flexWrap: 'wrap',
                            gap: 16,
                        }}
                    >
                        <div>
                            <div className="page-title">Рейтинг рентабельности</div>
                            <div className="page-sub">
                                Оценка маржи = медиана − нижний квартиль цен по модели. Риск учитывает объём выборки.
                                {!includeJunk && (
                                    <>
                                        {' · '}
                                        <span style={{ color: 'var(--up)' }}>
                                            ★ исключены аварийные / не на ходу / не растаможенные / на запчасти + price-outliers
                                        </span>
                                    </>
                                )}
                            </div>
                            <div style={{ marginTop: 8, display: 'flex', gap: 8, alignItems: 'center' }}>
                                <span
                                    className="uppercase"
                                    style={{ fontSize: 11, color: 'var(--text-muted)' }}
                                >
                                    выборка
                                </span>
                                <div className="period-group" role="group" aria-label="Junk-фильтр">
                                    <button
                                        type="button"
                                        className={`period-btn ${!includeJunk ? 'active' : ''}`}
                                        onClick={() => setIncludeJunk(false)}
                                        title="Только товарные: без битых/не на ходу/не растаможенных + outliers ниже 50% медианы"
                                    >
                                        Товарные
                                    </button>
                                    <button
                                        type="button"
                                        className={`period-btn ${includeJunk ? 'active' : ''}`}
                                        onClick={() => setIncludeJunk(true)}
                                        title="Без фильтра — raw данные включая аварийные, не на ходу, не растаможенные"
                                    >
                                        Все
                                    </button>
                                </div>
                            </div>
                        </div>

                        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                            {/* Год от */}
                            <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                                <span className="uppercase">год от</span>
                                <select
                                    value={yearFrom ?? ''}
                                    onChange={e => setYearFrom(e.target.value ? Number(e.target.value) : null)}
                                    style={{ fontSize: 13, padding: '4px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text)', cursor: 'pointer' }}
                                >
                                    <option value="">любой</option>
                                    {YEAR_OPTIONS.map(y => <option key={y} value={y}>{y}</option>)}
                                </select>
                            </label>
                            {/* Год до */}
                            <label style={{ display: 'flex', flexDirection: 'column', gap: 4, fontSize: 11, color: 'var(--text-muted)' }}>
                                <span className="uppercase">год до</span>
                                <select
                                    value={yearTo ?? ''}
                                    onChange={e => setYearTo(e.target.value ? Number(e.target.value) : null)}
                                    style={{ fontSize: 13, padding: '4px 8px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-card)', color: 'var(--text)', cursor: 'pointer' }}
                                >
                                    <option value="">любой</option>
                                    {YEAR_OPTIONS.map(y => <option key={y} value={y}>{y}</option>)}
                                </select>
                            </label>
                            <label
                                style={{
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: 4,
                                    fontSize: 11,
                                    color: 'var(--text-muted)',
                                }}
                            >
                                <span className="uppercase">мин. объявлений</span>
                                <div className="period-group">
                                    {MIN_VOLUME_OPTIONS.map(v => (
                                        <button
                                            key={v}
                                            type="button"
                                            className={`period-btn ${minVol === v ? 'active' : ''}`}
                                            onClick={() => setMinVol(v)}
                                        >
                                            {v}
                                        </button>
                                    ))}
                                </div>
                            </label>
                            <label
                                style={{
                                    display: 'flex',
                                    flexDirection: 'column',
                                    gap: 4,
                                    fontSize: 11,
                                    color: 'var(--text-muted)',
                                }}
                            >
                                <span className="uppercase">показать</span>
                                <div className="period-group">
                                    {LIMIT_OPTIONS.map(v => (
                                        <button
                                            key={v}
                                            type="button"
                                            className={`period-btn ${limit === v ? 'active' : ''}`}
                                            onClick={() => setLimit(v)}
                                        >
                                            {v}
                                        </button>
                                    ))}
                                </div>
                            </label>
                        </div>
                    </div>

                    <section className="card">
                        <div className="card-b flush">
                            {isLoading && !data ? (
                                <div className="skeleton" style={{ height: 400, margin: 16 }} />
                            ) : data && data.length ? (
                                <table className="tbl">
                                    <thead>
                                        <tr>
                                            <th style={{ width: 44 }}>#</th>
                                            <th>Модель</th>
                                            <th className="right">Год</th>
                                            <th className="right">Покупка (p25)</th>
                                            <th className="right">Продажа (медиана)</th>
                                            <th className="right">Маржа</th>
                                            <th className="right">Дней</th>
                                            <th className="right">Объём</th>
                                            <th className="right">Риск</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {data.map((r, i) => (
                                            <tr key={`${r.brand}|${r.model}|${r.year}`}>
                                                <td>
                                                    <span className="rank">{i + 1}</span>
                                                </td>
                                                <td>
                                                    <strong>{r.brand}</strong>{' '}
                                                    <span className="dim">{r.model}</span>
                                                </td>
                                                <td className="num">
                                                    {r.year ?? '—'}
                                                </td>
                                                <td className="num">
                                                    {r.buy_price != null ? fmt.price(r.buy_price) : '—'}
                                                </td>
                                                <td className="num">
                                                    {r.sell_price != null ? fmt.price(r.sell_price) : '—'}
                                                </td>
                                                <td className="num">
                                                    {r.margin_pct != null ? (
                                                        <Badge variant={r.margin_pct >= 15 ? 'up' : r.margin_pct >= 5 ? 'accent' : 'neutral'}>
                                                            +{r.margin_pct.toFixed(1)}%
                                                        </Badge>
                                                    ) : (
                                                        '—'
                                                    )}
                                                </td>
                                                <td className="num">
                                                    {r.median_days_to_sell != null
                                                        ? `${r.median_days_to_sell.toFixed(0)}д`
                                                        : '—'}
                                                </td>
                                                <td className="num">{fmt.int(r.volume)}</td>
                                                <td className="right">{riskBadge(r.risk)}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            ) : (
                                <div style={{ padding: 24, color: 'var(--text-muted)' }}>
                                    Нет моделей с объёмом ≥ {minVol}
                                </div>
                            )}
                        </div>
                    </section>

                    <div
                        className="mono dim"
                        style={{ fontSize: 11, padding: '0 2px' }}
                    >
                        модель оценки упрощённая — без PRO сигналов (тренд цены, сезонность). При высоком разбросе цен
                        маржа может быть завышена. Объём ≥ {minVol} отсекает редкие модели.
                    </div>
                </main>
            </div>
        </>
    );
}
