"""роль входа через ФСП ID, users.email_confirmed (почта подтверждена нашим кодом)

Revision ID: 0008_fsp_role_email_conf
Revises: 0007_merge_quest_express
Create Date: 2026-10-07 22:42:19.680706

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# идентификаторы ревизии: NNNN_slug, down_revision — ревизия, поверх которой эта
revision: str = '0008_fsp_role_email_conf'
down_revision: Union[str, Sequence[str], None] = '0007_merge_quest_express'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применить изменение схемы."""
    op.add_column('fsp_logins', sa.Column('role', sa.String(length=16), server_default='candidate', nullable=False))
    op.add_column('users', sa.Column('email_confirmed', sa.Boolean(), server_default=sa.false(), nullable=False))
    # все, кто пришёл не через ФСП ID, подтвердили почту кодом (или это сид)
    op.execute('UPDATE users SET email_confirmed = true WHERE fsp_id IS NULL')


def downgrade() -> None:
    """Откатить изменение схемы."""
    op.drop_column('users', 'email_confirmed')
    op.drop_column('fsp_logins', 'role')
