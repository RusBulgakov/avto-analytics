// pages/forecast.tsx — plcaeholder for upcoming PRO forecast feature
import Head from 'next/head';
import Link from 'next/link';

import Topbar from '@/components/layout/Topbar';
import Badge from '@/components/ui/Badge';

const PLANNED = [
    {
        title: 'Прогноз цены на 7 / 30 / 90 дней',
        desc: 'По каждой модели — точечная оценка плюс доверительный интервал. Модель учитывает сезонность, курс USD/KZT и изменения объёма.',
    },
    {
        title: 'Сигналы покупки',
        desc: 'Объявления, которые по оценке дешевле справедливой цены ≥ 10% и одновременно быстрее медианы закрываются.',
    },
    {
        title: 'Календарь скидок',
        desc: 'Дни когда исторически цена падает — перед праздниками, после выпусков новых моделей, в конце налоговых периодов.',
    },
    {
        title: 'Ретро-тест торговой стратегии',
        desc: 'Запустите стратегию перепродажи на исторических данных за 12 месяцев и посмотрите итоговую доходность.',
    },
];

export default function ForecastPage() {
    return (
        <>
            <Head>
                <title>Прогноз — Авто Аналитика KZ</title>
            </Head>

            <div className="app">
                <Topbar />

                <main className="main">
                    <div style={{ maxWidth: 780, margin: '24px auto 0', width: '100%' }}>
                        <div style={{ marginBottom: 6 }}>
                            <Badge variant="info">PRO · В разработке</Badge>
                        </div>
                        <div className="page-title">Прогноз цен</div>
                        <div className="page-sub" style={{ marginTop: 6 }}>
                            Следующий большой шаг платформы — количественный прогноз на основе 275k+ исторических цен.
                        </div>

                        <section
                            className="card"
                            style={{ marginTop: 20, padding: 0 }}
                        >
                            <div className="card-h">
                                <div>
                                    <div className="card-title">Что будет</div>
                                    <div className="card-sub">
                                        модуль появится как только накопится ≥ 6 месяцев price_history
                                    </div>
                                </div>
                            </div>
                            <div className="card-b" style={{ paddingTop: 0 }}>
                                <ul
                                    style={{
                                        listStyle: 'none',
                                        padding: 0,
                                        margin: 0,
                                        display: 'grid',
                                        gap: 12,
                                    }}
                                >
                                    {PLANNED.map((p, i) => (
                                        <li
                                            key={p.title}
                                            style={{
                                                display: 'grid',
                                                gridTemplateColumns: '28px 1fr',
                                                gap: 12,
                                                padding: '12px 0',
                                                borderTop: i === 0 ? 'none' : '1px solid var(--border)',
                                            }}
                                        >
                                            <span
                                                className="rank mono"
                                                style={{ width: 22, height: 22 }}
                                            >
                                                {i + 1}
                                            </span>
                                            <div>
                                                <div
                                                    style={{
                                                        fontFamily: 'var(--display)',
                                                        fontWeight: 600,
                                                        fontSize: 14,
                                                    }}
                                                >
                                                    {p.title}
                                                </div>
                                                <div
                                                    style={{
                                                        color: 'var(--text-muted)',
                                                        fontSize: 12,
                                                        marginTop: 3,
                                                    }}
                                                >
                                                    {p.desc}
                                                </div>
                                            </div>
                                        </li>
                                    ))}
                                </ul>
                            </div>
                        </section>

                        <div
                            className="card"
                            style={{
                                marginTop: 14,
                                padding: 18,
                                background: 'var(--up-soft)',
                                borderColor: 'var(--up)',
                            }}
                        >
                            <div
                                className="uppercase"
                                style={{ color: 'var(--up)', marginBottom: 6 }}
                            >
                                что уже работает
                            </div>
                            <div style={{ fontSize: 13 }}>
                                На дашборде доступны{' '}
                                <Link href="/" style={{ color: 'var(--info)', borderBottom: '1px dashed var(--info)' }}>
                                    индекс цен AA·IDX
                                </Link>
                                , воронка ликвидности, heatmap год × пробег и{' '}
                                <Link href="/profitability" style={{ color: 'var(--info)', borderBottom: '1px dashed var(--info)' }}>
                                    рейтинг рентабельности
                                </Link>
                                . На странице объявления —{' '}
                                <span style={{ color: 'var(--up)' }}>справедливая цена</span> и похожие предложения.
                            </div>
                        </div>
                    </div>
                </main>
            </div>
        </>
    );
}
