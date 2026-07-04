// pages/_app.tsx — App shell with next/font and theme provider
import type { AppProps } from 'next/app';
import Head from 'next/head';
import { Inter, Space_Grotesk, JetBrains_Mono } from 'next/font/google';
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

// --font-* обязаны быть определены на :root (<html>): токены --body/--display/
// --mono в globals.css объявлены на :root и резолвят var(--font-*) именно там.
// Классы next/font на wrapper-<div> до :root не «долетали» — var() был invalid
// at computed-value time и весь сайт падал на браузерный serif (Times).
// Инлайн-<style> в <head> рендерится в статический HTML → шрифты корректны
// с первой отрисовки, без FOUC и без SSR-рантайма.
const fontVars = `:root{--font-body:${body.style.fontFamily};--font-display:${display.style.fontFamily};--font-mono:${mono.style.fontFamily};}`;

// Тема (data-theme на <html>) выставляется инлайн-скриптом в _document.tsx
// до первой отрисовки; здесь ничего синхронизировать не нужно.
export default function App({ Component, pageProps }: AppProps) {
    return (
        <>
            <Head>
                <style dangerouslySetInnerHTML={{ __html: fontVars }} />
            </Head>
            <div className={`${body.variable} ${display.variable} ${mono.variable}`} style={{ minHeight: '100vh' }}>
                <Component {...pageProps} />
            </div>
        </>
    );
}
