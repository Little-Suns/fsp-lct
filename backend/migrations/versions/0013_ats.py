"""интеграция с ATS: ключи API, внешние id, лента событий

Revision ID: 0013_ats
Revises: 0012_invite_task
Create Date: 2026-10-11 00:30:39.995890

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# идентификаторы ревизии: NNNN_slug, down_revision — ревизия, поверх которой эта
revision: str = '0013_ats'
down_revision: Union[str, Sequence[str], None] = '0012_invite_task'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применить изменение схемы."""
    # новые таблицы, данных переносить не нужно
    op.create_table('api_keys',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('name', sa.String(length=64), nullable=False),
    sa.Column('key_hash', sa.String(length=64), nullable=False),
    sa.Column('prefix', sa.String(length=12), nullable=False),
    sa.Column('scopes', sa.JSON(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('revoked_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('key_hash')
    )
    op.create_index(op.f('ix_api_keys_company_id'), 'api_keys', ['company_id'], unique=False)
    op.create_table('ats_links',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('entity', sa.String(length=16), nullable=False),
    sa.Column('external_id', sa.String(length=128), nullable=False),
    sa.Column('internal_id', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'entity', 'external_id')
    )
    op.create_table('outbox_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('txid', sa.BigInteger(), server_default=sa.text('pg_current_xact_id()::text::bigint'), nullable=False),
    sa.Column('type', sa.String(length=40), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_outbox_company_id', 'outbox_events', ['company_id', 'txid', 'id'], unique=False)


def downgrade() -> None:
    """Откатить изменение схемы."""
    op.drop_index('ix_outbox_company_id', table_name='outbox_events')
    op.drop_table('outbox_events')
    op.drop_table('ats_links')
    op.drop_index(op.f('ix_api_keys_company_id'), table_name='api_keys')
    op.drop_table('api_keys')
