// lib/format.ts — shared formatting helpers (matches design_handoff/components.jsx fmt)

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
};
