"""Отдельное согласие на обработку данных внешних профилей (152-ФЗ)."""

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.models import Achievement, Candidate, ExternalAccount

EXTERNAL_SOURCES = ("codeforces", "ctftime")


def set_external_consent(db: Session, cand: Candidate, value: bool) -> None:
    """Поставить флаг согласия. Отзыв удаляет привязки CF/CTFtime и полученные из них достижения. Без commit."""
    cand.consent_external = value
    if not value:
        db.execute(delete(Achievement).where(Achievement.candidate_id == cand.id, Achievement.source.in_(EXTERNAL_SOURCES)))
        db.execute(delete(ExternalAccount).where(ExternalAccount.candidate_id == cand.id))
