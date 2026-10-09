"""повторное приглашение: уникальность только среди открытых

Revision ID: 0011_invite_repeat
Revises: 0010_vacancy_expires
Create Date: 2026-10-09 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# идентификаторы ревизии: NNNN_slug, down_revision — ревизия, поверх которой эта
revision: str = '0011_invite_repeat'
down_revision: Union[str, Sequence[str], None] = '0010_vacancy_expires'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применить изменение схемы."""
    # было: одно приглашение на (компания, кандидат, потребность) навсегда — после истечения пригласить заново нельзя
    op.drop_constraint('invitations_company_id_candidate_id_need_id_key', 'invitations', type_='unique')
    # уникальный индекс был и единственным индексом по company_id: запросы воронки, квоты и повтора — по обычному
    op.create_index('ix_invitations_company_candidate', 'invitations', ['company_id', 'candidate_id'])
    op.create_index('uq_invite_open', 'invitations', ['company_id', 'candidate_id', 'need_id'], unique=True,
                    postgresql_where=sa.text("status IN ('sent', 'seen')"))


def downgrade() -> None:
    """Откатить изменение схемы (упадёт, если уже есть повторные приглашения по той же потребности)."""
    op.drop_index('ix_invitations_company_candidate', table_name='invitations')
    op.drop_index('uq_invite_open', table_name='invitations', postgresql_where=sa.text("status IN ('sent', 'seen')"))
    op.create_unique_constraint('invitations_company_id_candidate_id_need_id_key', 'invitations', ['company_id', 'candidate_id', 'need_id'])
