"""потолок грейда после смены категории

Грейд до смены специализации/трека (`candidates.grade_cap`): в интервал смены грейда первое присвоение
в новой категории — не выше него (routers/quest.finish). Существующие профили — без потолка.

Revision ID: 0012_grade_cap
Revises: 0011_quest_category
Create Date: 2026-10-09 21:30:40.553636

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# идентификаторы ревизии: NNNN_slug, down_revision — ревизия, поверх которой эта
revision: str = '0012_grade_cap'
down_revision: Union[str, Sequence[str], None] = '0011_quest_category'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применить изменение схемы."""
    op.add_column('candidates', sa.Column('grade_cap', sa.String(length=16), nullable=True))


def downgrade() -> None:
    """Откатить изменение схемы."""
    op.drop_column('candidates', 'grade_cap')
