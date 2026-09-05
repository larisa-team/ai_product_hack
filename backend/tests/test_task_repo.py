"""create_extract_tasks — единственное место, откуда воркер узнаёт, что собирать.
Без БД: подменяем db.add() сборщиком, проверяем форму payload (worker/jobs.handle_extract
читает из неё project_id/source_type/source_key напрямую).
"""
from __future__ import annotations

from app.database.repositories.task_repo import EXTRACT, TaskRepository

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


def test_create_extract_tasks_empty():
    db = _FakeSession()
    TaskRepository(db).create_extract_tasks("run-1", "proj-1", [])
    assert db.added == []
