"""OpenAI-совместимый провайдер (RouterAI, OpenAI, локальные прокси)."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from app.config import settings
from app.llm import schema
from app.llm.provider import NewsGroup

log = logging.getLogger(__name__)

_RETRYABLE_STATUS = {429, 500, 502, 503, 504}
_NETWORK_RETRIES = 3

# Поддерживает ли текущий эндпоинт+модель strict `response_format: json_schema`.
# None — ещё не проверяли; False — не поддерживает, дальше только `json_object`.
# RouterAI проксирует ~490 моделей, и часть (в т.ч. deepseek-v4-flash) json_schema не умеет —
# первый же 400 переводит процесс на json_object и больше не пробует.
_json_schema_supported: bool | None = None


def _reset_json_schema_support() -> None:
    """Только для тестов: сбросить кэш определения поддержки json_schema."""
    global _json_schema_supported
    _json_schema_supported = None


# strict-схемы под два вызова. Требования strict-режима: additionalProperties=false и все
# поля в required на каждом объекте. Значения category/importance/doc_type ограничены
# прямо здесь — модель не сможет придумать своё, меньше *_UNSPECIFIED-фолбэков.
_FILTER_SCHEMA = {
    "name": "relevance",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["results"],
        "properties": {
            "results": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["i", "relevant"],
                    "properties": {
                        "i": {"type": "integer"},
                        "relevant": {"type": "boolean"},
                    },
                },
            }
        },
    },
}

_NEWS_SCHEMA = {
    "name": "news",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["news"],
        "properties": {
            "news": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "title", "content", "message_indices",
                        "category", "importance", "doc_type", "entities",
                    ],
                    "properties": {
                        "title": {"type": "string"},
                        "content": {"type": "string"},
                        "message_indices": {"type": "array", "items": {"type": "integer"}},
                        "category": {
                            "type": "string",
                            "enum": ["регуляторика", "репутация", "конкуренты", "тренды"],
                        },
                        "importance": {"type": "string", "enum": ["high", "medium", "low"]},
                        "doc_type": {"type": "string", "enum": ["npa", "news"]},
                        "entities": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["who", "what", "when", "consequences"],
                            "properties": {
                                "who": {"type": "string"},
                                "what": {"type": "string"},
                                "when": {"type": "string"},
                                "consequences": {"type": "string"},
                            },
                        },
                    },
                },
            }
        },
    },
}

_FILTER_SYS = (
    "Ты фильтр релевантности для мониторинга темы «{topic}».\n"
    "{extra}"
    "Тебе дан JSON-массив сообщений с индексами. Для каждого реши, относится ли оно к теме "
    "мониторинга (по существу, а не по случайному упоминанию).\n"
    'Ответ — строго JSON вида {{"results": [{{"i": <индекс>, "relevant": true|false}}]}}. '
    "Без пояснений и markdown."
)

_NEWS_SYS = (
    "Ты аналитик темы «{topic}». Тебе дан JSON-массив сообщений из СМИ, сайтов регуляторов "
    "и Telegram-каналов.\n"
    "Сгруппируй сообщения, относящиеся к ОДНОМУ И ТОМУ ЖЕ событию, и для каждой группы составь "
    "одну новость: короткий конкретный заголовок и текст в 3–5 предложений по сути события.\n"
    "Для каждой группы также определи:\n"
    "  category — одно из: регуляторика | репутация | конкуренты | тренды;\n"
    "  importance — одно из: high | medium | low (high — если есть риск штрафов, проверок, "
    "суда, отзыва лицензии, кризис или вступающее в силу требование);\n"
    "  doc_type — npa для нормативно-правового акта, news для новостной статьи;\n"
    "  entities — кто (who), что (what), когда (when), последствия (consequences); "
    "если чего-то в тексте нет, оставь пустую строку, не выдумывай.\n"
    "ВАЖНО: обработай ВСЕ сообщения из входного массива. Каждый индекс должен попасть ровно "
    "в одну группу; сообщение, ни с чем не совпавшее, становится отдельной новостью. "
    "Не рассуждай долго — сразу давай результат.\n"
    'Ответ — строго JSON вида {{"news": [{{"title": "...", "content": "...", '
    '"message_indices": [<индексы>], "category": "...", "importance": "...", '
    '"doc_type": "...", "entities": {{"who": "...", "what": "...", "when": "...", '
    '"consequences": "..."}}}}]}}. Без пояснений и markdown.'
)


class OpenAICompatProvider:
    def __init__(self) -> None:
        base = settings.LLM_BASE_URL.rstrip("/")
        # допускаем, что в ENV положили полный URL с /chat/completions
        if base.endswith("/chat/completions"):
            base = base[: -len("/chat/completions")]
        self.base_url = base
        self.api_key = settings.LLM_API_KEY
        self.model = settings.LLM_MODEL
        if not self.base_url or not self.model:
            raise RuntimeError("LLM_BASE_URL и LLM_MODEL обязательны для openai_compat")

    async def filter_relevance(self, topic: str, extra: str, texts: list[str]) -> list[bool]:
        extra_line = f"Дополнительно от пользователя: {extra}.\n" if extra else ""
        system = _FILTER_SYS.format(topic=topic, extra=extra_line)
        user = json.dumps([{"i": i, "text": t} for i, t in enumerate(texts)], ensure_ascii=False)
        data = await self._complete_json(system, user, json_schema=_FILTER_SCHEMA)
        flags = [False] * len(texts)
        for row in data.get("results", []):
            i = row.get("i")
            if isinstance(i, int) and 0 <= i < len(texts):
                flags[i] = bool(row.get("relevant"))
        return flags

    async def make_news(self, topic: str, messages: list[dict]) -> list[NewsGroup]:
        system = _NEWS_SYS.format(topic=topic)
        user = json.dumps(messages, ensure_ascii=False)
        data = await self._complete_json(system, user, json_schema=_NEWS_SCHEMA)
        out: list[NewsGroup] = []
        n = len(messages)
        for row in data.get("news", []):
            title = str(row.get("title") or "").strip()
            content = str(row.get("content") or "").strip()
            idxs = [i for i in row.get("message_indices", []) if isinstance(i, int) and 0 <= i < n]
            if not (title and content and idxs):
                continue
            # Поля обогащения читаем терпимо: пропущенное или незнакомое значение
            # станет *_UNSPECIFIED в app/llm/schema.py, но новость не потеряется.
            entities = row.get("entities")
            out.append(
                {
                    "title": title,
                    "content": content,
                    "message_indices": idxs,
                    "category": str(row.get("category") or "").strip(),
                    "importance": str(row.get("importance") or "").strip(),
                    "doc_type": str(row.get("doc_type") or "").strip(),
                    "entities": schema.entities_dict(entities if isinstance(entities, dict) else None),
                }
            )
        return out

    # --- внутреннее ---

    async def _complete_json(
        self,
        system: str,
        user: str,
        *,
        json_schema: dict[str, Any],
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Запрос к LLM с strict json_schema и откатом на json_object.

        Три уровня подстраховки формы ответа:
          1. `response_format: json_schema` — модель ограничена схемой на генерации;
          2. если эндпоинт её не принял (400) — `json_object` до конца процесса;
          3. `_loads_lenient` + ретрай ×3 на «почини JSON» — на случай, когда 200 пришёл,
             но форма всё равно кривая (json_object этого не гарантирует).
        Плюс поля читаются терпимо в `filter_relevance`/`make_news` — пропуск не роняет прогон.
        """
        global _json_schema_supported

        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        url = f"{self.base_url}/chat/completions"

        owns_client = client is None
        client = client or httpx.AsyncClient(timeout=180)
        try:
            for attempt in range(3):
                use_schema = _json_schema_supported is not False
                response_format = (
                    {"type": "json_schema", "json_schema": json_schema}
                    if use_schema
                    else {"type": "json_object"}
                )
                payload = {
                    "model": self.model,
                    "messages": messages,
                    "response_format": response_format,
                    "temperature": 0.2,
                }
                try:
                    resp = await _post_with_retry(client, url, payload, headers)
                except httpx.HTTPStatusError as exc:
                    if use_schema and exc.response.status_code == 400:
                        log.warning(
                            "LLM не принял json_schema — откат на json_object: %s",
                            exc.response.text[:200],
                        )
                        _json_schema_supported = False
                        continue  # тот же виток, но уже json_object
                    raise
                if use_schema and _json_schema_supported is None:
                    _json_schema_supported = True
                    log.info("LLM: strict json_schema поддерживается")

                content = resp.json()["choices"][0]["message"]["content"]
                try:
                    parsed = _loads_lenient(content)
                    if isinstance(parsed, list):
                        parsed = {"results": parsed, "news": parsed}
                    return parsed
                except ValueError:
                    log.warning("LLM вернул невалидный JSON (попытка %d)", attempt + 1)
                    messages.append({"role": "assistant", "content": content})
                    messages.append(
                        {"role": "user", "content": "Верни ТОЛЬКО валидный JSON, без markdown."}
                    )
            raise RuntimeError("LLM не вернул валидный JSON после 3 попыток")
        finally:
            if owns_client:
                await client.aclose()


