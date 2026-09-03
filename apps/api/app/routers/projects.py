from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Project, ProjectFilter, Source
from app.schemas import ProjectCreate, ProjectOut, ProjectUpdate

router = APIRouter(prefix="/api/projects", tags=["projects"])


def _get_or_404(db: Session, project_id: uuid.UUID) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "project not found")
    return project


@router.post("", response_model=ProjectOut, status_code=status.HTTP_201_CREATED)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db)) -> Project:
    project = Project(
        name=payload.name,
        topic=payload.topic,
        filters=[ProjectFilter(prompt=f.prompt) for f in payload.filters],
        sources=[Source(type=s.type, telegram=s.telegram) for s in payload.sources],
    )
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db)) -> list[Project]:
    return list(db.scalars(select(Project).order_by(Project.created_at.desc())))


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(project_id: uuid.UUID, db: Session = Depends(get_db)) -> Project:
    return _get_or_404(db, project_id)


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: uuid.UUID, payload: ProjectUpdate, db: Session = Depends(get_db)
) -> Project:
    project = _get_or_404(db, project_id)
    if payload.name is not None:
        project.name = payload.name
    if payload.topic is not None:
        project.topic = payload.topic
    if payload.filters is not None:
        project.filters = [ProjectFilter(prompt=f.prompt) for f in payload.filters]
    if payload.sources is not None:
        project.sources = [Source(type=s.type, telegram=s.telegram) for s in payload.sources]
    db.commit()
    db.refresh(project)
    return project


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_project(project_id: uuid.UUID, db: Session = Depends(get_db)) -> None:
    project = _get_or_404(db, project_id)
    db.delete(project)
    db.commit()
