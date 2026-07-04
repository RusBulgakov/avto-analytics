// components/Seo.tsx — базовые SEO-теги страницы: title, description,
// canonical, Open Graph, Twitter Card. Работает со static export (никакого SSR).
//
// Базовый URL берётся из NEXT_PUBLIC_SITE_URL (инлайнится Next'ом при билде).
// Fallback — дефолтный домен Render static-сайта `kolesa-frontend` из render.yaml.
// ВАЖНО: fallback-домен должен совпадать с fallback'ом в scripts/gen-sitemap.mjs.
// НЕ хардкодить домен в страницах — только через этот компонент.
import Head from 'next/head';

const SITE_URL = (
    process.env.NEXT_PUBLIC_SITE_URL || 'https://kolesa-frontend.onrender.com'
).replace(/\/+$/, '');

const SITE_NAME = 'Авто Аналитика KZ';

interface SeoProps {
    /** Полный <title> страницы (уже с суффиксом бренда, если нужен) */
    title: string;
    /** meta description — 1–2 предложения, по-русски */
    description: string;
    /** Путь страницы для canonical/og:url, начинается с "/" (например "/brands") */
    path: string;
    /** Абсолютный URL или путь от корня сайта до OG-картинки (опционально) */
    ogImage?: string;
}

export default function Seo({ title, description, path, ogImage }: SeoProps) {
    const url = `${SITE_URL}${path}`;
    const image = ogImage
        ? /^https?:\/\//.test(ogImage)
            ? ogImage
            : `${SITE_URL}${ogImage}`
        : undefined;

    // key обязателен: next/head сам дедуплицирует только title/viewport/
    // charSet/base; остальные теги без key задваиваются при override на странице.
    return (
        <Head>
            <title>{title}</title>
            <meta key="description" name="description" content={description} />
            <meta key="viewport" name="viewport" content="width=device-width, initial-scale=1" />
            <link key="canonical" rel="canonical" href={url} />

            <meta key="og:type" property="og:type" content="website" />
            <meta key="og:site_name" property="og:site_name" content={SITE_NAME} />
            <meta key="og:locale" property="og:locale" content="ru_RU" />
            <meta key="og:title" property="og:title" content={title} />
            <meta key="og:description" property="og:description" content={description} />
            <meta key="og:url" property="og:url" content={url} />
            {image && <meta key="og:image" property="og:image" content={image} />}

            <meta key="twitter:card" name="twitter:card" content={image ? 'summary_large_image' : 'summary'} />
            <meta key="twitter:title" name="twitter:title" content={title} />
            <meta key="twitter:description" name="twitter:description" content={description} />
            {image && <meta key="twitter:image" name="twitter:image" content={image} />}
        </Head>
    );
}
