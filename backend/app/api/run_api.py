"""Реализация monitoring.v1.RunService."""
from __future__ import annotations

from monitoring.v1 import monitoring_pb2 as pb
from sqlalchemy.ext.asyncio import AsyncSession

from app.connect import ConnectError, Method, registry
from app.services import mappers
from app.services.run_service import RunService

SERVICE = "monitoring.v1.RunService"


async def start_run(req: pb.StartRunRequest, db: AsyncSession) -> pb.StartRunResponse:
    run, problem = await RunService(db).start_run(req.project_id)
    if problem == "not_found":
        raise ConnectError("not_found", f"проект {req.project_id} не найден")
    if problem is not None:
        raise ConnectError("failed_precondition", problem)
    return pb.StartRunResponse(run=mappers.run_to_pb(run, []))


async def get_run(req: pb.GetRunRequest, db: AsyncSession) -> pb.GetRunResponse:
    found = await RunService(db).get_run(req.id)
    if found is None:
        raise ConnectError("not_found", f"запуск {req.id} не найден")
    run, news = found
    return pb.GetRunResponse(run=mappers.run_to_pb(run, news))


async def list_runs(req: pb.ListRunsRequest, db: AsyncSession) -> pb.ListRunsResponse:
    page_size = req.page_size or 100
    runs, next_token = await RunService(db).list_runs(
        req.project_id, page_size, req.page_token or None
    )
    # В списке новости не отдаём — они приходят через GetRun.
    return pb.ListRunsResponse(
        runs=[mappers.run_to_pb(r, []) for r in runs],
        next_page_token=next_token or "",
    )


registry.register(
    SERVICE,
    [
        Method("StartRun", pb.StartRunRequest, pb.StartRunResponse, start_run),
        Method("GetRun", pb.GetRunRequest, pb.GetRunResponse, get_run),
        Method("ListRuns", pb.ListRunsRequest, pb.ListRunsResponse, list_runs),
    ],
)
