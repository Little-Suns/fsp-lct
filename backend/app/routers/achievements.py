"""Внешние достижения кандидата: ФСП, хакатоны, Codeforces, CTFtime.

Привязка внешних профилей — только при отдельном согласии consent_external (152-ФЗ).
Сбой внешнего API → 502 с понятным текстом; данные в БД при этом не меняются.
"""

import json
import os
import secrets
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload
from starlette.concurrency import run_in_threadpool

from app.db import get_db
from app.deps import current_candidate, current_user, hash_secret
from app.integrations import codeforces, common, ctftime, hackathons
from app.integrations.consent import lock_candidate, set_external_consent
from app.integrations.scoring import combine
from app.models import Achievement, AuditLog, Candidate, Event, ExternalAccount
from app.services.matching import consent_ok

router = APIRouter(prefix="/api/achievements", tags=["achievements"])

VERIFY_ATTEMPTS = 5  # проверок на один код CF; новый код (link) сбрасывает счётчик
CACHE_TTL = timedelta(hours=1)  # не дёргаем внешний API чаще раза в час на аккаунт
MAX_UPLOAD = 2 * 1024 * 1024  # байт: CSV или JSON протокола
EVENT_FIELDS = ("source", "external_id", "title", "level", "date", "participants", "url", "tags")


class ConsentIn(BaseModel):
    value: bool = True


class CfLinkIn(BaseModel):
    handle: str


class CtfLinkIn(BaseModel):
    team_id: int
    role: str | None = None  # роль в команде со слов кандидата: pwn, web, капитан…


@contextmanager
def _upstream(db: Session):
    try:
        yield
    except common.ExternalError as e:
        db.rollback()
        raise HTTPException(502, str(e)) from e


def _account(db: Session, cand: Candidate, provider: str) -> ExternalAccount | None:
    return db.scalar(select(ExternalAccount).where(ExternalAccount.candidate_id == cand.id, ExternalAccount.provider == provider))


def _need_consent(cand: Candidate) -> None:
    if not consent_ok(cand, "external"):
        raise HTTPException(403, "Нужно действующее согласие на обработку данных внешних профилей "
                                 "в текущей редакции (POST /api/achievements/consent)")


def _snap(acc: ExternalAccount) -> tuple:
    """Отпечаток привязки до HTTP: перепривязка или новый код за время запроса его меняют."""
    key = acc.verify_code if acc.provider == "codeforces" else (acc.data or {}).get("team_id")
    return acc.id, acc.provider, acc.handle, key


def _recheck(db: Session, cand: Candidate, snap: tuple | None = None) -> ExternalAccount | None:
    """После внешнего HTTP и перед записью: FOR UPDATE на кандидата, перепроверка согласия и привязки.

    Согласие отозвано → 409; привязка удалена или изменилась (сравнение с _snap до HTTP) → 409. Ничего не пишем.
    Link/отзыв согласия тоже берут FOR UPDATE на кандидата, поэтому после проверки до commit привязка не изменится.
    """
    locked = lock_candidate(db, cand.id)
    if not locked or not consent_ok(locked, "external"):
        db.rollback()
        raise HTTPException(409, "Согласие на внешние данные отозвано — данные не сохранены")
    if snap is None:
        return None
    acc = db.get(ExternalAccount, snap[0], populate_existing=True)
    if acc is None or _snap(acc) != snap:
        db.rollback()
        raise HTTPException(409, "Привязка изменилась во время проверки — повторите")
    return acc


def _fresh(acc: ExternalAccount) -> bool:
    return bool(acc.fetched_at and datetime.now(UTC) - acc.fetched_at < CACHE_TTL)


def _ach(a: Achievement) -> dict:
    ev = a.event
    return {
        "id": a.id, "source": a.source, "title": a.title, "place": a.place, "team": a.team, "role": a.role,
        "weight": a.weight, "verified": a.verified, "event_id": a.event_id,
        "level": ev.level if ev else None, "date": ev.date if ev else None,
        "participants": ev.participants if ev else None, "url": ev.url if ev else None,
    }


