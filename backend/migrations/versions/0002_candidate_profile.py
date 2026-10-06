"""кандидат: роли, софт-скиллы, опыт в PDF

Роли и софт-скиллы из резюме (справочные, в подборе не участвуют) и флаг «места работы в PDF-профиле».
Колонки NOT NULL добавляются с server_default — ALTER проходит на базе с существующими кандидатами: им
достаются пустые списки и включённый раздел «Опыт» (как у новых). У JSON-колонок умолчание затем снимается:
как и у остальных JSON-колонок, его задаёт ORM (default=list), а у json в Postgres нет оператора «=», и
autogenerate-сверка server_default на нём падает.

Revision ID: 0002_candidate_profile
Revises: 0001_baseline
Create Date: 2026-10-07 00:09:06.107413

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# идентификаторы ревизии: NNNN_slug, down_revision — ревизия, поверх которой эта
revision: str = '0002_candidate_profile'
down_revision: Union[str, Sequence[str], None] = '0001_baseline'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применить изменение схемы."""
    op.add_column('candidates', sa.Column('roles', sa.JSON(), server_default=sa.text("'[]'"), nullable=False))
    op.add_column('candidates', sa.Column('soft_skills', sa.JSON(), server_default=sa.text("'[]'"), nullable=False))
    op.add_column('candidates', sa.Column('pdf_experience', sa.Boolean(), server_default=sa.text('true'), nullable=False))
    op.alter_column('candidates', 'roles', server_default=None)
    op.alter_column('candidates', 'soft_skills', server_default=None)


def downgrade() -> None:
    """Откатить изменение схемы."""
    op.drop_column('candidates', 'pdf_experience')
    op.drop_column('candidates', 'soft_skills')
    op.drop_column('candidates', 'roles')
