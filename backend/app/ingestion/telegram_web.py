"""Чтение публичных Telegram-каналов через веб-превью t.me/s/<channel>.

Без авторизации и API-ключей. Только публичные каналы, только текст постов.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import httpx
from dateutil import parser as dtparser
from selectolax.parser import HTMLParser

_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0 Safari/537.36"
)
_BASE = "https://t.me/s/"
_MAX_PAGES = 15

log = logging.getLogger(__name__)


class NoPreviewError(RuntimeError):
    """Канал не отдаёт веб-превью (t.me/s/ редиректит на обычную страницу)."""


@dataclass(slots=True)
class RawMessage:
    channel: str
    tg_msg_id: int
    url: str
    text: str
    posted_at: datetime | None

    @property
    def content_hash(self) -> str:
        norm = re.sub(r"\s+", " ", self.text).strip().lower()[:2000]
        return hashlib.sha1(norm.encode("utf-8")).hexdigest()


def normalize_channel(raw: str) -> str:
    s = raw.strip()
    s = re.sub(r"^https?://", "", s)
    s = re.sub(r"^t\.me/", "", s)
    s = re.sub(r"^s/", "", s)
    s = s.lstrip("@").strip("/")
    return s.split("/")[0].split("?")[0]


def _parse_page(html: str, channel: str) -> list[RawMessage]:
    tree = HTMLParser(html)
    out: list[RawMessage] = []
    for node in tree.css(".tgme_widget_message"):
        data_post = node.attributes.get("data-post") or ""
        m = re.search(r"/(\d+)$", data_post)
        if not m:
            continue
        msg_id = int(m.group(1))
        text_node = node.css_first(".tgme_widget_message_text")
        raw_text = text_node.text(separator=" ") if text_node else ""
        text = re.sub(r"\s+", " ", raw_text).strip()
        posted_at: datetime | None = None
        time_node = node.css_first(".tgme_widget_message_date time")
        iso = time_node.attributes.get("datetime") if time_node else None
        if iso:
            try:
                posted_at = dtparser.isoparse(iso)
            except (ValueError, TypeError):
                posted_at = None
        out.append(
            RawMessage(
                channel=channel,
                tg_msg_id=msg_id,
                url=f"https://t.me/{channel}/{msg_id}",
                text=text,
                posted_at=posted_at,
            )
        )
    out.sort(key=lambda r: r.tg_msg_id)  # старые -> новые
    return out


async def fetch(
    channel: str,
    since_msg_id: int | None = None,
    limit: int = 100,
    days: int = 7,
) -> list[RawMessage]:
    """Посты канала новее since_msg_id, не старше `days`, не больше `limit`."""
    channel = normalize_channel(channel)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    collected: dict[int, RawMessage] = {}
    before: int | None = None

    async with httpx.AsyncClient(
        headers={"User-Agent": _UA}, timeout=15, follow_redirects=True
    ) as client:
        for page_i in range(_MAX_PAGES):
            params = {"before": before} if before else None
            resp = await client.get(_BASE + channel, params=params)
            if resp.status_code != 200:
                break
            if page_i == 0 and "/s/" not in str(resp.url):
                raise NoPreviewError(
                    f"канал '{channel}' не отдаёт веб-превью (redirect -> {resp.url})"
                )
            page = _parse_page(resp.text, channel)
            if not page:
                break

            for msg in page:
                if since_msg_id is not None and msg.tg_msg_id <= since_msg_id:
                    continue
                if msg.posted_at is not None and msg.posted_at < cutoff:
                    continue
                if msg.text:
                    collected[msg.tg_msg_id] = msg

            page_min = min(m.tg_msg_id for m in page)
            oldest = page[0]
            reached_since = since_msg_id is not None and page_min <= since_msg_id
            reached_cutoff = oldest.posted_at is not None and oldest.posted_at < cutoff
            if len(collected) >= limit or reached_since or reached_cutoff:
                break
            if before is not None and page_min >= before:
                break
            before = page_min

    result = sorted(collected.values(), key=lambda r: r.tg_msg_id, reverse=True)[:limit]
    result.sort(key=lambda r: r.tg_msg_id)
    return result


async def _main(argv: list[str]) -> int:
    if not argv:
        print("usage: python -m app.ingestion.telegram_web <channel> [days]", file=sys.stderr)
        return 2
    channel, days = argv[0], int(argv[1]) if len(argv) > 1 else 7
    try:
        msgs = await fetch(channel, limit=30, days=days)
    except NoPreviewError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"{normalize_channel(channel)}: {len(msgs)} messages (last {days}d)")
    for m in msgs:
        ts = m.posted_at.isoformat() if m.posted_at else "?"
        print(f"  [{m.tg_msg_id}] {ts}  {m.text[:90]}  -> {m.url}  #{m.content_hash[:8]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main(sys.argv[1:])))
