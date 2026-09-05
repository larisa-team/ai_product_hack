"""Парсер RSS — на реальной фикстуре, без сети.

Фикстура снята живьём с ленты пресс-релизов Банка России: RSS 2.0, кириллица,
HTML внутри <description> — то есть ровно те особенности, на которых парсер и ломается.
"""
from __future__ import annotations

import pytest

from app.ingestion.rss import RawRssEntry, RssFetchError, _entry_text, _parse_feed, _strip_html

FEED = "https://www.cbr.ru/rss/RssPress"


def test_parse_fixture_returns_entries(cbr_rss_xml):
    entries = _parse_feed(cbr_rss_xml, FEED)
    assert len(entries) >= 5
    for e in entries:
        assert e.url.startswith("http")
        assert e.text
        assert e.feed_url == FEED


def test_parse_fixture_extracts_dates(cbr_rss_xml):
    entries = _parse_feed(cbr_rss_xml, FEED)
    dated = [e for e in entries if e.posted_at is not None]
    assert dated, "в ленте должны быть записи с датой — на ней строится курсор"
    for e in dated:
        # Курсор сравнивает даты между собой, поэтому tz обязателен: naive и aware
        # datetime в Python не сравниваются вовсе.
        assert e.posted_at.tzinfo is not None


def test_text_has_no_html_tags(cbr_rss_xml):
    entries = _parse_feed(cbr_rss_xml, FEED)
    for e in entries:
        assert "<" not in e.text and "&nbsp;" not in e.text


def test_broken_feed_raises():
    with pytest.raises(RssFetchError):
        _parse_feed("не xml вовсе".encode("utf-8"), FEED)


def test_content_hash_stable_to_whitespace_and_case():
    a = RawRssEntry(FEED, "g", "http://x", "ЦБ отозвал   лицензию", None)
    b = RawRssEntry(FEED, "g2", "http://y", "цб  отозвал лицензию  ", None)
    # Дедуп общий с Telegram (UNIQUE project_id+content_hash), поэтому перепечатка
    # одного текста в двух лентах обязана схлопываться.
    assert a.content_hash == b.content_hash


def test_content_hash_differs_for_different_text():
    a = RawRssEntry(FEED, "g", "http://x", "ЦБ отозвал лицензию", None)
    b = RawRssEntry(FEED, "g", "http://x", "ЦБ выдал лицензию", None)
    assert a.content_hash != b.content_hash


def test_entry_text_joins_title_and_summary():
    assert _entry_text({"title": "Заголовок", "summary": "Подробности"}) == "Заголовок. Подробности"


def test_entry_text_does_not_duplicate_title():
    # Часть лент кладёт в description тот же текст, что и в title.
    assert _entry_text({"title": "Заголовок", "summary": "Заголовок и продолжение"}) == "Заголовок и продолжение"


def test_strip_html_unwraps_fragment():
    assert _strip_html("<p>Текст <b>жирный</b></p>") == "Текст жирный"
