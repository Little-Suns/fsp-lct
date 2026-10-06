"""слияние: чат и профиль кандидата

Revision ID: 0003_merge_chat_profile
Revises: 0002_candidate_profile, 0002_chat_messages
Create Date: 2026-10-07 00:22:24.600545

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# идентификаторы ревизии: NNNN_slug, down_revision — ревизия, поверх которой эта
revision: str = '0003_merge_chat_profile'
down_revision: Union[str, Sequence[str], None] = ('0002_candidate_profile', '0002_chat_messages')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применить изменение схемы."""
    pass


def downgrade() -> None:
    """Откатить изменение схемы."""
    pass
