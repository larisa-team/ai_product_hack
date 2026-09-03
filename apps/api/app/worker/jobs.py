"""Обработчики задач воркера: extract (сбор) и compose (фильтр + news-maker)."""
from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.config import get_settings
from app.db import SessionLocal
from app.ingestion.telegram_web import NoPreviewError
from app.ingestion.telegram_web import fetch as tg_fetch
from app.llm.provider import get_provider
from app.models import Message, News, Project, Run, Source
from app.queue import Q_COMPOSE, claim, dec_pending, enqueue

log = logging.getLogger(__name__)

_MIN_DT = datetime.min.replace(tzinfo=timezone.utc)


def _chunks(seq: list, size: int) -> Iterator[list]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def handle_extract(payload: dict) -> None:
    run_id = payload["run_id"]
    source_id = payload["source_id"]
    job_id = f"{run_id}:{source_id}"
    if not claim(job_id):
        log.info("extract %s: уже в работе, пропуск", job_id)
        return

    settings = get_settings()
    with SessionLocal() as db:
        source = db.get(Source, uuid.UUID(source_id))
        run = db.get(Run, uuid.UUID(run_id))
        if source is None or run is None:
            log.warning("extract %s: source/run не найдены", job_id)
            _after_extract(run_id)
            return

        try:
            msgs = tg_fetch(
                source.telegram,
                since_msg_id=source.last_msg_id,
                limit=settings.tg_fetch_limit,
                days=settings.tg_fetch_days,
            )
        except NoPreviewError as exc:
            log.warning("extract %s: %s", job_id, exc)
            msgs = []
        except Exception:
            log.exception("extract %s: ошибка сбора", job_id)
            msgs = []

        inserted = 0
        max_id = source.last_msg_id or 0
        for m in msgs:
            max_id = max(max_id, m.tg_msg_id)
            dup = db.scalar(
                select(Message.id).where(
                    Message.project_id == source.project_id,
                    Message.content_hash == m.content_hash,
                )
            )
            if dup:
                continue
            sp = db.begin_nested()
            try:
                db.add(
                    Message(
                        project_id=source.project_id,
                        source_id=source.id,
                        run_id=run.id,
                        tg_channel=m.tg_channel,
                        tg_msg_id=m.tg_msg_id,
                        url=m.url,
                        text=m.text,
                        posted_at=m.posted_at,
                        content_hash=m.content_hash,
                    )
                )
                db.flush()
                sp.commit()
                inserted += 1
            except IntegrityError:
                sp.rollback()  # гонка по content_hash с другим воркером

        if max_id:
            source.last_msg_id = max_id
        db.commit()
        log.info("extract %s: fetched=%d inserted=%d", job_id, len(msgs), inserted)

    _after_extract(run_id)


def _after_extract(run_id: str) -> None:
    remaining = dec_pending(run_id)
    log.info("run %s: осталось extract-задач %d", run_id, remaining)
    if remaining <= 0:
        enqueue(Q_COMPOSE, {"run_id": run_id})


def _finish(db, run: Run, collected: int, relevant: int, news: int) -> None:
    run.state = "DONE"
    run.finished_at = datetime.now(timezone.utc)
    run.stats = {"collected": collected, "relevant": relevant, "news": news}
    db.commit()


def handle_compose(payload: dict) -> None:
    """Фильтр релевантности (батчами) + news-maker (один вызов) -> строки news."""
    run_id = payload["run_id"]
    if not claim(f"compose:{run_id}"):
        log.info("compose %s: уже в работе, пропуск", run_id)
        return

    settings = get_settings()
    with SessionLocal() as db:
        run = db.get(Run, uuid.UUID(run_id))
        if run is None:
            return
        project = db.get(Project, run.project_id)
        msgs = list(
            db.scalars(
                select(Message).where(Message.run_id == run.id).order_by(Message.posted_at)
            )
        )
        if not msgs or project is None:
            _finish(db, run, len(msgs), 0, 0)
            log.info("compose %s: нет новых сообщений", run_id)
            return

        try:
            provider = get_provider()

            # --- message-filter ---
            extra = "; ".join(f.prompt for f in project.filters)
            for batch in _chunks(msgs, settings.filter_batch):
                flags = provider.filter_relevance(project.topic, extra, [m.text for m in batch])
                for m, ok in zip(batch, flags):
                    m.relevant = bool(ok)
            db.flush()

            relevant = [m for m in msgs if m.relevant]
            if not relevant:
                _finish(db, run, len(msgs), 0, 0)
                log.info("compose %s: релевантных нет", run_id)
                return

            # --- news-maker (свежие, с обрезкой) ---
            capped = sorted(relevant, key=lambda m: m.posted_at or _MIN_DT, reverse=True)
            capped = capped[: settings.newsmaker_cap]
            capped.sort(key=lambda m: m.posted_at or _MIN_DT)
            payload_msgs = [
                {"i": i, "channel": m.tg_channel, "text": m.text} for i, m in enumerate(capped)
            ]
            groups = provider.make_news(project.topic, payload_msgs)

            n_news = 0
            for g in groups:
                idxs = [i for i in g["message_indices"] if 0 <= i < len(capped)]
                if not idxs:
                    continue
                sources = list(dict.fromkeys(capped[i].url for i in idxs))
                db.add(
                    News(
                        run_id=run.id,
                        project_id=run.project_id,
                        title=g["title"][:300],
                        content=g["content"],
                        sources=sources,
                    )
                )
                n_news += 1

            _finish(db, run, len(msgs), len(relevant), n_news)
            log.info(
                "compose %s: DONE collected=%d relevant=%d news=%d",
                run_id,
                len(msgs),
                len(relevant),
                n_news,
            )
        except Exception as exc:  # noqa: BLE001
            log.exception("compose %s: ошибка", run_id)
            db.rollback()
            run = db.get(Run, uuid.UUID(run_id))
            if run is not None:
                run.state = "FAILED"
                run.finished_at = datetime.now(timezone.utc)
                run.stats = {"collected": len(msgs), "error": str(exc)[:500]}
                db.commit()
