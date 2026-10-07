"""отзыв кандидата о компании и блок компании

Revision ID: 0008_company_feedback
Revises: 0007_merge_quest_express
Create Date: 2026-10-07 22:30:42.484329

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# идентификаторы ревизии: NNNN_slug, down_revision — ревизия, поверх которой эта
revision: str = '0008_company_feedback'
down_revision: Union[str, Sequence[str], None] = '0007_merge_quest_express'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применить изменение схемы."""
    op.add_column('companies', sa.Column('blocked_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('companies', sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('invitations', sa.Column('company_feedback', sa.String(length=16), nullable=True))
    op.add_column('invitations', sa.Column('company_feedback_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Откатить изменение схемы."""
    op.drop_column('invitations', 'company_feedback_at')
    op.drop_column('invitations', 'company_feedback')
    op.drop_column('companies', 'reviewed_at')
    op.drop_column('companies', 'blocked_at')
