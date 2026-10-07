"""Репутация работодателя по отзывам кандидатов — защита от фиктивных приглашений.

Через COMPANY_FEEDBACK_AFTER_DAYS после принятия приглашения кандидат может (не обязан) оставить отзыв о компании.
Кандидату репутация компании не показывается ни в каком виде: отзывы только меняют квоту работодателя.

- Штраф: за FEEDBACK_WINDOW_DAYS плохих отзывов ≥ FEEDBACK_BAD_MIN от разных кандидатов и ≥ FEEDBACK_BAD_SHARE
  всех отзывов окна → квота FEEDBACK_PENALTY_QUOTA. Окно скользящее — штраф снимается сам.
- Блок: «вакансии не было» от FRAUD_BLOCK_MIN разных кандидатов после последней ручной проверки → компания
  не приглашает, не публикует вакансии и задания, не пишет в чат, её вакансии скрыты. Снимает только человек:
  `python -m app.services.reputation unblock <ИНН>` (reviewed_at — отзывы до проверки блок больше не дают).

Отзыв можно оставить только по принятому приглашению — компания сама выбрала кандидата, конкурент не может
«накидать» отзывов, не получив приглашения.
"""

import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app import catalog
from app.models import AuditLog, Company, Invitation


def _now() -> datetime:
    return datetime.now(UTC)


def feedback_open(inv: Invitation, now: datetime | None = None) -> bool:
    """Кандидат может оставить отзыв: приглашение принято, прошла неделя, отзыва ещё нет."""
    if inv.status != "accepted" or inv.company_feedback or not inv.responded_at:
        return False
    return (now or _now()) >= inv.responded_at + timedelta(days=catalog.COMPANY_FEEDBACK_AFTER_DAYS)


def summary(db: Session, co: Company, now: datetime | None = None) -> dict:
    """Отзывы окна: штраф и сводка для работодателя (по типам — только от FEEDBACK_SUMMARY_MIN отзывов)."""
    since = (now or _now()) - timedelta(days=catalog.FEEDBACK_WINDOW_DAYS)
    rows = db.execute(
        select(Invitation.candidate_id, Invitation.company_feedback).where(
            Invitation.company_id == co.id, Invitation.company_feedback.is_not(None), Invitation.company_feedback_at >= since
        )
    ).all()
    # ponytail: доля — по отзывам, порог — по разным кандидатам; кандидат с несколькими принятыми приглашениями одной
    # компании весит в доле больше — считать долю по уникальным кандидатам, если это начнёт искажать штраф
    bad = [cid for cid, fb in rows if fb in catalog.COMPANY_FEEDBACK_BAD]
    penalty = len(set(bad)) >= catalog.FEEDBACK_BAD_MIN and len(bad) >= catalog.FEEDBACK_BAD_SHARE * len(rows)
    shown = len(rows) >= catalog.FEEDBACK_SUMMARY_MIN  # меньше трёх отзывов — ни числа, ни разбивки: автора не вычислить
    counts = {k: sum(fb == k for _, fb in rows) for k in catalog.COMPANY_FEEDBACK} if shown else None
    return {"window_days": catalog.FEEDBACK_WINDOW_DAYS, "total": len(rows) if shown else None, "bad": len(bad) if shown else None,
            "penalty": penalty, "counts": counts, "blocked": co.blocked_at is not None}


def check_block(db: Session, co: Company) -> bool:
    """Ставит блок, если «вакансии не было» сказали FRAUD_BLOCK_MIN разных кандидатов после ручной проверки.
    Вызывается под блокировкой строки компании (save_feedback): параллельные отзывы не проскочат мимо порога."""
    if co.blocked_at:
        return True
    q = select(func.count(func.distinct(Invitation.candidate_id))).where(Invitation.company_id == co.id, Invitation.company_feedback == "fraud")
    if co.reviewed_at:
        q = q.where(Invitation.company_feedback_at > co.reviewed_at)
    if db.scalar(q) >= catalog.FRAUD_BLOCK_MIN:
        co.blocked_at = _now()
        # открытые приглашения истекают: принять их и раскрыть контакты нельзя, а кандидат видит нейтральное «истекло»
        db.execute(update(Invitation).where(Invitation.company_id == co.id, Invitation.status.in_(("sent", "seen"))).values(status="expired"))
        db.add(AuditLog(actor_user_id=None, action="company_blocked", detail={"company_id": co.id, "basis": "fraud_feedback"}))
        return True
    return False


def save_feedback(db: Session, inv: Invitation, value: str) -> bool:
    """Сохраняет отзыв и проверяет блок. Блокировки: компания, затем приглашение — параллельные отзывы
    сериализуются, повторный отзыв на то же приглашение не перезапишет первый. False — отзыв уже был."""
    co = db.scalar(select(Company).where(Company.id == inv.company_id).with_for_update())
    db.refresh(inv, with_for_update=True)
    if inv.company_feedback:
        db.rollback()
        return False
    inv.company_feedback, inv.company_feedback_at = value, _now()
    db.flush()
    check_block(db, co)
    db.commit()
    return True


def unblock(db: Session, inn: str) -> Company:
    co = db.scalar(select(Company).where(Company.inn == inn))
    if not co:
        raise LookupError(f"Компания с ИНН {inn} не найдена")
    if not co.blocked_at:
        raise LookupError(f"Компания с ИНН {inn} не заблокирована")  # иначе сдвиг reviewed_at обнулил бы накопленные отзывы
    co.blocked_at, co.reviewed_at = None, _now()
    db.add(AuditLog(actor_user_id=None, action="company_unblocked", detail={"company_id": co.id, "basis": "manual_review"}))
    db.commit()
    return co


def main(argv: list[str]) -> int:
    """Ручная проверка. ponytail: CLI вместо кабинета модератора; роль модератора и очередь — когда появится команда поддержки."""
    from app.db import SessionLocal

    with SessionLocal() as db:
        if argv[:1] == ["blocked"]:
            for co in db.scalars(select(Company).where(Company.blocked_at.is_not(None)).order_by(Company.blocked_at)):
                print(f"{co.inn}\t{co.name}\t{co.blocked_at:%Y-%m-%d %H:%M}")
            return 0
        if len(argv) == 2 and argv[0] == "unblock":
            try:
                co = unblock(db, argv[1])
            except LookupError as e:
                print(e, file=sys.stderr)
                return 1
            print(f"Блок снят: {co.name}")
            return 0
    print("Использование: python -m app.services.reputation blocked | unblock <ИНН>", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
