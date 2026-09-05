"""Запуски мониторинга: создание Run и постановка задач воркеру."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import News, Run
from app.database.repositories.project_repo import ProjectRepository
from app.database.repositories.run_repo import RunRepository
from app.database.repositories.task_repo import TaskRepository
from app.services import mappers

STARTED = "RUN_STATE_STARTED"
DONE = "RUN_STATE_DONE"
FAILED = "RUN_STATE_FAILED"


class RunService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.runs = RunRepository(db)
        self.projects = ProjectRepository(db)
        self.tasks = TaskRepository(db)

    async def start_run(self, project_id: str) -> tuple[Run | None, str | None]:
        """(Run, None) при успехе, (None, причина) — если запускать нечего."""
        project = await self.projects.get_by_id(project_id)
        if project is None:
            return None, "not_found"

        sources = self._collect_sources(project.sources or [])
        if not sources:
            return None, "у проекта нет активных источников"

        run = await self.runs.create(
            Run(
                id=str(uuid.uuid4()),
                project_id=project.id,
                state=STARTED,
                created_at=datetime.utcnow(),
                stats={},
            )
        )

        self.tasks.create_extract_tasks(run.id, project.id, sources)
        return run, None

    @staticmethod
    def _collect_sources(raw_sources: list[dict]) -> list[dict[str, str]]:
        """JSONB-источники проекта -> задания на сбор.

        JSONB хранит Source в форме proto3-JSON, поэтому конвертация идёт через маппер:
        ключ источника и его тип знает контракт, а не этот сервис.
        Источники на паузе (`disabled`) пропускаем.
        """
        out: list[dict[str, str]] = []
        for raw in raw_sources:
            source = mappers.source_to_pb(raw)
            if source.disabled:
                continue
            key = mappers.source_key(source)
            if not key:
                continue
            out.append({"source_type": mappers.source_type_name(source), "source_key": key})
        return out

    async def get_run(self, run_id: str) -> tuple[Run, list[News]] | None:
        run = await self.runs.get_with_news(run_id)
        if run is None:
            return None
        return run, list(run.news)

    async def list_runs(self, project_id: str, page_size: int, page_token: str | None):
        return await self.runs.list_by_project(project_id, page_size, page_token)