def profile(db: Session, cand: Candidate) -> dict:
    """Форма для экрана профиля: блоки по источникам + сводный сигнал (scoring.combine)."""
    achs = db.scalars(
        select(Achievement).where(Achievement.candidate_id == cand.id)
        .options(selectinload(Achievement.event)).order_by(Achievement.weight.desc())
    ).all()
    by = lambda src: [_ach(a) for a in achs if a.source == src]  # noqa: E731
    cf, ct = _account(db, cand, "codeforces"), _account(db, cand, "ctftime")
    return {
        "consent_external": cand.consent_external,
        "fsp": by("fsp"),
        "hackathons": by("hackathon"),
        "codeforces": cf and {
            "handle": cf.handle, "rating": cf.rating, "rank": cf.rank, "max_rating": (cf.data or {}).get("max_rating"),
            "verified": cf.verified_at is not None, "fetched_at": cf.fetched_at,  # код отдаётся только в ответе link
            "achievements": by("codeforces"),
        },
        "ctftime": ct and {
            "team_id": (ct.data or {}).get("team_id"), "team": (ct.data or {}).get("team"), "role": (ct.data or {}).get("role"),
            "rating": ct.rating, "rank": ct.rank, "verified": False, "fetched_at": ct.fetched_at,
            "achievements": by("ctftime"),
        },
        "signal": combine([a.weight for a in achs]),
    }


