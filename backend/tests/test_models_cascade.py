"""FK на удаление должны быть CASCADE — иначе DeleteProject падает 500-й на любом проекте
с прогонами (реальный баг, пойманный вручную: DELETE projects -> FK violation на runs).
Без БД: проверяем декларацию через SQLAlchemy metadata, а не реальную транзакцию.
"""
from __future__ import annotations

from app.database.models import Base


def _ondelete_for(table_name: str, column_name: str) -> str | None:
    table = Base.metadata.tables[table_name]
    for fk in table.columns[column_name].foreign_keys:
        return fk.ondelete
    raise AssertionError(f"{table_name}.{column_name} — нет внешнего ключа")


def test_runs_cascade_from_project():
    assert _ondelete_for("runs", "project_id") == "CASCADE"


def test_news_cascade_from_run():
    assert _ondelete_for("news", "run_id") == "CASCADE"


def test_messages_cascade_from_project_and_run():
    assert _ondelete_for("messages", "project_id") == "CASCADE"
    assert _ondelete_for("messages", "run_id") == "CASCADE"


def test_source_cursors_cascade_from_project():
    assert _ondelete_for("source_cursors", "project_id") == "CASCADE"


def test_tasks_cascade_from_run():
    assert _ondelete_for("tasks", "run_id") == "CASCADE"


def test_tasks_compose_unique_per_run():
    """Партиальный уникальный индекс не даёт поставить вторую compose-задачу на run —
    без него гонка двух последних extract-задач одного прогона может создать дубль
    и compose выполнится дважды.
    """
    table = Base.metadata.tables["tasks"]
    index = next(i for i in table.indexes if i.name == "uq_tasks_compose_per_run")
    assert index.unique is True
    assert [c.name for c in index.columns] == ["run_id"]
