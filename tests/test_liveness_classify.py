"""Unit-тесты классификатора liveness — чистая логика, без сети/БД."""
from parsers.kolesa.liveness_classify import classify_listing, ALIVE, CLOSED, TRANSIENT

# Реальные маркеры со страниц kolesa /a/show/{id} (см. спеку §1):
# живой лист → <title> с "№{id}" и "цена ...₸", canonical на /a/show/{id}.
ALIVE_BODY = (
    '<html><head><title>Продажа ВАЗ (Lada) Kalina 2013 года в Актобе - '
    '№221153415: цена 3250000₸. Купить — Колёса</title>'
    '<link rel="canonical" href="https://kolesa.kz/a/show/221153415"/></head></html>'
)
# 404-страница kolesa возвращает дженерик-главную: общий title, без №id/canonical.
DEAD_BODY = (
    '<html><head><title>Колёса — продажа авто в Казахстане. Весь авторынок '
    'Казахстана на одном сайте</title></head><body>страница не найдена</body></html>'
)

def test_404_is_closed():
    assert classify_listing(404, DEAD_BODY, "217539026") == CLOSED

def test_410_is_closed():
    assert classify_listing(410, "", "217539026") == CLOSED

def test_200_with_listing_markers_is_alive():
    assert classify_listing(200, ALIVE_BODY, "221153415") == ALIVE

def test_200_soft404_without_markers_is_closed():
    # 200, но тело — дженерик-главная без №id/canonical → soft-404 → closed
    assert classify_listing(200, DEAD_BODY, "221153415") == CLOSED

def test_200_wrong_id_is_closed():
    # 200 с маркерами ДРУГОГО объявления (редирект на похожее) → не наш лист
    assert classify_listing(200, ALIVE_BODY, "999999999") == CLOSED

def test_5xx_is_transient():
    assert classify_listing(503, "", "221153415") == TRANSIENT

def test_network_error_is_transient():
    # -1 = network/timeout (см. liveness._check_one)
    assert classify_listing(-1, None, "221153415") == TRANSIENT

def test_429_is_transient():
    # rate-limit — НЕ закрываем, перечекаем
    assert classify_listing(429, "", "221153415") == TRANSIENT
