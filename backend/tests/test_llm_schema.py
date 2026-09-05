"""Перевод ответа LLM в значения контракта.

Смысл модуля — не упасть на том, что модель ответила не по инструкции. Поэтому тесты
в основном про мусор на входе, а не про счастливый путь.
"""
from __future__ import annotations

import pytest

from app.llm import schema


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("регуляторика", "NEWS_CATEGORY_REGULATORY"),
        ("  Репутация  ", "NEWS_CATEGORY_REPUTATION"),
        ("конкуренты", "NEWS_CATEGORY_COMPETITORS"),
        ("тренды", "NEWS_CATEGORY_TRENDS"),
        ("regulatory", "NEWS_CATEGORY_REGULATORY"),  # модель иногда отвечает по-английски
        ("что-то своё", "NEWS_CATEGORY_UNSPECIFIED"),
        ("", "NEWS_CATEGORY_UNSPECIFIED"),
        (None, "NEWS_CATEGORY_UNSPECIFIED"),
    ],
)
def test_category(raw, expected):
    assert schema.category_enum_name(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("high", "NEWS_IMPORTANCE_HIGH"),
        ("MEDIUM", "NEWS_IMPORTANCE_MEDIUM"),
        ("низкая", "NEWS_IMPORTANCE_LOW"),
        ("критическая", "NEWS_IMPORTANCE_UNSPECIFIED"),
        (None, "NEWS_IMPORTANCE_UNSPECIFIED"),
    ],
)
def test_importance(raw, expected):
    assert schema.importance_enum_name(raw) == expected


@pytest.mark.parametrize(
    "raw,expected",
    [("npa", "DOC_TYPE_NPA"), ("НПА", "DOC_TYPE_NPA"), ("news", "DOC_TYPE_NEWS"), ("", "DOC_TYPE_UNSPECIFIED")],
)
def test_doc_type(raw, expected):
    assert schema.doc_type_enum_name(raw) == expected


def test_entities_always_four_string_fields():
    result = schema.entities_dict({"who": "ЦБ", "лишнее": "выкинуть", "what": None})
    assert set(result) == {"who", "what", "when", "consequences"}
    assert result["who"] == "ЦБ"
    assert result["what"] == ""  # None не должен утечь в JSONB
    assert all(isinstance(v, str) for v in result.values())


def test_entities_from_none():
    assert schema.entities_dict(None) == {"who": "", "what": "", "when": "", "consequences": ""}
