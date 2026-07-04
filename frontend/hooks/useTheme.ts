// hooks/useTheme.ts — тёмная/светлая тема: zustand-store + persist в localStorage.
// Источник правды при загрузке — data-theme на <html>, который выставляет
// инлайн-скрипт в pages/_document.tsx (localStorage → prefers-color-scheme → dark)
// ещё до загрузки бандла. Store лишь подхватывает это значение, поэтому
// переключатель и панель Tweaks всегда согласованы между собой.
import { useEffect, useState } from 'react';
import { create } from 'zustand';

export type Theme = 'dark' | 'light';

const STORAGE_KEY = 'theme';

interface ThemeStore {
    theme: Theme;
    setTheme: (t: Theme) => void;
    toggle: () => void;
}

// На сервере (build-time рендер static export) document нет — берём 'dark',
// это же значение по умолчанию зашито в :root в globals.css.
function detectInitialTheme(): Theme {
    if (typeof document !== 'undefined') {
        const t = document.documentElement.getAttribute('data-theme');
        if (t === 'light' || t === 'dark') return t;
    }
    return 'dark';
}

export const useThemeStore = create<ThemeStore>((set, get) => ({
    theme: detectInitialTheme(),
    setTheme: (t: Theme) => {
        set({ theme: t });
        if (typeof document !== 'undefined') {
            document.documentElement.setAttribute('data-theme', t);
        }
        try {
            localStorage.setItem(STORAGE_KEY, t);
        } catch {
            // localStorage недоступен (private mode) — тема живёт до перезагрузки
        }
    },
    toggle: () => get().setTheme(get().theme === 'dark' ? 'light' : 'dark'),
}));

// Hydration-safe обёртка: до mount возвращает 'dark' (совпадает с тем, что
// отрендерил build-time HTML), после mount — реальную тему из store.
// Иначе у пользователя со светлой темой был бы hydration mismatch на иконке.
export function useTheme(): [Theme, (t: Theme) => void] {
    const theme = useThemeStore(s => s.theme);
    const setTheme = useThemeStore(s => s.setTheme);
    const [mounted, setMounted] = useState(false);
    useEffect(() => setMounted(true), []);
    return [mounted ? theme : 'dark', setTheme];
}
