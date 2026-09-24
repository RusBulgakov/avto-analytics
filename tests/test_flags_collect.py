"""collect_filter_ids: признак полноты сбора решает, можно ли сбрасывать флаги.
Оборванный tarpit'ом сбор (ошибки подряд) не должен считаться полным."""
import asyncio

import pytest

from parsers.kolesa import flags


def _run(pages, monkeypatch):
    async def fake_fetch(session, url, page):
        return pages.get(page)

    async def no_sleep(*_a, **_kw):
        return None

    monkeypatch.setattr(flags, "_fetch_page", fake_fetch)
    monkeypatch.setattr(flags.asyncio, "sleep", no_sleep)
    return asyncio.run(flags.collect_filter_ids(None, "https://kolesa.kz/cars/?need-repair=1", "t"))


def _page(*ids):
    return "".join(f'<a href="/a/show/{i}">x</a>' for i in ids)


def test_natural_end_is_complete(monkeypatch):
    ids, complete = _run({1: _page(1, 2), 2: _page(3), 3: "<html>no listings</html>"}, monkeypatch)
    assert ids == {"1", "2", "3"} and complete is True


def test_tarpit_errors_are_incomplete(monkeypatch):
    # страницы 3+ не отдаются (None) — 3 ошибки подряд
    ids, complete = _run({1: _page(1), 2: _page(2)}, monkeypatch)
    assert ids == {"1", "2"} and complete is False


def test_empty_first_page_is_not_trusted(monkeypatch):
    ids, complete = _run({1: "<html>layout changed</html>"}, monkeypatch)
    assert ids == set() and complete is False


def test_max_pages_cap_is_incomplete(monkeypatch):
    monkeypatch.setattr(flags, "MAX_PAGES", 2)
    ids, complete = _run({1: _page(1), 2: _page(2), 3: _page(3)}, monkeypatch)
    assert ids == {"1", "2"} and complete is False
