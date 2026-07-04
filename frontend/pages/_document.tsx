// pages/_document.tsx — кастомный Document.
// Главная задача: анти-FOUC скрипт темы. Он выполняется синхронно в <head>
// ДО первой отрисовки, поэтому data-theme на <html> появляется раньше, чем
// браузер применит CSS — «вспышки» противоположной темы нет.
// Работает со static export (output: 'export'): скрипт попадает в каждый
// экспортированный HTML, никакого SSR-рантайма не требует.
import { Html, Head, Main, NextScript } from 'next/document';

// Приоритет: сохранённый выбор (localStorage 'theme') → prefers-color-scheme →
// dark. try/catch — localStorage может быть недоступен (private mode, куки
// отключены); matchMedia — на всякий случай тоже.
const themeInitScript = `(function(){var t=null;try{t=localStorage.getItem('theme')}catch(e){}if(t!=='light'&&t!=='dark'){try{t=window.matchMedia('(prefers-color-scheme: light)').matches?'light':'dark'}catch(e){t='dark'}}document.documentElement.setAttribute('data-theme',t)})()`;

export default function Document() {
    return (
        <Html lang="ru">
            <Head>
                {/* eslint-disable-next-line react/no-danger */}
                <script dangerouslySetInnerHTML={{ __html: themeInitScript }} />
            </Head>
            <body>
                <Main />
                <NextScript />
            </body>
        </Html>
    );
}
