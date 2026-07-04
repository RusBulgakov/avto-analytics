// components/layout/SearchPalette.tsx — ⌘K поиск по маркам и моделям.
// Открывается кнопкой «Поиск» в топбаре или Cmd/Ctrl+K. Enter/клик по
// результату ставит фильтр дашборда (переход на / с query-параметрами).
import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useRouter } from 'next/router';
import useSWR from 'swr';

import { analyticsApi } from '@/lib/api';
import { fmt } from '@/lib/format';
import { useFilters } from '@/store/filters';

interface BrandItem { id: number; name: string; slug: string | null; listings_count: number }
interface ModelItem { id: number; name: string; slug: string | null; listings_count: number }

interface Props {
    open: boolean;
    onClose: () => void;
}

interface ResultRow {
    key: string;
    label: string;
    hint: string;
    count: number;
    brandId: number;
    modelId: number | null;
}

export default function SearchPalette({ open, onClose }: Props) {
    const router = useRouter();
    const setFilters = useFilters(s => s.setAll);
    const [query, setQuery] = useState('');
    const [cursor, setCursor] = useState(0);
    const inputRef = useRef<HTMLInputElement>(null);

    useEffect(() => {
        if (open) {
            setQuery('');
            setCursor(0);
            // Фокус после отрисовки
            requestAnimationFrame(() => inputRef.current?.focus());
        }
    }, [open]);

    const { data: brands } = useSWR<BrandItem[]>(
        open ? 'brands' : null,
        () => analyticsApi.getBrands(),
        { revalidateOnFocus: false }
    );

    // Если первым словом однозначно найдена марка — подгружаем её модели
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    const brandMatches = useMemo(() => {
        if (!brands || !words.length) return [];
        const w = words[0];
        return brands
            .filter(b => b.listings_count > 0)
            .filter(b => b.name.toLowerCase().includes(w) || (b.slug ?? '').toLowerCase().includes(w))
            .sort((a, b) => b.listings_count - a.listings_count)
            .slice(0, 8);
    }, [brands, words]);

    const exactBrand = brandMatches.length ? brandMatches[0] : null;
    const { data: models } = useSWR<ModelItem[]>(
        open && exactBrand && words.length > 1 ? ['models', exactBrand.id] : null,
        () => analyticsApi.getModels(exactBrand!.id),
        { revalidateOnFocus: false }
    );

    const results: ResultRow[] = useMemo(() => {
        const rows: ResultRow[] = [];
        if (words.length > 1 && exactBrand && models) {
            const mw = words.slice(1).join(' ');
            models
                .filter(m => m.listings_count > 0 && m.name.toLowerCase().includes(mw))
                .sort((a, b) => b.listings_count - a.listings_count)
                .slice(0, 8)
                .forEach(m => rows.push({
                    key: `m-${m.id}`,
                    label: `${fmt.brandName(exactBrand.name)} ${m.name}`,
                    hint: 'модель',
                    count: m.listings_count,
                    brandId: exactBrand.id,
                    modelId: m.id,
                }));
        }
        brandMatches.forEach(b => rows.push({
            key: `b-${b.id}`,
            label: fmt.brandName(b.name),
            hint: 'марка',
            count: b.listings_count,
            brandId: b.id,
            modelId: null,
        }));
        return rows.slice(0, 10);
    }, [brandMatches, exactBrand, models, words]);

    useEffect(() => setCursor(0), [query]);

    if (!open) return null;

    const go = (row: ResultRow) => {
        onClose();
        // Пишем фильтр напрямую в store — URL-sync хук допишет query сам.
        // router.push с query недостаточно: store гидрируется из URL только
        // при первом mount'е дашборда.
        setFilters({ brand_id: [row.brandId], model_id: row.modelId ? [row.modelId] : [] });
        if (router.pathname !== '/') router.push('/');
    };

    const onKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Escape') { e.preventDefault(); onClose(); }
        else if (e.key === 'ArrowDown') { e.preventDefault(); setCursor(c => Math.min(c + 1, results.length - 1)); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); setCursor(c => Math.max(c - 1, 0)); }
        else if (e.key === 'Enter' && results[cursor]) { e.preventDefault(); go(results[cursor]); }
    };

    return (
        <div
            className="palette-overlay"
            onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}
            role="dialog"
            aria-modal="true"
            aria-label="Поиск по маркам и моделям"
        >
            <div className="palette" onKeyDown={onKeyDown}>
                <input
                    ref={inputRef}
                    className="palette-input"
                    placeholder="Марка или марка + модель… (например: toyota camry)"
                    value={query}
                    onChange={(e) => setQuery(e.target.value)}
                    aria-label="Поисковый запрос"
                />
                <div className="palette-results" role="listbox">
                    {!query.trim() ? (
                        <div className="palette-empty">Начните вводить марку — Enter применит фильтр на дашборде</div>
                    ) : !results.length ? (
                        <div className="palette-empty">{brands ? 'Ничего не найдено' : 'загрузка…'}</div>
                    ) : (
                        results.map((r, i) => (
                            <button
                                key={r.key}
                                type="button"
                                role="option"
                                aria-selected={i === cursor}
                                className={`palette-row ${i === cursor ? 'active' : ''}`}
                                onMouseEnter={() => setCursor(i)}
                                onClick={() => go(r)}
                            >
                                <span className="palette-row-label">{r.label}</span>
                                <span className="palette-row-hint">{r.hint}</span>
                                <span className="palette-row-count mono">{fmt.int(r.count)}</span>
                            </button>
                        ))
                    )}
                </div>
                <div className="palette-foot">
                    <span>↑↓ — выбор · Enter — применить · Esc — закрыть</span>
                </div>
            </div>
        </div>
    );
}
