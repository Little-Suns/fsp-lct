"""Схема БД. Персональные данные (name/email/tg) живут только в Candidate и никогда не идут в ранжирование."""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, false, func, text, true
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
    token: Mapped[str | None] = mapped_column(String(64), unique=True, index=True)  # sha256 токена, сам токен не храним
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fsp_id: Mapped[str | None] = mapped_column(String(64), unique=True)  # sub из ФСП ID (в Keycloak — UUID, 36 символов)
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
    # 152-ФЗ: согласия раздельные, с датой и версией текста; отзыв согласия на обработку → профиль скрыт, данные удаляются
    consent_152: Mapped[bool] = mapped_column(Boolean, default=False)  # обработка ПДн
    consent_152_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consent_version: Mapped[str | None] = mapped_column(String(16))  # версия текста согласия на обработку
    # у каждой цели своя версия: повторное согласие на обработку не «оживляет» старые publish/external
    consent_publish_version: Mapped[str | None] = mapped_column(String(16))
    consent_external_version: Mapped[str | None] = mapped_column(String(16))
    consent_publish: Mapped[bool] = mapped_column(Boolean, default=False)  # показывать обезличенную карточку работодателям
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
    # заявлены (резюме / анкета), значения catalog.ROLES и SOFT_SKILLS; в подборе и грейде не участвуют
    roles: Mapped[list[str]] = mapped_column(JSON, default=list)
    soft_skills: Mapped[list[str]] = mapped_column(JSON, default=list)
    # места работы, распознанные из cv_text, в разделе «Опыт» PDF-профиля; кандидат видит их в профиле и может исключить
    pdf_experience: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # результат теста: категория = spec × track × grade
    grade: Mapped[str | None] = mapped_column(String(16))
    theta: Mapped[float | None] = mapped_column(Float)
    se: Mapped[float | None] = mapped_column(Float)
    percentile: Mapped[int | None] = mapped_column(Integer)
    competencies: Mapped[list[dict]] = mapped_column(JSON, default=list)  # [{"n": str, "t": float, "se": float}]
    skills_confirmed: Mapped[list[str]] = mapped_column(JSON, default=list)
    tested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    next_upgrade_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # грейд — предварительная экспресс-оценка (routers/quest.py): помечается в карточке, кулдаун не запускает
    grade_express: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
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
    verify_code: Mapped[str] = mapped_column(String(64))  # sha256 кода из профиля; сам код показывается кандидату один раз
    verify_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    verify_attempts: Mapped[int] = mapped_column(Integer, default=0)  # проверок на один код; лимит — в routers/achievements.py
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
    level: Mapped[str | None] = mapped_column(String(32))  # international | national | regional | local — факт, на вес не влияет
    discipline: Mapped[str | None] = mapped_column(String(64))  # дисциплина ФСП (catalog.DISCIPLINES), факт
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
    result: Mapped[str | None] = mapped_column(String(16))  # winner | prize | finalist | participant (scoring.RESULT_WEIGHT)
    sport_rank: Mapped[str | None] = mapped_column(String(32))  # разряд/звание по протоколу ФСП (catalog.SPORT_RANKS), факт
    weight: Mapped[float] = mapped_column(Float, default=0.0)
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    data: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = _now()

    candidate: Mapped[Candidate] = relationship(back_populates="achievements")
    event: Mapped[Event | None] = relationship(lazy="selectin")  # дисциплина в бейджах карточек — без N+1


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
    blocked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # блок по отзывам «вакансии не было», до ручной проверки
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # последняя ручная проверка: отзывы до неё блок не дают
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
    company_feedback: Mapped[str | None] = mapped_column(String(16))  # отзыв кандидата о компании, catalog.COMPANY_FEEDBACK
    company_feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
    # публичная часть оперирует псевдонимами sha256(salt + public_id): без соли не связать с кандидатом и другими лотереями
    salt: Mapped[str | None] = mapped_column(String(64))
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
    __table_args__ = (
        Index("uq_quest_active", "candidate_id", unique=True, postgresql_where=text("finished_at IS NULL")),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    story: Mapped[bool] = mapped_column(Boolean, default=True)
    answers: Mapped[list[dict]] = mapped_column(JSON, default=list)  # [{"item_id", "response", "correct", "ms"}]
    theta: Mapped[float] = mapped_column(Float, default=0.0)
    se: Mapped[float] = mapped_column(Float, default=1.0)
    prior_mean: Mapped[float] = mapped_column(Float, default=0.0)  # стартовая оценка (например, из рейтинга CF)
    target_grade: Mapped[str | None] = mapped_column(String(16))  # заявленный грейд, на который проходит тест
    focus: Mapped[dict | None] = mapped_column(JSON)  # веса компетенций из описания вакансии {competency: weight}
    mode: Mapped[str] = mapped_column(String(8), default="full", server_default="full")  # full | express
    grade: Mapped[str | None] = mapped_column(String(16))  # грейд, измеренный этой попыткой
    applied: Mapped[bool | None] = mapped_column(Boolean)  # попал ли результат в профиль (во время кулдауна — только понижение)
    flags: Mapped[list[str]] = mapped_column(JSON, default=list)  # подозрения: inconsistent, too_fast…
    started_at: Mapped[datetime] = _now()
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Vacancy(Base):
    """Опубликованная вакансия — дополнительный сценарий: кандидат без приглашений может проявить инициативу."""

    __tablename__ = "vacancies"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    title: Mapped[str] = mapped_column(String(255))
    description: Mapped[str] = mapped_column(Text, default="")
    spec: Mapped[str] = mapped_column(String(32))
    track: Mapped[str | None] = mapped_column(String(32))
    grade: Mapped[str] = mapped_column(String(16))
    must: Mapped[list[str]] = mapped_column(JSON, default=list)
    nice: Mapped[list[str]] = mapped_column(JSON, default=list)
    salary_from: Mapped[int] = mapped_column(Integer)  # вилка обязательна, как и в приглашении
    salary_to: Mapped[int] = mapped_column(Integer)
    format: Mapped[str] = mapped_column(String(16))
    city: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(8), default="open")  # open | closed
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _now()
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    company: Mapped[Company] = relationship()


