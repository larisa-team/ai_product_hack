"""Ретрай на сетевые ошибки/5xx в openai_compat — без сети, через httpx.MockTransport."""
from __future__ import annotations

import httpx
import pytest

from app.llm import openai_compat
from app.llm.openai_compat import _post_with_retry


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    # backoff реальный (1/2/4с) в проде, но в тестах ждать незачем — экономим ~6с/прогон.
    async def _instant_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(openai_compat.asyncio, "sleep", _instant_sleep)


async def test_retries_on_503_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={"error": "overloaded"})
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        resp = await _post_with_retry(client, "http://x/chat/completions", {"a": 1}, {})

    assert resp.status_code == 200
    assert calls["n"] == 3


async def test_non_retryable_status_fails_fast():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(400, json={"error": "bad request"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await _post_with_retry(client, "http://x/chat/completions", {"a": 1}, {})

    assert calls["n"] == 1, "400 не ретраится — незачем ждать 3 попытки на заведомо плохой запрос"


async def test_exhausts_retries_on_persistent_5xx():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(503, json={"error": "still overloaded"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(httpx.HTTPStatusError):
            await _post_with_retry(client, "http://x/chat/completions", {"a": 1}, {})

    assert calls["n"] == 3
