"""вход через ФСП ID: незавершённые OIDC-входы, users.fsp_id до 64 символов (sub Keycloak — UUID)

Revision ID: 0004_fsp_logins
Revises: 0003_merge_chat_profile
Create Date: 2026-10-07 02:21:23.026257

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# идентификаторы ревизии: NNNN_slug, down_revision — ревизия, поверх которой эта
revision: str = '0004_fsp_logins'
down_revision: Union[str, Sequence[str], None] = '0003_merge_chat_profile'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применить изменение схемы."""
    op.alter_column('users', 'fsp_id', existing_type=sa.String(length=32), type_=sa.String(length=64), existing_nullable=True)
    op.create_table('fsp_logins',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('state_hash', sa.String(length=64), nullable=True),
    sa.Column('browser_hash', sa.String(length=64), nullable=False),
    sa.Column('mode', sa.String(length=8), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('ticket_hash', sa.String(length=64), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('state_hash'),
    sa.UniqueConstraint('ticket_hash')
    )


def downgrade() -> None:
    """Откатить изменение схемы."""
    op.drop_table('fsp_logins')
    op.alter_column('users', 'fsp_id', existing_type=sa.String(length=64), type_=sa.String(length=32), existing_nullable=True)
