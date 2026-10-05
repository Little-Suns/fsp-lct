"""Схема БД. Персональные данные (name/email/tg) живут только в Candidate и никогда не идут в ранжирование."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


def _now():
    return mapped_column(DateTime(timezone=True), server_default=func.now())


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    role: Mapped[str] = mapped_column(String(16))  # candidate | employer | admin
    token: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)
    otp: Mapped[str | None] = mapped_column(String(8))
    otp_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    otp_attempts: Mapped[int] = mapped_column(Integer, default=0)
    fsp_id: Mapped[str | None] = mapped_column(String(32), unique=True)
    created_at: Mapped[datetime] = _now()


class Candidate(Base):
    __tablename__ = "candidates"
    id: Mapped[int] = mapped_column(primary_key=True)
    public_id: Mapped[str] = mapped_column(String(16), unique=True)  # анонимный код вида «A-1042»
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), unique=True)
    # персональное — раскрывается только после принятия приглашения
    name: Mapped[str] = mapped_column(String(255))
    email: Mapped[str] = mapped_column(String(255))
    tg: Mapped[str | None] = mapped_column(String(64))
    consent_152: Mapped[bool] = mapped_column(Boolean, default=False)
    consent_external: Mapped[bool] = mapped_column(Boolean, default=False)  # отдельное согласие на CF/CTFtime
    # профиль (catalog.SPECS / TRACKS / GRADES / FORMATS)
    spec: Mapped[str] = mapped_column(String(32))
    track: Mapped[str | None] = mapped_column(String(32))
    grade_claimed: Mapped[str] = mapped_column(String(16))
    min_salary: Mapped[int] = mapped_column(Integer)
    formats: Mapped[list[str]] = mapped_column(JSON, default=list)
    city: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(8), default="open")  # open | off
    notif: Mapped[dict] = mapped_column(JSON, default=lambda: {"mail": True, "tg": True})
    hidden_from: Mapped[list[str]] = mapped_column(JSON, default=list)  # ИНН компаний, которым профиль не показывать
    cv_filename: Mapped[str | None] = mapped_column(String(255))
    cv_text: Mapped[str | None] = mapped_column(Text)
    years_exp: Mapped[float | None] = mapped_column(Float)
    skills_claimed: Mapped[list[str]] = mapped_column(JSON, default=list)  # из резюме / анкеты
    # результат теста: категория = spec × track × grade
    grade: Mapped[str | None] = mapped_column(String(16))
    theta: Mapped[float | None] = mapped_column(Float)
    se: Mapped[float | None] = mapped_column(Float)
    percentile: Mapped[int | None] = mapped_column(Integer)
    competencies: Mapped[list[dict]] = mapped_column(JSON, default=list)  # [{"n": str, "t": float, "se": float}]
    skills_confirmed: Mapped[list[str]] = mapped_column(JSON, default=list)
    tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_upgrade_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_passed: Mapped[bool] = mapped_column(Boolean, default=False)  # «разбор решения» для Senior+
    employer_confirmed: Mapped[int] = mapped_column(Integer, default=0)
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    truth: Mapped[dict | None] = mapped_column(JSON)  # скрытая «правда» синтетики для валидации; в API не отдаётся
    created_at: Mapped[datetime] = _now()

    achievements: Mapped[list["Achievement"]] = relationship(back_populates="candidate", cascade="all, delete-orphan")
    accounts: Mapped[list["ExternalAccount"]] = relationship(back_populates="candidate", cascade="all, delete-orphan")


class ExternalAccount(Base):
    """Привязка внешнего профиля. Владение подтверждается кодом в профиле (CF: поле «Организация»)."""

    __tablename__ = "external_accounts"
    # одну CTF-команду могут привязать несколько участников; «один handle — один владелец» для CF проверяется в коде
    __table_args__ = (
        UniqueConstraint("provider", "handle", "candidate_id"),
        # один подтверждённый владелец CF-handle — на уровне БД, без гонки между двумя verify
        Index("uq_cf_verified_owner", text("lower(handle)"), unique=True,
              postgresql_where=text("provider = 'codeforces' AND verified_at IS NOT NULL")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    provider: Mapped[str] = mapped_column(String(16))  # codeforces | ctftime | kaggle
    handle: Mapped[str] = mapped_column(String(64))  # для ctftime — id команды
    verify_code: Mapped[str] = mapped_column(String(16))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rating: Mapped[float | None] = mapped_column(Float)
    rank: Mapped[str | None] = mapped_column(String(64))
    data: Mapped[dict | None] = mapped_column(JSON)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    candidate: Mapped[Candidate] = relationship(back_populates="accounts")


class Event(Base):
    """Соревнование: этап ФСП, хакатон, CTF, контест Codeforces."""

    __tablename__ = "events"
    __table_args__ = (UniqueConstraint("source", "external_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(16))  # fsp | hackathon | ctftime | codeforces
    external_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    level: Mapped[str | None] = mapped_column(String(32))  # international | national | regional | local
    date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    participants: Mapped[int | None] = mapped_column(Integer)
    url: Mapped[str | None] = mapped_column(String(512))
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)  # навыки/направления: ["ML", "Python"]


class Achievement(Base):
    """Подтверждённое достижение. weight ∈ [0,1] — нормированный вклад в сигнал ранжирования."""

    __tablename__ = "achievements"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    event_id: Mapped[int | None] = mapped_column(ForeignKey("events.id"))
    source: Mapped[str] = mapped_column(String(16))  # fsp | hackathon | ctftime | codeforces
    title: Mapped[str] = mapped_column(String(255))  # «Финал Кубка России ФСП 2025, продуктовое направление»
    place: Mapped[int | None] = mapped_column(Integer)
    team: Mapped[str | None] = mapped_column(String(128))
    role: Mapped[str | None] = mapped_column(String(64))  # роль в команде: backend, ML, капитан…
    weight: Mapped[float] = mapped_column(Float, default=0.0)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    data: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = _now()

    candidate: Mapped[Candidate] = relationship(back_populates="achievements")
    event: Mapped[Event | None] = relationship()


class Company(Base):
    __tablename__ = "companies"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), unique=True)
    inn: Mapped[str] = mapped_column(String(12), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    about: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str] = mapped_column(String(9), default="#402FFF")
    site_domain: Mapped[str | None] = mapped_column(String(128))
    recruiter_name: Mapped[str] = mapped_column(String(255))
    recruiter_email: Mapped[str] = mapped_column(String(255))
    recruiter_tg: Mapped[str | None] = mapped_column(String(64))
    verified: Mapped[bool] = mapped_column(Boolean, default=False)  # ИНН + домен почты
    quota_max: Mapped[int] = mapped_column(Integer, default=10)  # в неделю; растёт с долей принятых
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _now()


class Need(Base):
    """Потребность работодателя: свободный текст + структура после разбора."""

    __tablename__ = "needs"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    text: Mapped[str] = mapped_column(Text)
    spec: Mapped[str] = mapped_column(String(32))
    track: Mapped[str | None] = mapped_column(String(32))
    grade: Mapped[str] = mapped_column(String(16))
    must: Mapped[list[str]] = mapped_column(JSON, default=list)
    nice: Mapped[list[str]] = mapped_column(JSON, default=list)
    salary_from: Mapped[int | None] = mapped_column(Integer)
    salary_to: Mapped[int | None] = mapped_column(Integer)
    format: Mapped[str | None] = mapped_column(String(16))
    city: Mapped[str | None] = mapped_column(String(64))
    parsed_by: Mapped[str] = mapped_column(String(8), default="rules")  # rules | llm
    kind: Mapped[str | None] = mapped_column(String(16))  # синтетика: normal | adjacent | fork_low — разрез метрик валидации
    embedding: Mapped[list[float] | None] = mapped_column(ARRAY(Float))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _now()

    company: Mapped[Company] = relationship()


class Invitation(Base):
    """Приглашение-оффер. Статусы: sent → seen → accepted | declined | expired."""

    __tablename__ = "invitations"
    __table_args__ = (UniqueConstraint("company_id", "candidate_id", "need_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    need_id: Mapped[int | None] = mapped_column(ForeignKey("needs.id", ondelete="SET NULL"))
    lottery_id: Mapped[int | None] = mapped_column(ForeignKey("lotteries.id", ondelete="SET NULL"))
    role: Mapped[str] = mapped_column(String(255))
    salary_from: Mapped[int] = mapped_column(Integer)
    salary_to: Mapped[int] = mapped_column(Integer)
    format: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(Text, default="")
    task: Mapped[str | None] = mapped_column(Text)  # задача вместо первого созвона, по желанию
    status: Mapped[str] = mapped_column(String(12), default="sent")
    decline_reason: Mapped[str | None] = mapped_column(String(16))  # catalog.DECLINE_REASONS
    decline_comment: Mapped[str | None] = mapped_column(Text)
    feedback: Mapped[str | None] = mapped_column(String(16))  # confirmed | not_confirmed | hired
    sent_at: Mapped[datetime] = _now()
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)

    company: Mapped[Company] = relationship()
    candidate: Mapped[Candidate] = relationship()
    need: Mapped[Need | None] = relationship()


class Lottery(Base):
    """Квалифицированная лотерея (Frey & Osterloh): порог → жребий среди прошедших.

    Commit–reveal: при создании пул замораживается и публикуется sha256(seed); при розыгрыше seed
    раскрывается, и любой может повторить жеребьёвку по pool_ids + seed.
    """

    __tablename__ = "lotteries"
    __table_args__ = (UniqueConstraint("company_id", "need_id"),)  # одна жеребьёвка на потребность — нельзя перебрасывать жребий
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    need_id: Mapped[int | None] = mapped_column(ForeignKey("needs.id", ondelete="SET NULL"))
    threshold: Mapped[dict] = mapped_column(JSON)  # условия порога, см. services/lottery.py
    pool_ids: Mapped[list[str]] = mapped_column(JSON)  # public_id прошедших порог, отсортированы
    draw_count: Mapped[int] = mapped_column(Integer)
    seed_hash: Mapped[str] = mapped_column(String(64))
    # sha256 канонического JSON {threshold, pool_ids, draw_count, seed_hash}: фиксирует пул и условия до розыгрыша
    commitment: Mapped[str] = mapped_column(String(64))
    seed: Mapped[str | None] = mapped_column(String(64))  # раскрывается при розыгрыше
    drawn_ids: Mapped[list[str] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = _now()
    drawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Item(Base):
    """Задание банка IRT (2PL). family — параметрический шаблон; клоны семейства имеют близкую b."""

    __tablename__ = "items"
    id: Mapped[int] = mapped_column(primary_key=True)
    family: Mapped[str] = mapped_column(String(64), index=True)
    spec: Mapped[str] = mapped_column(String(32))
    competency: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(16))  # choice | mark | review
    a: Mapped[float] = mapped_column(Float)  # дискриминация
    b: Mapped[float] = mapped_column(Float)  # сложность
    payload: Mapped[dict] = mapped_column(JSON)  # сцена, сюжет, панель, варианты; ключ ответа — payload["key"], наружу не отдаётся
    pilot: Mapped[bool] = mapped_column(Boolean, default=False)  # пилотные задания не влияют на грейд


class QuestSession(Base):
    __tablename__ = "quest_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    story: Mapped[bool] = mapped_column(Boolean, default=True)
    answers: Mapped[list[dict]] = mapped_column(JSON, default=list)  # [{"item_id", "response", "correct", "ms"}]
    theta: Mapped[float] = mapped_column(Float, default=0.0)
    se: Mapped[float] = mapped_column(Float, default=1.0)
    prior_mean: Mapped[float] = mapped_column(Float, default=0.0)  # стартовая оценка (например, из рейтинга CF)
    flags: Mapped[list[str]] = mapped_column(JSON, default=list)  # подозрения: inconsistent, too_fast…
    started_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
