// components/charts/KZMapInner.tsx — client-only Leaflet map of Kazakhstan.
// Wrapped by KZMap.tsx via next/dynamic (Leaflet needs window).
import React, { useMemo } from 'react';
import { useRouter } from 'next/router';
import { MapContainer, TileLayer, CircleMarker, Tooltip } from 'react-leaflet';
import 'leaflet/dist/leaflet.css';

import { fmt } from '@/lib/format';

export interface GeoCity {
    slug: string;
    name: string;
    x: number;               // legacy percent (unused on real map)
    y: number;               // legacy percent (unused on real map)
    listings: number;
    avg_price_kzt: number | null;
}

interface Props {
    data: GeoCity[];
}

// Real lat/lng for every city the backend might return
const CITY_COORDS: Record<string, [number, number]> = {
    almaty:           [43.238, 76.945],
    astana:           [51.128, 71.430],
    'nur-sultan':     [51.128, 71.430],
    shymkent:         [42.321, 69.596],
    karaganda:        [49.807, 73.086],
    aktobe:           [50.284, 57.167],
    taraz:            [42.900, 71.367],
    pavlodar:         [52.285, 76.950],
    'ust-kamenogorsk':[49.974, 82.606],
    oskemen:          [49.974, 82.606],
    semey:            [50.423, 80.268],
    kyzylorda:        [44.852, 65.509],
    uralsk:           [51.225, 51.386],
    oral:             [51.225, 51.386],
    kostanai:         [53.217, 63.629],
    kostanay:         [53.217, 63.629],
    petropavlovsk:    [54.868, 69.137],
    aktau:            [43.650, 51.159],
    atyrau:           [47.094, 51.923],
    turkestan:        [43.297, 68.251],
    temirtau:         [50.053, 72.964],
    ekibastuz:        [51.729, 75.324],
    taldykorgan:      [45.017, 78.374],
    zhezkazgan:       [47.788, 67.700],
    kokshetau:        [53.294, 69.392],
    balkhash:         [46.843, 74.999],
    ridder:           [50.350, 83.512],
    satpayev:         [47.894, 67.540],
    stepnogorsk:      [52.350, 71.883],
    kentau:           [43.517, 68.506],
    rudny:            [52.974, 63.132],
    zhanaozen:        [43.341, 52.865],
    arkalyk:          [50.248, 66.911],
    shu:              [43.603, 73.762],
    'shar':           [49.600, 81.050],
    kapchagay:        [43.873, 77.068],
};

const UP = '#22e0a1';
const UP_DIM = 'rgba(34, 224, 161, 0.45)';
const MIN_R = 5;
const MAX_R = 22;

export default function KZMapInner({ data }: Props) {
    const router = useRouter();

    const cities = useMemo(
        () =>
            (data ?? [])
                .filter(c => CITY_COORDS[c.slug] && c.listings > 0)
                .map(c => ({
                    ...c,
                    lat: CITY_COORDS[c.slug][0],
                    lng: CITY_COORDS[c.slug][1],
                })),
        [data]
    );

    const maxListings = Math.max(1, ...cities.map(c => c.listings));
    const totalListings = cities.reduce((s, c) => s + c.listings, 0);
    // Always-visible labels for the biggest markets (top 3 by volume)
    const labelThreshold = useMemo(() => {
        if (cities.length < 4) return 0;
        const sorted = [...cities].sort((a, b) => b.listings - a.listings);
        return sorted[2]?.listings ?? Infinity;
    }, [cities]);

    return (
        <div>
            <div
                style={{
                    height: 380,
                    borderRadius: 8,
                    overflow: 'hidden',
                    border: '1px solid var(--border)',
                    position: 'relative',
                }}
            >
                <MapContainer
                    center={[48.5, 68]}
                    zoom={4}
                    minZoom={3}
                    maxZoom={8}
                    scrollWheelZoom={false}
                    attributionControl={false}
                    style={{ height: '100%', width: '100%', background: '#0a0c10' }}
                >
                    <TileLayer
                        url="https://{s}.basemaps.cartocdn.com/dark_nolabels/{z}/{x}/{y}{r}.png"
                        subdomains={['a', 'b', 'c', 'd']}
                        maxZoom={19}
                    />
                    <TileLayer
                        url="https://{s}.basemaps.cartocdn.com/dark_only_labels/{z}/{x}/{y}{r}.png"
                        subdomains={['a', 'b', 'c', 'd']}
                        maxZoom={19}
                        opacity={0.7}
                    />
                    {cities.map(c => {
                        const ratio = c.listings / maxListings;
                        const r = MIN_R + ratio * (MAX_R - MIN_R);
                        const permanent = c.listings >= labelThreshold;
                        return (
                            <CircleMarker
                                key={c.slug}
                                center={[c.lat, c.lng]}
                                radius={r}
                                pathOptions={{
                                    color: UP,
                                    fillColor: UP,
                                    fillOpacity: 0.55,
                                    weight: 1.5,
                                    opacity: 0.9,
                                }}
                                eventHandlers={{
                                    click: () => router.push(`/?city=${encodeURIComponent(c.slug)}`),
                                }}
                            >
                                <Tooltip
                                    direction="top"
                                    offset={[0, -4]}
                                    opacity={1}
                                    permanent={permanent}
                                    className="kz-map-tip"
                                >
                                    <strong>{c.name}</strong>{' '}
                                    <span style={{ color: UP_DIM, fontFamily: 'var(--mono)' }}>
                                        {fmt.int(c.listings)}
                                    </span>
                                </Tooltip>
                            </CircleMarker>
                        );
                    })}
                </MapContainer>
            </div>

            <div
                style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginTop: 8,
                    fontSize: 11,
                    fontFamily: 'var(--mono)',
                    color: 'var(--text-muted)',
                }}
            >
                <span>● РАЗМЕР = ОБЪЁМ РЫНКА · КЛИК = ФИЛЬТР</span>
                <span>
                    {cities.length} городов · {fmt.int(totalListings)} объявл.
                </span>
            </div>
        </div>
    );
}
