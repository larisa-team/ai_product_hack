"""RSS-источники и обогащение карточки новости

Две вещи разом, потому что они и в проде поедут вместе:
1) messages/source_cursors перестают быть Telegram-специфичными (channel -> source_key,
   tg_msg_id становится nullable, у курсора появляется дата публикации для RSS);
2) news получает project_id + обогащение (категория, важность, тип, сущности, теги,
   скрытие) и разрешает NULL в run_id — у материалов, добавленных вручную, прогона нет.

Переименования сделаны через alter_column, а не drop+add: данные существующих
проектов (курсоры чтения!) обязаны пережить миграцию.

Revision ID: a7e4b2c9d150
Revises: f1c2a4e9b7d3
Create Date: 2026-09-05 13:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'a7e4b2c9d150'
down_revision: Union[str, Sequence[str], None] = 'f1c2a4e9b7d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- источники: снимаем привязку схемы к Telegram ---
    op.alter_column('messages', 'channel', new_column_name='source_key')
    op.alter_column('messages', 'tg_msg_id', existing_type=sa.BigInteger(), nullable=True)

    op.alter_column('source_cursors', 'channel', new_column_name='source_key')
    op.add_column('source_cursors', sa.Column('last_published_at', sa.DateTime(), nullable=True))

    # --- news: обогащение ---
    # server_default обязателен: таблица не пуста, а колонки NOT NULL.
    op.add_column('news', sa.Column('category', sa.String(length=40), nullable=False,
                                    server_default='NEWS_CATEGORY_UNSPECIFIED'))
    op.add_column('news', sa.Column('importance', sa.String(length=40), nullable=False,
                                    server_default='NEWS_IMPORTANCE_UNSPECIFIED'))
    op.add_column('news', sa.Column('doc_type', sa.String(length=30), nullable=False,
                                    server_default='DOC_TYPE_UNSPECIFIED'))
    op.add_column('news', sa.Column('entities', postgresql.JSONB(astext_type=sa.Text()),
                                    nullable=False, server_default=sa.text("'{}'::jsonb")))
    op.add_column('news', sa.Column('tags', postgresql.JSONB(astext_type=sa.Text()),
                                    nullable=False, server_default=sa.text("'[]'::jsonb")))
    op.add_column('news', sa.Column('hidden', sa.Boolean(), nullable=False,
                                    server_default=sa.false()))
    op.add_column('news', sa.Column('created_at', sa.DateTime(), nullable=False,
                                    server_default=sa.text('now()')))

    # project_id: добавляем nullable -> заполняем из runs -> только потом NOT NULL,
    # иначе миграция упадёт на любой непустой таблице.
    op.add_column('news', sa.Column('project_id', sa.String(), nullable=True))
    op.execute("""
        UPDATE news SET project_id = runs.project_id
        FROM runs WHERE news.run_id = runs.id
    """)
    # Осиротевших строк быть не может (news.run_id был NOT NULL + FK), но если БД
    # чинили руками — такие строки удаляем, иначе SET NOT NULL не пройдёт.
    op.execute("DELETE FROM news WHERE project_id IS NULL")
    op.alter_column('news', 'project_id', nullable=False)
    op.create_foreign_key('news_project_id_fkey', 'news', 'projects', ['project_id'], ['id'],
                          ondelete='CASCADE')
    op.create_index(op.f('ix_news_project_id'), 'news', ['project_id'], unique=False)

    # run_id становится необязательным — у ручных материалов прогона нет.
    op.alter_column('news', 'run_id', existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    # Ручные материалы (run_id IS NULL) в старой схеме непредставимы.
    op.execute("DELETE FROM news WHERE run_id IS NULL")
    op.alter_column('news', 'run_id', existing_type=sa.String(), nullable=False)

    op.drop_index(op.f('ix_news_project_id'), table_name='news')
    op.drop_constraint('news_project_id_fkey', 'news', type_='foreignkey')
    op.drop_column('news', 'project_id')
    op.drop_column('news', 'created_at')
    op.drop_column('news', 'hidden')
    op.drop_column('news', 'tags')
    op.drop_column('news', 'entities')
    op.drop_column('news', 'doc_type')
    op.drop_column('news', 'importance')
    op.drop_column('news', 'category')

    op.drop_column('source_cursors', 'last_published_at')
    op.alter_column('source_cursors', 'source_key', new_column_name='channel')

    # RSS-материалы в старой схеме непредставимы: tg_msg_id там NOT NULL.
    op.execute("DELETE FROM messages WHERE tg_msg_id IS NULL")
    op.alter_column('messages', 'tg_msg_id', existing_type=sa.BigInteger(), nullable=False)
    op.alter_column('messages', 'source_key', new_column_name='channel')
