"""Кабинет кандидата: профиль, резюме, статус, приватность, согласия и права по 152-ФЗ, приглашения."""

import io
import math
import secrets
import string
from types import SimpleNamespace
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from pypdf import PdfReader
from pypdf.errors import PdfReadError
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app import catalog
from app.db import get_db
from app.deps import current_candidate, current_user
from app.integrations.consent import lock_candidate, set_external_consent
from app.models import Application, AuditLog, Candidate, Company, ConsentEvent, Invitation, Message, QuestSession, RetiredPublicId, TaskSubmission, User
from app.routers.employer import company_trust
from app.services import matching, profile_pdf
from app.services.chat import may_talk, peers_linked
from app.services.parsing import canon_skills, canon_terms, parse_cv

router = APIRouter(prefix="/api/candidate", tags=["candidate"])

CV_MAX_BYTES = 5 * 1024 * 1024
CV_MAX_CHARS = 100_000  # резюме — это страницы, а не мегабайты: длиннее — мусор из PDF, разбирать и хранить незачем
NO_STORE = {"Cache-Control": "no-store"}  # файлы с ПДн не оседают в кешах браузера и прокси


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
    roles: list[str] | None = None  # catalog.ROLES; None — не менять
    soft_skills: list[str] | None = None  # catalog.SOFT_SKILLS; None — не менять
    consent_152: bool = False
    consent_publish: bool | None = None  # показывать обезличенную карточку работодателям; None — не менять
    consent_external: bool | None = None  # None — не менять; False — отзыв, внешние данные удаляются


class ConsentsIn(BaseModel):
    consent_152: bool | None = None
    consent_publish: bool | None = None


class StatusIn(BaseModel):
    status: str


class PdfIn(BaseModel):
    experience: bool  # места работы, распознанные из резюме, в разделе «Опыт» PDF-профиля


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
        # id удалённых не переиспользуем: иначе старая лотерея или воронка «узнает» другого человека
        if not db.scalar(select(Candidate.id).where(Candidate.public_id == pid)) and not db.get(RetiredPublicId, pid):
            return pid


def _now() -> datetime:
    return datetime.now(UTC)


WITHDRAWN = "Согласие на обработку отозвано — восстановите его или удалите аккаунт"


OUTDATED = "Текст согласия обновился — подтвердите согласие на обработку заново"


def _require_152(c: Candidate | None) -> None:
    """Без действующего согласия (отозвано или дано на старую редакцию) запись ПДн запрещена;
    без него остаются только действия, сужающие обработку (/consents, DELETE /me, PATCH /status, отказ от приглашения,
    отзыв отклика, исключение мест работы из PDF), и чтение своих данных — /me, /me/export, /profile.pdf."""
    if c is not None and not matching.consent_ok(c, "processing"):
        raise HTTPException(403, WITHDRAWN if not c.consent_152 else OUTDATED)


# цель → (флаг, версия текста этой цели)
_FIELDS = {"processing": ("consent_152", "consent_version"), "publish": ("consent_publish", "consent_publish_version"), "external": ("consent_external", "consent_external_version")}


def _needs_reconsent(c: Candidate) -> bool:
    """Какая-то цель включена, но согласие на неё дано на старую редакцию текста."""
    return any(getattr(c, flag) and getattr(c, ver) != catalog.CONSENT_VERSION for flag, ver in _FIELDS.values())


def _set_consent(db: Session, c: Candidate, purpose: str, value: bool, *, force: bool = False) -> None:
    """Меняет флаг согласия на цель (processing | publish) и пишет событие в журнал: при изменении, при создании
    профиля (force) и при повторном согласии на новую редакцию (тот же флаг, старая версия). Версию обновляет только
    у этой цели: повторное согласие на обработку не «оживляет» публикацию старой редакции."""
    flag, ver = _FIELDS[purpose]
    renew = value and getattr(c, ver) != catalog.CONSENT_VERSION
    if not force and bool(getattr(c, flag)) == value and not renew:
        return
    setattr(c, flag, value)
    if value:
        setattr(c, ver, catalog.CONSENT_VERSION)
        if purpose == "processing":
            c.consent_152_at = _now()
    db.add(ConsentEvent(candidate_id=c.id, purpose=purpose, granted=value, version=catalog.CONSENT_VERSION))


