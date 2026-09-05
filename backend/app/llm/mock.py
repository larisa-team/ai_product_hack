"""Оффлайн-провайдер: без сети, повторяет контракт LLM грубыми эвристиками."""
from __future__ import annotations

import re
from functools import lru_cache

import pymorphy3

from app.llm.provider import NewsGroup

_morph = pymorphy3.MorphAnalyzer()
_WORD = re.compile(r"[А-Яа-яЁёA-Za-z0-9]+")

# Словари для «интеллектуальной обработки» без сети. Грубо, зато детерминированно:
# офлайн-демо обязано показывать те же поля, что и реальный LLM, иначе без ключа
# половина чек-листа выглядит пустой. Слова — в начальной форме (сверяем по леммам).
_CATEGORY_KEYWORDS: dict[str, set[str]] = {
    "регуляторика": {
        "закон", "законопроект", "приказ", "постановление", "указ", "нпа", "регулирование",
        "минфин", "минцифра", "госдума", "правительство", "цб", "фнс", "налог", "лицензия",
        "требование", "норматив", "реестр", "штраф",
    },
    "репутация": {
        "скандал", "иск", "жалоба", "критика", "репутация", "утечка", "расследование",
        "обвинение", "суд", "проверка",
    },
    "конкуренты": {"конкурент", "соперник", "рынок", "доля", "сделка", "поглощение"},
}
# «тренды» — корзина по умолчанию: материал по теме, но без явных признаков выше.
_DEFAULT_CATEGORY = "тренды"

_URGENT_KEYWORDS = {
    "суд", "штраф", "кризис", "срочно", "отзыв", "запрет", "блокировка", "проверка",
    "нарушение", "ущерб", "авария",
}
_NPA_KEYWORDS = {"закон", "законопроект", "приказ", "постановление", "указ", "нпа", "кодекс"}


@lru_cache(maxsize=20_000)
def _lemma(word: str) -> str:
    return _morph.parse(word)[0].normal_form


def _lemmas(text: str) -> set[str]:
    return {_lemma(w.lower()) for w in _WORD.findall(text) if len(w) > 2}


class MockProvider:
    async def filter_relevance(self, topic: str, extra: str, texts: list[str]) -> list[bool]:
        topic_lemmas = _lemmas(topic)
        if not topic_lemmas:
            return [True] * len(texts)
        return [bool(topic_lemmas & _lemmas(t)) for t in texts]

    async def make_news(self, topic: str, messages: list[dict]) -> list[NewsGroup]:
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
            lemmas = _lemmas(longest)
            out.append(
                {
                    "title": " ".join(longest.split()[:12]),
                    "content": longest[:800],
                    "message_indices": idxs,
                    "category": _category_of(lemmas),
                    "importance": _importance_of(lemmas, len(idxs)),
                    "doc_type": "npa" if lemmas & _NPA_KEYWORDS else "news",
                    # who/when mock честно не извлекает: NER без модели не сделать,
                    # а выдумывать сущности хуже, чем оставить пустыми.
                    "entities": {
                        "who": "",
                        "what": longest[:200],
                        "when": "",
                        "consequences": "",
                    },
                }
            )
        return out


def _category_of(lemmas: set[str]) -> str:
    """Категория по числу совпавших ключевых слов; ничего не совпало — «тренды»."""
    best, best_hits = _DEFAULT_CATEGORY, 0
    for category, keywords in _CATEGORY_KEYWORDS.items():
        hits = len(lemmas & keywords)
        if hits > best_hits:
            best, best_hits = category, hits
    return best


def _importance_of(lemmas: set[str], sources_count: int) -> str:
    """Высокая — тревожные слова; средняя — о событии сообщил не один источник."""
    if lemmas & _URGENT_KEYWORDS:
        return "high"
    return "medium" if sources_count > 1 else "low"
