"""Обработчики задач воркера: extract (сбор) и compose (фильтр + news-maker)."""
from __future__ import annotations

import logging
from collections.abc import Iterator
from datetime import datetime, timezone

from app.config import settings
from app.database.models import News, Project, Run, Task
from app.database.repositories.message_repo import MessageRepository
from app.database.repositories.task_repo import TaskRepository
from app.database.session import async_session
from app.ingestion.rss import RssFetchError
from app.ingestion.rss import fetch as rss_fetch
from app.ingestion.telegram_web import NoPreviewError
from app.ingestion.telegram_web import fetch as tg_fetch
from app.llm import schema
from app.llm.provider import get_provider
from app.queue import CLAIM_TTL_COMPOSE, CLAIM_TTL_EXTRACT, claim
from app.services.run_service import DONE, FAILED


def _n_batches(total: int, size: int) -> int:
    return -(-total // size) if total else 0

log = logging.getLogger(__name__)

_MIN_DT = datetime.min

# Имена значений monitoring.v1.SourceType — в таком виде тип едет в payload задачи.
TELEGRAM = "SOURCE_TYPE_TELEGRAM"
RSS = "SOURCE_TYPE_RSS"


def _chunks(seq: list, size: int) -> Iterator[list]:
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _entities_with_date(raw: dict | None, messages: list) -> dict[str, str]:
    """Сущности группы; `when` при необходимости достраивается из дат сообщений.

    Дата публикации у нас и так есть — просить её у модели значит рисковать выдумкой
    там, где есть факт. Но если модель вернула что-то содержательное («вступает в силу
    с 1 марта»), это ценнее даты поста, поэтому её ответ приоритетнее.
    """
    entities = schema.entities_dict(raw)
    if entities["when"]:
        return entities
    dates = [m.posted_at for m in messages if m.posted_at]
    if dates:
        entities["when"] = min(dates).strftime("%d.%m.%Y")
    return entities


async def handle_extract(task: Task) -> None:
    run_id = task.run_id
    project_id = task.payload["project_id"]
    source_key = task.payload["source_key"]
    source_type = task.payload.get("source_type", TELEGRAM)
    collection_days = task.payload.get("collection_days", settings.TG_FETCH_DAYS)
    job_id = f"{run_id}:{source_key}"

    if not await claim(job_id, ttl=CLAIM_TTL_EXTRACT):
        log.info("extract %s: уже в работе, пропуск", job_id)
        return

    # Отдельный коммит до самой работы: claim() уже гарантировал, что задачу исполняем
    # именно мы, а откат следующей транзакции (например, при сбое сбора) не должен
    # вернуть задачу обратно в pending и заставить её опрашивать заново.
    async with async_session() as db:
        await TaskRepository(db).mark_done(task.id)
        await db.commit()

    async with async_session() as db:
        repo = MessageRepository(db)

        if source_type == RSS:
            fetched, inserted = await _extract_rss(
                repo, project_id, run_id, source_key, job_id, collection_days
            )
        else:
            fetched, inserted = await _extract_telegram(
                repo, project_id, run_id, source_key, job_id, collection_days
            )

        task_repo = TaskRepository(db)
        remaining = await task_repo.count_pending(run_id, "extract")
        if remaining <= 0:
            await task_repo.enqueue_compose_if_ready(run_id)

        await db.commit()
        log.info(
            "extract %s [%s]: fetched=%d inserted=%d, осталось extract-задач %d",
            job_id, source_type, fetched, inserted, remaining,
        )


async def _extract_telegram(
    repo: MessageRepository, project_id: str, run_id: str, channel: str, job_id: str,
    collection_days: int,
) -> tuple[int, int]:
    """Telegram: курсор — сквозной номер сообщения."""
    cursor = await repo.get_cursor(project_id, channel)
    # Период проекта применяется только к первому сбору источника; дальше рулит курсор.
    days = collection_days if cursor is None else settings.TG_FETCH_DAYS
    try:
        msgs = await tg_fetch(
            channel,
            since_msg_id=cursor,
            limit=settings.TG_FETCH_LIMIT,
            days=days,
        )
    except NoPreviewError as exc:
        # Часть каналов отключает веб-превью — это не авария всего прогона.
        log.warning("extract %s: %s", job_id, exc)
        return 0, 0
    except Exception:
        log.exception("extract %s: ошибка сбора", job_id)
        return 0, 0

    inserted = 0
    max_id = cursor or 0
    for m in msgs:
        max_id = max(max_id, m.tg_msg_id)
        posted = m.posted_at.replace(tzinfo=None) if m.posted_at else None
        if await repo.add_if_new(
            project_id=project_id,
            run_id=run_id,
            source_key=m.channel,
            tg_msg_id=m.tg_msg_id,
            url=m.url,
            text=m.text,
            posted_at=posted,
            content_hash=m.content_hash,
        ):
            inserted += 1

    if max_id:
        await repo.set_cursor(project_id, channel, max_id)
    return len(msgs), inserted


async def _extract_rss(
    repo: MessageRepository, project_id: str, run_id: str, feed_url: str, job_id: str,
    collection_days: int,
) -> tuple[int, int]:
    """RSS: курсор — дата публикации, сквозных номеров у записей нет."""
    cursor = await repo.get_cursor_published_at(project_id, feed_url)
    # Курсор лежит в БД без таймзоны, а записи ленты приходят в UTC — сравнивать
    # naive и aware datetime нельзя, поэтому приводим курсор к UTC.
    since = cursor.replace(tzinfo=timezone.utc) if cursor is not None else None
    days = collection_days if cursor is None else settings.RSS_FETCH_DAYS
    try:
        entries = await rss_fetch(
            feed_url,
            since=since,
            limit=settings.RSS_FETCH_LIMIT,
            days=days,
        )
    except RssFetchError as exc:
        log.warning("extract %s: %s", job_id, exc)
        return 0, 0
    except Exception:
        log.exception("extract %s: ошибка сбора", job_id)
        return 0, 0

    inserted = 0
    newest: datetime | None = None
    for e in entries:
        posted = e.posted_at.replace(tzinfo=None) if e.posted_at else None
        if posted is not None and (newest is None or posted > newest):
            newest = posted
        if await repo.add_if_new(
            project_id=project_id,
            run_id=run_id,
            source_key=feed_url,
            url=e.url,
            text=e.text,
            posted_at=posted,
            content_hash=e.content_hash,
        ):
            inserted += 1

    if newest is not None:
        await repo.set_cursor_published_at(project_id, feed_url, newest)
    return len(entries), inserted


async def handle_compose(task: Task) -> None:
    run_id = task.run_id
    if not await claim(f"compose:{run_id}", ttl=CLAIM_TTL_COMPOSE):
        log.info("compose %s: уже в работе, пропуск", run_id)
        return

    async with async_session() as db:
        await TaskRepository(db).mark_done(task.id)
        await db.commit()

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
            # их в сессии устаревшими. Прогресс пишем после каждого батча —
            # фронт поллит GetRun и рисует полосу; заодно продлеваем heartbeat
            # (иначе на длинном compose /api/health покажет worker: false).
            n_filter = _n_batches(len(msgs), settings.FILTER_BATCH)
            run.stats = {
                "collected": len(msgs),
                "stage": "filtering",
                "stage_done": 0,
                "stage_total": n_filter,
            }
            await db.commit()
            for i, batch in enumerate(_chunks(msgs, settings.FILTER_BATCH)):
                flags = await provider.filter_relevance(
                    project.topic, extra, [m.text for m in batch]
                )
                for message, ok in zip(batch, flags):
                    message.relevant = bool(ok)
                run.stats = {**run.stats, "stage_done": i + 1}
                await db.commit()

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
            n_news_batches = _n_batches(len(capped), settings.NEWSMAKER_BATCH)
            run.stats = {
                "collected": len(msgs),
                "relevant": len(relevant),
                "stage": "composing",
                "stage_done": 0,
                "stage_total": n_news_batches,
            }
            await db.commit()
            # Батчим: на большом входе reasoning-модель сжигает бюджет на размышления
            # и возвращает результат лишь по части сообщений. Порядок хронологический,
            # поэтому посты об одном событии обычно попадают в один батч.
            groups = []
            for offset in range(0, len(capped), settings.NEWSMAKER_BATCH):
                batch = capped[offset : offset + settings.NEWSMAKER_BATCH]
                payload_msgs = [
                    {"i": i, "source": m.source_key, "text": m.text} for i, m in enumerate(batch)
                ]
                for g in await provider.make_news(
                    project.topic, payload_msgs, project.profile or ""
                ):
                    # индексы внутри батча -> позиции в capped
                    groups.append({**g, "message_indices": [offset + i for i in g["message_indices"]]})
                run.stats = {**run.stats, "stage_done": offset // settings.NEWSMAKER_BATCH + 1}
                await db.commit()

            n_news = 0
            for g in groups:
                idxs = [i for i in g["message_indices"] if 0 <= i < len(capped)]
                if not idxs:
                    continue
                sources = list(dict.fromkeys(capped[i].url for i in idxs))
                db.add(
                    News(
                        project_id=run.project_id,
                        run_id=run.id,
                        title=g["title"][:300],
                        content=g["content"],
                        sources=sources,
                        category=schema.category_enum_name(g.get("category")),
                        importance=schema.importance_enum_name(g.get("importance")),
                        doc_type=schema.doc_type_enum_name(g.get("doc_type")),
                        entities=_entities_with_date(g.get("entities"), [capped[i] for i in idxs]),
                        tags=[],
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