def _set_external(db: Session, c: Candidate, value: bool) -> None:
    set_external_consent(db, c, value)  # пишет событие; при отзыве удаляет внешние аккаунты и достижения
    if value:
        c.consent_external_version = catalog.CONSENT_VERSION


def _withdraw_processing(db: Session, c: Candidate) -> None:
    """Отзыв согласия на обработку (вызывать под lock_candidate): снимает публикацию, отзывает внешние профили
    с удалением их данных, скрывает профиль."""
    _set_consent(db, c, "publish", False)
    _set_external(db, c, False)
    _set_consent(db, c, "processing", False)
    c.status = "off"


def _consents(db: Session, c: Candidate) -> dict:
    """Последнее событие по каждой цели: {granted, at, version} или None, если событий нет."""
    out = dict.fromkeys(("processing", "publish", "external"))
    for e in db.scalars(select(ConsentEvent).where(ConsentEvent.candidate_id == c.id).order_by(ConsentEvent.at, ConsentEvent.id)):
        out[e.purpose] = {"granted": e.granted, "at": e.at, "version": e.version}
    return out


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
    skills = canon_skills(body.skills_claimed)
    # эмбеддинг (HTTP к модели) — до блокировки, чтобы не держать строку на время запроса
    vec = matching.embed_candidate(SimpleNamespace(spec=body.spec, track=body.track, grade=c.grade if c else None, grade_claimed=body.grade_claimed,
                                                   skills_confirmed=c.skills_confirmed if c else [], skills_claimed=skills))
    if c:
        # FOR UPDATE с перечитыванием: проверка согласия и запись сериализуются с PATCH /consents (отзыв не проскочит)
        c = lock_candidate(db, c.id)
    if c and body.consent_152 and c.consent_152 and c.consent_version != catalog.CONSENT_VERSION:
        _set_consent(db, c, "processing", True)  # повторное согласие на новую редакцию; отозванное — только через /consents
    _require_152(c)
    if not c:
        if not body.consent_152:
            raise HTTPException(422, "Нужно согласие на обработку персональных данных (152-ФЗ)")
        c = Candidate(user_id=user.id, public_id=_new_public_id(db), consent_152=False, consent_publish=False, consent_external=False)
        db.add(c)
    new = c.id is None
    c.name, c.email, c.tg = body.name, body.email or user.email, body.tg
    c.spec, c.track, c.grade_claimed = body.spec, body.track, body.grade_claimed
    c.min_salary, c.formats, c.city = body.min_salary, list(body.formats), body.city
    c.skills_claimed = skills
    c.years_exp = body.years_exp
    if body.roles is not None:  # вне справочника — отбрасываем, как навыки
        c.roles = canon_terms(body.roles, catalog.ROLES)
    if body.soft_skills is not None:
        c.soft_skills = canon_terms(body.soft_skills, catalog.SOFT_SKILLS)
    if new:
        db.flush()  # нужен id для журнала согласий
        _set_consent(db, c, "processing", True, force=True)
        _set_consent(db, c, "publish", bool(body.consent_publish), force=True)
    elif body.consent_publish is not None:
        _set_consent(db, c, "publish", body.consent_publish)
    if body.consent_external is not None:
        if body.consent_external and not matching.consent_ok(c, "processing"):
            raise HTTPException(422, "Согласие на внешние профили возможно только при согласии на обработку данных")
        _set_external(db, c, body.consent_external)
    c.embedding = vec
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
        "grade_express": bool(c.grade_express),  # грейд — предварительная экспресс-оценка
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
        "roles": c.roles or [],
        "soft_skills": c.soft_skills or [],
        "experience": profile_pdf.jobs(c),  # распознано из резюме — ровно то, что попадёт в «Опыт» PDF-профиля
        "pdf_experience": c.pdf_experience,
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
        "consent_152_at": c.consent_152_at,
        "consent_version": c.consent_version,
        "consent_publish": c.consent_publish,
        "consents": _consents(db, c),
        "needs_reconsent": _needs_reconsent(c),
        "consents_valid": {p: matching.consent_ok(c, p) for p in _FIELDS},  # флаг И текущая редакция текста
        "consent_external": c.consent_external,
        "invites_open": _open_count(db, c),
        "cap": catalog.CANDIDATE_CAP,
    }


