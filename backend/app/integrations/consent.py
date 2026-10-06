"""Отдельное согласие на обработку данных внешних профилей (152-ФЗ)."""

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.catalog import CONSENT_VERSION
from app.models import Achievement, AuditLog, Candidate, ConsentEvent, ExternalAccount
from app.services.matching import consent_ok

# все источники внешних достижений: и привязанные профили, и протоколы организаторов
EXTERNAL_SOURCES = ("codeforces", "ctftime", "hackathon", "fsp")


def lock_candidate(db: Session, cand_id: int) -> Candidate | None:
    """SELECT … FOR UPDATE на кандидата с перечитыванием полей: после внешнего HTTP и перед записью
    перепроверяем согласие под блокировкой — параллельный отзыв (тоже под FOR UPDATE) не проскочит."""
    return db.scalar(select(Candidate).where(Candidate.id == cand_id).with_for_update()
                     .execution_options(populate_existing=True))


def set_external_consent(db: Session, cand: Candidate, value: bool) -> None:
    """Поставить флаг согласия. Отзыв удаляет внешние аккаунты и достижения всех внешних источников
    (CF, CTFtime, хакатоны, ФСП) — повторный импорт протокола их не вернёт без нового согласия.

    Выдача требует действующего согласия на обработку (matching.consent_ok «processing») → иначе HTTPException 403.
    Пишет ConsentEvent(purpose="external") и AuditLog consent_changed (152-ФЗ). Без commit — коммитит вызывающий.
    """
    c = lock_candidate(db, cand.id)  # сериализуемся с импортом/синхронизацией; дальше — только перечитанные поля
    if c is None:
        raise HTTPException(404, "Кандидат не найден")
    if value and not consent_ok(c, "processing"):
        raise HTTPException(403, "Сначала дайте согласие на обработку персональных данных")
    c.consent_external = value
    c.consent_external_version = CONSENT_VERSION if value else None  # своя версия: согласие на внешние данные
    db.add(ConsentEvent(candidate_id=c.id, purpose="external", granted=value, version=CONSENT_VERSION))
    db.add(AuditLog(actor_user_id=c.user_id, action="consent_changed", subject_candidate_id=c.id,
                    detail={"consent": "external", "value": value}))
    if not value:
        db.execute(delete(Achievement).where(Achievement.candidate_id == c.id, Achievement.source.in_(EXTERNAL_SOURCES)))
        db.execute(delete(ExternalAccount).where(ExternalAccount.candidate_id == c.id))
