"""Redis: очереди задач, claim-ключи, счётчик прогресса Run."""
from __future__ import annotations

import json
from typing import Any

import redis

from app.config import get_settings

Q_EXTRACT = "q:extract"
Q_COMPOSE = "q:compose"

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.Redis.from_url(get_settings().redis_url, decode_responses=True)
    return _client


def enqueue(queue: str, payload: dict[str, Any]) -> None:
    get_redis().rpush(queue, json.dumps(payload))


def claim(job_id: str, ttl: int = 600) -> bool:
    """True — задачу взяли, False — её уже кто-то держит."""
    return bool(get_redis().set(f"claim:{job_id}", "1", nx=True, ex=ttl))


def set_pending(run_id: str, n: int) -> None:
    get_redis().set(f"run:{run_id}:pending", n, ex=3600)


def dec_pending(run_id: str) -> int:
    return int(get_redis().decr(f"run:{run_id}:pending"))
