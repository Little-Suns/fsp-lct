"""Вакансии и отклики — дополнительный сценарий к обратному найму: кандидат без приглашений может проявить инициативу.

Вилка в вакансии обязательна и проверяется теми же правилами, что и в приглашении. Кандидат откликнулся сам —
значит, контакты видны работодателю сразу; каждое первое раскрытие пишется в журнал (152-ФЗ).
Статусы отклика: sent → seen → accepted | declined; кандидат может отозвать отклик (withdrawn), пока нет ответа.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import object_session, Session, selectinload

from app import catalog
from app.db import get_db
from app.deps import active_company, current_candidate, current_company, current_user
from app.models import Application, AuditLog, Candidate, Company, Vacancy
from app.routers.employer import MSK, company_trust, validate_fork
from app.services import matching
from app.services.chat import may_talk, peers_linked
from app.services.parsing import canon_skills

router = APIRouter(prefix="/api/vacancies", tags=["vacancies"])

OPEN_APP = ("sent", "seen")
STATUSES = ("sent", "seen", "accepted", "declined", "withdrawn")
# переходы, доступные работодателю: в какой статус → из каких
EMPLOYER_MOVES = {"seen": {"sent"}, "accepted": {"sent", "seen"}, "declined": {"sent", "seen"}}


def _now() -> datetime:
    return datetime.now(UTC)


def _lock(db: Session, model, row_id: int):
    """SELECT … FOR UPDATE с перечитыванием полей: проверки после блокировки видят свежее состояние."""
    return db.scalar(select(model).where(model.id == row_id).with_for_update().execution_options(populate_existing=True))


def maybe_candidate(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> Candidate | None:
    """Необязательная авторизация: список вакансий открыт всем, кандидату — с сортировкой по соответствию."""
    if not authorization:
        return None
    try:
        user = current_user(authorization, db)
    except HTTPException:
        return None
    return db.scalar(select(Candidate).where(Candidate.user_id == user.id))


def fit(c: Candidate, v: Vacancy) -> float | None:
    """Соответствие кандидата вакансии по формуле подбора (тест, покрытие навыков, достижения × вероятность принятия).

    Вакансия подставляется вместо потребности: у неё те же поля spec/track/grade/must/nice/вилка/формат/город.
    Без LLM и эмбеддингов — список считается на лету для каждой вакансии.
    # ponytail: приватный matching._relevance; вынести в публичную функцию, если подбор начнут менять
    """
    if c.theta is None or c.spec != v.spec:
        return None
    r = matching._relevance(c, v)
    acc = matching.accept_prob(v.salary_to, c.min_salary, matching.format_ok(c.formats, c.city, v.format, v.city), r["stack"])
    return round(matching.final_score(r["match"], acc, 0), 3)


def vacancy_out(v: Vacancy, c: Candidate | None = None, applied: str | None = None) -> dict:
    co = v.company
    return {
        "id": v.id,
        "title": v.title,
        "description": v.description,
        "spec": v.spec,
        "track": v.track,
        "grade": v.grade,
        "must": v.must,
        "nice": v.nice,
        "from": v.salary_from,
        "to": v.salary_to,
        "format": v.format,
        "city": v.city,
        "status": v.status,
        "created_at": v.created_at,
        "updated_at": v.updated_at,
        "company": {"id": co.id, "name": co.name, "color": co.color, "verified": co.verified, **company_trust(object_session(co), co)},
        "market": catalog.market(v.spec, v.grade, v.city),
        "fit": fit(c, v) if c else None,
        "fork_vs_min": (v.salary_to >= c.min_salary) if c else None,  # верх вилки не ниже минимума кандидата
        "applied": applied,  # статус своего отклика или None
    }


# ---------- работодатель ----------


class VacancyIn(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    description: str = Field(default="", max_length=10000)
    spec: str
    track: str | None = None
    grade: str
    must: list[str] = []
    nice: list[str] = []
    salary_from: int | None = None
    salary_to: int | None = None
    format: str
    city: str | None = Field(default=None, max_length=64)


class VacancyPatch(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=255)
    description: str | None = Field(default=None, max_length=10000)
    spec: str | None = None
    track: str | None = None
    grade: str | None = None
    must: list[str] | None = None
    nice: list[str] | None = None
    salary_from: int | None = None
    salary_to: int | None = None
    format: str | None = None
    city: str | None = Field(default=None, max_length=64)


def _validate(v: Vacancy) -> list[str]:
    """Справочник + правила вилки. 422 с {errors, warnings}, как у приглашения."""
    if v.spec not in catalog.SPECS:
        raise HTTPException(422, {"errors": [f"Специализация: одна из {', '.join(catalog.SPECS)}"], "warnings": []})
    if v.track and v.track not in catalog.TRACKS[v.spec]:
        raise HTTPException(422, {"errors": [f"Трек для {v.spec}: один из {', '.join(catalog.TRACKS[v.spec])}"], "warnings": []})
    if v.grade not in catalog.GRADES:
        raise HTTPException(422, {"errors": [f"Грейд: один из {', '.join(catalog.GRADES)}"], "warnings": []})
    if v.format not in catalog.FORMATS:
        raise HTTPException(422, {"errors": [f"Формат: один из {', '.join(catalog.FORMATS)}"], "warnings": []})
    p25 = catalog.market(v.spec, v.grade, v.city)["p25"]
    errors, warnings = validate_fork(v.salary_from, v.salary_to, p25=p25, cand_min=None, grade=v.grade)
    if errors:
        raise HTTPException(422, {"errors": errors, "warnings": warnings})
    v.must = canon_skills(v.must or [])
    v.nice = [s for s in canon_skills(v.nice or []) if s not in v.must]
    return warnings


def _own_vacancy(db: Session, co: Company, vacancy_id: int) -> Vacancy:
    v = db.get(Vacancy, vacancy_id)
    if not v or v.company_id != co.id:
        raise HTTPException(404, "Вакансия не найдена")
    return v


@router.post("")
def create_vacancy(body: VacancyIn, co: Company = Depends(active_company), db: Session = Depends(get_db)):
    # неподтверждённая компания тоже публикует: в карточке вакансии company.verified → плашка у кандидата
    v = Vacancy(company_id=co.id, **body.model_dump())
    v.company = co
    warnings = _validate(v)
    db.add(v)
    db.commit()
    return {**vacancy_out(v), "warnings": warnings}


@router.patch("/{vacancy_id}")
def edit_vacancy(vacancy_id: int, body: VacancyPatch, co: Company = Depends(active_company), db: Session = Depends(get_db)):
    v = _own_vacancy(db, co, vacancy_id)
    for k, val in body.model_dump(exclude_unset=True).items():
        if val is not None or k in ("track", "city"):  # null сбрасывает только необязательные поля
            setattr(v, k, val)
    try:
        warnings = _validate(v)
    except HTTPException:
        db.rollback()
        raise
    v.updated_at = _now()
    db.commit()
    return {**vacancy_out(v), "warnings": warnings}


@router.post("/{vacancy_id}/close")
def close_vacancy(vacancy_id: int, co: Company = Depends(current_company), db: Session = Depends(get_db)):
    v = _own_vacancy(db, co, vacancy_id)
    v.status, v.updated_at = "closed", _now()
    db.commit()
    return vacancy_out(v)


@router.get("/mine")
def my_vacancies(co: Company = Depends(current_company), db: Session = Depends(get_db)):
    vs = db.scalars(select(Vacancy).where(Vacancy.company_id == co.id).order_by(Vacancy.created_at.desc(), Vacancy.id.desc())).all()
    rows = db.execute(
        select(Application.vacancy_id, Application.status, func.count())
        .where(Application.vacancy_id.in_([v.id for v in vs]))
        .group_by(Application.vacancy_id, Application.status)
    ).all()
    counts = {v.id: dict.fromkeys(STATUSES, 0) for v in vs}
    for vid, st, n in rows:
        counts[vid][st] = n
    return [{**vacancy_out(v), "applications": {**counts[v.id], "total": sum(counts[v.id].values())}} for v in vs]


def _reveal(db: Session, co: Company, apps: list[Application]) -> None:
    """Журнал: одна запись contacts_revealed на отклик. Атомарный UPDATE … WHERE contacts_revealed_at IS NULL берёт
    блокировку строки, поэтому из параллельных просмотров запись пишет только первый."""
    if not apps:
        return
    rows = db.execute(
        update(Application)
        .where(Application.id.in_([a.id for a in apps]), Application.contacts_revealed_at.is_(None))
        .values(contacts_revealed_at=_now())
        .returning(Application.id, Application.candidate_id, Application.vacancy_id)
        .execution_options(synchronize_session=False)
    ).all()
    for aid, cid, vid in rows:
        db.add(AuditLog(actor_user_id=co.user_id, action="contacts_revealed", subject_candidate_id=cid,
                        detail={"application_id": aid, "vacancy_id": vid, "basis": "application"}))
    db.commit()


def _shown(a: Application) -> bool:
    """Контакты по основанию «отклик»: пока отклик не отозван, согласие на обработку ПДн не отозвано и компании нет
    в «скрыть профиль от» кандидата (may_talk — то же правило, что у чата)."""
    return a.status != "withdrawn" and may_talk(a.candidate, a.vacancy.company)


def _employer_row(a: Application, v: Vacancy) -> dict:
    c = a.candidate
    consent = matching.consent_ok(c, "processing")  # отозвал согласие (или не подтвердил новую редакцию) на обработку — ни карточки, ни контактов
    return {
        "id": a.id,
        "status": a.status,
        "note": a.note,
        "reason": catalog.DECLINE_REASONS.get(a.decline_reason),
        "created_at": a.created_at,
        "seen_at": a.seen_at,
        "responded_at": a.responded_at,
        "hidden": not consent,
        "candidate": matching.card(c, need=v) if consent else None,
        "contacts": {"name": c.name, "email": c.email, "tg": c.tg} if _shown(a) else None,
    }


@router.get("/{vacancy_id}/applications")
def vacancy_applications(vacancy_id: int, co: Company = Depends(current_company), db: Session = Depends(get_db)):
    v = _own_vacancy(db, co, vacancy_id)
    apps = db.scalars(
        select(Application)
        .where(Application.vacancy_id == v.id)
        .options(selectinload(Application.candidate).selectinload(Candidate.achievements), selectinload(Application.candidate).selectinload(Candidate.accounts))
        .order_by(Application.created_at.desc(), Application.id.desc())
    ).all()
    _reveal(db, co, [a for a in apps if _shown(a)])
    chat = peers_linked(db, "employer", co.id, [a.candidate_id for a in apps])
    items = [{**_employer_row(a, v), "chat_peer": a.candidate.public_id if a.candidate_id in chat and may_talk(a.candidate, co) else None} for a in apps]
    return {"vacancy": vacancy_out(v), "items": items}


class AppStatusIn(BaseModel):
    status: str
    reason: str | None = None


@router.post("/applications/{application_id}/status")
def set_application_status(application_id: int, body: AppStatusIn, co: Company = Depends(active_company), db: Session = Depends(get_db)):
    if body.status not in EMPLOYER_MOVES:
        raise HTTPException(422, f"Статус: один из {', '.join(EMPLOYER_MOVES)}")
    if body.status == "declined" and body.reason not in catalog.DECLINE_REASONS:
        raise HTTPException(422, f"Причина отказа: одна из {', '.join(catalog.DECLINE_REASONS)}")
    a = _lock(db, Application, application_id)  # кандидат может отзывать отклик параллельно
    if not a or a.vacancy.company_id != co.id:
        raise HTTPException(404, "Отклик не найден")
    if a.status not in EMPLOYER_MOVES[body.status]:
        raise HTTPException(409, f"Нельзя перевести отклик из «{a.status}» в «{body.status}»")
    now = _now()
    a.status, a.seen_at = body.status, a.seen_at or now
    if body.status != "seen":
        a.responded_at = now
        a.decline_reason = body.reason if body.status == "declined" else None
    db.commit()
    return _employer_row(a, a.vacancy)


# ---------- кандидат ----------


@router.get("")
def list_vacancies(
    spec: str | None = None,
    track: str | None = None,
    grade: str | None = None,
    format: str | None = None,
    city: str | None = None,
    q: str | None = Query(default=None, max_length=100),
    salary_min: int | None = Query(default=None, ge=0),
    limit: int = Query(50, ge=1, le=200),
    c: Candidate | None = Depends(maybe_candidate),
    db: Session = Depends(get_db),
):
    """Открытые вакансии. Кандидату — по убыванию соответствия, остальным — сначала новые."""
    stmt = select(Vacancy).join(Company).where(Vacancy.status == "open", Company.blocked_at.is_(None)).options(selectinload(Vacancy.company))
    for col, val in ((Vacancy.spec, spec), (Vacancy.track, track), (Vacancy.grade, grade), (Vacancy.format, format), (Vacancy.city, city)):
        if val:
            stmt = stmt.where(col == val)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Vacancy.title.ilike(like), Vacancy.description.ilike(like)))
    if salary_min:
        stmt = stmt.where(Vacancy.salary_to >= salary_min)
    vs = db.scalars(stmt.order_by(Vacancy.created_at.desc(), Vacancy.id.desc())).all()
    applied = {}
    if c:
        applied = dict(db.execute(select(Application.vacancy_id, Application.status).where(Application.candidate_id == c.id)).all())
    items = [vacancy_out(v, c, applied.get(v.id)) for v in vs]
    if c:
        # ponytail: сортировка в памяти по всем открытым вакансиям; предрасчёт соответствия, если вакансий станут тысячи
        items.sort(key=lambda x: -(x["fit"] if x["fit"] is not None else -1))
    return {"items": items[:limit], "total": len(items), "sort": "fit" if c else "new"}


def _app_limit(db: Session, c: Candidate) -> tuple[int, datetime | None]:
    """Отклики за скользящие 7 дней (включая отозванные) и когда освободится место."""
    since = _now() - timedelta(days=7)
    times = db.scalars(select(Application.created_at).where(Application.candidate_id == c.id, Application.created_at >= since).order_by(Application.created_at)).all()
    free_at = times[0] + timedelta(days=7) if len(times) >= catalog.APPLICATIONS_PER_WEEK else None
    return len(times), free_at


def _cand_row(a: Application) -> dict:
    return {
        "id": a.id,
        "status": a.status,
        "note": a.note,
        "reason": catalog.DECLINE_REASONS.get(a.decline_reason),
        "created_at": a.created_at,
        "seen_at": a.seen_at,
        "responded_at": a.responded_at,
        "vacancy": vacancy_out(a.vacancy),
    }


@router.get("/applications/mine")
def my_applications(c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    apps = db.scalars(
        select(Application).where(Application.candidate_id == c.id)
        .options(selectinload(Application.vacancy).selectinload(Vacancy.company))
        .order_by(Application.created_at.desc(), Application.id.desc())
    ).all()
    used, free_at = _app_limit(db, c)
    chat = peers_linked(db, "candidate", c.id, [a.vacancy.company_id for a in apps])
    items = [{**_cand_row(a), "chat_peer": a.vacancy.company_id if a.vacancy.company_id in chat and may_talk(c, a.vacancy.company) else None} for a in apps]
    return {"items": items, "limit": {"used": used, "max": catalog.APPLICATIONS_PER_WEEK, "free_at": free_at}}


@router.post("/applications/{application_id}/withdraw")
def withdraw(application_id: int, c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    a = _lock(db, Application, application_id)  # работодатель может ответить параллельно
    if not a or a.candidate_id != c.id:
        raise HTTPException(404, "Отклик не найден")
    if a.status not in OPEN_APP:
        raise HTTPException(409, "Отозвать можно только отклик без ответа")
    a.status, a.responded_at = "withdrawn", _now()
    db.commit()
    return _cand_row(a)


@router.get("/{vacancy_id}")
def get_vacancy(vacancy_id: int, c: Candidate | None = Depends(maybe_candidate), db: Session = Depends(get_db)):
    v = db.get(Vacancy, vacancy_id)
    if not v or v.company.blocked_at:
        raise HTTPException(404, "Вакансия не найдена")
    applied = db.scalar(select(Application.status).where(Application.vacancy_id == v.id, Application.candidate_id == c.id)) if c else None
    return vacancy_out(v, c, applied)


class ApplyIn(BaseModel):
    note: str | None = Field(default=None, max_length=300)


@router.post("/{vacancy_id}/apply")
def apply(vacancy_id: int, body: ApplyIn, c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    # блокировки в стабильном порядке (вакансия, затем кандидат); все проверки — после них, на свежих данных
    v = _lock(db, Vacancy, vacancy_id)
    if not v:
        raise HTTPException(404, "Вакансия не найдена")
    c = _lock(db, Candidate, c.id)
    if not matching.consent_ok(c, "processing"):
        raise HTTPException(403, "Нужно согласие на обработку персональных данных: при отклике контакты увидит работодатель")
    if c.theta is None:
        raise HTTPException(403, "Откликаться можно после теста: работодатель видит категорию и результат")
    if v.status != "open" or v.company.blocked_at:
        raise HTTPException(409, "Вакансия закрыта")
    if db.scalar(select(Application.id).where(Application.vacancy_id == v.id, Application.candidate_id == c.id)):
        raise HTTPException(409, "Вы уже откликались на эту вакансию")
    used, free_at = _app_limit(db, c)
    if free_at:
        when = free_at.astimezone(MSK).strftime("%d.%m %H:%M")
        raise HTTPException(429, f"Не больше {catalog.APPLICATIONS_PER_WEEK} откликов за 7 дней — так работодатели внимательнее читают каждый. Следующий отклик — после {when} МСК")
    a = Application(vacancy_id=v.id, candidate_id=c.id, note=(body.note or "").strip() or None, status="sent")
    db.add(a)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Вы уже откликались на эту вакансию") from None
    # ponytail: уведомление работодателю не отправляется; очередь + почта, когда появится SMTP
    return _cand_row(a)
