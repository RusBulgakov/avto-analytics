// pages/brands.tsx — каталог марок: плитка + поиск + клик → фильтр на дашборде
import { useMemo, useState } from 'react';
import Head from 'next/head';
import { useRouter } from 'next/router';
import useSWR from 'swr';

import Topbar from '@/components/layout/Topbar';
import { analyticsApi } from '@/lib/api';
import { fmt } from '@/lib/format';

interface BrandItem {
    id: number;
    name: string;
    slug: string;
    listings_count: number;
}

export default function BrandsPage() {
    const router = useRouter();
    const [q, setQ] = useState('');

    const { data: brands, isLoading } = useSWR<BrandItem[]>(
        'brands-page',
        () => analyticsApi.getBrands(),
        { revalidateOnFocus: false }
    );

    const filtered = useMemo(() => {
        const list = brands ?? [];
        const qq = q.trim().toLowerCase();
        if (!qq) return list;
        return list.filter(b =>
            b.name.toLowerCase().includes(qq) || b.slug.toLowerCase().includes(qq)
        );
    }, [brands, q]);

    const total = brands?.reduce((s, b) => s + b.listings_count, 0) ?? 0;

    return (
        <>
            <Head>
                <title>Марки — Авто Аналитика KZ</title>
            </Head>

            <div className="app">
                <Topbar />

                <main className="main">
                    <div style={{ display: 'flex', alignItems: 'flex-end', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
                        <div>
                            <div className="page-title">Каталог марок</div>
                            <div className="page-sub">
                                {isLoading
                                    ? 'загрузка…'
                                    : `${fmt.int(brands?.length ?? 0)} марок · ${fmt.int(total)} активных объявлений`}
                            </div>
                        </div>
                        <input
                            className="filter-input"
                            type="search"
                            value={q}
                            onChange={e => setQ(e.target.value)}
                            placeholder="Поиск по марке…"
                            style={{ width: 260, height: 32 }}
                        />
                    </div>

                    {isLoading ? (
                        <div className="skeleton" style={{ height: 400 }} />
                    ) : (
                        <div
                            style={{
                                display: 'grid',
                                gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))',
                                gap: 10,
                            }}
                        >
                            {filtered.map(b => (
                                <button
                                    key={b.id}
                                    type="button"
                                    onClick={() => router.push(`/?brand_id=${b.id}`)}
                                    className="card"
                                    style={{
                                        textAlign: 'left',
                                        cursor: 'pointer',
                                        padding: '14px 16px',
                                        transition: 'background 0.12s, border-color 0.12s',
                                    }}
                                    onMouseEnter={e => {
                                        (e.currentTarget as HTMLButtonElement).style.background = 'var(--surface-hover)';
                                    }}
                                    onMouseLeave={e => {
                                        (e.currentTarget as HTMLButtonElement).style.background = 'var(--surface)';
                                    }}
                                >
                                    <div
                                        style={{
                                            fontFamily: 'var(--display)',
                                            fontWeight: 600,
                                            fontSize: 15,
                                            letterSpacing: '-0.01em',
                                            color: 'var(--text)',
                                        }}
                                    >
                                        {b.name}
                                    </div>
                                    <div
                                        className="mono dim"
                                        style={{ fontSize: 11, marginTop: 2, letterSpacing: '0.04em' }}
                                    >
                                        {fmt.int(b.listings_count)} активных
                                    </div>
                                </button>
                            ))}
                            {filtered.length === 0 && (
                                <div
                                    style={{
                                        gridColumn: '1 / -1',
                                        padding: 24,
                                        textAlign: 'center',
                                        color: 'var(--text-muted)',
                                    }}
                                >
                                    Ничего не найдено
                                </div>
                            )}
                        </div>
                    )}
                </main>
            </div>
        </>
    );
}
