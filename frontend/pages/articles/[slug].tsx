// pages/articles/[slug].tsx — страница статьи.
//
// Архитектура: getStaticPaths + getStaticProps (fallback: false) вместо
// query-string (/articles/view?slug=...). Оба варианта совместимы с
// output: 'export', но SEO-статьям нужны РЕАЛЬНЫЕ отдельные URL: у
// query-string-страницы один canonical на все статьи, что убивает
// индексацию. Пагинация путей известна на билде (файлы в content/),
// поэтому статический экспорт по slug'ам — естественный выбор.
import Head from 'next/head';
import type { GetStaticPaths, GetStaticProps } from 'next';
import Link from 'next/link';

import Seo from '@/components/Seo';
import Topbar from '@/components/layout/Topbar';
import type { Article } from '@/lib/articles';

const SITE_URL = (
    process.env.NEXT_PUBLIC_SITE_URL || 'https://kolesa-frontend.onrender.com'
).replace(/\/+$/, '');

interface Props {
    article: Article;
}

const fmtDate = (iso: string) =>
    new Date(`${iso}T00:00:00Z`).toLocaleDateString('ru-RU', {
        day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC',
    });

export default function ArticlePage({ article }: Props) {
    // JSON-LD Article — schema.org разметка для поисковиков
    const jsonLd = {
        '@context': 'https://schema.org',
        '@type': 'Article',
        headline: article.title,
        description: article.description,
        datePublished: article.date,
        inLanguage: 'ru',
        mainEntityOfPage: `${SITE_URL}/articles/${article.slug}`,
        author: {
            '@type': 'Organization',
            name: 'Авто Аналитика KZ',
            url: SITE_URL,
        },
        publisher: {
            '@type': 'Organization',
            name: 'Авто Аналитика KZ',
            url: SITE_URL,
        },
    };

    return (
        <>
            <Seo
                title={`${article.title} | Авто Аналитика KZ`}
                description={article.description}
                path={`/articles/${article.slug}`}
                ogType="article"
                publishedTime={article.date}
            />
            <Head>
                <script
                    type="application/ld+json"
                    // eslint-disable-next-line react/no-danger
                    dangerouslySetInnerHTML={{ __html: JSON.stringify(jsonLd) }}
                />
            </Head>

            <div className="app">
                <Topbar />

                <main className="main">
                    <article className="article">
                        <div className="article-head">
                            <Link href="/articles" className="article-back">← Все статьи</Link>
                            <div className="uppercase">{fmtDate(article.date)}</div>
                            <h1 className="article-title display">{article.title}</h1>
                            <p className="article-lead">{article.description}</p>
                        </div>

                        {/* HTML отрендерен из нашего же markdown на билде —
                            источник доверенный (файлы в репо), санитайзер не нужен */}
                        <div
                            className="article-prose"
                            dangerouslySetInnerHTML={{ __html: article.html }}
                        />
                    </article>
                </main>
            </div>
        </>
    );
}

export const getStaticPaths: GetStaticPaths = async () => {
    const { getArticleSlugs } = await import('@/lib/articles');
    return {
        paths: getArticleSlugs().map(slug => ({ params: { slug } })),
        // fallback: false обязателен для output: 'export' — все пути известны на билде
        fallback: false,
    };
};

export const getStaticProps: GetStaticProps<Props> = async ({ params }) => {
    const { getArticle } = await import('@/lib/articles');
    return { props: { article: getArticle(String(params?.slug)) } };
};
