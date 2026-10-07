"""слияние: достижения ФСП (разряды, результат) и входы через ФСП ID

Revision ID: 0005_merge_fsp_ach_logins
Revises: 0004_fsp_achievements, 0004_fsp_logins
Create Date: 2026-10-07 10:00:04.084171

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# идентификаторы ревизии: NNNN_slug, down_revision — ревизия, поверх которой эта
revision: str = '0005_merge_fsp_ach_logins'
down_revision: Union[str, Sequence[str], None] = ('0004_fsp_achievements', '0004_fsp_logins')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применить изменение схемы."""
    pass


def downgrade() -> None:
    """Откатить изменение схемы."""
    pass
