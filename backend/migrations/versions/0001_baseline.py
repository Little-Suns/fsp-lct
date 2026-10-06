"""baseline: полная схема main на момент перехода с create_all на Alembic.

Сгенерирована autogenerate по пустой базе и сверена вручную: pg_dump --schema-only совпадает с create_all
(имена ограничений — дефолтные Postgres, частичные уникальные индексы, server_default now(), ondelete у FK).
Базы, созданные create_all до Alembic, при старте помечаются этой ревизией (stamp) — см. app.db.migrate.

Revision ID: 0001_baseline
Revises: 
Create Date: 2026-10-06 23:42:44.575317

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# идентификаторы ревизии: NNNN_slug, down_revision — ревизия, поверх которой эта
revision: str = '0001_baseline'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Применить изменение схемы."""
    op.create_table('audit_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('actor_user_id', sa.Integer(), nullable=True),
    sa.Column('action', sa.String(length=32), nullable=False),
    sa.Column('subject_candidate_id', sa.Integer(), nullable=True),
    sa.Column('detail', sa.JSON(), nullable=True),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('consent_events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('candidate_id', sa.Integer(), nullable=True),
    sa.Column('purpose', sa.String(length=16), nullable=False),
    sa.Column('granted', sa.Boolean(), nullable=False),
    sa.Column('version', sa.String(length=16), nullable=False),
    sa.Column('at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_consent_events_candidate_id'), 'consent_events', ['candidate_id'], unique=False)
    op.create_table('events',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('external_id', sa.String(length=64), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('level', sa.String(length=32), nullable=True),
    sa.Column('date', sa.DateTime(timezone=True), nullable=True),
    sa.Column('participants', sa.Integer(), nullable=True),
    sa.Column('url', sa.String(length=512), nullable=True),
    sa.Column('tags', sa.JSON(), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('source', 'external_id')
    )
    op.create_table('items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('family', sa.String(length=64), nullable=False),
    sa.Column('spec', sa.String(length=32), nullable=False),
    sa.Column('competency', sa.String(length=64), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=False),
    sa.Column('a', sa.Float(), nullable=False),
    sa.Column('b', sa.Float(), nullable=False),
    sa.Column('payload', sa.JSON(), nullable=False),
    sa.Column('pilot', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_items_family'), 'items', ['family'], unique=False)
    op.create_table('login_challenges',
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('code_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('email')
    )
    op.create_table('retired_public_ids',
    sa.Column('public_id', sa.String(length=16), nullable=False),
    sa.PrimaryKeyConstraint('public_id')
    )
    op.create_table('users',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('role', sa.String(length=16), nullable=False),
    sa.Column('token', sa.String(length=64), nullable=True),
    sa.Column('token_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('fsp_id', sa.String(length=32), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email'),
    sa.UniqueConstraint('fsp_id')
    )
    op.create_index(op.f('ix_users_token'), 'users', ['token'], unique=True)
    op.create_table('candidates',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('public_id', sa.String(length=16), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('email', sa.String(length=255), nullable=False),
    sa.Column('tg', sa.String(length=64), nullable=True),
    sa.Column('consent_152', sa.Boolean(), nullable=False),
    sa.Column('consent_152_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('consent_version', sa.String(length=16), nullable=True),
    sa.Column('consent_publish_version', sa.String(length=16), nullable=True),
    sa.Column('consent_external_version', sa.String(length=16), nullable=True),
    sa.Column('consent_publish', sa.Boolean(), nullable=False),
    sa.Column('consent_external', sa.Boolean(), nullable=False),
    sa.Column('spec', sa.String(length=32), nullable=False),
    sa.Column('track', sa.String(length=32), nullable=True),
    sa.Column('grade_claimed', sa.String(length=16), nullable=False),
    sa.Column('min_salary', sa.Integer(), nullable=False),
    sa.Column('formats', sa.JSON(), nullable=False),
    sa.Column('city', sa.String(length=64), nullable=False),
    sa.Column('status', sa.String(length=8), nullable=False),
    sa.Column('notif', sa.JSON(), nullable=False),
    sa.Column('hidden_from', sa.JSON(), nullable=False),
    sa.Column('cv_filename', sa.String(length=255), nullable=True),
    sa.Column('cv_text', sa.Text(), nullable=True),
    sa.Column('years_exp', sa.Float(), nullable=True),
    sa.Column('skills_claimed', sa.JSON(), nullable=False),
    sa.Column('grade', sa.String(length=16), nullable=True),
    sa.Column('theta', sa.Float(), nullable=True),
    sa.Column('se', sa.Float(), nullable=True),
    sa.Column('percentile', sa.Integer(), nullable=True),
    sa.Column('competencies', sa.JSON(), nullable=False),
    sa.Column('skills_confirmed', sa.JSON(), nullable=False),
    sa.Column('tested_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('next_upgrade_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('review_passed', sa.Boolean(), nullable=False),
    sa.Column('employer_confirmed', sa.Integer(), nullable=False),
    sa.Column('embedding', postgresql.ARRAY(sa.Float()), nullable=True),
    sa.Column('is_synthetic', sa.Boolean(), nullable=False),
    sa.Column('truth', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('public_id'),
    sa.UniqueConstraint('user_id')
    )
    op.create_table('companies',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('user_id', sa.Integer(), nullable=True),
    sa.Column('inn', sa.String(length=12), nullable=False),
    sa.Column('name', sa.String(length=255), nullable=False),
    sa.Column('about', sa.Text(), nullable=True),
    sa.Column('color', sa.String(length=9), nullable=False),
    sa.Column('site_domain', sa.String(length=128), nullable=True),
    sa.Column('recruiter_name', sa.String(length=255), nullable=False),
    sa.Column('recruiter_email', sa.String(length=255), nullable=False),
    sa.Column('recruiter_tg', sa.String(length=64), nullable=True),
    sa.Column('verified', sa.Boolean(), nullable=False),
    sa.Column('quota_max', sa.Integer(), nullable=False),
    sa.Column('is_synthetic', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('inn'),
    sa.UniqueConstraint('user_id')
    )
    op.create_table('achievements',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('candidate_id', sa.Integer(), nullable=False),
    sa.Column('event_id', sa.Integer(), nullable=True),
    sa.Column('source', sa.String(length=16), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('place', sa.Integer(), nullable=True),
    sa.Column('team', sa.String(length=128), nullable=True),
    sa.Column('role', sa.String(length=64), nullable=True),
    sa.Column('weight', sa.Float(), nullable=False),
    sa.Column('verified', sa.Boolean(), nullable=False),
    sa.Column('data', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['event_id'], ['events.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('external_accounts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('candidate_id', sa.Integer(), nullable=False),
    sa.Column('provider', sa.String(length=16), nullable=False),
    sa.Column('handle', sa.String(length=64), nullable=False),
    sa.Column('verify_code', sa.String(length=64), nullable=False),
    sa.Column('verify_expires_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('verify_attempts', sa.Integer(), nullable=False),
    sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('rating', sa.Float(), nullable=True),
    sa.Column('rank', sa.String(length=64), nullable=True),
    sa.Column('data', sa.JSON(), nullable=True),
    sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('provider', 'handle', 'candidate_id')
    )
    op.create_index('uq_cf_verified_owner', 'external_accounts', [sa.literal_column('lower(handle)')], unique=True, postgresql_where=sa.text("provider = 'codeforces' AND verified_at IS NOT NULL"))
    op.create_table('needs',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('spec', sa.String(length=32), nullable=False),
    sa.Column('track', sa.String(length=32), nullable=True),
    sa.Column('grade', sa.String(length=16), nullable=False),
    sa.Column('must', sa.JSON(), nullable=False),
    sa.Column('nice', sa.JSON(), nullable=False),
    sa.Column('salary_from', sa.Integer(), nullable=True),
    sa.Column('salary_to', sa.Integer(), nullable=True),
    sa.Column('format', sa.String(length=16), nullable=True),
    sa.Column('city', sa.String(length=64), nullable=True),
    sa.Column('parsed_by', sa.String(length=8), nullable=False),
    sa.Column('kind', sa.String(length=16), nullable=True),
    sa.Column('embedding', postgresql.ARRAY(sa.Float()), nullable=True),
    sa.Column('is_synthetic', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('quest_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('candidate_id', sa.Integer(), nullable=False),
    sa.Column('story', sa.Boolean(), nullable=False),
    sa.Column('answers', sa.JSON(), nullable=False),
    sa.Column('theta', sa.Float(), nullable=False),
    sa.Column('se', sa.Float(), nullable=False),
    sa.Column('prior_mean', sa.Float(), nullable=False),
    sa.Column('target_grade', sa.String(length=16), nullable=True),
    sa.Column('focus', sa.JSON(), nullable=True),
    sa.Column('grade', sa.String(length=16), nullable=True),
    sa.Column('applied', sa.Boolean(), nullable=True),
    sa.Column('flags', sa.JSON(), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('uq_quest_active', 'quest_sessions', ['candidate_id'], unique=True, postgresql_where=sa.text('finished_at IS NULL'))
    op.create_table('vacancies',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('spec', sa.String(length=32), nullable=False),
    sa.Column('track', sa.String(length=32), nullable=True),
    sa.Column('grade', sa.String(length=16), nullable=False),
    sa.Column('must', sa.JSON(), nullable=False),
    sa.Column('nice', sa.JSON(), nullable=False),
    sa.Column('salary_from', sa.Integer(), nullable=False),
    sa.Column('salary_to', sa.Integer(), nullable=False),
    sa.Column('format', sa.String(length=16), nullable=False),
    sa.Column('city', sa.String(length=64), nullable=True),
    sa.Column('status', sa.String(length=8), nullable=False),
    sa.Column('is_synthetic', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('applications',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('vacancy_id', sa.Integer(), nullable=False),
    sa.Column('candidate_id', sa.Integer(), nullable=False),
    sa.Column('note', sa.String(length=300), nullable=True),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('decline_reason', sa.String(length=16), nullable=True),
    sa.Column('contacts_revealed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('is_synthetic', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['vacancy_id'], ['vacancies.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('vacancy_id', 'candidate_id')
    )
    op.create_table('lotteries',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('need_id', sa.Integer(), nullable=True),
    sa.Column('threshold', sa.JSON(), nullable=False),
    sa.Column('pool_ids', sa.JSON(), nullable=False),
    sa.Column('draw_count', sa.Integer(), nullable=False),
    sa.Column('seed_hash', sa.String(length=64), nullable=False),
    sa.Column('commitment', sa.String(length=64), nullable=False),
    sa.Column('salt', sa.String(length=64), nullable=True),
    sa.Column('seed', sa.String(length=64), nullable=True),
    sa.Column('drawn_ids', sa.JSON(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('drawn_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['need_id'], ['needs.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'need_id')
    )
    op.create_table('tasks',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('need_id', sa.Integer(), nullable=True),
    sa.Column('title', sa.String(length=255), nullable=False),
    sa.Column('text', sa.Text(), nullable=False),
    sa.Column('spec', sa.String(length=32), nullable=False),
    sa.Column('competency', sa.String(length=64), nullable=True),
    sa.Column('kind', sa.String(length=8), nullable=False),
    sa.Column('minutes', sa.Integer(), nullable=False),
    sa.Column('public', sa.Boolean(), nullable=False),
    sa.Column('is_synthetic', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['need_id'], ['needs.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('invitations',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('company_id', sa.Integer(), nullable=False),
    sa.Column('candidate_id', sa.Integer(), nullable=False),
    sa.Column('need_id', sa.Integer(), nullable=True),
    sa.Column('lottery_id', sa.Integer(), nullable=True),
    sa.Column('role', sa.String(length=255), nullable=False),
    sa.Column('salary_from', sa.Integer(), nullable=False),
    sa.Column('salary_to', sa.Integer(), nullable=False),
    sa.Column('format', sa.String(length=64), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('task', sa.Text(), nullable=True),
    sa.Column('status', sa.String(length=12), nullable=False),
    sa.Column('decline_reason', sa.String(length=16), nullable=True),
    sa.Column('decline_comment', sa.Text(), nullable=True),
    sa.Column('feedback', sa.String(length=16), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('seen_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('responded_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('is_synthetic', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['lottery_id'], ['lotteries.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['need_id'], ['needs.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('company_id', 'candidate_id', 'need_id')
    )
    op.create_table('task_submissions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('task_id', sa.Integer(), nullable=False),
    sa.Column('candidate_id', sa.Integer(), nullable=False),
    sa.Column('invitation_id', sa.Integer(), nullable=True),
    sa.Column('answer', sa.Text(), nullable=False),
    sa.Column('review', sa.String(length=8), nullable=True),
    sa.Column('review_comment', sa.Text(), nullable=True),
    sa.Column('is_synthetic', sa.Boolean(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['candidate_id'], ['candidates.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['invitation_id'], ['invitations.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('task_id', 'candidate_id')
    )


def downgrade() -> None:
    """Откатить изменение схемы."""
    op.drop_table('task_submissions')
    op.drop_table('invitations')
    op.drop_table('tasks')
    op.drop_table('lotteries')
    op.drop_table('applications')
    op.drop_table('vacancies')
    op.drop_index('uq_quest_active', table_name='quest_sessions', postgresql_where=sa.text('finished_at IS NULL'))
    op.drop_table('quest_sessions')
    op.drop_table('needs')
    op.drop_index('uq_cf_verified_owner', table_name='external_accounts', postgresql_where=sa.text("provider = 'codeforces' AND verified_at IS NOT NULL"))
    op.drop_table('external_accounts')
    op.drop_table('achievements')
    op.drop_table('companies')
    op.drop_table('candidates')
    op.drop_index(op.f('ix_users_token'), table_name='users')
    op.drop_table('users')
    op.drop_table('retired_public_ids')
    op.drop_table('login_challenges')
    op.drop_index(op.f('ix_items_family'), table_name='items')
    op.drop_table('items')
    op.drop_table('events')
    op.drop_index(op.f('ix_consent_events_candidate_id'), table_name='consent_events')
    op.drop_table('consent_events')
    op.drop_table('audit_log')
