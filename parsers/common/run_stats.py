"""
parsers/common/run_stats.py
Smart-thresholds: детекция «тихой деградации» парсера.

Проблема: парсер может завершиться с exit 0, но сохранить в разы меньше
обычного — сломались селекторы или частичный бан (ровно так молча ломался
OLX до фикса 2026-05-02). Обычные success-уведомления это не ловят.

Решение: после каждого прогона пишем метрики в parser_runs
(миграция database/migrations/003_parser_runs.sql) и сравниваем с последним
УСПЕШНЫМ прогоном той же гранулярности (source_id, shard_index, shard_count) —
шардированный прогон kolesa сравнивается только с таким же шардом, иначе
сравнение shard-run vs full-run было бы бессмысленным.

Если saved или new_count упали больше чем на PARSER_ALERT_DROP_PCT процентов
(default 50) — шлём один ⚠️-алерт в Telegram и записываем прогон со статусом
'degraded'. Деградировавший прогон НЕ становится baseline'ом: следующее
сравнение снова идёт с последним «хорошим» (status='ok') прогоном.
Прошлый прогон ниже шумового порога PARSER_ALERT_MIN_BASE (default 100)
baseline'ом не считается — мелкие фиды не генерируют ложные алерты.

Всё best-effort: любой сбой здесь (нет таблицы, нет сети, нет кредов)
логируется warning'ом и НИКОГДА не роняет сам прогон парсера.
"""
import logging
import os
from typing import Optional

import asyncpg

from parsers.common.db import _parse_database_url
from parsers.common.notifier import send_telegram_message

logger = logging.getLogger(__name__)

DEFAULT_DROP_PCT = 50.0   # алерт, если текущее значение < (100 - pct)% прошлого
DEFAULT_MIN_BASE = 100    # шумовой порог: baseline меньше этого не сравниваем


def evaluate_degradation(
    source_tag: str,
    prev_saved: Optional[int],
    prev_new: Optional[int],
    cur_saved: int,
    cur_new: int,
    drop_pct: float = DEFAULT_DROP_PCT,
    min_base: int = DEFAULT_MIN_BASE,
) -> Optional[str]:
    """
    Чистая функция принятия решения (без БД/сети — легко юнит-тестится).

    Возвращает текст алерта, если метрики текущего прогона упали больше чем
    на drop_pct% относительно прошлого успешного прогона, иначе None.

    Правила:
      - нет baseline (prev_saved is None) → None;
      - метрика прошлого прогона ниже min_base (шумовой порог) → эта метрика
        не проверяется (защита от ложных алертов на мелких фидах);
      - prev <= 0 → метрика не проверяется (и нет ZeroDivisionError);
      - saved и new_count проверяются независимо; сработавшие объединяются
        в ОДИН текст алерта.
    """
    if prev_saved is None:
        return None

    parts: list[str] = []
    for label, prev, cur in (("saved", prev_saved, cur_saved),
                             ("new", prev_new, cur_new)):
        if prev is None or prev < min_base or prev <= 0:
            continue
        threshold_value = prev * (1.0 - drop_pct / 100.0)
        if cur < threshold_value:
            drop = round((1.0 - cur / prev) * 100)
            parts.append(f"{label} {cur:,} vs {prev:,} (-{drop}%)")

    if not parts:
        return None

    return (
        f"⚠️ Деградация парсера {source_tag}: "
        + ", ".join(parts)
        + f" в прошлом успешном прогоне (порог {drop_pct:g}%). "
        f"Возможна поломка селекторов или частичный бан."
    )


async def _connect() -> asyncpg.Connection:
    """
    Отдельное соединение вместо common.db.get_pool(): record_and_alert
    вызывается из нового asyncio.run() после завершения основного цикла
    парсера, а закешированный _pool привязан к уже закрытому event loop.
    statement_cache_size=0 обязателен для Neon PgBouncer (см. common/db.py).
    """
    database_url = os.environ.get("DATABASE_URL")
    if database_url:
        kwargs = _parse_database_url(database_url)
        return await asyncpg.connect(**kwargs, statement_cache_size=0)
    return await asyncpg.connect(
        host=os.environ["POSTGRES_HOST"],
        port=int(os.environ.get("POSTGRES_PORT", 5432)),
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
        database=os.environ["POSTGRES_DB"],
    )


async def record_and_alert(
    source: str,
    saved: int,
    new_count: int,
    *,
    shard_index: int = 0,
    shard_count: int = 1,
    active_after: Optional[int] = None,
) -> Optional[str]:
    """
    Записывает метрики прогона в parser_runs и шлёт ⚠️-алерт при деградации.

    Best-effort: никогда не бросает исключение — сбой мониторинга не должен
    ронять успешный прогон парсера. Возвращает текст алерта (или None),
    чтобы вызывающий мог залогировать результат.
    """
    try:
        drop_pct = float(os.getenv("PARSER_ALERT_DROP_PCT", str(DEFAULT_DROP_PCT)))
        min_base = int(os.getenv("PARSER_ALERT_MIN_BASE", str(DEFAULT_MIN_BASE)))

        source_tag = (f"{source}[{shard_index + 1}/{shard_count}]"
                      if shard_count > 1 else source)

        conn = await _connect()
        try:
            source_id = await conn.fetchval(
                "SELECT id FROM sources WHERE name = $1", source
            )
            if source_id is None:
                logger.warning("run_stats: source %r не найден в sources — пропускаем", source)
                return None

            # Baseline = последний прогон той же гранулярности со status='ok'
            # и saved не ниже шумового порога. Деградировавшие прогоны
            # (status='degraded') baseline не понижают.
            prev = await conn.fetchrow(
                """
                SELECT saved, new_count FROM parser_runs
                WHERE source_id = $1 AND shard_index = $2 AND shard_count = $3
                  AND status = 'ok' AND saved >= $4
                ORDER BY finished_at DESC
                LIMIT 1
                """,
                source_id, shard_index, shard_count, min_base,
            )

            alert = evaluate_degradation(
                source_tag,
                prev["saved"] if prev else None,
                prev["new_count"] if prev else None,
                saved, new_count,
                drop_pct=drop_pct, min_base=min_base,
            )
            status = "degraded" if alert else "ok"

            await conn.execute(
                """
                INSERT INTO parser_runs
                    (source_id, shard_index, shard_count, saved, new_count,
                     active_after, status)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                """,
                source_id, shard_index, shard_count, saved, new_count,
                active_after, status,
            )
        finally:
            await conn.close()

        if alert:
            logger.warning("run_stats: %s", alert)
            # send_telegram_message сам best-effort (лог + False при сбое)
            await send_telegram_message(alert)
        else:
            logger.info(
                "run_stats: прогон %s записан (saved=%d, new=%d, status=ok)",
                source_tag, saved, new_count,
            )
        return alert
    except Exception as e:  # noqa: BLE001 — мониторинг не роняет прогон
        logger.warning(
            "run_stats: не удалось записать/проверить метрики прогона %s (%s) — игнорируем",
            source, e,
        )
        return None
