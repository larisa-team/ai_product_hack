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
        channel: str,
        tg_msg_id: int,
        url: str,
        text: str,
        posted_at: datetime | None,
        content_hash: str,
    ) -> bool:
        """Вставить пост. False — такой content_hash уже есть в проекте (дубль)."""
        stmt = (
            pg_insert(Message)
            .values(
                project_id=project_id,
                run_id=run_id,
                channel=channel,
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

    # --- курсоры каналов ---

    async def get_cursor(self, project_id: str, channel: str) -> int | None:
        result = await self.db.execute(
            select(SourceCursor.last_msg_id).where(
                SourceCursor.project_id == project_id, SourceCursor.channel == channel
            )
        )
        return result.scalar_one_or_none()

    async def set_cursor(self, project_id: str, channel: str, last_msg_id: int) -> None:
        stmt = (
            pg_insert(SourceCursor)
            .values(project_id=project_id, channel=channel, last_msg_id=last_msg_id)
            .on_conflict_do_update(
                index_elements=[SourceCursor.project_id, SourceCursor.channel],
                set_={"last_msg_id": last_msg_id},
            )
        )
        await self.db.execute(stmt)
