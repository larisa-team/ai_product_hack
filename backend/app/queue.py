"""Redis: очереди задач воркера, claim-ключи «взято в работу», счётчик прогресса Run."""
from __future__ import annotations

import json
from typing import Any

import redis.asyncio as redis

from app.config import settings

Q_EXTRACT = "q:extract"
Q_COMPOSE = "q:compose"

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(settings.REDIS_URL, decode_responses=True)
    return _client


async def ping_redis() -> bool:
    try:
        return bool(await get_redis().ping())
    except Exception:
        return False


async def enqueue(queue: str, payload: dict[str, Any]) -> None:
    await get_redis().rpush(queue, json.dumps(payload))


async def claim(job_id: str, ttl: int = 600) -> bool:
    """True — задачу взяли мы, False — её уже держит другой воркер."""
    return bool(await get_redis().set(f"claim:{job_id}", "1", nx=True, ex=ttl))


async def set_pending(run_id: str, n: int) -> None:
    await get_redis().set(f"run:{run_id}:pending", n, ex=3600)


async def dec_pending(run_id: str) -> int:
    return int(await get_redis().decr(f"run:{run_id}:pending"))
