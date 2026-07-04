// lib/sentry.ts — клиентская инициализация Sentry (t-0006).
//
// Почему @sentry/browser, а не @sentry/nextjs: проект собирается через
// output: 'export' (статический экспорт) — серверного runtime нет, а
// @sentry/nextjs требует webpack-плагин + auth-токен для sourcemaps и
// генерирует бесполезные server/edge-конфиги. @sentry/browser даёт тот же
// клиентский error-tracking без build-time зависимостей и токенов.
//
// Динамический import: SDK уходит в отдельный async-chunk и НЕ попадает в
// First Load JS (статический import добавлял +47 kB на каждую страницу).
// Загружается после гидрации и только если DSN задан на билде.
//
// Пустой NEXT_PUBLIC_SENTRY_DSN ⇒ no-op: локальная разработка и билд без
// DSN работают как раньше, без шума в консоли.

let initialized = false;

export function initSentry(): void {
    // Только браузер: при static export модуль исполняется и в Node во время
    // next build — там init не нужен и не должен вызываться.
    if (typeof window === 'undefined' || initialized) return;

    const dsn = process.env.NEXT_PUBLIC_SENTRY_DSN;
    if (!dsn) return;

    initialized = true;
    import('@sentry/browser')
        .then((Sentry) => {
            Sentry.init({
                dsn,
                // Низкий сэмплинг перфоманс-трейсов — важны ошибки, не APM
                integrations: [Sentry.browserTracingIntegration()],
                tracesSampleRate: 0.1,
                sendDefaultPii: false,
                environment: process.env.NODE_ENV,
            });
        })
        .catch(() => {
            // Chunk не загрузился (сеть/content-blocker) — работаем без Sentry
        });
}