class Application(Base):
    """Отклик кандидата. Статусы: sent → seen → accepted | declined. Контакты кандидата видны сразу — он откликнулся сам."""

    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("vacancy_id", "candidate_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    vacancy_id: Mapped[int] = mapped_column(ForeignKey("vacancies.id", ondelete="CASCADE"))
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    note: Mapped[str | None] = mapped_column(String(300))  # коротко, не сопроводительное письмо
    status: Mapped[str] = mapped_column(String(12), default="sent")
    decline_reason: Mapped[str | None] = mapped_column(String(16))
    contacts_revealed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # раскрытие пишется в журнал один раз
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _now()
    seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    responded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    vacancy: Mapped[Vacancy] = relationship()
    candidate: Mapped[Candidate] = relationship()


class Task(Base):
    """Короткое задание от работодателя: решить или предложить подход. Витрина без уведомлений или вложение в приглашение."""

    __tablename__ = "tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    need_id: Mapped[int | None] = mapped_column(ForeignKey("needs.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(255))
    text: Mapped[str] = mapped_column(Text)
    spec: Mapped[str] = mapped_column(String(32))
    competency: Mapped[str | None] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(8), default="approach")  # solve | approach
    minutes: Mapped[int] = mapped_column(Integer, default=45)
    public: Mapped[bool] = mapped_column(Boolean, default=True)  # на витрине для всех кандидатов специализации
    # open — оценивает работодатель; text | number | choice | multi | regex — автопроверка по эталону (services/autocheck)
    answer_type: Mapped[str] = mapped_column(String(8), default="open", server_default="open")
    options: Mapped[list[str] | None] = mapped_column(JSON)  # варианты для choice / multi — публичная часть задания
    reference: Mapped[dict | None] = mapped_column(JSON)  # эталон: только серверу и компании-автору, кандидату не уходит
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _now()

    company: Mapped[Company] = relationship()


