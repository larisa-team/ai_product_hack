"""Чтение RSS/Atom-лент.

Одним коннектором закрываются две категории источников из чек-листа — СМИ и сайты
регуляторов: те регуляторы, что нужны для демо (напр. Банк России), публикуют RSS,
поэтому категория источника это ярлык (`Source.label`), а не отдельная технология
парсинга. Скрейпинг произвольного HTML сознательно не делаем — он хрупок.

Форма модуля повторяет `telegram_web.py`: dataclass записи + `fetch()`, чтобы воркер
работал с источниками единообразно.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import feedparser
import httpx
from selectolax.parser import HTMLParser

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)

log = logging.getLogger(__name__)


class RssFetchError(RuntimeError):
    """Лента недоступна или не разбирается."""


@dataclass(slots=True)
class RawRssEntry:
    feed_url: str
    guid: str  # entry.id/link — для логов; курсор и дедуп на нём НЕ строятся
    url: str
    text: str
    posted_at: datetime | None

    @property
    def content_hash(self) -> str:
        # Тот же рецепт, что у RawMessage: дедуп в messages общий для всех типов
        # источников, поэтому нормализация обязана совпадать.
        norm = re.sub(r"\s+", " ", self.text).strip().lower()[:2000]
        return hashlib.sha1(norm.encode("utf-8")).hexdigest()


def _strip_html(raw: str) -> str:
    """Описание записи часто приходит как HTML-фрагмент."""
    if not raw:
        return ""
    text = HTMLParser(raw).text(separator=" ") if "<" in raw else raw
    return re.sub(r"\s+", " ", text).strip()


def _entry_datetime(entry) -> datetime | None:
    """published -> updated -> None. Всегда в UTC, чтобы сравнивать с курсором."""
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def _entry_text(entry) -> str:
    """Заголовок + описание — то, что уходит в LLM как текст материала."""
    title = _strip_html(entry.get("title") or "")
    summary = _strip_html(entry.get("summary") or entry.get("description") or "")
    if title and summary:
        # Часть лент кладёт в описание тот же текст, что и в заголовок, плюс продолжение —
        # тогда берём описание целиком, иначе склеиваем. Заголовок в этом случае
        # отбрасывать нельзя: в описании он уже есть.
        return summary if summary.startswith(title) else f"{title}. {summary}"
    return title or summary


def _parse_feed(content: bytes, feed_url: str) -> list[RawRssEntry]:
    parsed = feedparser.parse(content)
    # bozo=1 бывает и на «грязных», но читаемых лентах — падаем только если
    # записей нет вовсе, иначе потеряли бы рабочий источник из-за придирки парсера.
    if parsed.bozo and not parsed.entries:
        raise RssFetchError(f"лента '{feed_url}' не разбирается: {parsed.get('bozo_exception')}")

    out: list[RawRssEntry] = []
    for entry in parsed.entries:
        text = _entry_text(entry)
        url = (entry.get("link") or "").strip()
        if not text or not url:
            continue
        out.append(
            RawRssEntry(
                feed_url=feed_url,
                guid=(entry.get("id") or url).strip(),
                url=url,
                text=text,
                posted_at=_entry_datetime(entry),
            )
        )
    return out


async def fetch(
    feed_url: str,
    since: datetime | None = None,
    limit: int = 50,
    days: int = 7,
) -> list[RawRssEntry]:
    """Записи ленты новее `since`, не старше `days`, не больше `limit`.

    Записи без даты пропускают проверку по времени: курсор они не двигают, а от
    повторной обработки их защищает UNIQUE(project_id, content_hash) в messages.
    """
    async with httpx.AsyncClient(
        headers={"User-Agent": _UA}, timeout=20, follow_redirects=True
    ) as client:
        try:
            resp = await client.get(feed_url)
        except httpx.HTTPError as exc:
            raise RssFetchError(f"лента '{feed_url}' недоступна: {exc}") from exc

    if resp.status_code != 200:
        raise RssFetchError(f"лента '{feed_url}' вернула HTTP {resp.status_code}")

    entries = _parse_feed(resp.content, feed_url)

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    selected: list[RawRssEntry] = []
    for entry in entries:
        if entry.posted_at is not None:
            if entry.posted_at < cutoff:
                continue
            if since is not None and entry.posted_at <= since:
                continue
        selected.append(entry)

    # Свежие — приоритетнее при обрезке по limit, но наружу отдаём по возрастанию:
    # compose рассчитывает на хронологический порядок.
    selected.sort(key=lambda e: (e.posted_at is not None, e.posted_at or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)
    selected = selected[:limit]
    selected.sort(key=lambda e: (e.posted_at is not None, e.posted_at or datetime.min.replace(tzinfo=timezone.utc)))
    return selected


async def _main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m app.ingestion.rss <feed_url> [days]", file=sys.stderr)
        return 2
    feed_url, days = argv[0], int(argv[1]) if len(argv) > 1 else 7
    try:
        entries = await fetch(feed_url, limit=30, days=days)
    except RssFetchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{feed_url}: {len(entries)} записей (последние {days}д)")
    for e in entries:
        ts = e.posted_at.isoformat() if e.posted_at else "?"
        print(f"  {ts}  {e.text[:90]}  -> {e.url}  #{e.content_hash[:8]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(sys.argv[1:])))
