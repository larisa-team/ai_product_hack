"""Парсинг t.me/s/ — на сохранённой HTML-фикстуре, без сети.
Фикстура: tests/fixtures/tme_cit_gov.html, снята с реального канала cit_gov.
"""
from __future__ import annotations

import re

from app.ingestion.telegram_web import _parse_page, normalize_channel


def test_normalize_channel():
    assert normalize_channel("cit_gov") == "cit_gov"
    assert normalize_channel("@cit_gov") == "cit_gov"
    assert normalize_channel("https://t.me/cit_gov") == "cit_gov"
    assert normalize_channel("t.me/cit_gov") == "cit_gov"
    assert normalize_channel(" @cit_gov/ ") == "cit_gov"


def test_parse_page_extracts_messages(tme_cit_gov_html: str):
    messages = _parse_page(tme_cit_gov_html, "cit_gov")
    assert len(messages) > 0, "фикстура должна содержать хотя бы один пост"

    for m in messages:
        assert m.channel == "cit_gov"
        assert m.tg_msg_id > 0
        assert m.url == f"https://t.me/cit_gov/{m.tg_msg_id}"
        assert "\n" not in m.text, "текст должен быть схлопнут в одну строку (collapse whitespace)"
        assert re.fullmatch(r"[0-9a-f]{40}", m.content_hash), "content_hash — sha1 hex"

    # старые -> новые
    ids = [m.tg_msg_id for m in messages]
    assert ids == sorted(ids)


def test_content_hash_stable_for_same_text():
    from app.ingestion.telegram_web import RawMessage

    a = RawMessage(channel="c", tg_msg_id=1, url="u1", text="Привет   мир", posted_at=None)
    b = RawMessage(channel="c", tg_msg_id=2, url="u2", text="привет мир", posted_at=None)
    # регистр и лишние пробелы не должны влиять — это и есть дедуп по смыслу текста
    assert a.content_hash == b.content_hash


def test_content_hash_differs_for_different_text():
    from app.ingestion.telegram_web import RawMessage

    a = RawMessage(channel="c", tg_msg_id=1, url="u1", text="Новость номер один", posted_at=None)
    b = RawMessage(channel="c", tg_msg_id=2, url="u2", text="Совсем другая новость", posted_at=None)
    assert a.content_hash != b.content_hash
