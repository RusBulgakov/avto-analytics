"""
Backend FastAPI приложение — точка входа.
"""
from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.database import init_db, pool_stats
from app.core.rate_limit import RateLimitMiddleware
from app.api.v1.router import api_router

logger = logging.getLogger(__name__)

# Sentry (t-0006) — инициализируем ДО создания app, чтобы интеграция FastAPI
# успела обернуть все middleware/handlers. Пустой SENTRY_DSN ⇒ полный no-op:
# sentry_sdk даже не импортируется, локалка и CI не шумят.
if settings.SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=settings.SENTRY_DSN,
        traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
        send_default_pii=False,
        environment=settings.SENTRY_ENVIRONMENT,
    )
    logger.info("Sentry инициализирован (environment=%s)", settings.SENTRY_ENVIRONMENT)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Инициализация и cleanup при старте/остановке сервера."""
    await init_db()
    logger.info("База данных подключена")
    yield
    logger.info("Сервер остановлен")


app = FastAPI(
    title="Авторынок Аналитика KZ — API",
    description="RESTful API для аналитической платформы авторынка Казахстана",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# Rate limiter добавлен ДО CORSMiddleware намеренно: в Starlette последний
# add_middleware — внешний, поэтому CORS оборачивает лимитер и 429-ответы
# тоже получают CORS-заголовки (иначе браузер не смог бы прочитать 429).
app.add_middleware(
    RateLimitMiddleware,
    enabled=settings.RATE_LIMIT_ENABLED,
    global_rate=settings.RATE_LIMIT_GLOBAL,
    heavy_rate=settings.RATE_LIMIT_HEAVY,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api/v1")


@app.get("/health", tags=["health"])
async def health():
    # pool — интроспекция asyncpg-пула без запросов к БД (мониторинг утечек
    # соединений к Neon Pooler, t-0015). null пока пул не инициализирован.
    return {"status": "ok", "service": "automarket-api", "pool": pool_stats()}
