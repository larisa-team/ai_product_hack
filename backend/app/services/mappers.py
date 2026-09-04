"""Единственное место, где ORM превращается в protobuf и обратно.

Приём: вложенные структуры (filters/sources) лежат в JSONB ровно в форме proto3-JSON
соответствующего сообщения. Тогда конвертация — это `ParseDict`/`MessageToDict`, а не
ручное перекладывание полей: при изменении proto расхождение вылезает здесь и сразу.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from google.protobuf import json_format
from google.protobuf.timestamp_pb2 import Timestamp
from monitoring.v1 import monitoring_pb2 as pb

from app.database.models import News, Project, Run


# --- примитивы ---

def to_timestamp(value: datetime | None) -> Timestamp | None:
    if value is None:
        return None
    ts = Timestamp()
    ts.FromDatetime(value)
    return ts


# --- вложенные структуры проекта ---

def filter_to_pb(raw: dict[str, Any]) -> pb.ProjectFilter:
    return json_format.ParseDict(raw, pb.ProjectFilter(), ignore_unknown_fields=True)


def source_to_pb(raw: dict[str, Any]) -> pb.Source:
    return json_format.ParseDict(raw, pb.Source(), ignore_unknown_fields=True)


def filters_to_json(filters: list[pb.ProjectFilter]) -> list[dict[str, Any]]:
    return [json_format.MessageToDict(f) for f in filters]


def sources_to_json(sources: list[pb.Source]) -> list[dict[str, Any]]:
    return [json_format.MessageToDict(s) for s in sources]


# --- агрегаты ---

def project_to_pb(project: Project) -> pb.Project:
    return pb.Project(
        id=project.id,
        name=project.name,
        topic=project.topic,
        filters=[filter_to_pb(f) for f in (project.filters or [])],
        sources=[source_to_pb(s) for s in (project.sources or [])],
        created_at=to_timestamp(project.created_at),
        updated_at=to_timestamp(project.updated_at),
    )


def news_to_pb(item: News) -> pb.News:
    return pb.News(
        title=item.title,
        content=item.content,
        sources=list(item.sources or []),
    )


def stats_to_pb(raw: dict[str, Any] | None) -> pb.RunStats:
    return json_format.ParseDict(raw or {}, pb.RunStats(), ignore_unknown_fields=True)


def run_to_pb(run: Run, news: list[News] | None = None) -> pb.Run:
    return pb.Run(
        id=run.id,
        project_id=run.project_id,
        created_at=to_timestamp(run.created_at),
        news=[news_to_pb(n) for n in (news or [])],
        state=pb.RunState.Value(run.state),
        stats=stats_to_pb(run.stats),
    )


# --- утилиты для источников ---

def channel_of(source: pb.Source) -> str:
    """Имя Telegram-канала из Source (нормализация — в ingestion.telegram_web)."""
    return source.telegram
