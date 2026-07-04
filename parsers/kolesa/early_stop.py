"""
parsers/kolesa/early_stop.py — Phase 2 discovery: early-stop + resumable cursor
(t-0017, спека docs/superpowers/specs/2026-06-04-kolesa-stable-parser-design.md §5.3).

╔══════════════════════════════════════════════════════════════════════════╗
║ ОПАСНО ВКЛЮЧАТЬ БЕЗ LIVENESS! KOLESA_EARLY_STOP=0 по умолчанию.           ║
║                                                                            ║
║ Ранняя остановка фида означает, что глубокие страницы (старые объявления)  ║
║ перестают получать бамп last_seen_at от discovery. По дизайну их живость   ║
║ должна подтверждать liveness-sweep (§5.2), но он сейчас ЗАБЛОКИРОВАН       ║
║ (kolesa тарпитит detail-GET'ы с IP GitHub Actions — backlog t-0016).       ║
║ Если включить early-stop сейчас, слепой 168h-deactivate массово убьёт      ║
║ живые объявления с глубоких страниц. Включать KOLESA_EARLY_STOP=1 ТОЛЬКО   ║
║ после того, как liveness работает (или принято решение по t-0016).         ║
╚══════════════════════════════════════════════════════════════════════════╝

Три составляющие (все активны ТОЛЬКО при KOLESA_EARLY_STOP=1):

1. Sort newest-first — query-param сортировки «по дате, свежие первыми»
   добавляется к URL каждого фида. Точное имя параметра kolesa.kz в спеке
   помечено «подтвердить при реализации» — поэтому оно конфигурируемо через
   KOLESA_SORT_PARAM (default: «sort_by=add_date-desc», исторически
   используемый kolesa.kz формат). Если параметр окажется неверным — это
   правка env-переменной, не кода. Проверка перед включением: открыть
   https://kolesa.kz/cars/?<KOLESA_SORT_PARAM> в браузере и убедиться, что
   выбрана сортировка «По дате добавления» (свежие сверху).

2. Early-stop — семантика «нового»: save_listing возвращает is_new из
   `RETURNING (xmax = 0)`, т.е. новый = INSERT (объявления не было в БД
   вообще). Дополнительных запросов не нужно — parse_city уже считает
   page_new. Фид останавливается после KOLESA_EARLY_STOP_PAGES (default 3)
   подряд страниц с 0 новых. При newest-first это значит «дошли до уже
   известных объявлений» — хвост фида не даст новых.

3. Резюмируемый курсор — parse_cursor(source_id, feed_key, last_page,
   cycle_id) (миграция database/migrations/004_parse_cursor.sql).
   cycle_id = KOLESA_CYCLE_ID env, иначе UTC-дата (YYYY-MM-DD): один
   discovery-цикл в сутки. Повторный запуск в тот же день продолжает фид
   со страницы last_page+1; новый день (другой cycle_id) — фид с начала.
   Запись после каждой страницы, best-effort (ошибка курсора не роняет фид).
"""
import logging
import os
from datetime import datetime, timezone

logger = logging.getLogger("parser.kolesa.early_stop")

DEFAULT_SORT_PARAM = "sort_by=add_date-desc"
DEFAULT_EARLY_STOP_PAGES = 3


# ─── Конфигурация (env читается в момент вызова — тестируемо monkeypatch'ем) ──

def early_stop_enabled() -> bool:
    """Мастер-флаг Phase 2. Default '0' = поведение парсера идентично прежнему."""
    return os.getenv("KOLESA_EARLY_STOP", "0") == "1"


def early_stop_pages() -> int:
    """Сколько подряд страниц с 0 новых объявлений останавливают фид (>= 1)."""
    try:
        pages = int(os.getenv("KOLESA_EARLY_STOP_PAGES", str(DEFAULT_EARLY_STOP_PAGES)))
    except ValueError:
        return DEFAULT_EARLY_STOP_PAGES
    return max(1, pages)


def sort_param() -> str:
    """
    Query-param сортировки newest-first (без ведущих '?'/'&').
    Пустая строка = сортировку не добавлять.
    """
    return os.getenv("KOLESA_SORT_PARAM", DEFAULT_SORT_PARAM).strip().lstrip("?&")


def cycle_id() -> str:
    """Идентификатор discovery-цикла: KOLESA_CYCLE_ID env или UTC-дата YYYY-MM-DD."""
    explicit = os.getenv("KOLESA_CYCLE_ID", "").strip()
    if explicit:
        return explicit
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


# ─── Чистая логика early-stop (unit-тестируется без сети/БД) ─────────────────

class EarlyStopTracker:
    """
    Считает подряд идущие страницы без новых объявлений.

    record_page(new_count) -> True, когда фид пора остановить:
    threshold подряд страниц с new_count == 0. Любая страница с new_count > 0
    сбрасывает счётчик. При enabled=False НИКОГДА не возвращает True.
    """

    def __init__(self, enabled: bool, threshold: int):
        self.enabled = enabled
        self.threshold = max(1, threshold)
        self.consecutive_zero_pages = 0

    def record_page(self, new_count: int) -> bool:
        if not self.enabled:
            return False
        if new_count > 0:
            self.consecutive_zero_pages = 0
            return False
        self.consecutive_zero_pages += 1
        return self.consecutive_zero_pages >= self.threshold


# ─── Курсор в БД (вызывается из parser.py ТОЛЬКО при early_stop_enabled()) ───

async def load_cursor(conn, source: str, feed_key: str, cycle: str) -> int:
    """
    Возвращает last_page фида для ТЕКУЩЕГО цикла (0, если курсора нет или он
    от другого цикла — фид начинается с 1-й страницы).
    """
    row = await conn.fetchrow(
        """
        SELECT last_page FROM parse_cursor
        WHERE source_id = (SELECT id FROM sources WHERE name = $1)
          AND feed_key = $2 AND cycle_id = $3
        """,
        source, feed_key, cycle,
    )
    return row["last_page"] if row else 0


async def save_cursor(conn, source: str, feed_key: str, page: int, cycle: str) -> None:
    """Upsert курсора после обработанной страницы. Новый cycle_id перезаписывает старый."""
    await conn.execute(
        """
        INSERT INTO parse_cursor (source_id, feed_key, last_page, cycle_id, updated_at)
        SELECT id, $2, $3, $4, NOW() FROM sources WHERE name = $1
        ON CONFLICT (source_id, feed_key) DO UPDATE
            SET last_page = EXCLUDED.last_page,
                cycle_id = EXCLUDED.cycle_id,
                updated_at = NOW()
        """,
        source, feed_key, page, cycle,
    )
