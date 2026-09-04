from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import Project


class ProjectRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, project: Project) -> Project:
        self.db.add(project)
        await self.db.flush()
        return project

    async def get_by_id(self, project_id: str) -> Project | None:
        result = await self.db.execute(
            select(Project).where(Project.id == project_id)
        )
        return result.scalar_one_or_none()

    async def list(self, page_size: int = 100, page_token: str | None = None) -> tuple[list[Project], str | None]:
        query = select(Project).order_by(Project.created_at.desc()).limit(page_size)
        
        if page_token:
            query = query.where(Project.id > page_token)
        
        result = await self.db.execute(query)
        projects = list(result.scalars().all())
        
        next_page_token = projects[-1].id if len(projects) == page_size else None
        
        return projects, next_page_token

    async def update(self, project: Project) -> Project:
        await self.db.merge(project)
        await self.db.flush()
        return project

    async def delete(self, project_id: str) -> bool:
        project = await self.get_by_id(project_id)
        if not project:
            return False
        await self.db.delete(project)
        return True
