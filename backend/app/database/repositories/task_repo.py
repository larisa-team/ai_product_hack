"""Очередь задач воркера в Postgres. Redis больше не хранит очередь — только claim()."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Task

EXTRACT = "extract"
COMPOSE = "compose"


class TaskRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def create_extract_tasks(
        self, run_id: str, project_id: str, sources: list[dict[str, str]]
    ) -> None:
        """По задаче на источник. `sources` — [{"source_type": ..., "source_key": ...}].

        Тип источника едет в payload, чтобы воркер не ходил повторно за проектом:
        какой коннектор дёргать, видно прямо из задачи.
        """
        for source in sources:
            self.db.add(
                Task(
                    id=str(uuid.uuid4()),
                    run_id=run_id,
                    kind=EXTRACT,
                    payload={
                        "project_id": project_id,
                        "source_type": source["source_type"],
                        "source_key": source["source_key"],
                    },
                )
            )

    async def fetch_pending(self, limit: int = 20) -> list[Task]:
        result = await self.db.execute(
            select(Task).where(Task.status == "pending").order_by(Task.created_at).limit(limit)
        )
        return list(result.scalars().all())

    async def mark_done(self, task_id: str) -> None:
        await self.db.execute(update(Task).where(Task.id == task_id).values(status="done"))

    async def count_pending(self, run_id: str, kind: str) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(Task)
            .where(Task.run_id == run_id, Task.kind == kind, Task.status == "pending")
        )
        return int(result.scalar_one())

    async def enqueue_compose_if_ready(self, run_id: str) -> None:
        """Ставит compose-задачу, если у прогона больше нет pending extract-задач."""
        if await self.count_pending(run_id, EXTRACT) > 0:
            return
        stmt = (
            pg_insert(Task)
            .values(id=str(uuid.uuid4()), run_id=run_id, kind=COMPOSE, payload={})
            .on_conflict_do_nothing(index_elements=["run_id"], index_where=(Task.kind == COMPOSE))
        )
        await self.db.execute(stmt)
