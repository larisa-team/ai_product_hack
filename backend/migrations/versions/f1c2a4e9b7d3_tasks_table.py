"""tasks table (queue moves from Redis to Postgres)

Revision ID: f1c2a4e9b7d3
Revises: 3d9eab625881
Create Date: 2026-09-05 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'f1c2a4e9b7d3'
down_revision: Union[str, Sequence[str], None] = '3d9eab625881'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'tasks',
        sa.Column('id', sa.String(), nullable=False),
        sa.Column('run_id', sa.String(), nullable=False),
        sa.Column('kind', sa.String(length=20), nullable=False),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['run_id'], ['runs.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_tasks_run_id'), 'tasks', ['run_id'], unique=False)
    op.create_index(op.f('ix_tasks_created_at'), 'tasks', ['created_at'], unique=False)
    op.create_index(
        'uq_tasks_compose_per_run',
        'tasks',
        ['run_id'],
        unique=True,
        postgresql_where=sa.text("kind = 'compose'"),
    )


def downgrade() -> None:
    op.drop_index('uq_tasks_compose_per_run', table_name='tasks', postgresql_where=sa.text("kind = 'compose'"))
    op.drop_index(op.f('ix_tasks_created_at'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_run_id'), table_name='tasks')
    op.drop_table('tasks')
