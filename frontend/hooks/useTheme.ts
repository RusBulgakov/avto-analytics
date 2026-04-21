// hooks/useTheme.ts — dark/light theme toggle persisted to localStorage
import { useEffect, useState } from 'react';

export type Theme = 'dark' | 'light';

const STORAGE_KEY = 'theme';

export function useTheme(): [Theme, (t: Theme) => void] {
    const [theme, setThemeState] = useState<Theme>('dark');

    useEffect(() => {
        const saved = localStorage.getItem(STORAGE_KEY);
        if (saved === 'light' || saved === 'dark') {
            setThemeState(saved);
            document.documentElement.setAttribute('data-theme', saved);
        }
    }, []);

    const setTheme = (t: Theme) => {
        setThemeState(t);
        localStorage.setItem(STORAGE_KEY, t);
        document.documentElement.setAttribute('data-theme', t);
    };

    return [theme, setTheme];
}
