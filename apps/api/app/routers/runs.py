from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from sqlalchemy import select

from app.db import get_db
from app.models import Project, Run
from app.queue import Q_EXTRACT, enqueue, set_pending
from app.schemas import RunOut, RunSummary

router = APIRouter(prefix="/api", tags=["runs"])


@router.post(
    "/projects/{project_id}/runs",
    response_model=RunSummary,
    status_code=status.HTTP_201_CREATED,
)
def start_run(project_id: uuid.UUID, db: Session = Depends(get_db)) -> Run:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    sources = list(project.sources)
    if not sources:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "project has no sources")

    run = Run(project_id=project.id, state="STARTED", stats={})
    db.add(run)
    db.commit()
    db.refresh(run)

    set_pending(str(run.id), len(sources))
    for source in sources:
        enqueue(Q_EXTRACT, {"run_id": str(run.id), "source_id": str(source.id)})

    return run


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: uuid.UUID, db: Session = Depends(get_db)) -> Run:
    run = db.get(Run, run_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    return run


@router.get("/projects/{project_id}/runs", response_model=list[RunSummary])
def list_runs(project_id: uuid.UUID, db: Session = Depends(get_db)) -> list[Run]:
    if db.get(Project, project_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return list(
        db.scalars(
            select(Run).where(Run.project_id == project_id).order_by(Run.created_at.desc())
        )
    )
