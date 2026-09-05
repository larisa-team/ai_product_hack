"""Лента новостей проекта: чтение с фильтрами, правка карточки, ручное добавление.

Р11: правки пользователя не перезатираются. Здесь это соблюдается тем, что compose
всегда создаёт новые строки News, а не обновляет старые — то есть UpdateNews ниже
трогает только то, что руками и завели.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import News
from app.database.repositories.news_repo import NewsRepository

# Поля, которые UpdateNews умеет менять. Пустая маска = менять всё перечисленное.
UPDATABLE = ("title", "content", "category", "importance", "tags", "hidden")


class NewsService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = NewsRepository(db)

    async def list_news(self, **filters) -> tuple[list[News], str | None, int]:
        page = await self.repo.list_filtered(**filters)
        total = await self.repo.count_for_project(
            filters["project_id"], include_hidden=filters.get("include_hidden", False)
        )
        return page[0], page[1], total

    async def update_news(self, news_id: int, changes: dict) -> News | None:
        news = await self.repo.get_by_id(news_id)
        if news is None:
            return None
        for field, value in changes.items():
            setattr(news, field, value)
        await self.db.flush()
        return news

    async def create_news(
        self,
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
        news = self.repo.new_manual(
            project_id=project_id,
            title=title,
            content=content,
            sources=sources,
            category=category,
            importance=importance,
            doc_type=doc_type,
            tags=tags,
        )
        return await self.repo.create(news)
