"""projects.collection_days — период первичного сбора на уровне проекта

Раньше глубина сбора была глобальным ENV (TG_FETCH_DAYS/RSS_FETCH_DAYS). Чек-лист
организаторов требует выбор периода в визарде создания проекта.

Revision ID: c3f8b1a25e07
Revises: a7e4b2c9d150
Create Date: 2026-09-05 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c3f8b1a25e07'
down_revision: Union[str, Sequence[str], None] = 'a7e4b2c9d150'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default обязателен: таблица не пуста, колонка NOT NULL.
    op.add_column(
        'projects',
        sa.Column('collection_days', sa.Integer(), nullable=False, server_default='7'),
    )


def downgrade() -> None:
    op.drop_column('projects', 'collection_days')
