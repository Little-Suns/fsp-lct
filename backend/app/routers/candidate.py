"""Кабинет кандидата: профиль, резюме, статус, приватность, приглашения."""

import io
import math
import secrets
import string
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import catalog
from app.db import get_db
from app.deps import current_candidate, current_user
from app.models import Candidate, Company, Invitation, User
from app.integrations.consent import set_external_consent
from app.services import matching
from app.services.parsing import canon_skills, parse_cv

router = APIRouter(prefix="/api/candidate", tags=["candidate"])

CV_MAX_BYTES = 5 * 1024 * 1024


class ProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: str | None = None  # по умолчанию — почта входа
    tg: str | None = Field(default=None, max_length=64)
    spec: str
    track: str | None = None
    grade_claimed: str
    min_salary: int = Field(gt=0)
    formats: list[str]
    city: str = Field(min_length=1, max_length=64)
    skills_claimed: list[str] = []
    years_exp: float | None = Field(default=None, ge=0, le=60)
    consent_152: bool = False
    consent_external: bool = False


class StatusIn(BaseModel):
    status: str


class NotifIn(BaseModel):
    mail: bool | None = None
    tg: bool | None = None


class HiddenIn(BaseModel):
    inns: list[str]


class DeclineIn(BaseModel):
    reason: str
    comment: str | None = Field(default=None, max_length=1000)


def _new_public_id(db: Session) -> str:
    while True:
        pid = f"{secrets.choice(string.ascii_uppercase)}-{secrets.randbelow(9000) + 1000}"
        if not db.scalar(select(Candidate.id).where(Candidate.public_id == pid)):
            return pid


def _now() -> datetime:
    return datetime.now(UTC)


