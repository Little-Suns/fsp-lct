"""чат: таблица messages

Внутренний чат кандидата и компании (app.models.Message). Сгенерирована autogenerate поверх 0001_baseline и сверена
с моделью вручную: FK на companies/candidates с ON DELETE CASCADE (переписка удаляется вместе с аккаунтом),
created_at со server_default now(), индексы idx_chat_history (история диалога) и idx_chat_candidate (диалоги кандидата).

Revision ID: 0002_chat_messages
Revises: 0001_baseline
Create Date: 2026-10-07 00:05:24.455992

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# идентификаторы ревизии: NNNN_slug, down_revision — ревизия, поверх которой эта
revision: str = '0002_chat_messages'
down_revision: Union[str, Sequence[str], None] = '0001_baseline'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применить изменение схемы."""
    # база от create_all ветки чата до Alembic: messages уже создана той же моделью, а stamp поставил только baseline
    if "messages" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table('messages',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('candidate_id', sa.Integer(), nullable=False),
    sa.Column('sender', sa.String(length=16), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('idx_chat_candidate', 'messages', ['candidate_id', 'id'], unique=False)
    op.create_index('idx_chat_history', 'messages', ['company_id', 'candidate_id', 'id'], unique=False)


def downgrade() -> None:
    """Откатить изменение схемы."""
    op.drop_index('idx_chat_history', table_name='messages')
    op.drop_index('idx_chat_candidate', table_name='messages')
    op.drop_table('messages')
