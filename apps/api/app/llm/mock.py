"""Оффлайн-провайдер: работает без сети, повторяет контракт LLM грубыми эвристиками."""
from __future__ import annotations

import re
from functools import lru_cache

import pymorphy3

from app.llm.provider import NewsGroup

_morph = pymorphy3.MorphAnalyzer()
_WORD = re.compile(r"[А-Яа-яЁёA-Za-z0-9]+")


@lru_cache(maxsize=20_000)
def _lemma(word: str) -> str:
    return _morph.parse(word)[0].normal_form


def _lemmas(text: str) -> set[str]:
    return {_lemma(w.lower()) for w in _WORD.findall(text) if len(w) > 2}


class MockProvider:
    def filter_relevance(self, topic: str, extra: str, texts: list[str]) -> list[bool]:
        topic_lemmas = _lemmas(topic)
        if not topic_lemmas:
            return [True] * len(texts)
        return [bool(topic_lemmas & _lemmas(t)) for t in texts]

    def make_news(self, topic: str, messages: list[dict]) -> list[NewsGroup]:
        # группировка по совпадению первых 4 значимых слов сообщения
        by_key: dict[tuple[str, ...], list[int]] = {}
        for msg in messages:
            words = [w.lower() for w in _WORD.findall(msg.get("text", ""))]
            key = tuple(words[:4]) or ("_",)
            by_key.setdefault(key, []).append(msg["i"])

        text_by_i = {m["i"]: re.sub(r"\s+", " ", m.get("text", "")).strip() for m in messages}
        out: list[NewsGroup] = []
        for idxs in by_key.values():
            longest = max((text_by_i[i] for i in idxs), key=len, default="")
            if not longest:
                continue
            title = " ".join(longest.split()[:12])
            content = longest[:800]
            out.append({"title": title, "content": content, "message_indices": idxs})
        return out
