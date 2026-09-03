"""BRPOP-цикл воркера: слушает очереди и диспатчит задачи в jobs."""
from __future__ import annotations

import json
import logging
import time

import redis

from app.queue import Q_COMPOSE, Q_EXTRACT, get_redis
from app.worker import jobs

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("worker")

HANDLERS = {
    Q_EXTRACT: jobs.handle_extract,
    Q_COMPOSE: jobs.handle_compose,
}


def main() -> None:
    client = get_redis()
    log.info("worker started, listening on %s", list(HANDLERS))
    while True:
        try:
            item = client.blpop(list(HANDLERS), timeout=5)
        except redis.RedisError as exc:  # pragma: no cover
            log.error("redis error: %s", exc)
            time.sleep(2)
            continue
        if item is None:
            continue
        queue, raw = item
        try:
            payload = json.loads(raw)
            HANDLERS[queue](payload)
        except Exception:  # noqa: BLE001 — задача не должна ронять воркер
            log.exception("job failed: %s %s", queue, raw)


if __name__ == "__main__":
    main()
