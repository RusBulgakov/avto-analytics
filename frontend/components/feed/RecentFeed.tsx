// components/feed/RecentFeed.tsx — live stream of freshest listings
import React from 'react';
import { fmt } from '@/lib/format';

export interface RecentItem {
    id: string;
    brand: string | null;
    model: string | null;
    year: number | null;
    price_kzt: number | null;
    price_delta_kzt: number | null;
    mileage_km: number | null;
    city: string | null;
    source: string;
    listing_url: string;
    first_seen_at: string;
}

interface Props {
    data: RecentItem[];
    loading?: boolean;
}

function minutesAgo(iso: string): number {
    const then = new Date(iso).getTime();
    if (Number.isNaN(then)) return 0;
    return Math.max(0, Math.round((Date.now() - then) / 60_000));
}

export default function RecentFeed({ data, loading }: Props) {
    if (loading && data.length === 0) {
        return <div className="skeleton" style={{ height: 340 }} />;
    }

    if (!data.length) {
        return (
            <div style={{ padding: 14, color: 'var(--text-muted)', fontSize: 12 }}>
                Нет свежих объявлений
            </div>
        );
    }

    return (
        <div style={{ display: 'flex', flexDirection: 'column' }}>
            {data.map(item => {
                const title = [item.brand, item.model].filter(Boolean).join(' ') || 'Без названия';
                const delta = item.price_delta_kzt ?? 0;
                const deltaClass = delta > 0 ? 'up' : delta < 0 ? 'down' : '';
                const deltaSign = delta > 0 ? '▲' : delta < 0 ? '▼' : '·';
                const min = minutesAgo(item.first_seen_at);

                return (
                    <a
                        key={item.id}
                        href={item.listing_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="recent-row"
                        title={`${title} ${item.year ?? ''} · ${item.city ?? ''}`}
                    >
                        <div className="recent-main">
                            <div className="recent-title">
                                <strong>{title}</strong>
                                {item.year ? <span className="dim"> · {item.year}</span> : null}
                            </div>
                            <div className="recent-meta mono">
                                {item.city ?? '—'}
                                {item.mileage_km != null ? ` · ${Math.round(item.mileage_km / 1000)} тыс.км` : ''}
                                {' · '}
                                <span style={{ textTransform: 'capitalize' }}>{item.source}</span>
                            </div>
                        </div>
                        <div className="recent-right">
                            <div className="mono tnum recent-price">
                                {item.price_kzt != null ? fmt.price(item.price_kzt) + ' ₸' : '—'}
                            </div>
                            <div className={`mono recent-delta ${deltaClass}`}>
                                <span>{deltaSign}</span>
                                {delta !== 0 ? fmt.price(Math.abs(delta)) : '—'}
                            </div>
                            <div className="mono dim recent-age">{fmt.relMin(min)}</div>
                        </div>
                    </a>
                );
            })}
        </div>
    );
}
