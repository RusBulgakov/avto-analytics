// pages/_app.tsx — App shell with next/font and theme provider
import type { AppProps } from 'next/app';
import { Inter, Space_Grotesk, JetBrains_Mono } from 'next/font/google';
import { useEffect } from 'react';
import '@/styles/globals.css';
import { initSentry } from '@/lib/sentry';

// Sentry: module-level, чтобы ловить ошибки максимально рано (до первого
// рендера). Внутри guard на typeof window и пустой DSN — на билде это no-op.
initSentry();

const body = Inter({
    subsets: ['latin', 'cyrillic'],
    weight: ['400', '500', '600'],
    variable: '--font-body',
    display: 'swap',
});

const display = Space_Grotesk({
    subsets: ['latin'],
    weight: ['400', '500', '600', '700'],
    variable: '--font-display',
    display: 'swap',
});

const mono = JetBrains_Mono({
    subsets: ['latin'],
    weight: ['400', '500'],
    variable: '--font-mono',
    display: 'swap',
});

export default function App({ Component, pageProps }: AppProps) {
    // Sync theme from localStorage on mount (data-theme attribute on <html>)
    useEffect(() => {
        const saved = localStorage.getItem('theme');
        if (saved === 'light' || saved === 'dark') {
            document.documentElement.setAttribute('data-theme', saved);
        } else {
            document.documentElement.setAttribute('data-theme', 'dark');
        }
    }, []);

    return (
        <div className={`${body.variable} ${display.variable} ${mono.variable}`} style={{ minHeight: '100vh' }}>
            <Component {...pageProps} />
        </div>
    );
}
