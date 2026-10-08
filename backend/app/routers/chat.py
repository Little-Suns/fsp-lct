"""Внутренний чат между кандидатом и компанией. Правила доступа — в services/chat.py."""

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import desc, func, select, update
from sqlalchemy.orm import Session

from app.db import get_db
from app.deps import current_user
from app.models import Application, Candidate, Company, Invitation, Message, User, Vacancy
from app.routers.vacancies import _reveal, _shown
from app.services import matching
from app.services.chat import MAX_LEN, hub, may_talk, over_rate, peers_linked

router = APIRouter(prefix="/api/chat", tags=["chat"])
KEEPALIVE = 20  # секунд тишины в потоке до служебной строки: держит соединение за прокси и замечает обрыв


def _me(db: Session, user: User) -> tuple[Candidate | None, Company | None]:
    if user.role == "candidate":
        c = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
        if not c:
            raise HTTPException(403, "Профиль кандидата не создан")
        return c, None
    if user.role == "employer":
        co = db.scalar(select(Company).where(Company.user_id == user.id))
        if not co:
            raise HTTPException(403, "Компания не зарегистрирована")
        return None, co
    raise HTTPException(403, "Чат доступен только кандидатам и компаниям")


def _dialog(db: Session, user: User, peer_id: str, *, write: bool) -> tuple[Company, Candidate]:
    """Диалог по peer_id: у кандидата это id компании, у работодателя — публичный id кандидата.
    Работодатель теряет доступ, как только кандидат отозвал согласие на обработку или скрыл профиль (как и к контактам).
    Кандидат не пишет компании, от которой скрыл профиль: она не может ни прочитать, ни ответить."""
    me_c, me_co = _me(db, user)
    if me_c:
        co = db.get(Company, int(peer_id)) if peer_id.isascii() and peer_id.isdigit() and len(peer_id) < 10 else None  # длиннее — не влезет в int4
        if not co:
            raise HTTPException(404, "Компания не найдена")
        cand = me_c
    else:
        cand = db.scalar(select(Candidate).where(Candidate.public_id == peer_id))
        if not cand:
            raise HTTPException(404, "Кандидат не найден")
        co = me_co
    role, self_id, other = (user.role, cand.id, co.id) if me_c else (user.role, co.id, cand.id)
    if not peers_linked(db, role, self_id, [other], active=write):
        raise HTTPException(403, "Нет активной связи для отправки сообщений" if write else "Нет связи для просмотра диалога")
    if me_co and not may_talk(cand, co):
        raise HTTPException(403, "Кандидат закрыл доступ: отозвал согласие или скрыл профиль от компании")
    if me_c and write and not matching.consent_ok(cand, "processing"):
        raise HTTPException(403, "Подтвердите согласие на обработку данных")
    if me_c and write and not may_talk(cand, co):
        raise HTTPException(403, "Вы скрыли профиль от этой компании: она не прочитает сообщение")
    return co, cand


def _cand_label(db: Session, co: Company, cand: Candidate, reveal: list[Application]) -> str:
    """Имя кандидата — только когда оно уже открыто работодателю (принятое приглашение или принятый отклик); иначе публичный id.
    Отклики, по которым имя показано, складываются в reveal: вызывающий пишет их в AuditLog одним _reveal (как список откликов)."""
    accepted = db.scalar(select(Invitation.id).where(Invitation.company_id == co.id, Invitation.candidate_id == cand.id, Invitation.status == "accepted").limit(1))
    apps = db.scalars(
        select(Application).join(Vacancy, Vacancy.id == Application.vacancy_id).where(Vacancy.company_id == co.id, Application.candidate_id == cand.id)
    ).all()
    shown = [a for a in apps if _shown(a)]
    reveal += shown
    return cand.name if accepted or shown else f"Кандидат {cand.public_id}"


def _out(m: Message) -> dict:
    return {"id": m.id, "sender": m.sender, "text": m.text, "created_at": m.created_at, "read_at": m.read_at}


def _dialogs(db: Session, user: User) -> list[tuple[Message, int, Company, Candidate]]:
    """Последнее сообщение каждого диалога + число непрочитанных от собеседника. Работодателю не видны диалоги, которые он не может
    открыть (_dialog): отозваны согласие или отклик, профиль скрыт от компании."""
    me_c, me_co = _me(db, user)
    unread = func.count(Message.id).filter(Message.read_at.is_(None), Message.sender != user.role)
    mine = Message.candidate_id == me_c.id if me_c else Message.company_id == me_co.id
    sub = select(func.max(Message.id).label("last_id"), unread.label("unread")).where(mine).group_by(Message.company_id, Message.candidate_id).subquery()
    rows = db.execute(
        select(Message, sub.c.unread, Company, Candidate)
        .join(sub, Message.id == sub.c.last_id)
        .join(Company, Company.id == Message.company_id)
        .join(Candidate, Candidate.id == Message.candidate_id)
        .order_by(desc(Message.id))
    ).all()
    if me_c:
        return list(rows)
    linked = peers_linked(db, "employer", me_co.id, [c.id for _, _, _, c in rows], active=False)
    return [(m, n, co, c) for m, n, co, c in rows if c.id in linked and may_talk(c, co)]


