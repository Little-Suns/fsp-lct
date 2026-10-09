"""Снимок категории тестовой попытки: история не переносится в другую специализацию."""

from alembic import op
import sqlalchemy as sa

revision = "0011_quest_category"
down_revision = "0010_vacancy_expires"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("quest_sessions", sa.Column("spec", sa.String(64), nullable=True))
    op.add_column("quest_sessions", sa.Column("track", sa.String(64), nullable=True))
    # У старых попыток категория не записана: текущий профиль мог измениться, поэтому оставляем неизвестной.


def downgrade() -> None:
    op.drop_column("quest_sessions", "track")
    op.drop_column("quest_sessions", "spec")
