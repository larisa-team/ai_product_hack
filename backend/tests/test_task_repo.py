"""create_extract_tasks — единственное место, откуда воркер узнаёт, что собирать.
Без БД: подменяем db.add() сборщиком, проверяем форму payload (worker/jobs.handle_extract
читает из неё project_id/source_type/source_key напрямую).
"""
from __future__ import annotations

import uuid

from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database.models import Task
from app.database.repositories.task_repo import _COMPOSE_INDEX_WHERE, EXTRACT, TaskRepository

TELEGRAM = "SOURCE_TYPE_TELEGRAM"
RSS = "SOURCE_TYPE_RSS"


class _FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        self.added.append(obj)


def test_create_extract_tasks_one_per_source():
    db = _FakeSession()
    TaskRepository(db).create_extract_tasks(
        "run-1",
        "proj-1",
        [
            {"source_type": TELEGRAM, "source_key": "cit_gov"},
            {"source_type": RSS, "source_key": "https://tass.ru/rss/v2.xml"},
        ],
    )

    assert len(db.added) == 2
    assert {t.payload["source_key"] for t in db.added} == {"cit_gov", "https://tass.ru/rss/v2.xml"}
    for t in db.added:
        assert t.run_id == "run-1"
        assert t.kind == EXTRACT
        assert t.payload["project_id"] == "proj-1"
        assert t.id  # uuid сгенерирован


def test_source_type_travels_in_payload():
    """Тип источника обязан лежать в задаче: по нему воркер выбирает коннектор."""
    db = _FakeSession()
    TaskRepository(db).create_extract_tasks(
        "run-1", "proj-1", [{"source_type": RSS, "source_key": "https://example.com/feed"}]
    )
    assert db.added[0].payload["source_type"] == RSS


def test_collection_days_travels_in_payload():
    """Период сбора едет в задаче — воркер не ходит за проектом повторно."""
    db = _FakeSession()
    TaskRepository(db).create_extract_tasks(
        "run-1", "proj-1",
        [{"source_type": RSS, "source_key": "https://example.com/feed"}],
        collection_days=15,
    )
    assert db.added[0].payload["collection_days"] == 15


def test_collection_days_defaults_when_omitted():
    db = _FakeSession()
    TaskRepository(db).create_extract_tasks(
        "run-1", "proj-1", [{"source_type": RSS, "source_key": "x"}]
    )
    assert db.added[0].payload["collection_days"] == 7


def test_create_extract_tasks_empty():
    db = _FakeSession()
    TaskRepository(db).create_extract_tasks("run-1", "proj-1", [])
    assert db.added == []


def test_compose_on_conflict_predicate_is_literal():
    """ON CONFLICT ... WHERE должен совпадать с предикатом частичного индекса ДОСЛОВНО.

    Регрессия: SQLAlchemy 2.0.52 рендерит `Task.kind == 'compose'` как bound-параметр
    (`WHERE kind = $1`), Postgres не матчит его с индексом `WHERE kind = 'compose'` и
    роняет вставку compose-задачи — Run навсегда виснет в STARTED.
    """
    stmt = (
        pg_insert(Task)
        .values(id=str(uuid.uuid4()), run_id="r", kind="compose", payload={})
        .on_conflict_do_nothing(index_elements=["run_id"], index_where=_COMPOSE_INDEX_WHERE)
    )
    sql = str(stmt.compile(dialect=postgresql.dialect()))
    assert "WHERE kind = 'compose'" in sql
    assert "WHERE kind = %(" not in sql  # именно литерал, не параметр
