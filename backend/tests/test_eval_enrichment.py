"""Защита оценочного харнесса app/eval/enrichment.py.

Гоняем на `mock` — он детерминирован, без сети и ключа. Тест не «валидирует LLM»:
он фиксирует, что харнесс считает метрики и не теряет записи, плюс держит базовую
линию mock-эвристик. Честная цифра по реальному конвейеру — из CLI-прогона
`python -m app.eval.enrichment` с `LLM_PROVIDER=openai_compat`.
"""
from __future__ import annotations

import asyncio

import pytest

from app.config import settings
from app.eval import enrichment
from app.llm.provider import get_provider


@pytest.fixture
def mock_provider(monkeypatch):
    monkeypatch.setattr(settings, "LLM_PROVIDER", "mock")
    return get_provider()


@pytest.fixture(scope="module")
def dataset():
    return enrichment.load_dataset()


def test_dataset_shape(dataset):
    topic, profile, items = dataset
    assert topic
    assert profile, "importance размечена относительно профиля бизнеса — он должен быть задан"
    assert len(items) >= 50, "чек-лист требует оффлайн-набор 50+ материалов"
    for it in items:
        assert it.text.strip()
        # метки — на языке предметной области, распознаются schema.*_enum_name
        assert enrichment.schema.category_enum_name(it.category) != "NEWS_CATEGORY_UNSPECIFIED"
        assert enrichment.schema.importance_enum_name(it.importance) != "NEWS_IMPORTANCE_UNSPECIFIED"
        assert enrichment.schema.doc_type_enum_name(it.doc_type) != "DOC_TYPE_UNSPECIFIED"


def test_harness_runs_and_scores(mock_provider, dataset, capsys):
    topic, profile, items = dataset
    preds = asyncio.run(enrichment.run(mock_provider, topic, items, profile))
    sc = enrichment.score(preds, items)

    assert sc["total"] == len(items)
    # mock раскладывает по группам все записи — если coverage < 1, баг в атрибуции харнесса
    assert sc["coverage"] == pytest.approx(1.0)
    for dim, d in sc["dimensions"].items():
        assert d["coverage"] == pytest.approx(1.0), dim
        assert 0.0 <= d["accuracy"] <= 1.0, dim

    # базовая линия mock (детерминированная эвристика заметно бьёт случайную):
    dims = sc["dimensions"]
    assert dims["category"]["accuracy"] >= 0.55      # 4 класса, случайно ~0.25
    assert dims["doc_type"]["accuracy"] >= 0.75      # 2 класса, случайно ~0.5
    assert dims["importance"]["accuracy"] >= 0.15    # mock тут слаб by design

    report = enrichment.format_report(sc, {"provider": "mock"})
    assert "Enrichment eval" in report
    assert "category confusion" in report
    print("\n" + report)


def test_missing_group_marks_prediction_none(mock_provider, dataset):
    """Запись, которую make_news не вернул ни в одной группе, → предсказание None и промах."""
    topic, profile, items = dataset
    subset = items[:3]

    class Dropping:
        async def make_news(self, topic, messages, profile=""):
            groups = await mock_provider.make_news(topic, messages, profile)
            # выкидываем последнюю запись из результата
            drop = messages[-1]["i"]
            return [
                {**g, "message_indices": [i for i in g["message_indices"] if i != drop]}
                for g in groups
            ]

        async def filter_relevance(self, *a, **k):  # не используется
            return []

    preds = asyncio.run(enrichment.run(Dropping(), topic, subset))
    last = next(p for p in preds if p.item_id == subset[-1].id)
    assert last.category is None and last.importance is None and last.doc_type is None

    sc = enrichment.score(preds, subset)
    assert sc["coverage"] == pytest.approx(2 / 3)
