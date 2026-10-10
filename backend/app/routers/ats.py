"""Интеграция с ATS: ключи API в кабинете работодателя и входящий API /api/ats/v1 (ключ в X-Api-Key).

Ключ — «fsp_…», в БД только sha256; у каждого ключа области (services/ats.SCOPES). Через API работодатель видит и делает
ровно то же, что в кабинете: вакансии по external_id (PUT идемпотентен), статус отклика, отметка по принятому приглашению.
Лента событий (outbox) хранит только id и статусы; анонимная карточка и контакты собираются при чтении по текущим правилам
кабинета (согласие, «скрыть от», блок компании), поэтому отозванное согласие и удалённый кандидат не утекают из старых событий.
"""

import re
import secrets
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query
from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, Text, cast, func, select, tuple_
from sqlalchemy.orm import Session, selectinload

from app import catalog, deps
from app.db import get_db
from app.models import Application, ApiKey, AtsLink, AuditLog, Candidate, Company, Invitation, OutboxEvent, Vacancy
from app.routers import employer, vacancies
from app.services import ats, matching
from app.services.chat import may_talk

keys_router = APIRouter(prefix="/api/employer/api-keys", tags=["ats"])
router = APIRouter(prefix="/api/ats/v1", tags=["ats"])

KEY_LIMIT = 10  # активных ключей на компанию


def _now() -> datetime:
    return datetime.now(UTC)


# ---------- ключи в кабинете ----------


def _key_out(k: ApiKey) -> dict:
    return {"id": k.id, "name": k.name, "prefix": k.prefix, "scopes": k.scopes, "created_at": k.created_at,
            "last_used_at": k.last_used_at, "revoked_at": k.revoked_at}


class KeyIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    scopes: list[str] = Field(min_length=1)


@keys_router.get("")
def list_keys(co: Company = Depends(deps.current_company), db: Session = Depends(get_db)):
    ks = db.scalars(select(ApiKey).where(ApiKey.company_id == co.id).order_by(ApiKey.id.desc())).all()
    return {"items": [_key_out(k) for k in ks], "scopes": ats.SCOPES}


@keys_router.post("")
def issue_key(body: KeyIn, co: Company = Depends(deps.active_company), db: Session = Depends(get_db)):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "Укажите название ключа")
    bad = [s for s in body.scopes if s not in ats.SCOPES]
    if bad:
        raise HTTPException(422, f"Неизвестная область: {', '.join(bad)}. Доступны: {', '.join(ats.SCOPES)}")
    vacancies._lock(db, Company, co.id)  # параллельные выпуски не пробьют лимит
    active = db.scalars(select(ApiKey.id).where(ApiKey.company_id == co.id, ApiKey.revoked_at.is_(None))).all()
    if len(active) >= KEY_LIMIT:
        db.rollback()
        raise HTTPException(409, f"Уже {KEY_LIMIT} активных ключей — отзовите ненужный")
    key = "fsp_" + secrets.token_urlsafe(32)
    k = ApiKey(company_id=co.id, name=name, key_hash=deps.hash_secret(key), prefix=key[:12],
               scopes=list(dict.fromkeys(body.scopes)))
    db.add(k)
    db.flush()
    db.add(AuditLog(actor_user_id=co.user_id, action="api_key_issued", detail={"key_id": k.id, "company_id": co.id}))
    db.commit()
    return {**_key_out(k), "key": key}  # открытый ключ — только в этом ответе


@keys_router.delete("/{key_id}")
def revoke_key(key_id: int, co: Company = Depends(deps.current_company), db: Session = Depends(get_db)):
    k = db.get(ApiKey, key_id)
    if not k or k.company_id != co.id:
        raise HTTPException(404, "Ключ не найден")
    if not k.revoked_at:
        k.revoked_at = _now()
        db.add(AuditLog(actor_user_id=co.user_id, action="api_key_revoked", detail={"key_id": k.id, "company_id": co.id}))
        db.commit()
    return _key_out(k)


# ---------- входящий API ----------


def _auth(*need: str, blocked_ok: bool = False):
    """Зависимость: ключ из X-Api-Key → (ключ, компания). Нужна хотя бы одна из областей need;
    записывающие запросы заблокированной компании закрыты, как в кабинете (deps.active_company), кроме blocked_ok
    (закрыть вакансию можно всегда: это сужает показ, в кабинете close_vacancy тоже на current_company)."""

    def dep(x_api_key: str = Header(default=""), db: Session = Depends(get_db)) -> tuple[ApiKey, Company]:
        k = db.scalar(select(ApiKey).where(ApiKey.key_hash == deps.hash_secret(x_api_key))) if x_api_key else None
        if not k or k.revoked_at:
            raise HTTPException(401, "Неверный ключ API")
        if not set(need) & set(k.scopes or []):
            raise HTTPException(403, "У ключа нет доступа: " + " или ".join(need))
        co = db.get(Company, k.company_id)
        if need[0].endswith(":write") and co.blocked_at and not blocked_ok:
            raise HTTPException(403, deps.BLOCKED)
        k.last_used_at = _now()
        db.commit()
        return k, co

    return dep


