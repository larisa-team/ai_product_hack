"""FastAPI-приложение: Connect-RPC из proto + служебный health."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.registry import register_all
from app.config import settings
from app.connect import (
    ConnectError,
    connect_error_handler,
    registry,
    router as connect_router,
    unhandled_error_handler,
)
from app.database.session import engine

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = FastAPI(title="Monitoring API", docs_url=None, redoc_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.add_exception_handler(ConnectError, connect_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)

# Регистрируем реализации RPC в реестре Connect
register_all()
app.include_router(connect_router, prefix="/api", tags=["connect"])


@app.get("/api/health")
async def health() -> dict:
    db_ok = True
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        db_ok = False

    redis_ok = True
    worker_ok = False
    try:
        from app.queue import ping_redis, worker_alive

        redis_ok = await ping_redis()
        if redis_ok:
            worker_ok = await worker_alive()
    except Exception:
        redis_ok = False

    return {
        "status": "ok" if (db_ok and redis_ok and worker_ok) else "degraded",
        "db": db_ok,
        "redis": redis_ok,
        "worker": worker_ok,
        "llm_provider": settings.LLM_PROVIDER,
        "rpc": registry.describe(),
    }
