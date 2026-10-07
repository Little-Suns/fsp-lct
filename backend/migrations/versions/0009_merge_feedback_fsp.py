"""слияние: отзывы о компании и роль входа через ФСП ID

Revision ID: 0009_merge_feedback_fsp
Revises: 0008_company_feedback, 0008_fsp_role_email_conf
Create Date: 2026-10-07 23:55:47.135119

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# идентификаторы ревизии: NNNN_slug, down_revision — ревизия, поверх которой эта
revision: str = '0009_merge_feedback_fsp'
down_revision: Union[str, Sequence[str], None] = ('0008_company_feedback', '0008_fsp_role_email_conf')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применить изменение схемы."""
    pass


def downgrade() -> None:
    """Откатить изменение схемы."""
    pass
