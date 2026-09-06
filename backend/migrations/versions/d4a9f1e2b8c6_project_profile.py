"""projects.profile — профиль бизнеса-заказчика для оценки важности

Важность события LLM оценивает относительно конкретного бизнеса (кейс PR/GR: влияние
на компанию, а не абстрактная значимость). Профиль уходит в промпт саммаризации.
На размеченном датасете это подняло accuracy importance ~0.63 -> ~0.78.

Revision ID: d4a9f1e2b8c6
Revises: c3f8b1a25e07
Create Date: 2026-09-05 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'd4a9f1e2b8c6'
down_revision: Union[str, Sequence[str], None] = 'c3f8b1a25e07'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # server_default обязателен: таблица не пуста, колонка NOT NULL.
    op.add_column(
        'projects',
        sa.Column('profile', sa.String(), nullable=False, server_default=''),
    )


def downgrade() -> None:
    op.drop_column('projects', 'profile')
