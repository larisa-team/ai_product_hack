"""Контракт proto — то, ради чего он вообще заведён, проверяем как свойство, а не как соглашение.

Здесь ловятся ровно те ошибки, которые иначе всплывают на демо: поле мимо контракта,
потерянное значение enum, скалярный bool с неудачным дефолтом.
"""
from __future__ import annotations

import pytest
from google.protobuf import json_format
from monitoring.v1 import monitoring_pb2 as pb

# Запросы, приходящие снаружи: каждый разбирается в connect.py с
# ignore_unknown_fields=False, поэтому лишнее поле обязано валиться.
REQUESTS = [
    pb.CreateProjectRequest,
    pb.UpdateProjectRequest,
    pb.DeleteProjectRequest,
    pb.GetProjectRequest,
    pb.ListProjectsRequest,
    pb.StartRunRequest,
    pb.GetRunRequest,
    pb.ListRunsRequest,
    pb.ListNewsRequest,
    pb.UpdateNewsRequest,
    pb.CreateNewsRequest,
]


@pytest.mark.parametrize("message_type", REQUESTS, ids=lambda t: t.DESCRIPTOR.name)
def test_unknown_field_rejected(message_type):
    """Поле, которого нет в контракте, -> ParseError (в API это 400 invalid_argument)."""
    with pytest.raises(json_format.ParseError):
        json_format.Parse('{"definitelyNotInContract": 1}', message_type(), ignore_unknown_fields=False)


@pytest.mark.parametrize(
    "enum_type",
    [pb.NewsCategory, pb.NewsImportance, pb.DocType, pb.SourceType, pb.RunState],
    ids=lambda e: e.DESCRIPTOR.name,
)
def test_enum_round_trip(enum_type):
    """Имя <-> значение ходят в обе стороны: в БД мы храним именно имя (как Run.state)."""
    for value in enum_type.values():
        assert enum_type.Value(enum_type.Name(value)) == value


@pytest.mark.parametrize(
    "enum_type",
    [pb.NewsCategory, pb.NewsImportance, pb.DocType, pb.SourceType, pb.RunState],
    ids=lambda e: e.DESCRIPTOR.name,
)
def test_enum_zero_is_unspecified(enum_type):
    """Нулевое значение — всегда *_UNSPECIFIED.

    В proto3-JSON нулевое значение опускается, поэтому содержательный ноль делает
    «не задано» неотличимым от осмысленного выбора. Легаси FilterType.PROMT_BASED = 0
    этим уже болеет (см. SYSTEM_DESIGN.md §10), новые enum'ы повторять это не должны.
    """
    assert enum_type.Name(0).endswith("_UNSPECIFIED")


def test_source_without_disabled_is_active():
    """Источник из старого JSONB (без поля disabled) обязан читаться как активный.

    Регрессия на инверсию флага: если бы поле называлось `enabled`, пропущенное значение
    пришло бы как false и молча выключило бы все существующие источники проекта.
    """
    source = json_format.Parse(
        '{"type": "SOURCE_TYPE_TELEGRAM", "telegram": "cit_gov"}',
        pb.Source(),
        ignore_unknown_fields=False,
    )
    assert source.disabled is False


def test_update_news_mask_distinguishes_unhide_from_absent():
    """«Показать скрытую новость» выразимо только через маску.

    hidden=false без маски неотличимо от «поле не прислали», поэтому UpdateNews
    обязан ходить с update_mask — на этом держится вся правка карточки.
    """
    req = json_format.Parse(
        '{"id": 1, "hidden": false, "updateMask": "hidden"}',
        pb.UpdateNewsRequest(),
        ignore_unknown_fields=False,
    )
    assert req.hidden is False
    assert list(req.update_mask.paths) == ["hidden"]


def test_news_carries_enrichment_and_identity():
    """News должна быть адресуемой (id) и нести обогащение — иначе ни правка, ни фильтры."""
    fields = set(pb.News.DESCRIPTOR.fields_by_name)
    assert {"id", "project_id", "category", "importance", "doc_type", "entities",
            "tags", "hidden", "created_at"} <= fields