@router.get("")
def my_achievements(cand: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    return profile(db, cand)


@router.post("/consent")
def set_consent(body: ConsentIn, cand: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    """Дать / отозвать согласие. Отзыв удаляет привязки CF/CTFtime и полученные из них достижения."""
    set_external_consent(db, cand, body.value)
    db.commit()
    return {"consent_external": cand.consent_external}


# --- Codeforces ---


def _cf_owned_by_other(db: Session, cand: Candidate, handle: str) -> None:
    """Один хэндл CF — один подтверждённый владелец; неподтверждённых заявок может быть несколько."""
    if db.scalar(select(ExternalAccount.id).where(
        ExternalAccount.provider == "codeforces", func.lower(ExternalAccount.handle) == handle.lower(),
        ExternalAccount.candidate_id != cand.id, ExternalAccount.verified_at.is_not(None),
    )):
        raise HTTPException(409, "Этот аккаунт Codeforces уже подтверждён другим пользователем")


@router.post("/codeforces/link")
def cf_link(body: CfLinkIn, cand: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    """Выдать новый код подтверждения. Открытый код — только в этом ответе; в БД — sha256, живёт 24 ч."""
    _need_consent(cand)
    handle = body.handle.strip()
    if not codeforces.HANDLE_RE.match(handle):
        raise HTTPException(422, "Некорректный хэндл Codeforces")
    _recheck(db, cand)  # FOR UPDATE на кандидата + согласие: параллельный отзыв не оставит привязку
    _cf_owned_by_other(db, cand, handle)
    acc = _account(db, cand, "codeforces")
    if acc and acc.handle.lower() != handle.lower():
        db.execute(delete(Achievement).where(Achievement.candidate_id == cand.id, Achievement.source == "codeforces"))
        acc.handle, acc.verified_at, acc.rating, acc.rank, acc.data, acc.fetched_at = handle, None, None, None, None, None
    elif not acc:
        acc = ExternalAccount(candidate_id=cand.id, provider="codeforces", handle=handle, verify_code="")
        db.add(acc)
    code = codeforces.new_code()  # каждый link — новый код, прежний перестаёт действовать
    acc.verify_code, acc.verify_expires_at = hash_secret(code), datetime.now(UTC) + codeforces.CODE_TTL
    acc.verify_attempts = 0
    db.commit()
    return {
        "handle": acc.handle, "code": code, "expires_at": acc.verify_expires_at, "verified": acc.verified_at is not None,
        "instructions": f"Откройте codeforces.com/settings/social, впишите {code} в поле «Организация» "
                        f"(или в «Имя»), сохраните и нажмите «Проверить» в течение 24 часов. После проверки код можно убрать.",
    }


@router.post("/codeforces/verify")
def cf_verify(cand: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    _need_consent(cand)
    acc = _account(db, cand, "codeforces")
    if not acc:
        raise HTTPException(404, "Сначала укажите хэндл Codeforces")
    if cand.is_synthetic:  # выдуманные хэндлы синтетики (dorlov) во внешние API не отправляем
        return profile(db, cand)
    if not acc.verify_code:
        if acc.verified_at:
            return profile(db, cand)  # уже подтверждён, код стёрт
        raise HTTPException(400, "Запросите код подтверждения: POST /api/achievements/codeforces/link")
    if not acc.verify_expires_at or acc.verify_expires_at < datetime.now(UTC):
        raise HTTPException(400, "Код истёк — запросите новый")
    snap = _snap(acc)  # (id, provider, handle, хеш кода) на момент чтения
    _cf_owned_by_other(db, cand, acc.handle)
    # атомарное списание попытки только для той же привязки и того же кода: новый код (перепривязка) попытку не теряет
    took = db.execute(
        update(ExternalAccount)
        .where(ExternalAccount.id == snap[0], ExternalAccount.handle == snap[2], ExternalAccount.verify_code == snap[3],
               ExternalAccount.verify_attempts < VERIFY_ATTEMPTS)
        .values(verify_attempts=ExternalAccount.verify_attempts + 1)
        .returning(ExternalAccount.id)
    ).first()
    if not took:
        fresh = db.get(ExternalAccount, snap[0], populate_existing=True)
        changed = fresh is None or _snap(fresh) != snap
        db.rollback()
        if changed:
            raise HTTPException(409, "Привязка изменилась — повторите")
        raise HTTPException(429, "Слишком много проверок — получите новый код")
    db.commit()
    try:
        with _upstream(db):
            info = codeforces.user_info(acc.handle)
            if not codeforces.code_found(info, acc.verify_code):
                org = info.get("organization") or "пусто"
                raise HTTPException(400, f"Код не найден в профиле {acc.handle}: в поле «Организация» сейчас «{org}». "
                                         "Изменения на Codeforces могут появиться в API через минуту")
            info, history = codeforces.fetch(acc.handle, info)
        acc = _recheck(db, cand, snap)
        acc.verified_at = datetime.now(UTC)
        acc.verify_code, acc.verify_expires_at = "", None  # одноразовый: после проверки стираем
        codeforces.apply(db, acc, info, history)
        db.commit()
    except IntegrityError:
        # гонка: другой кандидат подтвердил тот же хэндл между проверкой и записью (индекс uq_cf_verified_owner)
        db.rollback()
        raise HTTPException(409, "Этот аккаунт Codeforces уже подтверждён другим пользователем") from None
    return profile(db, cand)


@router.post("/codeforces/refresh")
def cf_refresh(cand: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    _need_consent(cand)
    acc = _account(db, cand, "codeforces")
    if not acc or not acc.verified_at:
        raise HTTPException(404, "Аккаунт Codeforces не привязан или не подтверждён")
    if not _fresh(acc) and not cand.is_synthetic:
        snap = _snap(acc)
        with _upstream(db):
            info, history = codeforces.fetch(acc.handle)
        codeforces.apply(db, _recheck(db, cand, snap), info, history)
        db.commit()
    return profile(db, cand)


# --- CTFtime ---


@router.post("/ctftime/link")
def ctf_link(body: CtfLinkIn, cand: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    _need_consent(cand)
    fetched = None
    if not cand.is_synthetic:
        with _upstream(db):
            fetched = ctftime.fetch(body.team_id)  # сначала HTTP, в БД ничего не пишем
    _recheck(db, cand)
    acc = _account(db, cand, "ctftime")
    handle = str(body.team_id)  # одну команду могут привязать все её участники: уникальность (provider, handle, candidate_id)
    if acc and acc.handle != handle:
        db.execute(delete(Achievement).where(
            Achievement.candidate_id == cand.id, Achievement.source == "ctftime", Achievement.verified.is_(False)))
    if not acc:
        acc = ExternalAccount(candidate_id=cand.id, provider="ctftime", handle=handle, verify_code="")
        db.add(acc)
    acc.handle, acc.fetched_at = handle, None
    acc.data = {"team_id": body.team_id, "role": body.role}
    db.flush()
    if fetched:
        ctftime.apply(db, acc, fetched)
    db.commit()
    return profile(db, cand)


@router.post("/ctftime/refresh")
def ctf_refresh(cand: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    _need_consent(cand)
    acc = _account(db, cand, "ctftime")
    if not acc:
        raise HTTPException(404, "Команда CTFtime не привязана")
    if not _fresh(acc) and not cand.is_synthetic:
        snap = _snap(acc)
        with _upstream(db):
            fetched = ctftime.fetch(int(acc.handle))
        ctftime.apply(db, _recheck(db, cand, snap), fetched)
        db.commit()
    return profile(db, cand)


# --- Импорт протоколов (организатор) ---


def organizer(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> int | None:
    """Организатор: Bearer ORGANIZER_TOKEN из окружения (→ None) или пользователь с ролью admin (→ его id)."""
    token = authorization.removeprefix("Bearer ").strip()
    org = os.environ.get("ORGANIZER_TOKEN", "")
    if org and token and secrets.compare_digest(token, org):
        return None
    user = current_user(authorization, db)  # 401, если токена нет или он неверен/просрочен
    if user.role != "admin":
        raise HTTPException(403, "Импорт протоколов доступен только организатору")
    return user.id


@router.post("/import")
async def import_results(request: Request, db: Session = Depends(get_db), actor: int | None = Depends(organizer)):
    """JSON {event:{...}, rows:[...]} или multipart: поля события + файл file (CSV email,fsp_id,team,place,role)."""
    ctype = request.headers.get("content-type", "")
    try:
        if ctype.startswith("multipart/form-data"):
            form = await request.form()
            upload = form.get("file")
            if upload is None or isinstance(upload, str):
                raise ValueError("Нужен файл протокола в поле file")
            event = {k: form.get(k) for k in EVENT_FIELDS}
            raw = await upload.read(MAX_UPLOAD + 1)
            if len(raw) > MAX_UPLOAD:
                raise HTTPException(413, "Файл протокола больше 2 МБ")
            rows = hackathons.parse_csv(raw.decode("utf-8-sig"))
        else:
            raw = await request.body()
            if len(raw) > MAX_UPLOAD:
                raise HTTPException(413, "Протокол больше 2 МБ")
            body = json.loads(raw)
            if not isinstance(body, dict) or not isinstance(body.get("rows"), list) \
                    or not all(isinstance(r, dict) for r in body["rows"]) or not isinstance(body.get("event"), dict):
                raise ValueError("Ожидается JSON {event: {...}, rows: [{...}]} или multipart с CSV в поле file")
            event, rows = body["event"], body["rows"]
        report = await run_in_threadpool(hackathons.import_protocol, db, event, rows)
        db.add(AuditLog(actor_user_id=actor, action="protocol_imported", detail={
            "event_id": report["event_id"], "matched": report["matched"], "unmatched_count": len(report["unmatched"])}))
        db.commit()
        return report
    except UnicodeDecodeError:
        raise HTTPException(422, "CSV должен быть в UTF-8") from None
    except json.JSONDecodeError:
        raise HTTPException(422, "Тело запроса — не JSON") from None
    except ValueError as e:
        db.rollback()
        raise HTTPException(422, str(e)) from None


@router.get("/events")
def list_events(source: str | None = None, db: Session = Depends(get_db)):
    """Список событий (для жюри/демо): сколько кандидатов платформы в протоколе."""
    q = (select(Event, func.count(Achievement.id)).outerjoin(Achievement, Achievement.event_id == Event.id)
         .group_by(Event.id).order_by(Event.date.desc().nulls_last(), Event.id.desc()))
    if source:
        q = q.where(Event.source == source)
    return [
        {"id": e.id, "source": e.source, "external_id": e.external_id, "title": e.title, "level": e.level, "date": e.date,
         "participants": e.participants, "url": e.url, "tags": e.tags, "candidates": n}
        for e, n in db.execute(q).all()
    ]
