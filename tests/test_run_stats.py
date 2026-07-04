"""Unit-тесты детектора тихой деградации — чистая логика, без сети/БД.

Проверяется parsers/common/run_stats.py::evaluate_degradation:
сравнение метрик текущего прогона с последним успешным baseline'ом.
"""
from parsers.common.run_stats import evaluate_degradation


def test_drop_below_threshold_alerts():
    # 5400 → 1200 = -78%, порог 50% → алерт
    msg = evaluate_degradation("kolesa[1/3]", 5400, 900, 1200, 800)
    assert msg is not None
    assert "kolesa[1/3]" in msg
    assert "saved" in msg
    assert "-78%" in msg
    assert msg.startswith("⚠️")


def test_normal_run_is_silent():
    # Небольшая просадка (-10%) — не алертим
    assert evaluate_degradation("olx", 1000, 200, 900, 190) is None


def test_growth_is_silent():
    assert evaluate_degradation("mycar", 1000, 200, 1500, 300) is None


def test_no_previous_run_is_silent():
    # Первый прогон: baseline'а нет → молчим
    assert evaluate_degradation("newauto", None, None, 5, 5) is None


def test_prev_below_noise_floor_is_silent():
    # Прошлый saved=80 < min_base=100 → мелкий фид, не алертим даже при -90%
    assert evaluate_degradation("avtorynok", 80, 80, 8, 8) is None


def test_zero_prev_no_zero_division():
    # prev=0 не должен ронять ZeroDivisionError и не должен алертить
    assert evaluate_degradation("olx", 0, 0, 0, 0) is None


def test_exact_threshold_boundary_is_silent():
    # Ровно 50% от прошлого — НЕ ниже порога (строгое <) → молчим
    assert evaluate_degradation("olx", 1000, 0, 500, 0) is None


def test_new_count_drop_alone_alerts():
    # saved в норме, но new_count рухнул (1000 → 10 = -99%) → алерт по new
    msg = evaluate_degradation("kolesa", 10000, 1000, 9800, 10)
    assert msg is not None
    assert "new" in msg
    assert "saved" not in msg  # saved не деградировал — в алерте его нет


def test_new_count_below_noise_floor_is_silent():
    # prev_new=50 < min_base → просадка new не проверяется
    assert evaluate_degradation("kolesa", 10000, 50, 9800, 2) is None


def test_both_metrics_in_single_alert():
    # Обе метрики упали → ОДИН алерт с обеими
    msg = evaluate_degradation("olx", 5000, 500, 100, 10)
    assert msg is not None
    assert "saved" in msg
    assert "new" in msg


def test_custom_drop_pct():
    # Порог 90%: -78% не алертит, -95% алертит
    assert evaluate_degradation("kolesa", 5400, 0, 1200, 0, drop_pct=90.0) is None
    assert evaluate_degradation("kolesa", 5400, 0, 200, 0, drop_pct=90.0) is not None


def test_prev_new_none_is_silent_for_new():
    # Старые записи без new_count не должны ломать проверку
    assert evaluate_degradation("olx", 1000, None, 950, 0) is None
