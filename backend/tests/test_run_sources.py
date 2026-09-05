"""Отбор источников проекта в задания на сбор.

Здесь ловится инверсия флага `disabled`: если её сломать, прогон либо молча перестанет
собирать (все источники «выключены»), либо начнёт дёргать те, что поставили на паузу.
"""
from __future__ import annotations

from app.services.run_service import RunService

TELEGRAM = {"type": "SOURCE_TYPE_TELEGRAM", "telegram": "cit_gov"}
RSS = {"type": "SOURCE_TYPE_RSS", "rssUrl": "https://tass.ru/rss/v2.xml", "label": "ТАСС"}


def test_both_source_types_become_tasks():
    result = RunService._collect_sources([TELEGRAM, RSS])
    assert result == [
        {"source_type": "SOURCE_TYPE_TELEGRAM", "source_key": "cit_gov"},
        {"source_type": "SOURCE_TYPE_RSS", "source_key": "https://tass.ru/rss/v2.xml"},
    ]


def test_source_without_disabled_flag_is_collected():
    """Источник из старого проекта (в JSONB нет поля disabled) обязан собираться."""
    assert len(RunService._collect_sources([TELEGRAM])) == 1


def test_disabled_source_skipped():
    paused = {**TELEGRAM, "disabled": True}
    assert RunService._collect_sources([paused]) == []


def test_source_without_key_skipped():
    """RSS без URL и Telegram без канала — мусор, задачу на них ставить нечего."""
    assert RunService._collect_sources([{"type": "SOURCE_TYPE_RSS"}, {"type": "SOURCE_TYPE_TELEGRAM"}]) == []


def test_rss_url_is_the_key_not_telegram_field():
    """У RSS ключ берётся из rss_url, иначе курсор чтения будет пустой строкой."""
    assert RunService._collect_sources([RSS])[0]["source_key"] == "https://tass.ru/rss/v2.xml"
