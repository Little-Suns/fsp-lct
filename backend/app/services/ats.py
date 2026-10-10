"""Интеграция с ATS работодателя: ключи API, входящий API /api/ats/v1 (routers/ats.py) и лента событий (outbox).

События пишутся в OutboxEvent в той же транзакции, что и смена статуса (emit не коммитит), — лента не расходится с базой.
ATS забирает ленту курсором (GET /api/ats/v1/events?after=…). В payload только идентификаторы и статусы, без ПДн:
анонимную карточку и контакты лента собирает при чтении по тем же правилам, что и кабинет, — удалённый кандидат
или отозванное согласие не утекают из старых событий.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Application, Candidate, Invitation, OutboxEvent, Vacancy

# ponytail: только pull-лента; вебхуки с подписью — доставщик поверх той же таблицы (docs/11-concepts.md, table.md).
LOCK_NS = 0x415453  # «ATS»: первый ключ advisory-блокировки порядка ленты, второй — company_id

# область ключа → что она открывает
SCOPES = {
    "vacancies:write": "публиковать, править, закрывать и продлевать вакансии",
    "applications:read": "читать события по откликам",
    "applications:write": "менять статус отклика",
    "invites:read": "читать события по приглашениям",
    "invites:write": "ставить отметку по принятому приглашению (наняли, подтвердился)",
}

# тип события → область, без которой ключ его не видит; candidate.access_revoked видит ключ с любой из областей чтения
EVENTS = {
    "application.created": "applications:read",
    "application.withdrawn": "applications:read",
    "application.status": "applications:read",  # seen | accepted | declined — из кабинета или через API
    "invitation.seen": "invites:read",
    "invitation.accepted": "invites:read",
    "invitation.declined": "invites:read",
    "invitation.expired": "invites:read",
    "candidate.access_revoked": None,
}
READ_SCOPES = ("applications:read", "invites:read")


def emit(db: Session, company_id: int, type: str, **payload) -> None:
    """Событие в ленту компании. Не коммитит: пишется вместе со сменой статуса. payload — только id и статусы, без ПДн."""
    assert type in EVENTS, type
    # Курсор ленты — id события, а id выдаются не в порядке коммитов: событие с меньшим id, закоммиченное позже, ATS бы потерял.
    # Блокировка до INSERT (id берётся при flush) на время транзакции выстраивает коммиты событий компании в порядке id.
    # Порядок блокировок везде один: строки (FOR UPDATE, в том числе удаляемые каскадом) → эта; компании в emit_revoked и
    # expire_invites — по возрастанию. Поэтому delete_me шлёт события после db.delete + flush, а здесь сначала flush:
    # select(advisory) autoflush не запускает, и отложенный UPDATE строки ушёл бы уже после блокировки.
    db.flush()
    db.execute(select(func.pg_advisory_xact_lock(LOCK_NS, company_id)))
    db.add(OutboxEvent(company_id=company_id, type=type, payload=payload))


def access_companies(db: Session, c: Candidate, company_ids: set[int] | None = None) -> set[int]:
    """Компании, которым открыты контакты кандидата (принятое приглашение или отклик). company_ids — сузить."""
    inv = select(Invitation.company_id).where(Invitation.candidate_id == c.id, Invitation.status == "accepted")
    app = select(Vacancy.company_id).join(Application, Application.vacancy_id == Vacancy.id).where(
        Application.candidate_id == c.id, Application.status == "accepted"
    )
    ids = set(db.scalars(inv)) | set(db.scalars(app))
    return ids if company_ids is None else ids & company_ids


def emit_revoked(db: Session, ids: set[int], public_id: str, why: str) -> None:
    """candidate.access_revoked компаниям из ids (по возрастанию). why: consent | deleted | hidden."""
    for cid in sorted(ids):
        emit(db, cid, "candidate.access_revoked", public_id=public_id, why=why)


def revoke_access(db: Session, c: Candidate, why: str, company_ids: set[int] | None = None) -> None:
    """access_companies + emit_revoked. При удалении кандидата не годится: там события после удаления строк (см. delete_me)."""
    emit_revoked(db, access_companies(db, c, company_ids), c.public_id, why)
