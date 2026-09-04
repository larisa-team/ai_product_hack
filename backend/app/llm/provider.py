"""Абстракция LLM: два метода под две стадии compose.

filter_relevance — отсев нерелевантного (батчами);
make_news        — группировка сообщений об одном событии + саммари (один вызов на прогон).
"""
from __future__ import annotations

from typing import Protocol, TypedDict

from app.config import settings


class NewsGroup(TypedDict):
    title: str
    content: str
    message_indices: list[int]


class LLMProvider(Protocol):
    async def filter_relevance(self, topic: str, extra: str, texts: list[str]) -> list[bool]:
        """Для каждого текста — относится ли он к теме мониторинга."""
        ...

    async def make_news(self, topic: str, messages: list[dict]) -> list[NewsGroup]:
        """Сгруппировать сообщения (`{i, channel, text}`) в новости и саммаризировать."""
        ...


def get_provider() -> LLMProvider:
    if settings.LLM_PROVIDER == "openai_compat":
        from app.llm.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider()
    from app.llm.mock import MockProvider

    return MockProvider()
