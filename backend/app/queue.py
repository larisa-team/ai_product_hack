"""Redis: только claim-локи «взято в работу» и heartbeat воркера.

Очередь задач переехала в Postgres (см. app/database/models.Task,
app/database/repositories/task_repo.py) — воркер поллит таблицу, а не блокируется на
Redis-списке. Redis здесь решает только один вопрос: если несколько воркеров одновременно
выбрали одну и ту же pending-задачу (обычный `SELECT`, без блокировки строки), кто из них
реально её исполняет.
"""
from __future__ import annotations

import redis.asyncio as redis

from app.config import settings

# extract — один HTTP-запрос к t.me, укладывается с запасом.
# compose — несколько батчей filter+news-maker к reasoning-модели, каждый может занять
# десятки секунд; на большом Run суммарно должно укладываться с запасом, иначе claim
# истечёт раньше, чем задача реально закончится, и другой воркер возьмёт её повторно.
CLAIM_TTL_EXTRACT = 600
CLAIM_TTL_COMPOSE = 1800

# Воркер обновляет этот ключ на каждом тике поллинга (см. worker/loop.py). Если ключ
# просрочен или отсутствует — воркер не пишет в Redis: либо упал, либо завис.
# HEARTBEAT_TTL с запасом больше интервала поллинга.
WORKER_HEARTBEAT_KEY = "worker:heartbeat"
HEARTBEAT_TTL = 15

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(
            settings.REDIS_URL,
            decode_responses=True,
            socket_timeout=15,
            socket_connect_timeout=5,
        )
    return _client


async def ping_redis() -> bool:
    try:
        return bool(await get_redis().ping())
    except Exception:
        return False


async def claim(job_id: str, ttl: int = 600) -> bool:
    """True — задачу взяли мы, False — её уже держит другой воркер."""
    return bool(await get_redis().set(f"claim:{job_id}", "1", nx=True, ex=ttl))


async def touch_worker_heartbeat() -> None:
    await get_redis().set(WORKER_HEARTBEAT_KEY, "1", ex=HEARTBEAT_TTL)


async def worker_alive() -> bool:
    try:
        return bool(await get_redis().exists(WORKER_HEARTBEAT_KEY))
    except Exception:
        return False
