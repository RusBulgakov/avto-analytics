// components/charts/KZMap.tsx — Kazakhstan geo map with city pins (size = listings volume)
import React, { useState } from 'react';
import { useRouter } from 'next/router';
import { fmt } from '@/lib/format';

export interface GeoCity {
    slug: string;
    name: string;
    x: number;              // percent 0..100 in the viewBox
    y: number;              // percent 0..100 in the viewBox
    listings: number;
    avg_price_kzt: number | null;
}

interface Props {
    data: GeoCity[];
    loading?: boolean;
}

// Pin size range (px). Min shown when listings === 0, max for the dataset's largest city.
const MIN_SIZE = 5;
const MAX_SIZE = 22;
// Listing threshold above which a city's label stays visible without hover (keeps the map readable).
const ALWAYS_LABEL_THRESHOLD = 30_000;

export default function KZMap({ data, loading }: Props) {
    const router = useRouter();
    const [hover, setHover] = useState<number | null>(null);

    if (loading) {
        return (
            <div>
                <div className="map-wrap">
                    <div className="skeleton" style={{ width: '100%', height: '100%' }} />
                </div>
            </div>
        );
    }

    if (!data || data.length === 0) {
        return (
            <div>
                <div
                    className="map-wrap"
                    style={{
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        color: 'var(--text-muted)',
                        fontSize: 12,
                    }}
                >
                    нет данных
                </div>
            </div>
        );
    }

    const maxListings = Math.max(1, ...data.map(c => c.listings));
    const totalListings = data.reduce((s, c) => s + c.listings, 0);

    return (
        <div>
            <div className="map-wrap">
                <svg className="map-svg" viewBox="0 0 100 50" preserveAspectRatio="none">
                    {/* Simplified KZ silhouette (from design handoff) */}
                    <path
                        className="map-region"
                        d="M 5,22 L 9,18 L 14,16 L 18,13 L 24,11 L 30,9 L 38,8 L 46,7 L 54,7 L 62,8 L 68,10 L 74,12 L 80,14 L 86,17 L 90,20 L 93,24 L 95,28 L 94,32 L 92,35 L 88,37 L 84,39 L 80,41 L 74,42 L 68,43 L 62,44 L 56,44 L 50,45 L 44,45 L 38,44 L 32,43 L 26,42 L 20,41 L 14,39 L 10,37 L 7,34 L 5,30 L 4,26 Z"
                    />
                    {/* Caspian notch */}
                    <path fill="var(--bg-2)" d="M 0,28 L 8,26 L 12,32 L 10,40 L 5,44 L 0,44 Z" />
                    {/* Balkhash lake hint */}
                    <ellipse cx="68" cy="34" rx="8" ry="2" fill="var(--bg)" opacity="0.6" />
                </svg>

                {data.map((c, i) => {
                    const ratio = c.listings / maxListings;
                    const size = MIN_SIZE + ratio * (MAX_SIZE - MIN_SIZE);
                    const isHover = hover === i;
                    const showLabel = isHover || c.listings >= ALWAYS_LABEL_THRESHOLD;
                    return (
                        <div
                            key={c.slug}
                            className="city-pin"
                            style={{ left: `${c.x}%`, top: `${c.y}%` }}
                            onMouseEnter={() => setHover(i)}
                            onMouseLeave={() => setHover(null)}
                            onClick={() => router.push(`/?city=${encodeURIComponent(c.slug)}`)}
                            title={`${c.name} · ${fmt.int(c.listings)} объявл.`}
                        >
                            <div
                                className="city-dot"
                                style={{
                                    width: size,
                                    height: size,
                                    opacity: isHover ? 1 : 0.85,
                                }}
                            />
                            {showLabel && (
                                <>
                                    <div className="city-label">{c.name}</div>
                                    {isHover && (
                                        <div className="city-price mono">
                                            {fmt.price(c.avg_price_kzt)} ₸
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    );
                })}
            </div>
            <div
                style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginTop: 10,
                    fontSize: 11,
                    fontFamily: 'var(--mono)',
                    color: 'var(--text-muted)',
                }}
            >
                <span>● РАЗМЕР = ОБЪЁМ РЫНКА</span>
                <span>
                    {hover != null
                        ? `${fmt.int(data[hover].listings)} активных объявлений`
                        : `${data.length} городов · ${fmt.int(totalListings)} объявл.`}
                </span>
            </div>
        </div>
    );
}
