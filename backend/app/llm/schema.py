"""Перевод ответа LLM в значения контракта.

Провайдеры (и реальный, и mock) говорят на языке предметной области — русские названия
категорий ровно как в чек-листе и решении Р5. Контракт хранит канонические имена
enum'ов. Стык между ними — здесь, в одном месте: иначе каждый провайдер начнёт лепить
свой диалект, а неизвестное значение будет ронять весь compose.

Правило: чего не поняли — то `*_UNSPECIFIED`, но никогда не исключение. Карточка с
неизвестной категорией полезнее, чем упавший прогон.
"""
from __future__ import annotations

_CATEGORY = {
    "регуляторика": "NEWS_CATEGORY_REGULATORY",
    "регулирование": "NEWS_CATEGORY_REGULATORY",
    "репутация": "NEWS_CATEGORY_REPUTATION",
    "конкуренты": "NEWS_CATEGORY_COMPETITORS",
    "тренды": "NEWS_CATEGORY_TRENDS",
    # модель периодически отвечает по-английски, хотя просили иначе
    "regulatory": "NEWS_CATEGORY_REGULATORY",
    "reputation": "NEWS_CATEGORY_REPUTATION",
    "competitors": "NEWS_CATEGORY_COMPETITORS",
    "trends": "NEWS_CATEGORY_TRENDS",
}

_IMPORTANCE = {
    "high": "NEWS_IMPORTANCE_HIGH",
    "medium": "NEWS_IMPORTANCE_MEDIUM",
    "low": "NEWS_IMPORTANCE_LOW",
    "высокая": "NEWS_IMPORTANCE_HIGH",
    "средняя": "NEWS_IMPORTANCE_MEDIUM",
    "низкая": "NEWS_IMPORTANCE_LOW",
}

_DOC_TYPE = {
    "npa": "DOC_TYPE_NPA",
    "нпа": "DOC_TYPE_NPA",
    "news": "DOC_TYPE_NEWS",
    "новость": "DOC_TYPE_NEWS",
}

CATEGORY_UNSPECIFIED = "NEWS_CATEGORY_UNSPECIFIED"
IMPORTANCE_UNSPECIFIED = "NEWS_IMPORTANCE_UNSPECIFIED"
DOC_TYPE_UNSPECIFIED = "DOC_TYPE_UNSPECIFIED"

ENTITY_KEYS = ("who", "what", "when", "consequences")


def category_enum_name(raw: str | None) -> str:
    return _CATEGORY.get((raw or "").strip().lower(), CATEGORY_UNSPECIFIED)


def importance_enum_name(raw: str | None) -> str:
    return _IMPORTANCE.get((raw or "").strip().lower(), IMPORTANCE_UNSPECIFIED)


def doc_type_enum_name(raw: str | None) -> str:
    return _DOC_TYPE.get((raw or "").strip().lower(), DOC_TYPE_UNSPECIFIED)


def entities_dict(raw: dict | None) -> dict[str, str]:
    """Ровно четыре строковых поля NewsEntities, без мусора и без None."""
    raw = raw or {}
    return {key: str(raw.get(key) or "").strip() for key in ENTITY_KEYS}
