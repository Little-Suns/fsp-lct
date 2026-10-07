"""экспресс-режим теста

Режим попытки (`quest_sessions.mode`: full | express) и пометка «грейд — предварительная экспресс-оценка»
(`candidates.grade_express`). Колонки NOT NULL с server_default: существующие попытки — полные, существующие
грейды — по полному тесту.

Revision ID: 0004_quest_express
Revises: 0003_merge_chat_profile
Create Date: 2026-10-07 02:28:17.942983

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# идентификаторы ревизии: NNNN_slug, down_revision — ревизия, поверх которой эта
revision: str = '0004_quest_express'
down_revision: Union[str, Sequence[str], None] = '0003_merge_chat_profile'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применить изменение схемы."""
    op.add_column('candidates', sa.Column('grade_express', sa.Boolean(), server_default=sa.text('false'), nullable=False))
    op.add_column('quest_sessions', sa.Column('mode', sa.String(length=8), server_default='full', nullable=False))


def downgrade() -> None:
    """Откатить изменение схемы."""
    op.drop_column('quest_sessions', 'mode')
    op.drop_column('candidates', 'grade_express')
