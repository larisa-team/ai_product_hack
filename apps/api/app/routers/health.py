from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.config import get_settings
from app.db import engine

router = APIRouter(prefix="/api", tags=["health"])


def _check_db() -> bool:
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


def _check_redis(url: str) -> bool:
    try:
        import redis

        redis.Redis.from_url(url, socket_connect_timeout=2).ping()
        return True
    except Exception:
        return False


@router.get("/health")
def health() -> dict:
    s = get_settings()
    db_ok = _check_db()
    redis_ok = _check_redis(s.redis_url)
    return {
        "status": "ok" if (db_ok and redis_ok) else "degraded",
        "db": db_ok,
        "redis": redis_ok,
        "llm_provider": s.llm_provider,
    }
