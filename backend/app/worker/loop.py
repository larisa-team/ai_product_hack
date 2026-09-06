"""Цикл воркера: поллинг таблицы tasks (Postgres), диспатч в обработчики.

Очередь живёт в Postgres, а не в Redis (см. app/database/models.Task) — на пустом
поллинге воркеру нечего блокирующе ждать в Redis, поэтому здесь нет ничего похожего на
BLPOP и его капризы с клиентским сокет-таймаутом. Redis остался только под claim()
(app/queue.py) — он решает, кто из воркеров реально исполняет задачу, если несколько
одновременно выбрали одну и ту же pending-строку.
"""
from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.database.repositories.task_repo import COMPOSE, EXTRACT, TaskRepository
from app.database.session import async_session
from app.queue import HEARTBEAT_INTERVAL, touch_worker_heartbeat
from app.worker import jobs

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("worker")

HANDLERS = {
    EXTRACT: jobs.handle_extract,
    COMPOSE: jobs.handle_compose,
}

POLL_INTERVAL = 2.0
BATCH_SIZE = 20


async def _heartbeat() -> None:
    """Пульс воркера — отдельной задачей, чтобы `/api/health` был честным и во время
    многоминутного compose с медленными LLM-вызовами (обработчик в это время не может
    ничего трогать сам)."""
    while True:
        try:
            await touch_worker_heartbeat()
        except Exception as exc:  # noqa: BLE001 — Redis моргнул, не роняем воркер
            log.warning("heartbeat: %s", exc)
        await asyncio.sleep(HEARTBEAT_INTERVAL)


async def main() -> None:
    log.info("worker started (poll mode), tasks in postgres, redis только под claim()")
    # Ссылку держим: event loop хранит на задачи только слабые ссылки, без этого
    # _heartbeat может быть собран сборщиком мусора.
    _hb = asyncio.create_task(_heartbeat())  # noqa: F841
    while True:
        try:
            async with async_session() as db:
                tasks = await TaskRepository(db).fetch_pending(limit=BATCH_SIZE)
        except Exception as exc:  # noqa: BLE001 — БД недоступна, не роняем воркер
            log.error("db poll error: %s", exc)
            await asyncio.sleep(POLL_INTERVAL)
            continue

        if not tasks:
            await asyncio.sleep(POLL_INTERVAL)
            continue

        for task in tasks:
            try:
                await HANDLERS[task.kind](task)
            except Exception:  # noqa: BLE001 — задача не должна ронять воркер
                log.exception("job failed: %s %s", task.kind, task.id)


if __name__ == "__main__":
    asyncio.run(main())
