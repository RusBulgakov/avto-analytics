"""
Тесты Sentry-init (t-0006).

Критерий: с пустым SENTRY_DSN приложение импортируется как раньше,
а Sentry SDK остаётся неактивным (init не вызывался).
Сеть/БД не нужны.
"""
import sentry_sdk

import app.main  # noqa: F401 — сам импорт и есть проверяемое поведение
from app.core.config import settings


def test_sentry_dsn_empty_by_default():
    """Дефолт SENTRY_DSN — пустая строка: локалка/CI без Sentry."""
    assert settings.SENTRY_DSN == ""
    assert settings.SENTRY_TRACES_SAMPLE_RATE == 0.1
    assert settings.SENTRY_ENVIRONMENT == "production"


def test_sentry_not_initialized_with_empty_dsn():
    """Пустой DSN ⇒ sentry_sdk.init не вызывался, клиент неактивен."""
    assert not sentry_sdk.get_client().is_active()
