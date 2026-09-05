from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.models import Message, SourceCursor


class MessageRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def add_if_new(
        self,
        *,
        project_id: str,
        run_id: str,
        source_key: str,
        url: str,
        text: str,
        posted_at: datetime | None,
        content_hash: str,
        tg_msg_id: int | None = None,
    ) -> bool:
        """Вставить материал. False — такой content_hash уже есть в проекте (дубль).

        `tg_msg_id` только для Telegram; у записей RSS сквозного номера нет.
        """
        stmt = (
            pg_insert(Message)
            .values(
                project_id=project_id,
                run_id=run_id,
                source_key=source_key,
                tg_msg_id=tg_msg_id,
                url=url,
                text=text,
                posted_at=posted_at,
                content_hash=content_hash,
            )
            .on_conflict_do_nothing(constraint="uq_messages_hash")
            .returning(Message.id)
        )
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none() is not None

    async def list_by_run(self, run_id: str) -> list[Message]:
        result = await self.db.execute(
            select(Message).where(Message.run_id == run_id).order_by(Message.posted_at)
        )
        return list(result.scalars().all())

    async def mark_relevant(self, message_ids: list[int], relevant: bool) -> None:
        if not message_ids:
            return
        await self.db.execute(
            update(Message).where(Message.id.in_(message_ids)).values(relevant=relevant)
        )

    # --- курсоры источников ---
    #
    # Курсор зависит от типа: у Telegram это сквозной номер сообщения, у RSS —
    # дата публикации (номеров там нет). Отсюда две пары методов на одну таблицу.

    async def get_cursor(self, project_id: str, source_key: str) -> int | None:
        """Курсор Telegram: последний прочитанный номер сообщения."""
        result = await self.db.execute(
            select(SourceCursor.last_msg_id).where(
                SourceCursor.project_id == project_id, SourceCursor.source_key == source_key
            )
        )
        return result.scalar_one_or_none()

    async def set_cursor(self, project_id: str, source_key: str, last_msg_id: int) -> None:
        stmt = (
            pg_insert(SourceCursor)
            .values(project_id=project_id, source_key=source_key, last_msg_id=last_msg_id)
            .on_conflict_do_update(
                index_elements=[SourceCursor.project_id, SourceCursor.source_key],
                set_={"last_msg_id": last_msg_id},
            )
        )
        await self.db.execute(stmt)

    async def get_cursor_published_at(self, project_id: str, source_key: str) -> datetime | None:
        """Курсор RSS: дата публикации последней прочитанной записи."""
        result = await self.db.execute(
            select(SourceCursor.last_published_at).where(
                SourceCursor.project_id == project_id, SourceCursor.source_key == source_key
            )
        )
        return result.scalar_one_or_none()

    async def set_cursor_published_at(
        self, project_id: str, source_key: str, last_published_at: datetime
    ) -> None:
        stmt = (
            pg_insert(SourceCursor)
            .values(
                project_id=project_id,
                source_key=source_key,
                last_published_at=last_published_at,
            )
            .on_conflict_do_update(
                index_elements=[SourceCursor.project_id, SourceCursor.source_key],
                set_={"last_published_at": last_published_at},
            )
        )
        await self.db.execute(stmt)
