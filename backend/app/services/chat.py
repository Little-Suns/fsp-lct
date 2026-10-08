"""Внутренний чат: кто с кем может переписываться.

Писать можно, пока есть живая связь: приглашение принято кандидатом или отклик принят компанией — контакты в этот
момент уже открыты, чат их не расширяет. Отклик без ответа чата не открывает: иначе фиктивная вакансия выспросила бы
контакты в переписке. Читать историю кандидату — пока есть любая связь (приглашение или отклик), чтобы диалог не исчезал.
Работодателю — только пока ему открыты контакты: принятое приглашение или принятый отклик (как `vacancies._shown`)."""

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Application, Candidate, Company, Invitation, Message, Vacancy
from app.services import matching

MAX_LEN = 2000
RATE_LIMIT = 20  # сообщений в минуту от одной стороны в одном диалоге


def peers_linked(db: Session, role: str, self_id: int, peer_ids: list[int], *, active: bool = True) -> set[int]:
    """Какие из peer_ids связаны с участником. role — кто спрашивает (candidate: peers — компании, employer: peers — кандидаты).
    active=True — можно писать, False — можно читать: кандидату любая связь, работодателю — принятое приглашение или принятый отклик.
    Неотвеченные приглашение и отклик переписки не создают; принятые — конечные статусы, их не отозвать."""
    if not peer_ids:
        return set()
    if role == "candidate":
        inv = select(Invitation.company_id).where(Invitation.candidate_id == self_id, Invitation.company_id.in_(peer_ids))
        app = (
            select(Vacancy.company_id)
            .select_from(Application)
            .join(Vacancy, Vacancy.id == Application.vacancy_id)
            .where(Application.candidate_id == self_id, Vacancy.company_id.in_(peer_ids))
        )
    else:
        inv = select(Invitation.candidate_id).where(Invitation.company_id == self_id, Invitation.candidate_id.in_(peer_ids))
        app = (
            select(Application.candidate_id)
            .select_from(Application)
            .join(Vacancy, Vacancy.id == Application.vacancy_id)
            .where(Vacancy.company_id == self_id, Application.candidate_id.in_(peer_ids))
        )
    if active or role == "employer":
        inv = inv.where(Invitation.status == "accepted")
        app = app.where(Application.status == "accepted")
    return set(db.scalars(inv)) | set(db.scalars(app))


def may_talk(cand: Candidate, co: Company) -> bool:
    """Кандидат не закрыл доступ компании: действует согласие на обработку и компании нет в его «скрыть от».
    Без этого работодатель не видит диалог, а писать не может ни одна сторона; кнопка «Написать» (chat_peer) — тоже по нему.
    Заблокированная по отзывам компания (services/reputation.py) не переписывается ни с кем."""
    return matching.consent_ok(cand, "processing") and co.inn not in (cand.hidden_from or []) and co.blocked_at is None


class Hub:
    """Рассылка «есть новое» открытым SSE-потокам; сами сообщения клиент забирает обычным GET.
    ponytail: подписчики живут в памяти одного процесса uvicorn (как в compose); при нескольких воркерах — Redis pub/sub."""

    def __init__(self) -> None:
        self.subs: dict[tuple[str, int], set[tuple[asyncio.AbstractEventLoop, asyncio.Queue]]] = {}

    def subscribe(self, key: tuple[str, int]) -> tuple[asyncio.AbstractEventLoop, asyncio.Queue]:
        entry = (asyncio.get_running_loop(), asyncio.Queue(maxsize=1))  # одно непрочитанное «есть новое» склеивает серию
        self.subs.setdefault(key, set()).add(entry)
        return entry

    def unsubscribe(self, key: tuple[str, int], entry: tuple[asyncio.AbstractEventLoop, asyncio.Queue]) -> None:
        self.subs.get(key, set()).discard(entry)
        if not self.subs.get(key):
            self.subs.pop(key, None)

    def notify(self, key: tuple[str, int]) -> None:
        """Из любого потока: обработчики записи работают в пуле, потоки SSE — в цикле событий."""
        for loop, q in list(self.subs.get(key, ())):
            try:
                loop.call_soon_threadsafe(lambda q=q: q.empty() and q.put_nowait(1))
            except RuntimeError:  # цикл уже закрыт
                pass

    def ping_dialog(self, company_id: int, candidate_id: int) -> None:
        self.notify(("candidate", candidate_id))
        self.notify(("employer", company_id))


hub = Hub()


def over_rate(db: Session, company_id: int, candidate_id: int, sender: str) -> bool:
    since = datetime.now(UTC) - timedelta(minutes=1)
    n = db.scalar(
        select(func.count(Message.id)).where(
            Message.company_id == company_id, Message.candidate_id == candidate_id, Message.sender == sender, Message.created_at > since
        )
    )
    return (n or 0) >= RATE_LIMIT
