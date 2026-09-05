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


def test_stats_to_pb_progress():
    # Воркер пишет транзиентный прогресс в тот же JSONB — маппер обязан его прокинуть.
    stats = mappers.stats_to_pb(
        {"collected": 50, "stage": "filtering", "stage_done": 2, "stage_total": 4}
    )
    assert stats.stage == "filtering"
    assert (stats.stage_done, stats.stage_total) == (2, 4)


def test_project_to_pb_shape():
    project = SimpleNamespace(
        id="p1",
        name="ИТ-мониторинг",
        topic="цифровые технологии",
        filters=[{"prompt": "не интересны вакансии"}],
        sources=[{"type": "SOURCE_TYPE_TELEGRAM", "telegram": "cit_gov"}],
        collection_days=15,
        profile="вендор корпоративного ПО",
        created_at=datetime(2026, 9, 4, 10, 0, 0),
        updated_at=datetime(2026, 9, 4, 10, 0, 0),
    )
    out = mappers.project_to_pb(project)
    assert isinstance(out, pb.Project)
    assert out.id == "p1"
    assert out.collection_days == 15
    assert out.profile == "вендор корпоративного ПО"
    assert len(out.filters) == 1 and out.filters[0].prompt == "не интересны вакансии"
    assert len(out.sources) == 1 and out.sources[0].telegram == "cit_gov"


def test_project_to_pb_collection_days_defaults_to_7():
    project = SimpleNamespace(
        id="p1", name="x", topic="y", filters=[], sources=[],
        collection_days=0,  # старый проект / не задано
        profile="",
        created_at=datetime(2026, 9, 4), updated_at=datetime(2026, 9, 4),
    )
    assert mappers.project_to_pb(project).collection_days == 7


def _news_stub(**over):
    """ORM-строка News как SimpleNamespace: все поля, которые читает news_to_pb."""
    base = dict(
        id=1,
        project_id="p1",
        run_id="r1",
        title="Заголовок",
        content="Текст",
        sources=["https://t.me/a/1"],
        category="NEWS_CATEGORY_UNSPECIFIED",
        importance="NEWS_IMPORTANCE_UNSPECIFIED",
        doc_type="DOC_TYPE_UNSPECIFIED",
        entities={},
        tags=[],
        hidden=False,
        created_at=datetime(2026, 9, 4, 10, 0, 0),
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_run_to_pb_with_news():
    run = SimpleNamespace(
        id="r1",
        project_id="p1",
        created_at=datetime(2026, 9, 4, 10, 0, 0),
        state="RUN_STATE_DONE",
        stats={"collected": 3, "relevant": 2, "news": 1},
    )
    out = mappers.run_to_pb(run, [_news_stub()])
    assert out.state == pb.RUN_STATE_DONE
    assert len(out.news) == 1
    assert out.news[0].title == "Заголовок"
    assert out.stats.collected == 3


def test_news_to_pb_enrichment():
    n = _news_stub(
        category="NEWS_CATEGORY_REGULATORY",
        importance="NEWS_IMPORTANCE_HIGH",
        doc_type="DOC_TYPE_NPA",
        entities={"who": "ЦБ", "what": "отозвал лицензию", "when": "01.03.2026", "consequences": ""},
        tags=["банки"],
        hidden=True,
    )
    out = mappers.news_to_pb(n)
    assert out.id == 1
    assert out.category == pb.NEWS_CATEGORY_REGULATORY
    assert out.importance == pb.NEWS_IMPORTANCE_HIGH
    assert out.doc_type == pb.DOC_TYPE_NPA
    assert out.entities.who == "ЦБ"
    assert list(out.tags) == ["банки"]
    assert out.hidden is True


def test_news_to_pb_tolerates_unknown_enum_string():
    """В БД строку писали и миграции, и руки — незнакомое значение не должно ронять."""
    out = mappers.news_to_pb(_news_stub(category="какая-то-старая-категория"))
    assert out.category == pb.NEWS_CATEGORY_UNSPECIFIED


def test_news_to_pb_manual_item_has_empty_run_id():
    out = mappers.news_to_pb(_news_stub(run_id=None))
    assert out.run_id == ""
