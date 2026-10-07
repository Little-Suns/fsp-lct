"""слияние: автопроверка заданий по эталону и достижения/ФСП ID

Revision ID: 0006_merge_task_autocheck
Revises: 0004_task_autocheck, 0005_merge_fsp_ach_logins
Create Date: 2026-10-07 10:08:43.084852

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# идентификаторы ревизии: NNNN_slug, down_revision — ревизия, поверх которой эта
revision: str = '0006_merge_task_autocheck'
down_revision: Union[str, Sequence[str], None] = ('0004_task_autocheck', '0005_merge_fsp_ach_logins')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применить изменение схемы."""
    pass


def downgrade() -> None:
    """Откатить изменение схемы."""
    pass
