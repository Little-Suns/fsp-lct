"""задания: тип ответа, эталон, автопроверка

Тип ответа задания (open — оценивает работодатель; text / number / choice / multi / regex — система по эталону),
публичные варианты для выбора, эталон (только серверу и компании-автору) и результат автопроверки решения.
answer_type — NOT NULL с server_default 'open': существующие задания остаются открытыми, ALTER проходит на
заполненной базе. Остальные колонки nullable — старые решения без автопроверки.

Revision ID: 0004_task_autocheck
Revises: 0003_merge_chat_profile
Create Date: 2026-10-07 02:20:29.249376

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# идентификаторы ревизии: NNNN_slug, down_revision — ревизия, поверх которой эта
revision: str = '0004_task_autocheck'
down_revision: Union[str, Sequence[str], None] = '0003_merge_chat_profile'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применить изменение схемы."""
    op.add_column('task_submissions', sa.Column('auto_ok', sa.Boolean(), nullable=True))
    op.add_column('tasks', sa.Column('answer_type', sa.String(length=8), server_default='open', nullable=False))
    op.add_column('tasks', sa.Column('options', sa.JSON(), nullable=True))
    op.add_column('tasks', sa.Column('reference', sa.JSON(), nullable=True))


def downgrade() -> None:
    """Откатить изменение схемы."""
    op.drop_column('tasks', 'reference')
    op.drop_column('tasks', 'options')
    op.drop_column('tasks', 'answer_type')
    op.drop_column('task_submissions', 'auto_ok')
