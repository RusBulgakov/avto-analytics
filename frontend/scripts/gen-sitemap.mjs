// scripts/gen-sitemap.mjs — генерирует public/sitemap.xml и public/robots.txt
// перед билдом (npm prebuild). Нужен потому что output: 'export' — нет SSR,
// сайтмап должен лежать статикой в public/. Оба файла — build-артефакты,
// в git НЕ коммитятся (см. .gitignore); единственный источник правды — этот скрипт.
//
// Базовый URL: NEXT_PUBLIC_SITE_URL (без trailing slash), fallback — дефолтный
// домен Render static-сайта `kolesa-frontend` (см. render.yaml).
// ВАЖНО: fallback-домен должен совпадать с fallback'ом в components/Seo.tsx.
//
// Добавление новой индексируемой страницы = одна строка в ROUTES ниже.
// Не включаем: /listing и /model (query-string driven детальные страницы,
// без параметров бессмысленны), /auth/* (не для индексации, закрыто в robots).
import { writeFileSync, mkdirSync, readdirSync, readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const SITE_URL = (
    process.env.NEXT_PUBLIC_SITE_URL || 'https://kolesa-frontend.onrender.com'
).replace(/\/+$/, '');

/** Индексируемые страницы: path + приоритет + частота обновления. */
const ROUTES = [
    { path: '/', changefreq: 'daily', priority: '1.0' },
    { path: '/brands', changefreq: 'daily', priority: '0.8' },
    // /compare без параметров — осмысленный лендинг (пикер моделей);
    // параметризованные /compare?items=… в sitemap не включаем.
    { path: '/compare', changefreq: 'weekly', priority: '0.6' },
    { path: '/profitability', changefreq: 'daily', priority: '0.8' },
    { path: '/forecast', changefreq: 'weekly', priority: '0.7' },
    { path: '/articles', changefreq: 'weekly', priority: '0.7' },
];

// ── Статьи (t-0008): file-based контент из content/articles/*.md ──
// Каждый файл = страница /articles/<slug> (slug = имя файла).
// Дублируем мини-парсер frontmatter из lib/articles.ts: скрипт обязан
// оставаться dependency-free и не может импортировать TS-модуль.
const articlesDir = join(dirname(fileURLToPath(import.meta.url)), '..', 'content', 'articles');
if (existsSync(articlesDir)) {
    for (const file of readdirSync(articlesDir).filter(f => f.endsWith('.md')).sort()) {
        const raw = readFileSync(join(articlesDir, file), 'utf8');
        // lastmod для статьи семантически корректен — это frontmatter-дата
        // публикации контента (в отличие от «даты билда» для остальных страниц)
        const date = raw.match(/^---\r?\n[\s\S]*?^date:\s*["']?(\d{4}-\d{2}-\d{2})["']?\s*$[\s\S]*?\r?\n---/m)?.[1];
        ROUTES.push({
            path: `/articles/${file.replace(/\.md$/, '')}`,
            changefreq: 'monthly',
            priority: '0.6',
            lastmod: date,
        });
    }
}

/** Минимальный XML-escape для значений внутри тегов. */
const xml = s => String(s)
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;');

// <lastmod> для обычных страниц намеренно не пишем: по спецификации
// sitemaps.org он опционален, а «дата билда» — семантически неверное значение
// (контент страниц не менялся). Исключение — статьи: у них есть честная
// frontmatter-дата публикации (r.lastmod).
const sitemap = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${ROUTES.map(
    r => `  <url>
    <loc>${xml(SITE_URL + r.path)}</loc>${r.lastmod ? `
    <lastmod>${xml(r.lastmod)}</lastmod>` : ''}
    <changefreq>${xml(r.changefreq)}</changefreq>
    <priority>${xml(r.priority)}</priority>
  </url>`
).join('\n')}
</urlset>
`;

const robots = `User-agent: *
Allow: /
Disallow: /auth/

Sitemap: ${SITE_URL}/sitemap.xml
`;

const publicDir = join(dirname(fileURLToPath(import.meta.url)), '..', 'public');
mkdirSync(publicDir, { recursive: true });
writeFileSync(join(publicDir, 'sitemap.xml'), sitemap);
writeFileSync(join(publicDir, 'robots.txt'), robots);

console.log(`[gen-sitemap] base=${SITE_URL} routes=${ROUTES.length} -> public/sitemap.xml, public/robots.txt`);
