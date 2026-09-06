"""Реализация monitoring.v1.NewsService."""
from __future__ import annotations

from monitoring.v1 import monitoring_pb2 as pb
from sqlalchemy.ext.asyncio import AsyncSession

from app.connect import ConnectError, Method, registry
from app.services import mappers
from app.services.news_service import UPDATABLE, NewsService

SERVICE = "monitoring.v1.NewsService"


def _ts_to_dt(ts):
    """google.protobuf.Timestamp -> naive datetime; незаполненный -> None."""
    if ts is None or (ts.seconds == 0 and ts.nanos == 0):
        return None
    return ts.ToDatetime()


async def list_news(req: pb.ListNewsRequest, db: AsyncSession) -> pb.ListNewsResponse:
    if not req.project_id:
        raise ConnectError("invalid_argument", "project_id обязателен")

    rows, next_token, total = await NewsService(db).list_news(
        project_id=req.project_id,
        categories=[mappers.category_name(c) for c in req.categories] or None,
        importances=[mappers.importance_name(i) for i in req.importances] or None,
        source=req.source or None,
        date_from=_ts_to_dt(req.published_from),
        date_to=_ts_to_dt(req.published_to),
        query=req.q or None,
        include_hidden=req.include_hidden,
        page_size=req.page_size or 50,
        page_token=req.page_token or None,
    )
    return pb.ListNewsResponse(
        news=[mappers.news_to_pb(n) for n in rows],
        next_page_token=next_token or "",
        total=total,
    )


async def update_news(req: pb.UpdateNewsRequest, db: AsyncSession) -> pb.UpdateNewsResponse:
    paths = set(req.update_mask.paths) if req.update_mask.paths else set(UPDATABLE)
    unknown = paths - set(UPDATABLE)
    if unknown:
        raise ConnectError("invalid_argument", f"update_mask: неизвестные поля {sorted(unknown)}")

    changes: dict = {}
    if "title" in paths:
        changes["title"] = req.title
    if "content" in paths:
        changes["content"] = req.content
    if "category" in paths:
        changes["category"] = mappers.category_name(req.category)
    if "importance" in paths:
        changes["importance"] = mappers.importance_name(req.importance)
    if "tags" in paths:
        changes["tags"] = list(req.tags)
    if "hidden" in paths:
        changes["hidden"] = req.hidden

    news = await NewsService(db).update_news(req.id, changes)
    if news is None:
        raise ConnectError("not_found", f"новость {req.id} не найдена")
    return pb.UpdateNewsResponse(news=mappers.news_to_pb(news))


async def create_news(req: pb.CreateNewsRequest, db: AsyncSession) -> pb.CreateNewsResponse:
    if not req.project_id:
        raise ConnectError("invalid_argument", "project_id обязателен")
    if not req.title.strip() or not req.content.strip():
        raise ConnectError("invalid_argument", "title и content обязательны")

    news = await NewsService(db).create_news(
        project_id=req.project_id,
        title=req.title.strip(),
        content=req.content.strip(),
        sources=list(req.sources),
        category=mappers.category_name(req.category),
        importance=mappers.importance_name(req.importance),
        doc_type=mappers.doc_type_name(req.doc_type),
        tags=list(req.tags),
    )
    return pb.CreateNewsResponse(news=mappers.news_to_pb(news))


registry.register(
    SERVICE,
    [
        Method("ListNews", pb.ListNewsRequest, pb.ListNewsResponse, list_news),
        Method("UpdateNews", pb.UpdateNewsRequest, pb.UpdateNewsResponse, update_news),
        Method("CreateNews", pb.CreateNewsRequest, pb.CreateNewsResponse, create_news),
    ],
)
