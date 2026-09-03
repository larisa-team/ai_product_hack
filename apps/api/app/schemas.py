"""Pydantic-схемы API — зеркало x.proto."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class FilterIn(BaseModel):
    prompt: str


class FilterOut(BaseModel):
    id: uuid.UUID
    prompt: str
    model_config = ConfigDict(from_attributes=True)


class SourceIn(BaseModel):
    type: str = "telegram"
    telegram: str


class SourceOut(BaseModel):
    id: uuid.UUID
    type: str
    telegram: str
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    name: str
    topic: str
    filters: list[FilterIn] = Field(default_factory=list)
    sources: list[SourceIn] = Field(default_factory=list)


class ProjectUpdate(BaseModel):
    name: str | None = None
    topic: str | None = None
    filters: list[FilterIn] | None = None
    sources: list[SourceIn] | None = None


class ProjectOut(BaseModel):
    id: uuid.UUID
    name: str
    topic: str
    filters: list[FilterOut]
    sources: list[SourceOut]
    created_at: datetime
    updated_at: datetime
    model_config = ConfigDict(from_attributes=True)


class NewsOut(BaseModel):
    title: str
    content: str
    sources: list[str]
    model_config = ConfigDict(from_attributes=True)


class RunSummary(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    state: str
    created_at: datetime
    finished_at: datetime | None
    stats: dict
    model_config = ConfigDict(from_attributes=True)


class RunOut(RunSummary):
    news: list[NewsOut] = Field(default_factory=list)
