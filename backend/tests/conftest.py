"""Общие фикстуры. Тесты в этом каталоге — на чистой логике: без Postgres,
без Redis, без сети. Для генерённого protobuf-кода нужен PYTHONPATH на gen/
(уже прописан в Dockerfile: PYTHONPATH=/app:/app/gen).
"""
from __future__ import annotations

import pathlib

import pytest

FIXTURES = pathlib.Path(__file__).parent / "fixtures"


@pytest.fixture
def tme_cit_gov_html() -> str:
    return (FIXTURES / "tme_cit_gov.html").read_text(encoding="utf-8")


@pytest.fixture
def cbr_rss_xml() -> bytes:
    """Лента ЦБ РФ, снятая живьём. Байты, а не str: feedparser сам разбирает кодировку."""
    return (FIXTURES / "cbr_rsspress.xml").read_bytes()
