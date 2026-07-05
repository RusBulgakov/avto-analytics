"""
Тесты TTL-кеша insights-эндпоинтов (app/api/v1/endpoints/insights.py::TTLCache).

БД не нужна: TTLCache — чистая структура данных, время инъектируется
параметром now (monotonic-семантика).
"""
from app.api.v1.endpoints.insights import TTLCache


def test_get_miss_returns_none():
    cache = TTLCache(ttl_seconds=60)
    assert cache.get("nope", now=0.0) is None


def test_set_then_get_within_ttl():
    cache = TTLCache(ttl_seconds=60)
    cache.set("k", {"leaders": [1, 2]}, now=0.0)
    assert cache.get("k", now=59.9) == {"leaders": [1, 2]}


def test_expires_after_ttl():
    cache = TTLCache(ttl_seconds=60)
    cache.set("k", "v", now=0.0)
    assert cache.get("k", now=60.0) is None       # ровно на границе — истёк
    assert len(cache) == 0                        # истёкшая запись удалена при чтении


def test_set_refreshes_ttl():
    cache = TTLCache(ttl_seconds=60)
    cache.set("k", "v1", now=0.0)
    cache.set("k", "v2", now=50.0)                # перезапись сдвигает истечение
    assert cache.get("k", now=100.0) == "v2"
    assert cache.get("k", now=110.5) is None


def test_maxsize_evicts_expired_first():
    cache = TTLCache(ttl_seconds=60, maxsize=2)
    cache.set("old", "v", now=0.0)
    cache.set("live", "v", now=50.0)
    # old к этому моменту истёк → выселяется он, live выживает
    cache.set("new", "v", now=70.0)
    assert cache.get("live", now=70.0) == "v"
    assert cache.get("new", now=70.0) == "v"
    assert cache.get("old", now=70.0) is None
    assert len(cache) == 2


def test_maxsize_evicts_closest_to_expiry_when_all_alive():
    cache = TTLCache(ttl_seconds=60, maxsize=2)
    cache.set("a", "v", now=0.0)                  # истекает в 60
    cache.set("b", "v", now=10.0)                 # истекает в 70
    cache.set("c", "v", now=20.0)                 # все живые → выселяется "a"
    assert cache.get("a", now=20.0) is None
    assert cache.get("b", now=20.0) == "v"
    assert cache.get("c", now=20.0) == "v"
    assert len(cache) == 2


def test_overwrite_does_not_evict_others():
    cache = TTLCache(ttl_seconds=60, maxsize=2)
    cache.set("a", "v1", now=0.0)
    cache.set("b", "v", now=1.0)
    cache.set("a", "v2", now=2.0)                 # перезапись существующего ключа
    assert cache.get("a", now=3.0) == "v2"
    assert cache.get("b", now=3.0) == "v"
