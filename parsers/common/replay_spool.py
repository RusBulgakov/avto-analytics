"""
common/replay_spool.py
Долив спула (parsers/common/spool.py) в БД.

    python -m parsers.common.replay_spool <root> [--done-file replayed.txt]

<root> — каталог, где каждая подпапка = один скачанный GHA-артефакт спула
(имя подпапки = id артефакта), либо просто каталог с *.jsonl.
Каждая строка доливается через save_listing с исходным seen_at, поэтому
долив идемпотентен: повторная строка ничего не меняет.

Имена полностью долитых подпапок пишутся в --done-file — workflow удаляет
только эти артефакты. Если БД всё ещё не принимает запись (переполнение,
обрыв) — долив останавливается с exit 1, и артефакты остаются до следующего
запуска. Строки с ошибками самих данных (DataError/IntegrityError) не
блокируют артефакт: они логируются и считаются «rejected».
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

import asyncpg

from parsers.common.db import (
    _NON_RETRYABLE_DB_ERRORS, close_pool, get_pool, save_listing,
)
from parsers.common.spool import iter_spool_file

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("replay_spool")


class DbUnavailable(Exception):
    pass


async def _replay_file(conn: asyncpg.Connection, path: Path) -> tuple[int, int]:
    ok = rejected = 0
    for rec in iter_spool_file(path):
        data = dict(rec.get("data") or {})
        if not data.get("source") or not data.get("external_id"):
            rejected += 1
            continue
        data["seen_at"] = rec.get("seen_at")
        try:
            await save_listing(conn, data, spool_on_error=False)
            ok += 1
        except _NON_RETRYABLE_DB_ERRORS as e:
            rejected += 1
            logger.warning("rejected %s/%s: %s", data["source"], data["external_id"], e)
        except Exception as e:
            raise DbUnavailable(f"{path.name}: {e}") from e
    return ok, rejected


async def replay(root: Path, done_file: Path | None) -> int:
    groups = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name.zfill(20))
    if not groups and any(root.glob("*.jsonl")):
        groups = [root]  # ручной запуск на плоском каталоге спула
    if not groups:
        logger.info("%s: спул пуст — доливать нечего", root)
    total_ok = total_rej = 0
    done: list[str] = []
    pool = await get_pool()
    try:
        for group in groups:
            files = sorted(group.rglob("*.jsonl"))
            g_ok = g_rej = 0
            try:
                async with pool.acquire() as conn:
                    for f in files:
                        ok, rej = await _replay_file(conn, f)
                        g_ok += ok
                        g_rej += rej
            except DbUnavailable as e:
                logger.error("БД не принимает запись — долив остановлен, артефакты сохранены: %s", e)
                return 1
            total_ok += g_ok
            total_rej += g_rej
            done.append(group.name)
            logger.info("%s: долито %d, rejected %d (%d файлов)", group.name, g_ok, g_rej, len(files))
    finally:
        if done_file is not None:
            done_file.write_text("".join(f"{d}\n" for d in done), encoding="utf-8")
        await close_pool()
    logger.info("итого: долито %d, rejected %d, групп %d", total_ok, total_rej, len(done))
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("root", type=Path)
    ap.add_argument("--done-file", type=Path, default=None)
    args = ap.parse_args()
    if not args.root.is_dir():
        logger.info("%s не существует — доливать нечего", args.root)
        sys.exit(0)
    sys.exit(asyncio.run(replay(args.root, args.done_file)))


if __name__ == "__main__":
    main()
