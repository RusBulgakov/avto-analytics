// lib/format.ts — shared formatting helpers (matches design_handoff/components.jsx fmt)

// Аббревиатуры и составные имена, которые ломает title-case из БД
const BRAND_DISPLAY: Record<string, string> = {
    'bmw': 'BMW', 'byd': 'BYD', 'jac': 'JAC', 'mg': 'MG', 'gac': 'GAC',
    'faw': 'FAW', 'gmc': 'GMC', 'vaz': 'VAZ', 'zaz': 'ZAZ', 'uaz': 'UAZ',
    'gaz': 'GAZ', 'zx': 'ZX', 'baw': 'BAW', 'baic': 'BAIC', 'swm': 'SWM',
    'gwm': 'GWM', 'dfsk': 'DFSK', 'jmc': 'JMC', 'kyc': 'KYC', 'im': 'IM',
    'ds': 'DS', 'tlc': 'TLC', 'wv': 'VW', 'aro': 'ARO',
    'mercedes benz': 'Mercedes-Benz', 'mercedes maybach': 'Mercedes-Maybach',
    'ssangyong': 'SsangYong', 'ssang yong': 'SsangYong',
    'lynk co': 'Lynk & Co', 'lynk': 'Lynk & Co',
    'mclaren': 'McLaren', 'xpeng': 'XPeng', 'hiphi': 'HiPhi',
    'rolls royce': 'Rolls-Royce',
    'gwm wey': 'GWM Wey',
};

// Русские названия для слагов городов из БД (частые); остальное — капитализация
const CITY_DISPLAY: Record<string, string> = {
    'almaty': 'Алматы', 'astana': 'Астана', 'nur-sultan': 'Астана',
    'shymkent': 'Шымкент', 'karaganda': 'Караганда', 'aktobe': 'Актобе',
    'pavlodar': 'Павлодар', 'ust-kamenogorsk': 'Усть-Каменогорск',
    'oskemen': 'Усть-Каменогорск', 'kostanay': 'Костанай', 'kostanai': 'Костанай',
    'atyrau': 'Атырау', 'uralsk': 'Уральск', 'oral': 'Уральск',
    'semey': 'Семей', 'taraz': 'Тараз', 'kyzylorda': 'Кызылорда',
    'aktau': 'Актау', 'petropavlovsk': 'Петропавловск', 'temirtau': 'Темиртау',
    'kokshetau': 'Кокшетау', 'turkestan': 'Туркестан', 'ekibastuz': 'Экибастуз',
    'taldykorgan': 'Талдыкорган', 'zhezkazgan': 'Жезказган', 'ridder': 'Риддер',
    'balkhash': 'Балхаш', 'satpayev': 'Сатпаев', 'rudny': 'Рудный',
    'stepnogorsk': 'Степногорск', 'kentau': 'Кентау', 'zhanaozen': 'Жанаозен',
    'arkalyk': 'Аркалык', 'kapchagay': 'Капшагай', 'khromtau': 'Хромтау',
    'shu': 'Шу',
};

export const fmt = {
    /** Integer with Russian grouping: 128_400 → "128 400" */
    int: (n: number | null | undefined): string =>
        (n ?? 0).toLocaleString('ru-RU'),

    /** Short price: 16_800_000 → "16.8 млн", 450_000 → "450К" */
    price: (n: number | null | undefined): string => {
        if (n == null) return '—';
        if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)} млн`;
        if (n >= 1_000) return `${(n / 1_000).toFixed(0)}К`;
        return n.toString();
    },

    /** Full price with currency: 16_800_000 → "16 800 000 ₸" */
    priceFull: (n: number | null | undefined): string =>
        `${(n ?? 0).toLocaleString('ru-RU')} ₸`,

    /** Percent with sign: 4.2 → "+4.2%", -1.1 → "-1.1%" */
    pct: (n: number, digits = 1): string =>
        `${n > 0 ? '+' : ''}${n.toFixed(digits)}%`,

    /** Mileage: 78 → "78 тыс км" */
    km: (n: number): string => `${n} тыс км`,

    /** Relative minutes: 2 → "2 мин назад" */
    relMin: (n: number): string => {
        if (n < 1) return 'только что';
        if (n < 60) return `${n} мин`;
        const h = Math.floor(n / 60);
        if (h < 24) return `${h} ч`;
        const d = Math.floor(h / 24);
        return `${d} д`;
    },

    /** HH:MM in local timezone */
    hhmm: (d: Date = new Date()): string =>
        d.toLocaleString('ru-RU', { hour: '2-digit', minute: '2-digit' }),

    /** Brand display name: "Bmw" → "BMW", "Mercedes Benz" → "Mercedes-Benz" */
    brandName: (name: string | null | undefined): string => {
        if (!name) return '—';
        return BRAND_DISPLAY[name.trim().toLowerCase()] ?? name;
    },

    /** City display name: "almaty" → "Алматы"; неизвестный слаг — капитализация */
    cityName: (slug: string | null | undefined): string => {
        if (!slug) return '—';
        const known = CITY_DISPLAY[slug.trim().toLowerCase()];
        if (known) return known;
        return slug
            .split('-')
            .map(s => (s ? s.charAt(0).toUpperCase() + s.slice(1) : s))
            .join('-');
    },

    /** Russian plural: plural(31, ['город', 'города', 'городов']) → "город" */
    plural: (n: number, forms: [string, string, string]): string => {
        const abs = Math.abs(n) % 100;
        const d = abs % 10;
        if (abs > 10 && abs < 20) return forms[2];
        if (d > 1 && d < 5) return forms[1];
        if (d === 1) return forms[0];
        return forms[2];
    },
};
