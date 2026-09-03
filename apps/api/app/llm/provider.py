"""Абстракция LLM: два метода под две стадии compose (см. SYSTEM_DESIGN_LIGHT §5)."""
from __future__ import annotations

from typing import Protocol, TypedDict

from app.config import get_settings


class NewsGroup(TypedDict):
    title: str
    content: str
    message_indices: list[int]


class LLMProvider(Protocol):
    def filter_relevance(self, topic: str, extra: str, texts: list[str]) -> list[bool]:
        """Для каждого текста — относится ли он к теме мониторинга."""
        ...

    def make_news(self, topic: str, messages: list[dict]) -> list[NewsGroup]:
        """Сгруппировать сообщения (`{i, channel, text}`) в новости и саммаризировать."""
        ...


def get_provider() -> LLMProvider:
    provider = get_settings().llm_provider
    if provider == "openai_compat":
        from app.llm.openai_compat import OpenAICompatProvider

        return OpenAICompatProvider()
    from app.llm.mock import MockProvider

    return MockProvider()
