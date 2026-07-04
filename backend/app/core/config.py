"""
app/core/config.py — Settings через Pydantic BaseSettings
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional
import json


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Neon / serverless — единая строка подключения (приоритет над POSTGRES_*)
    DATABASE_URL: Optional[str] = None

    # DB
    POSTGRES_USER: str = "automarket"
    POSTGRES_PASSWORD: str = "password"
    POSTGRES_DB: str = "automarket_db"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432

    # Redis
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_PASSWORD: str = ""

    # JWT
    SECRET_KEY: str = "change_me_in_production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # CORS
    BACKEND_CORS_ORIGINS: List[str] = ["http://localhost:3000"]

    # Rate limiting (см. app/core/rate_limit.py). Формат: "N/second|minute|hour|day"
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_GLOBAL: str = "120/minute"   # все /api/* эндпоинты, per-IP
    RATE_LIMIT_HEAVY: str = "20/minute"     # profit-ranking, profitability, backtest, forecast, insights/*

    # TTL in-memory кеша /analytics/insights/* (секунды). См. endpoints/insights.py
    INSIGHTS_CACHE_TTL_SEC: int = 3600

    # Sentry (t-0006). Пустой DSN ⇒ Sentry полностью выключен (локалка/CI не шумят).
    SENTRY_DSN: str = ""
    SENTRY_TRACES_SAMPLE_RATE: float = 0.1
    SENTRY_ENVIRONMENT: str = "production"

    @property
    def db_url(self) -> str:
        if self.DATABASE_URL:
            # Заменяем postgresql:// на postgresql+asyncpg:// для SQLAlchemy
            return self.DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def db_url_raw(self) -> str:
        if self.DATABASE_URL:
            # asyncpg: убираем query params (sslmode, channel_binding) из URL —
            # они передаются отдельно через ssl= параметр в create_pool
            return self.DATABASE_URL.split("?")[0]
        return (
            f"postgresql://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @property
    def db_requires_ssl(self) -> bool:
        """True если DATABASE_URL содержит sslmode=require (Neon)"""
        return bool(self.DATABASE_URL and "sslmode=require" in self.DATABASE_URL)

    @property
    def redis_url(self) -> str:
        if self.REDIS_PASSWORD:
            return f"redis://:{self.REDIS_PASSWORD}@{self.REDIS_HOST}:{self.REDIS_PORT}/0"
        return f"redis://{self.REDIS_HOST}:{self.REDIS_PORT}/0"


settings = Settings()