@router.post("/profile")
def save_profile(body: ProfileIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "candidate":
        raise HTTPException(403, "Профиль кандидата доступен только кандидатам")
    if body.spec not in catalog.SPECS:
        raise HTTPException(422, f"Специализация: одна из {', '.join(catalog.SPECS)}")
    if body.track and body.track not in catalog.TRACKS[body.spec]:
        raise HTTPException(422, f"Трек для {body.spec}: один из {', '.join(catalog.TRACKS[body.spec])}")
    if body.grade_claimed not in catalog.GRADES:
        raise HTTPException(422, f"Грейд: один из {', '.join(catalog.GRADES)}")
    if not body.formats or any(f not in catalog.FORMATS for f in body.formats):
        raise HTTPException(422, f"Формат: один или несколько из {', '.join(catalog.FORMATS)}")
    c = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    if not c:
        if not body.consent_152:
            raise HTTPException(422, "Нужно согласие на обработку персональных данных (152-ФЗ)")
        c = Candidate(user_id=user.id, public_id=_new_public_id(db))
        db.add(c)
    c.name, c.email, c.tg = body.name, body.email or user.email, body.tg
    c.spec, c.track, c.grade_claimed = body.spec, body.track, body.grade_claimed
    c.min_salary, c.formats, c.city = body.min_salary, list(body.formats), body.city
    c.skills_claimed = canon_skills(body.skills_claimed)
    c.years_exp = body.years_exp
    c.consent_152 = c.consent_152 or body.consent_152
    set_external_consent(db, c, body.consent_external)  # отзыв удаляет CF/CTFtime и их достижения
    c.embedding = matching.embed_candidate(c)
    db.commit()
    db.expire(c, ["achievements", "accounts"])  # удаление было bulk-запросом мимо загруженных коллекций
    return me(c, db)


def _open_count(db: Session, c: Candidate) -> int:
    return matching.candidate_loads(db, [c.id])[c.id]


@router.get("/me")
def me(c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    matching.expire_invites(db, candidate_id=c.id)
    cf = matching.cf_account(c)
    return {
        "id": c.public_id,
        "name": c.name,
        "email": c.email,
        "tg": c.tg,
        "spec": c.spec,
        "track": c.track,
        "grade": c.grade,  # по тесту; None — тест не пройден
        "grade_claimed": c.grade_claimed,
        "pct": c.percentile,
        "theta": c.theta,
        "se": c.se,
        "min": c.min_salary,
        "formats": c.formats or [],
        "format": matching.format_text(c.formats, c.city),
        "city": c.city,
        "status": c.status,
        "notif": c.notif,
        "hidden_from": c.hidden_from or [],
        "years_exp": c.years_exp,
        "skills_claimed": c.skills_claimed or [],
        "skills_confirmed": c.skills_confirmed or [],
        "competencies": c.competencies or [],
        "cv_filename": c.cv_filename,
        "tested_at": c.tested_at,
        "confirmed": matching.months_ago(c.tested_at),
        "next_upgrade_at": c.next_upgrade_at,
        "review_passed": c.review_passed,
        "employer_confirmed": c.employer_confirmed,
        "achievements": [
            {"id": a.id, "source": a.source, "title": a.title, "place": a.place, "role": a.role, "weight": a.weight, "verified": a.verified}
            for a in c.achievements
        ],
        "fsp": matching.fsp_title(c),
        "cf": {"handle": cf.handle, "rating": cf.rating, "rank": cf.rank} if cf else None,
        "consent_152": c.consent_152,
        "consent_external": c.consent_external,
        "invites_open": _open_count(db, c),
        "cap": catalog.CANDIDATE_CAP,
    }


@router.post("/cv")
async def upload_cv(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    """PDF → текст → разбор. Возвращает распознанное для правки; профиль сам не меняет (кроме текста резюме)."""
    data = await file.read(CV_MAX_BYTES + 1)
    if len(data) > CV_MAX_BYTES:
        raise HTTPException(413, "Резюме больше 5 МБ")
    if not data.startswith(b"%PDF"):
        raise HTTPException(422, "Нужен PDF-файл")
    try:
        text = "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages).strip()
    except (PdfReadError, ValueError) as e:
        raise HTTPException(422, "Не удалось прочитать PDF") from e
    if not text:
        raise HTTPException(422, "В PDF нет текстового слоя (скан?). Заполните поля вручную")
    c = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    if c:
        c.cv_filename, c.cv_text = file.filename, text
        db.commit()
    return {"filename": file.filename, "chars": len(text), "parsed": parse_cv(text)}


@router.patch("/status")
def set_status(body: StatusIn, c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    if body.status not in ("open", "off"):
        raise HTTPException(422, "Статус: open | off")
    c.status = body.status
    db.commit()
    return {"status": c.status}


@router.patch("/notif")
def set_notif(body: NotifIn, c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    c.notif = {**(c.notif or {}), **body.model_dump(exclude_none=True)}
    db.commit()
    return {"notif": c.notif}


@router.patch("/hidden-from")
def set_hidden(body: HiddenIn, c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    inns = list(dict.fromkeys(i.strip() for i in body.inns if i.strip()))
    bad = [i for i in inns if not (i.isdigit() and len(i) in (10, 12))]
    if bad:
        raise HTTPException(422, f"ИНН — 10 или 12 цифр: {', '.join(bad)}")
    c.hidden_from = inns
    db.commit()
    known = {co.inn: co.name for co in db.scalars(select(Company).where(Company.inn.in_(inns)))} if inns else {}
    return {"hidden_from": inns, "companies": [{"inn": i, "name": known.get(i)} for i in inns]}


# ---------- приглашения ----------

_STATUS = {"sent": "new", "seen": "seen", "accepted": "accepted", "declined": "declined", "expired": "expired"}


def _days_left(inv: Invitation) -> int:
    return max(0, math.ceil((inv.expires_at - _now()).total_seconds() / 86400))


def _brief(inv: Invitation, c: Candidate) -> dict:
    co = inv.company
    return {
        "id": inv.id,
        "company": co.name,
        "color": co.color,
        "about": co.about,
        "verified": co.verified,
        "role": inv.role,
        "from": inv.salary_from,
        "to": inv.salary_to,
        "format": inv.format,
        "task": inv.task,
        "desc": inv.description,
        "due": _days_left(inv) if inv.status in matching.OPEN else None,
        "status": _STATUS[inv.status],
        "reason": catalog.DECLINE_REASONS.get(inv.decline_reason),
        "below_min": inv.salary_to < c.min_salary,
        "sent_at": inv.sent_at,
        "expires_at": inv.expires_at,
    }


def _own_invite(db: Session, c: Candidate, invite_id: int) -> Invitation:
    matching.expire_invites(db, candidate_id=c.id)
    inv = db.get(Invitation, invite_id)
    if not inv or inv.candidate_id != c.id:
        raise HTTPException(404, "Приглашение не найдено")
    return inv


@router.get("/invites")
def list_invites(c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    matching.expire_invites(db, candidate_id=c.id)
    invs = db.scalars(
        select(Invitation).where(Invitation.candidate_id == c.id).options(selectinload(Invitation.company)).order_by(Invitation.sent_at.desc(), Invitation.id.desc())
    ).all()
    return {"items": [_brief(i, c) for i in invs], "open": sum(i.status in matching.OPEN for i in invs), "cap": catalog.CANDIDATE_CAP}


def _detail(db: Session, inv: Invitation, c: Candidate) -> dict:
    out = _brief(inv, c)
    out["fork_check"] = {
        "ok": not out["below_min"],
        "min": c.min_salary,
        "text": f"Верхняя граница ниже вашего минимума ({c.min_salary:,} ₽)".replace(",", " ")
        if out["below_min"]
        else f"Вилка покрывает ваш минимум {c.min_salary:,} ₽".replace(",", " "),
    }
    out["why"] = None
    if inv.need:
        r = matching.score_candidates(db, inv.need, [c], limit=1)
        out["why"] = r[0].explanation["why"] if r else None
    out["company_knows"] = "contacts" if inv.status == "accepted" else "anonymous"
    out["public_id"] = c.public_id
    out["load"] = {"open": _open_count(db, c), "cap": catalog.CANDIDATE_CAP}
    if inv.status == "accepted":
        co = inv.company
        out["recruiter"] = {"name": co.recruiter_name, "email": co.recruiter_email, "tg": co.recruiter_tg}
        out["company_sees"] = {"name": c.name, "email": c.email, "tg": c.tg}
    return out


@router.get("/invites/{invite_id}")
def get_invite(invite_id: int, c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    inv = _own_invite(db, c, invite_id)
    if inv.status == "sent":
        inv.status, inv.seen_at = "seen", _now()
        db.commit()
    return _detail(db, inv, c)


def _respond(db: Session, c: Candidate, invite_id: int) -> Invitation:
    inv = _own_invite(db, c, invite_id)
    if inv.status not in matching.OPEN:
        raise HTTPException(409, "Приглашение уже закрыто" if inv.status != "expired" else "Срок ответа истёк")
    inv.seen_at = inv.seen_at or _now()
    inv.responded_at = _now()
    return inv


@router.post("/invites/{invite_id}/accept")
def accept(invite_id: int, c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    inv = _respond(db, c, invite_id)
    inv.status = "accepted"
    db.commit()
    return _detail(db, inv, c)


@router.post("/invites/{invite_id}/decline")
def decline(invite_id: int, body: DeclineIn, c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    if body.reason not in catalog.DECLINE_REASONS:
        raise HTTPException(422, f"Причина отказа: одна из {', '.join(catalog.DECLINE_REASONS)}")
    inv = _respond(db, c, invite_id)
    inv.status, inv.decline_reason, inv.decline_comment = "declined", body.reason, body.comment
    db.commit()
    return _detail(db, inv, c)
