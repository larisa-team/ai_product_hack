"""Реализация monitoring.v1.ProjectService."""
from __future__ import annotations

from monitoring.v1 import monitoring_pb2 as pb
from sqlalchemy.ext.asyncio import AsyncSession

from app.connect import ConnectError, Method, registry
from app.services import mappers
from app.services.project_service import ProjectService

SERVICE = "monitoring.v1.ProjectService"

# Поля, которые UpdateProject умеет менять. Пустая маска = менять всё перечисленное.
UPDATABLE = ("name", "topic", "filters", "sources")


async def create_project(req: pb.CreateProjectRequest, db: AsyncSession) -> pb.CreateProjectResponse:
    if not req.name.strip():
        raise ConnectError("invalid_argument", "name обязателен")
    if not req.topic.strip():
        raise ConnectError("invalid_argument", "topic обязателен")

    project = await ProjectService(db).create_project(
        name=req.name,
        topic=req.topic,
        filters=mappers.filters_to_json(list(req.filters)),
        sources=mappers.sources_to_json(list(req.sources)),
    )
    return pb.CreateProjectResponse(project=mappers.project_to_pb(project))


async def get_project(req: pb.GetProjectRequest, db: AsyncSession) -> pb.GetProjectResponse:
    project = await ProjectService(db).get_project(req.id)
    if project is None:
        raise ConnectError("not_found", f"проект {req.id} не найден")
    return pb.GetProjectResponse(project=mappers.project_to_pb(project))


async def list_projects(req: pb.ListProjectsRequest, db: AsyncSession) -> pb.ListProjectsResponse:
    page_size = req.page_size or 100
    projects, next_token = await ProjectService(db).list_projects(page_size, req.page_token or None)
    return pb.ListProjectsResponse(
        projects=[mappers.project_to_pb(p) for p in projects],
        next_page_token=next_token or "",
    )


async def update_project(req: pb.UpdateProjectRequest, db: AsyncSession) -> pb.UpdateProjectResponse:
    paths = set(req.update_mask.paths) if req.update_mask.paths else set(UPDATABLE)
    unknown = paths - set(UPDATABLE)
    if unknown:
        raise ConnectError("invalid_argument", f"update_mask: неизвестные поля {sorted(unknown)}")

    project = await ProjectService(db).update_project(
        project_id=req.id,
        name=req.name if "name" in paths else None,
        topic=req.topic if "topic" in paths else None,
        filters=mappers.filters_to_json(list(req.filters)) if "filters" in paths else None,
        sources=mappers.sources_to_json(list(req.sources)) if "sources" in paths else None,
    )
    if project is None:
        raise ConnectError("not_found", f"проект {req.id} не найден")
    return pb.UpdateProjectResponse(project=mappers.project_to_pb(project))


async def delete_project(req: pb.DeleteProjectRequest, db: AsyncSession) -> pb.DeleteProjectResponse:
    if not await ProjectService(db).delete_project(req.id):
        raise ConnectError("not_found", f"проект {req.id} не найден")
    return pb.DeleteProjectResponse()


registry.register(
    SERVICE,
    [
        Method("CreateProject", pb.CreateProjectRequest, pb.CreateProjectResponse, create_project),
        Method("GetProject", pb.GetProjectRequest, pb.GetProjectResponse, get_project),
        Method("ListProjects", pb.ListProjectsRequest, pb.ListProjectsResponse, list_projects),
        Method("UpdateProject", pb.UpdateProjectRequest, pb.UpdateProjectResponse, update_project),
        Method("DeleteProject", pb.DeleteProjectRequest, pb.DeleteProjectResponse, delete_project),
    ],
)
