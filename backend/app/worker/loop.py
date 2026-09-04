"""Цикл воркера: BRPOP по очередям Redis, диспатч в обработчики."""
from __future__ import annotations

import asyncio
import json
import logging

from app.config import settings
from app.queue import Q_COMPOSE, Q_EXTRACT, get_redis
from app.worker import jobs

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("worker")

HANDLERS = {
    Q_EXTRACT: jobs.handle_extract,
    Q_COMPOSE: jobs.handle_compose,
}


async def main() -> None:
    client = get_redis()
    log.info("worker started, listening on %s", list(HANDLERS))
    while True:
        try:
            item = await client.blpop(list(HANDLERS), timeout=5)
        except Exception as exc:  # noqa: BLE001 — сеть/redis не должны ронять воркер
            log.error("redis error: %s", exc)
            await asyncio.sleep(2)
            continue
        if item is None:
            continue
        queue, raw = item
        try:
            await HANDLERS[queue](json.loads(raw))
        except Exception:  # noqa: BLE001 — задача не должна ронять воркер
            log.exception("job failed: %s %s", queue, raw)


if __name__ == "__main__":
    asyncio.run(main())
