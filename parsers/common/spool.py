"""
common/spool.py
Спул несохранённых объявлений — страховка «данные собираются всегда».

Если save_listing не смог записать объявление (Neon упёрся в лимит 512 MB,
compute недоступен, pooler оборвал соединение), спарсенные данные не
теряются: строка уходит в JSONL-файл PARSER_SPOOL_DIR/<source>-<pid>.jsonl
вместе с моментом наблюдения (seen_at). В GitHub Actions каталог спула
заливается артефактом, а workflow replay_spool.yml доливает его в БД через
тот же save_listing с исходным seen_at (last_seen_at/price_history получают
реальное время наблюдения, а не время долива).

Прецедент: 2026-09-20…25 Neon был переполнен, все парсеры несколько суток
качали страницы впустую — всё спарсенное терялось с WARNING в логе.

Формат строки: {"seen_at": iso8601-utc, "error": str, "data": {...save_listing dict}}
"""
from __future__ import annotations

import atexit
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

logger = logging.getLogger(__name__)

_spooled = 0


def spool_dir() -> Path:
    return Path(os.getenv("PARSER_SPOOL_DIR", "spool"))


def spooled_count() -> int:
    return _spooled


def spool_listing(data: dict, error: BaseException | str) -> None:
    """Дописывает объявление в спул. Никогда не бросает исключений:
    сбой спула не должен ронять парсер (хуже — только потерять и спул)."""
    global _spooled
    try:
        seen_at = data.get("seen_at") or datetime.now(timezone.utc).isoformat()
        payload = {k: v for k, v in data.items() if k != "seen_at"}
        line = json.dumps(
            {"seen_at": str(seen_at), "error": str(error)[:300], "data": payload},
            ensure_ascii=False, default=str,
        )
        d = spool_dir()
        d.mkdir(parents=True, exist_ok=True)
        source = str(data.get("source") or "unknown")
        with open(d / f"{source}-{os.getpid()}.jsonl", "a", encoding="utf-8") as f:
            f.write(line + "\n")
        if _spooled == 0:
            logger.warning(
                "БД не принимает запись (%s) — объявления пишутся в спул %s",
                str(error)[:200], d,
            )
        _spooled += 1
    except Exception as e:  # pragma: no cover — защитный путь
        logger.error("spool: не удалось сохранить в спул: %s", e)


def iter_spool_file(path: Path) -> Iterator[dict]:
    """Строки спула; битые (оборванная запись) пропускаются с предупреждением."""
    with open(path, encoding="utf-8") as f:
        for n, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                yield json.loads(raw)
            except json.JSONDecodeError:
                logger.warning("spool %s:%d: битая строка пропущена", path, n)


@atexit.register
def _report() -> None:
    if not _spooled:
        return
    msg = (
        f"{_spooled} объявлений не записаны в БД и сохранены в спул "
        f"{spool_dir()} — их дольёт workflow replay_spool.yml"
    )
    logger.warning(msg)
    if os.getenv("GITHUB_ACTIONS") == "true":
        # Аннотация видна на странице прогона, даже если job зелёный
        print(f"::warning title=Spool::{msg}", flush=True)
