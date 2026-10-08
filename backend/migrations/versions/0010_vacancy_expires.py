"""срок публикации вакансии

Revision ID: 0010_vacancy_expires
Revises: 0009_merge_feedback_fsp
Create Date: 2026-10-09 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# идентификаторы ревизии: NNNN_slug, down_revision — ревизия, поверх которой эта
revision: str = '0010_vacancy_expires'
down_revision: Union[str, Sequence[str], None] = '0009_merge_feedback_fsp'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применить изменение схемы."""
    op.add_column('vacancies', sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True))
    # существующим вакансиям — полный срок от момента обновления (catalog.VACANCY_TTL_DAYS = 30): обновление стенда
    # не должно разом скрыть все старые вакансии; дальше компания продлевает их сама
    op.execute("UPDATE vacancies SET expires_at = now() + interval '30 days'")
    op.alter_column('vacancies', 'expires_at', nullable=False)


def downgrade() -> None:
    """Откатить изменение схемы."""
    op.drop_column('vacancies', 'expires_at')