async def _post_with_retry(
    client: httpx.AsyncClient, url: str, payload: dict[str, Any], headers: dict[str, str]
) -> httpx.Response:
    """POST с ретраем на транспортные ошибки и 429/5xx (не на 4xx вроде 400/401).

    Отдельно от ретрая на «невалидный JSON» в _complete_json — тот про содержимое ответа,
    этот про то, что ответ вообще дошёл.
    """
    delay = 1.0
    for attempt in range(_NETWORK_RETRIES):
        last = attempt == _NETWORK_RETRIES - 1
        try:
            resp = await client.post(url, json=payload, headers=headers)
        except httpx.TransportError as exc:
            if last:
                raise
            log.warning(
                "LLM: сетевая ошибка (попытка %d/%d): %s — повтор через %.0fс",
                attempt + 1, _NETWORK_RETRIES, exc, delay,
            )
            await asyncio.sleep(delay)
            delay *= 2
            continue

        if resp.status_code in _RETRYABLE_STATUS and not last:
            log.warning(
                "LLM: ответ %d (попытка %d/%d) — повтор через %.0fс",
                resp.status_code, attempt + 1, _NETWORK_RETRIES, delay,
            )
            await asyncio.sleep(delay)
            delay *= 2
            continue

        resp.raise_for_status()  # некоретраибельная 4xx — сразу наружу; исчерпанный retryable — тоже
        return resp

    raise RuntimeError("unreachable")  # цикл всегда либо return, либо raise


def _loads_lenient(text: str) -> Any:
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text.strip("`")
        if text.lstrip().lower().startswith("json"):
            text = text.lstrip()[4:]
    start = min((text.find(c) for c in "{[" if text.find(c) != -1), default=-1)
    end = max(text.rfind("}"), text.rfind("]"))
    if start != -1 and end != -1 and end > start:
        text = text[start : end + 1]
    return json.loads(text)
