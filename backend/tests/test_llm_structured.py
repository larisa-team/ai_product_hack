"""strict json_schema + откат на json_object — без сети, через httpx.MockTransport.

Проверяем именно подстраховку: не все модели за RouterAI умеют json_schema, и первый 400
обязан молча перевести процесс на json_object, а не уронить прогон.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.llm import openai_compat
from app.llm.openai_compat import OpenAICompatProvider, _NEWS_SCHEMA


@pytest.fixture(autouse=True)
def _env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(openai_compat.settings, "LLM_BASE_URL", "http://llm.test/v1", raising=False)
    monkeypatch.setattr(openai_compat.settings, "LLM_MODEL", "test-model", raising=False)
    monkeypatch.setattr(openai_compat.settings, "LLM_API_KEY", "", raising=False)

    async def _instant_sleep(_s: float) -> None:
        return None

    monkeypatch.setattr(openai_compat.asyncio, "sleep", _instant_sleep)
    openai_compat._reset_json_schema_support()
    yield
    openai_compat._reset_json_schema_support()


def _ok_body() -> dict:
    return {"choices": [{"message": {"content": json.dumps({"news": []})}}]}


async def _run(handler) -> tuple[dict, list[dict]]:
    seen: list[dict] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content))
        return handler(request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(wrapped)) as client:
        data = await OpenAICompatProvider()._complete_json(
            "sys", "user", json_schema=_NEWS_SCHEMA, client=client
        )
    return data, seen


async def test_uses_json_schema_when_supported():
    data, seen = await _run(lambda _r: httpx.Response(200, json=_ok_body()))
    assert data == {"news": []}
    assert seen[0]["response_format"]["type"] == "json_schema"
    assert seen[0]["response_format"]["json_schema"]["name"] == "news"
    assert openai_compat._json_schema_supported is True


async def test_falls_back_to_json_object_on_400():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["response_format"]["type"] == "json_schema":
            return httpx.Response(400, json={"error": "response_format json_schema not supported"})
        return httpx.Response(200, json=_ok_body())

    data, seen = await _run(handler)
    assert data == {"news": []}
    assert seen[0]["response_format"]["type"] == "json_schema"  # попробовали
    assert seen[1]["response_format"]["type"] == "json_object"  # откатились
    assert openai_compat._json_schema_supported is False


async def test_fallback_is_remembered_across_calls():
    """После первого отказа второй вызов идёт сразу json_object — без лишнего 400."""
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["response_format"]["type"] == "json_schema":
            return httpx.Response(400, json={"error": "nope"})
        return httpx.Response(200, json=_ok_body())

    await _run(handler)  # тут сработал откат
    _, seen = await _run(handler)
    assert [s["response_format"]["type"] for s in seen] == ["json_object"]


async def test_real_400_still_raises():
    """Если и json_object отдаёт 400 — это настоящая ошибка, не глотаем."""
    with pytest.raises(httpx.HTTPStatusError):
        await _run(lambda _r: httpx.Response(400, json={"error": "bad model"}))
