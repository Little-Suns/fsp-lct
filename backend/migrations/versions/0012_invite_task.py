"""приглашение: ссылка на приложенное задание

Revision ID: 0012_invite_task
Revises: 0011_invite_repeat
Create Date: 2026-10-09 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# идентификаторы ревизии: NNNN_slug, down_revision — ревизия, поверх которой эта
revision: str = '0012_invite_task'
down_revision: Union[str, Sequence[str], None] = '0011_invite_repeat'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применить изменение схемы."""
    # было: в приглашении только текст задачи — кандидат искал задание сам в «Задачах»; старые приглашения остаются с NULL
    op.add_column('invitations', sa.Column('task_id', sa.Integer(), nullable=True))
    op.create_foreign_key('invitations_task_id_fkey', 'invitations', 'tasks', ['task_id'], ['id'], ondelete='SET NULL')


def downgrade() -> None:
    """Откатить изменение схемы."""
    op.drop_constraint('invitations_task_id_fkey', 'invitations', type_='foreignkey')
    op.drop_column('invitations', 'task_id')
