from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database.models import Run


class RunRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, run: Run) -> Run:
        self.db.add(run)
        await self.db.flush()
        return run

    async def get_by_id(self, run_id: str) -> Run | None:
        result = await self.db.execute(
            select(Run).where(Run.id == run_id)
        )
        return result.scalar_one_or_none()

    async def list_by_project(
        self,
        project_id: str,
        page_size: int = 100,
        page_token: str | None = None
    ) -> tuple[list[Run], str | None]:
        query = (
            select(Run)
            .where(Run.project_id == project_id)
            .order_by(Run.created_at.desc())
            .limit(page_size)
        )
        
        if page_token:
            query = query.where(Run.id > page_token)
        
        result = await self.db.execute(query)
        runs = list(result.scalars().all())
        
        next_page_token = runs[-1].id if len(runs) == page_size else None
        
        return runs, next_page_token

    async def find_not_done(self, project_id: str | None = None) -> list[Run]:
        """Найти все запуски, которые не в состоянии DONE"""
        query = select(Run).where(Run.state != "RUN_STATE_DONE")
        
        if project_id:
            query = query.where(Run.project_id == project_id)
        
        result = await self.db.execute(query)
        return list(result.scalars().all())

    async def update(self, run: Run) -> Run:
        await self.db.merge(run)
        await self.db.flush()
        return run