@router.get("/unread")
def get_unread(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return {"unread_count": sum(n for _, n, _, _ in _dialogs(db, user))}


@router.get("/contacts")
def get_contacts(user: User = Depends(current_user), db: Session = Depends(get_db)):
    employer = user.role == "employer"
    rows, reveal = _dialogs(db, user), []
    # ponytail: имя считается по диалогу отдельным запросом — диалогов у одной стороны десятки; при тысячах — одним JOIN
    out = [
        {
            "peer_id": c.public_id if employer else co.id,
            "peer_name": _cand_label(db, co, c, reveal) if employer else co.name,
            "unread_count": n,
            "last_message": {"id": m.id, "text": m.text, "created_at": m.created_at, "sender": m.sender},
        }
        for m, n, co, c in rows
    ]
    if reveal:
        _reveal(db, rows[0][2], reveal)  # работодатель один: co у всех строк тот же
    return {"contacts": out}


@router.get("/stream")
async def stream(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """SSE: строка «data: new» — у участника появилось что-то новое (сообщение или отметка «прочитано»), клиент перечитывает GET.
    Сессию БД закрываем сразу: поток живёт долго и не должен держать соединение пула."""
    me_c, me_co = await run_in_threadpool(_me, db, user)
    key = ("candidate", me_c.id) if me_c else ("employer", me_co.id)
    db.close()
    entry = hub.subscribe(key)  # до ответа: событие между заголовками и первым кадром не теряется

    async def events():
        try:
            yield ": ok\n\n"
            while not await request.is_disconnected():
                try:
                    await asyncio.wait_for(entry[1].get(), KEEPALIVE)
                    yield "data: new\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            hub.unsubscribe(key, entry)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@router.get("/{peer_id}")
def get_chat(
    peer_id: str,
    limit: int = Query(50, ge=1, le=100),
    before_id: int | None = None,
    after_id: int | None = None,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if before_id is not None and after_id is not None:
        raise HTTPException(422, "Нельзя указывать before_id и after_id одновременно")
    co, cand = _dialog(db, user, peer_id, write=False)
    q = select(Message).where(Message.company_id == co.id, Message.candidate_id == cand.id)
    if after_id is not None:
        msgs = db.scalars(q.where(Message.id > after_id).order_by(Message.id).limit(limit)).all()
    else:
        if before_id is not None:
            q = q.where(Message.id < before_id)
        msgs = list(reversed(db.scalars(q.order_by(desc(Message.id)).limit(limit)).all()))
    reveal: list[Application] = []
    name = _cand_label(db, co, cand, reveal) if user.role == "employer" else co.name
    if reveal:
        _reveal(db, co, reveal)
    role, self_id, other = (user.role, cand.id, co.id) if user.role == "candidate" else (user.role, co.id, cand.id)
    return {
        "peer": {"id": peer_id, "name": name},
        # можно ли ещё писать: иначе фронт прячет поле ввода, а не показывает 403 тостом
        "can_write": bool(peers_linked(db, role, self_id, [other])) and may_talk(cand, co),
        "messages": [_out(m) for m in msgs],
        # есть ли ещё более ранние сообщения: для кнопки «Показать ранее»
        "more": bool(msgs) and after_id is None and db.scalar(select(Message.id).where(Message.company_id == co.id, Message.candidate_id == cand.id, Message.id < msgs[0].id).limit(1)) is not None,
    }


class MessageIn(BaseModel):
    text: str


@router.post("/{peer_id}")
def send_message(peer_id: str, body: MessageIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "Сообщение не может быть пустым")
    if "\x00" in text:
        raise HTTPException(422, "Недопустимый символ в сообщении")
    if len(text) > MAX_LEN:
        raise HTTPException(422, f"Сообщение длиннее {MAX_LEN} символов")
    co, cand = _dialog(db, user, peer_id, write=True)
    if over_rate(db, co.id, cand.id, user.role):
        raise HTTPException(429, "Слишком часто: подождите минуту")
    m = Message(company_id=co.id, candidate_id=cand.id, sender=user.role, text=text)
    db.add(m)
    db.commit()
    db.refresh(m)
    hub.ping_dialog(co.id, cand.id)
    return _out(m)


@router.post("/{peer_id}/read")
def mark_read(peer_id: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    co, cand = _dialog(db, user, peer_id, write=False)
    db.execute(
        update(Message)
        .where(Message.company_id == co.id, Message.candidate_id == cand.id, Message.sender != user.role, Message.read_at.is_(None))
        .values(read_at=datetime.now(UTC))
    )
    db.commit()
    hub.ping_dialog(co.id, cand.id)
    return {"ok": True}