class TaskSubmission(Base):
    """Решение задания. Оценка работодателя — свежий сигнал о кандидате; на грейд и место в выдаче не влияет."""

    __tablename__ = "task_submissions"
    __table_args__ = (UniqueConstraint("task_id", "candidate_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"))
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    invitation_id: Mapped[int | None] = mapped_column(ForeignKey("invitations.id", ondelete="SET NULL"))
    answer: Mapped[str] = mapped_column(Text)
    review: Mapped[str | None] = mapped_column(String(8))  # strong | ok | weak
    review_comment: Mapped[str | None] = mapped_column(Text)
    auto_ok: Mapped[bool | None] = mapped_column(Boolean)  # автопроверка по эталону; None — открытый ответ или проверка не сработала
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = _now()
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    task: Mapped[Task] = relationship()
    candidate: Mapped[Candidate] = relationship()


class AuditLog(Base):
    """Журнал раскрытий и операций с ПДн (152-ФЗ): кто, что, о ком и когда. Только добавление."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int | None] = mapped_column(Integer)  # без FK: запись переживает удаление аккаунта
    action: Mapped[str] = mapped_column(String(32))  # contacts_revealed | data_exported | account_deleted | consent_changed | company_blocked | company_unblocked
    subject_candidate_id: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[dict | None] = mapped_column(JSON)  # без самих ПДн: только идентификаторы и основания
    at: Mapped[datetime] = _now()


class ConsentEvent(Base):
    """152-ФЗ: журнал согласий — каждая выдача и отзыв по каждой цели с версией текста. Только добавление."""

    __tablename__ = "consent_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[int | None] = mapped_column(Integer, index=True)  # без FK: доказательство переживает удаление
    purpose: Mapped[str] = mapped_column(String(16))  # processing | publish | external
    granted: Mapped[bool] = mapped_column(Boolean)
    version: Mapped[str] = mapped_column(String(16))
    at: Mapped[datetime] = _now()


class LoginChallenge(Base):
    """Ожидающий вход по коду. Пользователь создаётся только после проверки — чужую роль заранее не закрепить."""

    __tablename__ = "login_challenges"
    email: Mapped[str] = mapped_column(String(255), primary_key=True)
    role: Mapped[str] = mapped_column(String(16))
    code_hash: Mapped[str] = mapped_column(String(64))  # HMAC-SHA256(перец, email + код): по дампу БД не перебрать
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class FspLogin(Base):
    """Вход или привязка через ФСП ID (OIDC) от /start до /exchange. Секреты — только sha256: state, кука браузера,
    одноразовый билет. PKCE-верификатор и nonce не хранятся вовсе — выводятся HMAC(SECRET_KEY, state)."""

    __tablename__ = "fsp_logins"
    id: Mapped[int] = mapped_column(primary_key=True)
    state_hash: Mapped[str | None] = mapped_column(String(64), unique=True)  # None — callback уже был (повтор не пройдёт)
    browser_hash: Mapped[str] = mapped_column(String(64))  # sha256 куки fsp_flow: callback и обмен — только в том же браузере
    mode: Mapped[str] = mapped_column(String(8))  # login | link
    # link — кому привязываем ФСП ID (выбрал вошедший пользователь); login после callback — кто вошёл
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    ticket_hash: Mapped[str | None] = mapped_column(String(64), unique=True)  # билет на обмен в наш токен, живёт минуту
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RetiredPublicId(Base):
    """public_id удалённых кандидатов: не выдаются повторно, иначе старая лотерея «узнает» другого человека."""

    __tablename__ = "retired_public_ids"
    public_id: Mapped[str] = mapped_column(String(16), primary_key=True)


class Message(Base):
    """Сообщение во внутреннем чате между кандидатом и компанией."""

    __tablename__ = "messages"
    __table_args__ = (
        Index("idx_chat_history", "company_id", "candidate_id", "id"),
        Index("idx_chat_candidate", "candidate_id", "id"),  # диалоги кандидата: фильтр без company_id
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id", ondelete="CASCADE"))
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id", ondelete="CASCADE"))
    sender: Mapped[str] = mapped_column(String(16))  # employer | candidate
    text: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _now()
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
