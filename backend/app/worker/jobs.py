"""Обработчики задач воркера: extract (сбор) и compose (фильтр + news-maker)."""
from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime

from app.config import settings
from app.database.models import News, Project, Run
from app.database.repositories.message_repo import MessageRepository
from app.database.session import async_session
from app.ingestion.telegram_web import NoPreviewError
from app.ingestion.telegram_web import fetch as tg_fetch
from app.llm.provider import get_provider
from app.queue import Q_COMPOSE, claim, dec_pending, enqueue
from app.services.run_service import DONE, FAILED

log = logging.getLogger(__name__)

_MIN_DT = datetime.min


def _chunks(seq: list, size: int) -> Iterator[list]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


async def handle_extract(payload: dict) -> None:
    run_id = payload["run_id"]
    project_id = payload["project_id"]
    channel = payload["channel"]
    job_id = f"{run_id}:{channel}"

    if not await claim(job_id):
        log.info("extract %s: уже в работе, пропуск", job_id)
        return

    async with async_session() as db:
        repo = MessageRepository(db)
        cursor = await repo.get_cursor(project_id, channel)

        try:
            msgs = await tg_fetch(
                channel,
                since_msg_id=cursor,
                limit=settings.TG_FETCH_LIMIT,
                days=settings.TG_FETCH_DAYS,
            )
        except NoPreviewError as exc:
            log.warning("extract %s: %s", job_id, exc)
            msgs = []
        except Exception:
            log.exception("extract %s: ошибка сбора", job_id)
            msgs = []

        inserted = 0
        max_id = cursor or 0
        for m in msgs:
            max_id = max(max_id, m.tg_msg_id)
            posted = m.posted_at.replace(tzinfo=None) if m.posted_at else None
            if await repo.add_if_new(
                project_id=project_id,
                run_id=run_id,
                channel=m.channel,
                tg_msg_id=m.tg_msg_id,
                url=m.url,
                text=m.text,
                posted_at=posted,
                content_hash=m.content_hash,
            ):
                inserted += 1

        if max_id:
            await repo.set_cursor(project_id, channel, max_id)
        await db.commit()
        log.info("extract %s: fetched=%d inserted=%d", job_id, len(msgs), inserted)

    remaining = await dec_pending(run_id)
    log.info("run %s: осталось extract-задач %d", run_id, remaining)
    if remaining <= 0:
        await enqueue(Q_COMPOSE, {"run_id": run_id})


async def handle_compose(payload: dict) -> None:
    run_id = payload["run_id"]
    if not await claim(f"compose:{run_id}"):
        log.info("compose %s: уже в работе, пропуск", run_id)
        return

    async with async_session() as db:
        run = await db.get(Run, run_id)
        if run is None:
            return
        project = await db.get(Project, run.project_id)
        repo = MessageRepository(db)
        msgs = await repo.list_by_run(run_id)

        if not msgs or project is None:
            run.state = DONE
            run.stats = {"collected": len(msgs), "relevant": 0, "news": 0}
            await db.commit()
            log.info("compose %s: нет новых сообщений", run_id)
            return

        try:
            provider = get_provider()
            extra = "; ".join(
                (f.get("prompt") or "").strip() for f in (project.filters or [])
            ).strip("; ")

            # --- message-filter ---
            # Ставим relevant прямо на загруженных объектах: bulk-UPDATE оставил бы
            # их в сессии устаревшими.
            for batch in _chunks(msgs, settings.FILTER_BATCH):
                flags = await provider.filter_relevance(
                    project.topic, extra, [m.text for m in batch]
                )
                for message, ok in zip(batch, flags):
                    message.relevant = bool(ok)
            await db.flush()

            relevant = [m for m in msgs if m.relevant]

            if not relevant:
                run.state = DONE
                run.stats = {"collected": len(msgs), "relevant": 0, "news": 0}
                await db.commit()
                log.info("compose %s: релевантных нет", run_id)
                return

            # --- news-maker (свежие, с обрезкой) ---
            capped = sorted(relevant, key=lambda m: m.posted_at or _MIN_DT, reverse=True)
            capped = capped[: settings.NEWSMAKER_CAP]
            capped.sort(key=lambda m: m.posted_at or _MIN_DT)
            # Батчим: на большом входе reasoning-модель сжигает бюджет на размышления
            # и возвращает результат лишь по части сообщений. Порядок хронологический,
            # поэтому посты об одном событии обычно попадают в один батч.
            groups = []
            for offset in range(0, len(capped), settings.NEWSMAKER_BATCH):
                batch = capped[offset : offset + settings.NEWSMAKER_BATCH]
                payload_msgs = [
                    {"i": i, "channel": m.channel, "text": m.text} for i, m in enumerate(batch)
                ]
                for g in await provider.make_news(project.topic, payload_msgs):
                    # индексы внутри батча -> позиции в capped
                    groups.append({**g, "message_indices": [offset + i for i in g["message_indices"]]})

            n_news = 0
            for g in groups:
                idxs = [i for i in g["message_indices"] if 0 <= i < len(capped)]
                if not idxs:
                    continue
                sources = list(dict.fromkeys(capped[i].url for i in idxs))
                db.add(
                    News(
                        run_id=run.id,
                        title=g["title"][:300],
                        content=g["content"],
                        sources=sources,
                    )
                )
                n_news += 1

            run.state = DONE
            run.stats = {
                "collected": len(msgs),
                "relevant": len(relevant),
                "news": n_news,
            }
            await db.commit()
            log.info(
                "compose %s: DONE collected=%d relevant=%d news=%d",
                run_id,
                len(msgs),
                len(relevant),
                n_news,
            )
        except Exception as exc:
            log.exception("compose %s: ошибка", run_id)
            await db.rollback()
            run = await db.get(Run, run_id)
            if run is not None:
                run.state = FAILED
                run.stats = {"collected": len(msgs), "error": str(exc)[:500]}
                await db.commit()
