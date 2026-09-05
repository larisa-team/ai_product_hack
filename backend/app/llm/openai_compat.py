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
        data = await self._complete_json(system, user)
        flags = [False] * len(texts)
        for row in data.get("results", []):
            i = row.get("i")
            if isinstance(i, int) and 0 <= i < len(texts):
                flags[i] = bool(row.get("relevant"))
        return flags

    async def make_news(self, topic: str, messages: list[dict]) -> list[NewsGroup]:
        system = _NEWS_SYS.format(topic=topic)
        user = json.dumps(messages, ensure_ascii=False)
        data = await self._complete_json(system, user)
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

    async def _complete_json(self, system: str, user: str) -> dict[str, Any]:
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]
        payload = {
            "model": self.model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "temperature": 0.2,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=180) as client:
            for attempt in range(3):
                resp = await _post_with_retry(
                    client, f"{self.base_url}/chat/completions", payload, headers
                )
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
