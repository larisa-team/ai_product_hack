import uuid
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import Project
from app.database.repositories.project_repo import ProjectRepository


class ProjectService:
    def __init__(self, db: AsyncSession):
        self.repo = ProjectRepository(db)

    async def create_project(
        self,
        name: str,
        topic: str,
        filters: list[dict],
        sources: list[dict]
    ) -> Project:
        project = Project(
            id=str(uuid.uuid4()),
            name=name,
            topic=topic,
            filters=filters,
            sources=sources,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        return await self.repo.create(project)

    async def get_project(self, project_id: str) -> Project | None:
        return await self.repo.get_by_id(project_id)

    async def list_projects(self, page_size: int = 100, page_token: str | None = None):
        return await self.repo.list(page_size, page_token)

    async def update_project(
        self,
        project_id: str,
        name: str | None = None,
        topic: str | None = None,
        filters: list[dict] | None = None,
        sources: list[dict] | None = None
    ) -> Project | None:
        project = await self.repo.get_by_id(project_id)
        if not project:
            return None
        
        if name is not None:
            project.name = name
        if topic is not None:
            project.topic = topic
        if filters is not None:
            project.filters = filters
        if sources is not None:
            project.sources = sources
        
        project.updated_at = datetime.utcnow()
        
        return await self.repo.update(project)

    async def delete_project(self, project_id: str) -> bool:
        return await self.repo.delete(project_id)