def _link(db: Session, co: Company, external_id: str) -> AtsLink | None:
    return db.scalar(select(AtsLink).where(AtsLink.company_id == co.id, AtsLink.entity == "vacancy", AtsLink.external_id == external_id))


def _linked_vacancy_id(db: Session, co: Company, external_id: str) -> int:
    link = _link(db, co, external_id)
    if not link:
        raise HTTPException(404, "Вакансия не найдена")
    return link.internal_id


@router.put("/vacancies/{external_id}")
def put_vacancy(body: vacancies.VacancyIn, external_id: str = Path(min_length=1, max_length=128), ka: tuple = Depends(_auth("vacancies:write")), db: Session = Depends(get_db)):
    """Создаёт вакансию или полностью заменяет поля уже связанной. Связь пишется в той же транзакции, что и вакансия."""
    co = ka[1]
    vacancies._lock(db, Company, co.id)  # два PUT с одним external_id идут по очереди: дублей не будет
    link = _link(db, co, external_id)
    v = db.get(Vacancy, link.internal_id) if link else None
    if v and v.company_id == co.id:
        for k, val in body.model_dump().items():
            setattr(v, k, val)
        try:
            warnings = vacancies._validate(v)
        except HTTPException:
            db.rollback()
            raise
        v.updated_at = _now()
        db.commit()
    else:
        v = Vacancy(company_id=co.id, **body.model_dump())
        v.company = co
        try:
            warnings = vacancies._validate(v)
        except HTTPException:
            db.rollback()
            raise
        vacancies._check_limit(db, co)
        db.add(v)
        db.flush()
        if link:  # защитная ветка: в приложении вакансии не удаляются, но связь не должна висеть на пустом месте — переносим на новую
            link.internal_id = v.id
        else:
            db.add(AtsLink(company_id=co.id, entity="vacancy", external_id=external_id, internal_id=v.id))
        db.commit()
    return {**vacancies.vacancy_out(v), "warnings": warnings, "external_id": external_id}


@router.post("/vacancies/{external_id}/close")
def close_vacancy(external_id: str = Path(min_length=1, max_length=128), ka: tuple = Depends(_auth("vacancies:write", blocked_ok=True)), db: Session = Depends(get_db)):
    return vacancies.close_vacancy(_linked_vacancy_id(db, ka[1], external_id), ka[1], db)


@router.post("/vacancies/{external_id}/extend")
def extend_vacancy(external_id: str = Path(min_length=1, max_length=128), ka: tuple = Depends(_auth("vacancies:write")), db: Session = Depends(get_db)):
    return vacancies.extend_vacancy(_linked_vacancy_id(db, ka[1], external_id), ka[1], db)


@router.post("/applications/{application_id}/status")
def application_status(application_id: int, body: vacancies.AppStatusIn, ka: tuple = Depends(_auth("applications:write")), db: Session = Depends(get_db)):
    co = ka[1]
    a = db.get(Application, application_id)
    if a and a.vacancy.company_id == co.id and a.status == body.status and body.status in vacancies.EMPLOYER_MOVES:
        # повтор того же статуса — не ошибка: ATS ретраит запросы. Причину проверяем как при первом вызове
        if body.status == "declined":
            if body.reason not in catalog.DECLINE_REASONS:
                raise HTTPException(422, f"Причина отказа: одна из {', '.join(catalog.DECLINE_REASONS)}")
            if body.reason != a.decline_reason:
                raise HTTPException(409, "Отклик уже отклонён с другой причиной")
        if vacancies._shown(a):
            vacancies._reveal(db, co, [a])  # контакты отдаём только с записью в журнале (идемпотентно)
        return vacancies._employer_row(a, a.vacancy)
    return vacancies.set_application_status(application_id, body, co, db)


@router.post("/invites/{invite_id}/feedback")
def invite_feedback(invite_id: int, body: employer.FeedbackIn, ka: tuple = Depends(_auth("invites:write")), db: Session = Depends(get_db)):
    co = ka[1]
    inv = db.get(Invitation, invite_id)
    if inv and inv.company_id == co.id and inv.status == "accepted" and inv.feedback == body.value:
        return employer._row(inv)  # повтор той же отметки
    return employer.feedback(invite_id, body, co, db)


# ---------- лента событий ----------


