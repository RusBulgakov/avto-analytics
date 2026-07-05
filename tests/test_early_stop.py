"""Unit-тесты parsers/kolesa/early_stop.py — чистая логика, без сети/БД (t-0017)."""
from parsers.kolesa.early_stop import (
    DEFAULT_EARLY_STOP_PAGES,
    DEFAULT_SORT_PARAM,
    EarlyStopTracker,
    cycle_id,
    early_stop_enabled,
    early_stop_pages,
    sort_param,
)


# ─── EarlyStopTracker: подсчёт подряд идущих страниц без новых ───────────────

def test_disabled_never_stops():
    t = EarlyStopTracker(enabled=False, threshold=3)
    for _ in range(100):
        assert t.record_page(0) is False


def test_stops_after_threshold_consecutive_zero_pages():
    t = EarlyStopTracker(enabled=True, threshold=3)
    assert t.record_page(0) is False
    assert t.record_page(0) is False
    assert t.record_page(0) is True


def test_new_items_reset_counter():
    t = EarlyStopTracker(enabled=True, threshold=3)
    assert t.record_page(0) is False
    assert t.record_page(0) is False
    assert t.record_page(5) is False   # новые объявления → сброс
    assert t.record_page(0) is False
    assert t.record_page(0) is False
    assert t.record_page(0) is True    # снова 3 подряд


def test_pages_with_new_items_never_stop():
    t = EarlyStopTracker(enabled=True, threshold=1)
    for _ in range(50):
        assert t.record_page(1) is False


def test_threshold_one_stops_on_first_zero_page():
    t = EarlyStopTracker(enabled=True, threshold=1)
    assert t.record_page(20) is False
    assert t.record_page(0) is True


def test_threshold_clamped_to_at_least_one():
    t = EarlyStopTracker(enabled=True, threshold=0)
    assert t.record_page(0) is True


# ─── Конфигурация из env ─────────────────────────────────────────────────────

def test_flag_default_off(monkeypatch):
    monkeypatch.delenv("KOLESA_EARLY_STOP", raising=False)
    assert early_stop_enabled() is False


def test_flag_on(monkeypatch):
    monkeypatch.setenv("KOLESA_EARLY_STOP", "1")
    assert early_stop_enabled() is True


def test_flag_requires_exact_one(monkeypatch):
    for val in ("0", "true", "yes", ""):
        monkeypatch.setenv("KOLESA_EARLY_STOP", val)
        assert early_stop_enabled() is False


def test_pages_default(monkeypatch):
    monkeypatch.delenv("KOLESA_EARLY_STOP_PAGES", raising=False)
    assert early_stop_pages() == DEFAULT_EARLY_STOP_PAGES == 3


def test_pages_from_env(monkeypatch):
    monkeypatch.setenv("KOLESA_EARLY_STOP_PAGES", "7")
    assert early_stop_pages() == 7


def test_pages_garbage_falls_back_to_default(monkeypatch):
    monkeypatch.setenv("KOLESA_EARLY_STOP_PAGES", "not-a-number")
    assert early_stop_pages() == DEFAULT_EARLY_STOP_PAGES


def test_pages_clamped_to_one(monkeypatch):
    monkeypatch.setenv("KOLESA_EARLY_STOP_PAGES", "0")
    assert early_stop_pages() == 1


def test_sort_param_default(monkeypatch):
    monkeypatch.delenv("KOLESA_SORT_PARAM", raising=False)
    assert sort_param() == DEFAULT_SORT_PARAM == "sort_by=add_date-desc"


def test_sort_param_override_strips_leading_separators(monkeypatch):
    monkeypatch.setenv("KOLESA_SORT_PARAM", "?sort=new-first")
    assert sort_param() == "sort=new-first"
    monkeypatch.setenv("KOLESA_SORT_PARAM", "&sort=new-first")
    assert sort_param() == "sort=new-first"


def test_sort_param_can_be_disabled_with_empty(monkeypatch):
    monkeypatch.setenv("KOLESA_SORT_PARAM", "")
    assert sort_param() == ""


def test_cycle_id_default_is_utc_date(monkeypatch):
    monkeypatch.delenv("KOLESA_CYCLE_ID", raising=False)
    from datetime import datetime, timezone
    assert cycle_id() == datetime.now(timezone.utc).strftime("%Y-%m-%d")


def test_cycle_id_env_override(monkeypatch):
    monkeypatch.setenv("KOLESA_CYCLE_ID", "run-42")
    assert cycle_id() == "run-42"
