// lib/csv.ts — генерация и скачивание CSV на клиенте (без зависимостей)
//
// RFC 4180: поле экранируется кавычками, если содержит `"`, `,`, `;`, `\n` или `\r`;
// внутренние кавычки удваиваются. Разделитель строк — CRLF (Excel-friendly).
// В начало добавляется UTF-8 BOM, чтобы Excel/Numbers корректно открывали кириллицу.

export type CsvValue = string | number | null | undefined;

/** Экранирует одно значение по RFC 4180. null/undefined → пустое поле. */
function escapeCsvField(value: CsvValue): string {
    if (value == null) return '';
    const s = String(value);
    if (/[",;\r\n]/.test(s)) {
        return `"${s.replace(/"/g, '""')}"`;
    }
    return s;
}

/** Собирает CSV-строку (с UTF-8 BOM) из заголовков и строк данных. */
export function toCsv(headers: string[], rows: CsvValue[][]): string {
    const lines = [headers, ...rows].map(row => row.map(escapeCsvField).join(','));
    return '﻿' + lines.join('\r\n') + '\r\n';
}

/**
 * Убирает из фрагмента имени файла недопустимые символы.
 * Оставляет буквы (включая кириллицу), цифры, `-`; пробелы/прочее → `-`.
 */
export function sanitizeFilenamePart(part: string): string {
    return part
        .replace(/[^\p{L}\p{N}-]+/gu, '-')
        .replace(/-{2,}/g, '-')
        .replace(/^-|-$/g, '');
}

/** Инициирует скачивание CSV-файла в браузере через Blob + <a download>. */
export function downloadCsv(filename: string, csv: string): void {
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}