@router.post("/cv")
async def upload_cv(file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    """PDF → текст → разбор. Возвращает распознанное для правки; профиль сам не меняет (кроме текста резюме)."""
    c = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    _require_152(c)
    data = await file.read(CV_MAX_BYTES + 1)
    if len(data) > CV_MAX_BYTES:
        raise HTTPException(413, "Резюме больше 5 МБ")
    if not data.startswith(b"%PDF"):
        raise HTTPException(422, "Нужен PDF-файл")
    try:  # разбор PDF и текста — CPU, в пуле потоков, чтобы не держать цикл событий для всех запросов
        text = (await run_in_threadpool(lambda: "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)))[:CV_MAX_CHARS].strip()
    except (PdfReadError, ValueError) as e:
        raise HTTPException(422, "Не удалось прочитать PDF") from e
    if not text:
        raise HTTPException(422, "В PDF нет текстового слоя (скан?). Заполните поля вручную")
    if c:
        c.cv_filename, c.cv_text = file.filename, text
        db.commit()
    return {"filename": file.filename, "chars": len(text), "parsed": await run_in_threadpool(parse_cv, text)}


@router.get("/profile.pdf")
def profile_pdf_file(c: Candidate = Depends(current_candidate)):
    """PDF-профиль для самого кандидата: с ФИО и контактами (как /me), чтобы приложить к отклику или отправить самому.
    Чтение своих данных — доступно и после отзыва согласия, как выгрузка."""
    return Response(profile_pdf.render(c), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="fsp-career-{c.public_id}.pdf"', **NO_STORE})


@router.patch("/pdf")
def set_pdf(body: PdfIn, c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    """Кандидат видит в профиле распознанные места работы (`experience` в /me) и решает, класть ли их в PDF.
    Исключить можно и без действующего согласия (PDF скачивается и после отзыва), включить — только с ним."""
    if body.experience:
        _require_152(c)
    c.pdf_experience = body.experience
    db.commit()
    return {"pdf_experience": c.pdf_experience}


@router.patch("/status")
def set_status(body: StatusIn, c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    if body.status not in ("open", "off"):
        raise HTTPException(422, "Статус: open | off")
    c.status = body.status
    db.commit()
    return {"status": c.status}


@router.patch("/notif")
def set_notif(body: NotifIn, c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    _require_152(c)
    c.notif = {**(c.notif or {}), **body.model_dump(exclude_none=True)}
    db.commit()
    return {"notif": c.notif}


@router.patch("/hidden-from")
def set_hidden(body: HiddenIn, c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    _require_152(c)
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


def _brief(db: Session, inv: Invitation, c: Candidate) -> dict:
    co = inv.company
    return {
        "id": inv.id,
        "company": co.name,
        "color": co.color,
        "about": co.about,
        **company_trust(db, co),  # «почта на домене подтверждена», «ИНН: контрольные цифры верны»
        "role": inv.role,
        "from": inv.salary_from,
        "to": inv.salary_to,
        "format": inv.format,
        "task": inv.task,
        "desc": inv.description,
        "due": _days_left(inv) if inv.status in matching.OPEN else None,
        "status": _STATUS[inv.status],
        "chat_peer": None,  # id компании, если ей можно писать — как can_write в чате (заполняют list_invites/_detail)
        "reason": catalog.DECLINE_REASONS.get(inv.decline_reason),
        "below_min": inv.salary_to < c.min_salary,
        "sent_at": inv.sent_at,
        "expires_at": inv.expires_at,
    }


def _own_invite(db: Session, c: Candidate, invite_id: int, *, expire: bool = True) -> Invitation:
    if expire:
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
    items = [_brief(db, i, c) for i in invs]
    chat = peers_linked(db, "candidate", c.id, [i.company_id for i in invs])
    for i, inv in zip(items, invs):
        i["chat_peer"] = inv.company_id if inv.company_id in chat and may_talk(c, inv.company) else None
    return {"items": items, "open": sum(i.status in matching.OPEN for i in invs), "cap": catalog.CANDIDATE_CAP}


def _detail(db: Session, inv: Invitation, c: Candidate) -> dict:
    out = _brief(db, inv, c)
    out["chat_peer"] = inv.company_id if peers_linked(db, "candidate", c.id, [inv.company_id]) and may_talk(c, inv.company) else None
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
    co = inv.company
    # способ связи с компанией — часть приглашения (это не ПДн кандидата), виден и до принятия
    out["recruiter"] = {"name": co.recruiter_name, "email": co.recruiter_email, "tg": co.recruiter_tg}
    if inv.status == "accepted":
        out["company_sees"] = {"name": c.name, "email": c.email, "tg": c.tg}
    return out


@router.get("/invites/{invite_id}")
def get_invite(invite_id: int, c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    inv = _own_invite(db, c, invite_id)
    if inv.status == "sent":
        inv.status, inv.seen_at = "seen", _now()
        db.commit()
    return _detail(db, inv, c)


def _respond(db: Session, c: Candidate, invite_id: int, *, expire: bool = True) -> Invitation:
    inv = _own_invite(db, c, invite_id, expire=expire)
    if inv.status not in matching.OPEN:
        raise HTTPException(409, "Приглашение уже закрыто" if inv.status != "expired" else "Срок ответа истёк")
    inv.seen_at = inv.seen_at or _now()
    inv.responded_at = _now()
    return inv


@router.post("/invites/{invite_id}/accept")
def accept(invite_id: int, c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    matching.expire_invites(db, candidate_id=c.id)  # коммитит — до блокировки
    # принятие раскрывает контакты: проверяем согласие под той же блокировкой строки кандидата, что и отзыв
    # (PATCH /consents) — запросы сериализуются, отзыв не проскочит между проверкой и раскрытием
    c = lock_candidate(db, c.id)
    _require_152(c)
    inv = _respond(db, c, invite_id, expire=False)
    inv.status = "accepted"
    db.add(AuditLog(actor_user_id=c.user_id, action="contacts_revealed", subject_candidate_id=c.id, detail={"invitation_id": inv.id, "company_id": inv.company_id}))
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


# ---------- согласия и права субъекта ПДн (152-ФЗ) ----------


@router.patch("/consents")
def set_consents(body: ConsentsIn, c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    """Отзыв согласия на обработку → публикация и внешние профили сняты (внешние данные удалены), профиль скрыт.
    Повторное согласие на обработку не трогает publish/external. Всё под блокировкой строки кандидата; каждое изменение — в журнал."""
    c = lock_candidate(db, c.id)
    snap = lambda: {"consent_152": c.consent_152, "consent_publish": c.consent_publish, "consent_external": c.consent_external,  # noqa: E731
                    "versions": [c.consent_version, c.consent_publish_version, c.consent_external_version]}
    before = snap()
    if body.consent_152 is False:
        _withdraw_processing(db, c)
    elif body.consent_152:
        _set_consent(db, c, "processing", True)
    if body.consent_publish is not None and body.consent_152 is not False:
        if body.consent_publish and not matching.consent_ok(c, "processing"):
            raise HTTPException(422, "Публикация карточки возможна только при согласии на обработку данных")
        _set_consent(db, c, "publish", body.consent_publish)
    after = snap()
    if after != before:
        db.add(AuditLog(actor_user_id=c.user_id, action="consent_changed", subject_candidate_id=c.id, detail={"before": before, "after": after}))
    db.commit()
    db.expire(c, ["achievements", "accounts"])
    return {"consent_152": c.consent_152, "consent_publish": c.consent_publish, "consent_external": c.consent_external, "consent_152_at": c.consent_152_at,
            "consent_version": c.consent_version, "consent_publish_version": c.consent_publish_version, "consent_external_version": c.consent_external_version,
            "valid": {p: matching.consent_ok(c, p) for p in _FIELDS}, "needs_reconsent": _needs_reconsent(c), "status": c.status}


def _rows(objs, skip=()) -> list[dict]:
    return [{k: getattr(o, k) for k in o.__mapper__.columns.keys() if k not in skip} for o in objs]


@router.get("/me/export")
def export(response: Response, c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    """Все свои данные одним JSON (право на доступ, ст. 14 152-ФЗ; включая переписку в чате). Не выгружаются только секреты: хеши токена/OTP и код
    подтверждения внешнего профиля. Запись data_exported коммитится до снимка — и попадает в раздел audit выгрузки."""
    response.headers.update(NO_STORE)
    db.add(AuditLog(actor_user_id=c.user_id, action="data_exported", subject_candidate_id=c.id, detail=None))
    db.commit()
    by_cand = lambda m: db.scalars(select(m).where(m.candidate_id == c.id).order_by(m.id)).all()  # noqa: E731
    invs = by_cand(Invitation)
    user = db.get(User, c.user_id) if c.user_id else None
    profile = _rows([c], skip={"embedding"})[0]
    profile["truth"] = c.truth if c.is_synthetic else None
    out = {
        "exported_at": _now(),
        "account": {"email": user.email, "role": user.role, "fsp_id": user.fsp_id, "created_at": user.created_at} if user else None,
        "profile": profile,
        "embedding": {"vector": list(c.embedding) if c.embedding is not None else None, "dim": len(c.embedding) if c.embedding else 0},
        "consents": _rows(db.scalars(select(ConsentEvent).where(ConsentEvent.candidate_id == c.id).order_by(ConsentEvent.id))),
        "audit": _rows(db.scalars(select(AuditLog).where(AuditLog.subject_candidate_id == c.id).order_by(AuditLog.id))),
        "achievements": _rows(c.achievements),
        "external_accounts": _rows(c.accounts, skip={"verify_code"}),
        "invitations": [{**r, "company": i.company.name} for r, i in zip(_rows(invs), invs)],
        "applications": _rows(by_cand(Application)),
        "messages": _rows(by_cand(Message)),
        "task_submissions": _rows(by_cand(TaskSubmission)),
        # ответы теста без ключей заданий: id задания, ответ, верно/нет, время
        "quest_sessions": _rows(by_cand(QuestSession)),
    }
    return out


@router.delete("/me")
def delete_me(c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    """Удаление аккаунта: кандидат (каскадом — достижения, приглашения, отклики, сообщения чата, решения, сессии теста) и пользователь.
    В журнале остаются только идентификаторы."""
    user = db.get(User, c.user_id) if c.user_id else None
    db.add(AuditLog(actor_user_id=c.user_id, action="account_deleted", subject_candidate_id=c.id, detail=None))
    db.add(RetiredPublicId(public_id=c.public_id))
    db.delete(c)
    db.flush()
    if user:
        db.delete(user)
    db.commit()
    return {"deleted": True}
