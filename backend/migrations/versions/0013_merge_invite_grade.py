"""merge: повтор приглашения (0011_invite_repeat) и потолок грейда (0012_grade_cap)

Revision ID: 0013_merge_invite_grade
Revises: 0011_invite_repeat, 0012_grade_cap
Create Date: 2026-10-09 22:14:10.262949

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# идентификаторы ревизии: NNNN_slug, down_revision — ревизия, поверх которой эта
revision: str = '0013_merge_invite_grade'
down_revision: Union[str, Sequence[str], None] = ('0011_invite_repeat', '0012_grade_cap')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применить изменение схемы."""
    pass


def downgrade() -> None:
    """Откатить изменение схемы."""
    pass
