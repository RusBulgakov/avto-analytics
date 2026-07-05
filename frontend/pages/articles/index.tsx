// pages/articles/index.tsx — список статей раздела /articles.
// Полностью статический: список собирается в getStaticProps на билде
// из frontend/content/articles/*.md (совместимо с output: 'export').
import type { GetStaticProps } from 'next';
import Link from 'next/link';

import Seo from '@/components/Seo';
import Topbar from '@/components/layout/Topbar';
import type { ArticleMeta } from '@/lib/articles';

interface Props {
    articles: ArticleMeta[];
}

const fmtDate = (iso: string) =>
    new Date(`${iso}T00:00:00Z`).toLocaleDateString('ru-RU', {
        day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC',
    });

export default function ArticlesIndex({ articles }: Props) {
    return (
        <>
            <Seo
                title="Статьи об авторынке Казахстана — аналитика и данные | Авто Аналитика KZ"
                description="Статьи о вторичном авторынке Казахстана на основе живых данных: динамика цен, сезонность, ликвидность брендов и практические выводы для покупателей и продавцов."
                path="/articles"
            />

            <div className="app">
                <Topbar />

                <main className="main">
                    <div>
                        <div className="page-title">Статьи</div>
                        <div className="page-sub">
                            Аналитика авторынка Казахстана — на данных, а не на ощущениях
                        </div>
                    </div>

                    <div className="article-list">
                        {articles.map(a => (
                            <Link key={a.slug} href={`/articles/${a.slug}`} className="card article-card">
                                <div className="uppercase">{fmtDate(a.date)}</div>
                                <h2 className="article-card-title display">{a.title}</h2>
                                <p className="article-card-desc">{a.description}</p>
                                <span className="article-card-more">Читать →</span>
                            </Link>
                        ))}
                    </div>
                </main>
            </div>
        </>
    );
}

export const getStaticProps: GetStaticProps<Props> = async () => {
    // Импорт внутри функции: lib/articles использует node:fs и не должен
    // попадать в клиентский бандл (Next вырезает только сам getStaticProps).
    const { getAllArticlesMeta } = await import('@/lib/articles');
    return { props: { articles: getAllArticlesMeta() } };
};
