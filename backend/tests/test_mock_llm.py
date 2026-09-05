"""MockProvider — офлайн-фолбэк LLM. Грубый, но должен вести себя предсказуемо:
это то, на чём демо работает, если сеть до RouterAI пропала.
"""
from __future__ import annotations

import pytest

from app.llm.mock import MockProvider


@pytest.fixture
def provider() -> MockProvider:
    return MockProvider()


async def test_filter_relevance_matches_topic(provider: MockProvider):
    flags = await provider.filter_relevance(
        topic="гранты для ИТ-разработчиков",
        extra="",
        texts=[
            "Минцифры выделило гранты на разработку отечественного ПО",
            "Поздравляем коллег с Днём знаний!",
        ],
    )
    assert flags == [True, False]


async def test_filter_relevance_empty_topic_keeps_everything(provider: MockProvider):
    # Пустая тема (нет значимых лемм) — не должны молча выкидывать всё подряд.
    flags = await provider.filter_relevance(topic="", extra="", texts=["что угодно"])
    assert flags == [True]


async def test_make_news_groups_similar_messages(provider: MockProvider):
    messages = [
        {"i": 0, "channel": "a", "text": "Минцифры выделило гранты на разработку ПО в 2026 году"},
        {"i": 1, "channel": "b", "text": "Минцифры выделило гранты на разработку ПО для отрасли"},
        {"i": 2, "channel": "c", "text": "Совершенно другая новость про 5G в России"},
    ]
    groups = await provider.make_news(topic="гранты", messages=messages)
    # Первые два сообщения начинаются одинаково -> один группа; третье отдельно.
    sizes = sorted(len(g["message_indices"]) for g in groups)
    assert sizes == [1, 2]
    for g in groups:
        assert g["title"]
        assert g["content"]


async def test_make_news_empty_input(provider: MockProvider):
    assert await provider.make_news(topic="x", messages=[]) == []
