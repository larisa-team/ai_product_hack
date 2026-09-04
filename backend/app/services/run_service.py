"""Запуски мониторинга: создание Run и постановка задач воркеру."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import News, Run
from app.database.repositories.project_repo import ProjectRepository
from app.database.repositories.run_repo import RunRepository
from app.queue import Q_EXTRACT, enqueue, set_pending

STARTED = "RUN_STATE_STARTED"
DONE = "RUN_STATE_DONE"
FAILED = "RUN_STATE_FAILED"


class RunService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.runs = RunRepository(db)
        self.projects = ProjectRepository(db)

    async def start_run(self, project_id: str) -> tuple[Run | None, str | None]:
        """(Run, None) при успехе, (None, причина) — если запускать нечего."""
        project = await self.projects.get_by_id(project_id)
        if project is None:
            return None, "not_found"

        channels = [s.get("telegram", "").strip() for s in (project.sources or [])]
        channels = [c for c in channels if c]
        if not channels:
            return None, "у проекта нет источников"

        run = await self.runs.create(
            Run(
                id=str(uuid.uuid4()),
                project_id=project.id,
                state=STARTED,
                created_at=datetime.utcnow(),
                stats={},
            )
        )

        await set_pending(run.id, len(channels))
        for channel in channels:
            await enqueue(
                Q_EXTRACT,
                {"run_id": run.id, "project_id": project.id, "channel": channel},
            )
        return run, None

    async def get_run(self, run_id: str) -> tuple[Run, list[News]] | None:
        run = await self.runs.get_with_news(run_id)
        if run is None:
            return None
        return run, list(run.news)

    async def list_runs(self, project_id: str, page_size: int, page_token: str | None):
        return await self.runs.list_by_project(project_id, page_size, page_token)
