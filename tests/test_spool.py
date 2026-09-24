"""Спул несохранённых объявлений: save_listing при сбое БД пишет в JSONL,
ошибки самих данных в спул не попадают, битые строки при чтении пропускаются."""
import asyncio
import json

import asyncpg
import pytest

from parsers.common import db, spool


class _FailingConn:
    def __init__(self, exc):
        self.exc = exc

    async def execute(self, *a, **kw):
        raise self.exc

    async def fetchrow(self, *a, **kw):
        raise self.exc

    async def fetchval(self, *a, **kw):
        raise self.exc


ITEM = {"source": "kolesa", "external_id": "42", "brand_slug": "toyota",
        "model_slug": "camry", "price_kzt": 1_000_000}


@pytest.fixture(autouse=True)
def _spool_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("PARSER_SPOOL_DIR", str(tmp_path / "spool"))
    monkeypatch.setattr(spool, "_spooled", 0)
    return tmp_path / "spool"


def _save(conn, **kw):
    return asyncio.run(db.save_listing(conn, dict(ITEM), **kw))


def test_disk_full_is_spooled_and_reraised(_spool_dir):
    exc = asyncpg.exceptions.DiskFullError("could not extend file")
    with pytest.raises(asyncpg.exceptions.DiskFullError):
        _save(_FailingConn(exc))
    files = list(_spool_dir.glob("kolesa-*.jsonl"))
    assert len(files) == 1
    rec = json.loads(files[0].read_text(encoding="utf-8"))
    assert rec["data"]["external_id"] == "42"
    assert "could not extend file" in rec["error"]
    assert rec["seen_at"]
    assert spool.spooled_count() == 1


def test_data_error_not_spooled(_spool_dir):
    with pytest.raises(asyncpg.exceptions.DataError):
        _save(_FailingConn(asyncpg.exceptions.DataError("smallint out of range")))
    assert not _spool_dir.exists()


def test_replay_does_not_respool(_spool_dir):
    with pytest.raises(ConnectionError):
        _save(_FailingConn(ConnectionError("closed")), spool_on_error=False)
    assert not _spool_dir.exists()


def test_iter_spool_skips_broken_lines(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text('{"seen_at": "2026-09-25T00:00:00+00:00", "data": {"a": 1}}\n{broken\n\n',
                 encoding="utf-8")
    assert [r["data"] for r in spool.iter_spool_file(p)] == [{"a": 1}]


def test_parse_seen_at_naive_is_utc():
    dt = db._parse_seen_at("2026-09-25T10:00:00")
    assert dt.tzinfo is not None and dt.utcoffset().total_seconds() == 0
    assert db._parse_seen_at(None) is None
