"""Мапперы ORM <-> protobuf — единственное место, где JSONB превращается в proto-сообщения.
Смена proto должна ломать эти тесты первой, до того как расхождение всплывёт в API.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from monitoring.v1 import monitoring_pb2 as pb

from app.services import mappers


def test_filter_round_trip():
    raw = {"prompt": "не интересны вакансии"}
    parsed = [mappers.filter_to_pb(raw)]
    back = mappers.filters_to_json(parsed)
    assert back == [raw]


def test_source_round_trip():
    raw = {"type": "SOURCE_TYPE_TELEGRAM", "telegram": "cit_gov"}
    parsed = [mappers.source_to_pb(raw)]
    back = mappers.sources_to_json(parsed)
    assert back == [raw]
    assert mappers.source_key(parsed[0]) == "cit_gov"


def test_filter_to_pb_ignores_unknown_fields():
    # ParseDict(..., ignore_unknown_fields=True) — старые записи в БД с полем,
    # которого больше нет в proto, не должны ронять чтение.
    parsed = mappers.filter_to_pb({"prompt": "x", "legacy_field": "y"})
    assert parsed.prompt == "x"


def test_to_timestamp_none():
    assert mappers.to_timestamp(None) is None


def test_to_timestamp_roundtrip():
    dt = datetime(2026, 9, 4, 12, 0, 0)
    ts = mappers.to_timestamp(dt)
    assert ts is not None
    assert ts.ToDatetime() == dt


def test_stats_to_pb_none_is_safe():
    # Run.stats может быть {} (только что созданный Run) — не должно падать,
    # и proto3-JSON-терсность: нули просто не сериализуются, это ок.
    stats = mappers.stats_to_pb(None)
    assert stats.collected == 0
    assert stats.relevant == 0
    assert stats.news == 0
    assert stats.error == ""


def test_stats_to_pb_values():
    stats = mappers.stats_to_pb({"collected": 40, "relevant": 29, "news": 27})
    assert (stats.collected, stats.relevant, stats.news) == (40, 29, 27)


def test_project_to_pb_shape():
    project = SimpleNamespace(
        id="p1",
        name="ИТ-мониторинг",
        topic="цифровые технологии",
        filters=[{"prompt": "не интересны вакансии"}],
        sources=[{"type": "SOURCE_TYPE_TELEGRAM", "telegram": "cit_gov"}],
        created_at=datetime(2026, 9, 4, 10, 0, 0),
        updated_at=datetime(2026, 9, 4, 10, 0, 0),
    )
    out = mappers.project_to_pb(project)
    assert isinstance(out, pb.Project)
    assert out.id == "p1"
    assert len(out.filters) == 1 and out.filters[0].prompt == "не интересны вакансии"
    assert len(out.sources) == 1 and out.sources[0].telegram == "cit_gov"


def test_run_to_pb_with_news():
    run = SimpleNamespace(
        id="r1",
        project_id="p1",
        created_at=datetime(2026, 9, 4, 10, 0, 0),
        state="RUN_STATE_DONE",
        stats={"collected": 3, "relevant": 2, "news": 1},
    )
    news = [SimpleNamespace(title="Заголовок", content="Текст", sources=["https://t.me/a/1"])]
    out = mappers.run_to_pb(run, news)
    assert out.state == pb.RUN_STATE_DONE
    assert len(out.news) == 1
    assert out.news[0].title == "Заголовок"
    assert out.stats.collected == 3
