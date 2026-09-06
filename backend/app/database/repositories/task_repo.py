"""Очередь задач воркера в Postgres. Redis больше не хранит очередь — только claim()."""
from __future__ import annotations

import uuid

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Task

EXTRACT = "extract"
COMPOSE = "compose"

# Предикат частичного индекса uq_tasks_compose_per_run — дословно как в миграции.
# Именно text(), а не (Task.kind == COMPOSE): SQLAlchemy 2.0.52 рендерит выражение как
# bound-параметр (`WHERE kind = $1`), а Postgres сверяет ON CONFLICT с предикатом индекса
# текстуально — параметр не совпадёт с литералом, и вставка упадёт
# «no unique or exclusion constraint matching the ON CONFLICT specification».
_COMPOSE_INDEX_WHERE = text("kind = 'compose'")


class TaskRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    def create_extract_tasks(
        self,
        run_id: str,
        project_id: str,
        sources: list[dict[str, str]],
        collection_days: int = 7,
    ) -> None:
        """По задаче на источник. `sources` — [{"source_type": ..., "source_key": ...}].

        Тип источника и период сбора едут в payload, чтобы воркер не ходил повторно
        за проектом: какой коннектор дёргать и на какую глубину — видно прямо из задачи.
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
                        "collection_days": collection_days,
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
            .on_conflict_do_nothing(index_elements=["run_id"], index_where=_COMPOSE_INDEX_WHERE)
        )
        await self.db.execute(stmt)