def _enrich(db: Session, co: Company, events: list[OutboxEvent]) -> list[dict]:
    """data = payload + то, что работодатель сейчас видит в кабинете. ПДн в самих событиях нет; ссылки на удалённое — None.
    ponytail: сущности подгружаются пачкой на страницу ленты (до 500); кэш карточек, если ATS начнёт опрашивать чаще раза в секунду."""
    app_ids = {e.payload["application_id"] for e in events if e.type.startswith("application.")}
    inv_ids = {e.payload["invitation_id"] for e in events if e.type.startswith("invitation.")}
    cand_opts = (selectinload(Candidate.achievements), selectinload(Candidate.accounts))
    apps = {a.id: a for a in db.scalars(select(Application).where(Application.id.in_(app_ids)).options(selectinload(Application.candidate).options(*cand_opts)))}
    invs = {i.id: i for i in db.scalars(select(Invitation).where(Invitation.id.in_(inv_ids), Invitation.company_id == co.id).options(selectinload(Invitation.candidate).options(*cand_opts)))}
    vac_ids = {e.payload["vacancy_id"] for e in events if e.type.startswith("application.")}
    vacs = {v.id: v for v in db.scalars(select(Vacancy).where(Vacancy.id.in_(vac_ids), Vacancy.company_id == co.id))}
    ext = dict(db.execute(select(AtsLink.internal_id, AtsLink.external_id).where(AtsLink.company_id == co.id, AtsLink.entity == "vacancy")).all())

    def visible(c: Candidate) -> bool:
        return matching.consent_ok(c, "processing") and co.inn not in (c.hidden_from or [])

    # контакты отдаются только с записью в журнале: принятый при недействующем согласии отклик мог раскрыться позже
    vacancies._reveal(db, co, [a for a in apps.values() if a.vacancy.company_id == co.id and vacancies._shown(a)])
    out = []
    for e in events:
        d = dict(e.payload)
        if e.type.startswith("application."):
            a, v = apps.get(d["application_id"]), vacs.get(d["vacancy_id"])
            if a and a.vacancy.company_id != co.id:
                a = None
            d["vacancy"] = {"id": d["vacancy_id"], "title": v.title if v else None, "external_id": ext.get(d["vacancy_id"])}
            d["candidate"] = matching.card(a.candidate, need=v) if a and v and visible(a.candidate) else None
            d["contacts"] = None
            if a and vacancies._shown(a):
                c = a.candidate
                d["contacts"] = {"name": c.name, "email": c.email, "tg": c.tg}
        elif e.type.startswith("invitation."):
            i = invs.get(d["invitation_id"])
            d["invitation"] = None
            d["candidate"] = d["contacts"] = None
            if i:
                c = i.candidate
                d["invitation"] = {"id": i.id, "role": i.role, "salary_from": i.salary_from, "salary_to": i.salary_to,
                                   "status": i.status, "feedback": i.feedback}
                d["candidate"] = {"public_id": c.public_id}  # карточка — через /api/employer/candidates/{public_id} с её правилами видимости
                if i.status == "accepted" and may_talk(c, co):
                    d["contacts"] = {"name": c.name, "email": c.email, "tg": c.tg}
        out.append({"id": e.id, "type": e.type, "at": e.at, "data": d})
    return out


def _cursor(after: str) -> tuple[int, int]:
    """Курсор ленты «txid.id» (непрозрачная строка из next); «0» — с начала."""
    if after == "0":
        return 0, 0
    if not re.fullmatch(r"\d{1,19}\.\d{1,19}", after):
        raise HTTPException(422, "Курсор after — строка из поля next предыдущего ответа (или 0 для чтения с начала)")
    txid, eid = after.split(".")
    return int(txid), int(eid)


@router.get("/events")
def events(after: str = Query("0", max_length=40), limit: int = Query(100, ge=1, le=500),
           ka: tuple = Depends(_auth(*ats.READ_SCOPES)), db: Session = Depends(get_db)):
    k, co = ka
    cur = _cursor(after)
    matching.expire_invites(db, company_id=co.id)  # истечение ленивое: без этого ATS не получит invitation.expired; коммитит — события уже в базе
    types = [t for t, s in ats.EVENTS.items() if s is None or s in k.scopes]
    # Лента отдаёт только события завершённых транзакций: у любой ещё идущей транзакции xid >= xmin снимка, поэтому её события
    # лягут после курсора (txid, id), когда закоммитятся, и ATS их не пропустит, хотя id у них может быть меньше уже отданных.
    # ponytail: долгая посторонняя транзакция в базе задерживает (не теряет) события всех компаний; вебхуки/доставщик — table.md.
    xmin = cast(cast(func.pg_snapshot_xmin(func.pg_current_snapshot()), Text), BigInteger)
    rows = db.scalars(
        select(OutboxEvent).where(OutboxEvent.company_id == co.id, OutboxEvent.txid < xmin,
                                  tuple_(OutboxEvent.txid, OutboxEvent.id) > tuple_(*cur), OutboxEvent.type.in_(types))
        .order_by(OutboxEvent.txid, OutboxEvent.id).limit(limit)
    ).all()
    return {"items": _enrich(db, co, rows), "next": f"{rows[-1].txid}.{rows[-1].id}" if rows else after}
