"""слияние: экспресс-режим теста и ветка main (ФСП ID, достижения, автопроверка)

Revision ID: 0007_merge_quest_express
Revises: 0004_quest_express, 0006_merge_task_autocheck
Create Date: 2026-10-07 10:31:27.925178

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# идентификаторы ревизии: NNNN_slug, down_revision — ревизия, поверх которой эта
revision: str = '0007_merge_quest_express'
down_revision: Union[str, Sequence[str], None] = ('0004_quest_express', '0006_merge_task_autocheck')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применить изменение схемы."""
    pass


def downgrade() -> None:
    """Откатить изменение схемы."""
    pass
