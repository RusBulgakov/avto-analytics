// components/charts/KZMap.tsx — thin wrapper that lazy-loads the Leaflet map.
// Leaflet requires `window`, so we wrap the real component in next/dynamic
// with ssr:false. Static export still works fine — the map hydrates on the client.
import dynamic from 'next/dynamic';

import type { GeoCity } from './KZMapInner';

export type { GeoCity } from './KZMapInner';

interface Props {
    data: GeoCity[];
    loading?: boolean;
}

const KZMapInner = dynamic(() => import('./KZMapInner'), {
    ssr: false,
    loading: () => (
        <div>
            <div
                className="skeleton"
                style={{ height: 380, borderRadius: 8 }}
            />
            <div
                style={{
                    marginTop: 8,
                    fontSize: 11,
                    fontFamily: 'var(--mono)',
                    color: 'var(--text-muted)',
                }}
            >
                загрузка карты…
            </div>
        </div>
    ),
});

export default function KZMap({ data, loading }: Props) {
    if (loading && (!data || data.length === 0)) {
        return (
            <div>
                <div
                    className="skeleton"
                    style={{ height: 380, borderRadius: 8 }}
                />
            </div>
        );
    }
    if (!data || data.length === 0) {
        return (
            <div
                style={{
                    height: 380,
                    borderRadius: 8,
                    background: 'var(--bg-2)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: 'var(--text-muted)',
                    fontSize: 12,
                }}
            >
                нет данных
            </div>
        );
    }
    return <KZMapInner data={data} />;
}
