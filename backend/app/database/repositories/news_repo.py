"""Доступ к карточкам новостей: лента проекта с фильтрами, правка, ручное добавление."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import News


class NewsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, news_id: int) -> News | None:
        return await self.db.get(News, news_id)

    async def create(self, news: News) -> News:
        self.db.add(news)
        await self.db.flush()
        return news

    async def list_filtered(
        self,
        *,
        project_id: str,
        categories: list[str] | None = None,
        importances: list[str] | None = None,
        source: str | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
        query: str | None = None,
        include_hidden: bool = False,
        page_size: int = 50,
        page_token: str | None = None,
    ) -> tuple[list[News], str | None]:
        """Лента проекта. Пагинация — keyset по News.id (реальный autoincrement),
        а не по created_at: id монотонен, поэтому `id < cursor` не пропускает и не
        дублирует строки при равных датах.
        """
        stmt = select(News).where(News.project_id == project_id)

        if not include_hidden:
            stmt = stmt.where(News.hidden.is_(False))
        if categories:
            stmt = stmt.where(News.category.in_(categories))
        if importances:
            stmt = stmt.where(News.importance.in_(importances))
        if source:
            # News.sources — JSONB-массив строк; `?` — «содержит такой элемент».
            stmt = stmt.where(News.sources.op("?")(source))
        if date_from is not None:
            stmt = stmt.where(News.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(News.created_at <= date_to)
        if query:
            like = f"%{query}%"
            stmt = stmt.where(or_(News.title.ilike(like), News.content.ilike(like)))
        if page_token:
            stmt = stmt.where(News.id < int(page_token))

        stmt = stmt.order_by(News.id.desc()).limit(page_size)

        rows = list((await self.db.execute(stmt)).scalars().all())
        next_token = str(rows[-1].id) if len(rows) == page_size else None
        return rows, next_token

    async def count_for_project(self, project_id: str, include_hidden: bool = False) -> int:
        from sqlalchemy import func

        stmt = select(func.count()).select_from(News).where(News.project_id == project_id)
        if not include_hidden:
            stmt = stmt.where(News.hidden.is_(False))
        return int((await self.db.execute(stmt)).scalar_one())

    @staticmethod
    def new_manual(
        *,
        project_id: str,
        title: str,
        content: str,
        sources: list[str],
        category: str,
        importance: str,
        doc_type: str,
        tags: list[str],
    ) -> News:
        """Карточка, добавленная руками: без run_id, без сущностей от LLM."""
        return News(
            id=None,
            project_id=project_id,
            run_id=None,
            title=title,
            content=content,
            sources=sources,
            category=category,
            importance=importance,
            doc_type=doc_type,
            entities={},
            tags=tags,
            hidden=False,
            created_at=datetime.utcnow(),
        )
