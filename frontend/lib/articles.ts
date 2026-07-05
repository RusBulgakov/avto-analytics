// lib/articles.ts — файловый контент-пайплайн для раздела /articles.
//
// Статьи лежат в frontend/content/articles/*.md: YAML-подобный frontmatter
// (плоские `key: value`, без вложенности) + markdown-тело. Slug = имя файла.
//
// ВАЖНО: модуль использует node:fs, поэтому импортировать его можно ТОЛЬКО
// из getStaticProps/getStaticPaths (Next вырезает эти функции из клиентского
// бандла). Не импортировать из компонентов/хуков.
//
// Frontmatter парсим руками (~20 строк) вместо gray-matter: нам нужны лишь
// плоские строки-значения, лишняя зависимость с js-yaml внутри не окупается.
// Тот же формат читает scripts/gen-sitemap.mjs (там своя копия парсера —
// скрипт обязан оставаться dependency-free и не может импортировать TS).
import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { marked } from 'marked';

const ARTICLES_DIR = join(process.cwd(), 'content', 'articles');

export interface ArticleMeta {
    slug: string;
    /** Заголовок статьи (H1 и <title> без суффикса бренда) */
    title: string;
    /** 1–2 предложения для meta description и карточки в списке */
    description: string;
    /** Дата публикации ISO YYYY-MM-DD (идёт в JSON-LD и sitemap lastmod) */
    date: string;
}

export interface Article extends ArticleMeta {
    /** Отрендеренный из markdown HTML-контент статьи */
    html: string;
}

/** Плоский frontmatter: блок между `---` в начале файла, строки `key: value`. */
function parseFrontmatter(raw: string): { meta: Record<string, string>; body: string } {
    const m = raw.match(/^---\r?\n([\s\S]*?)\r?\n---\r?\n?/);
    if (!m) return { meta: {}, body: raw };
    const meta: Record<string, string> = {};
    for (const line of m[1].split(/\r?\n/)) {
        const kv = line.match(/^([A-Za-z_][\w-]*):\s*(.*)$/);
        if (!kv) continue;
        // Снимаем опциональные одинарные/двойные кавычки вокруг значения
        meta[kv[1]] = kv[2].trim().replace(/^(["'])(.*)\1$/, '$2');
    }
    return { meta, body: raw.slice(m[0].length) };
}

function readArticleFile(slug: string): { meta: Record<string, string>; body: string } {
    const raw = readFileSync(join(ARTICLES_DIR, `${slug}.md`), 'utf8');
    return parseFrontmatter(raw);
}

function toMeta(slug: string, meta: Record<string, string>): ArticleMeta {
    // Падаем на билде, а не молча отдаём пустые метатеги: SEO-раздел без
    // title/description бессмысленен.
    for (const key of ['title', 'description', 'date'] as const) {
        if (!meta[key]) {
            throw new Error(`[articles] ${slug}.md: обязательное поле frontmatter "${key}" отсутствует`);
        }
    }
    return { slug, title: meta.title, description: meta.description, date: meta.date };
}

/** Slug'и всех статей (для getStaticPaths). */
export function getArticleSlugs(): string[] {
    return readdirSync(ARTICLES_DIR)
        .filter(f => f.endsWith('.md'))
        .map(f => f.replace(/\.md$/, ''));
}

/** Метаданные всех статей, свежие первыми (для списка /articles). */
export function getAllArticlesMeta(): ArticleMeta[] {
    return getArticleSlugs()
        .map(slug => toMeta(slug, readArticleFile(slug).meta))
        .sort((a, b) => b.date.localeCompare(a.date));
}

/** Полная статья с отрендеренным HTML (для страницы /articles/[slug]). */
export function getArticle(slug: string): Article {
    const { meta, body } = readArticleFile(slug);
    const html = marked.parse(body, { async: false }) as string;
    return { ...toMeta(slug, meta), html };
}
