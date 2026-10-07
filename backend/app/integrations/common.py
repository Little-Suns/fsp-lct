"""Общий слой провайдеров достижений: HTTP с троттлингом и upsert событий/достижений.

Конвенция «провайдер достижений» (без формального Protocol — модулей мало):
  * модуль провайдера пишет строки только через upsert_event / upsert_achievement с source=<провайдер>;
  * живые API (codeforces, ctftime) экспортируют fetch(...) — только HTTP — и apply(db, account, данные) —
    только запись; между ними вызывающий берёт FOR UPDATE на кандидата и перепроверяет согласие
    (consent.lock_candidate). Файловые (hackathon, fsp) идут через hackathons.import_protocol.
  * вес достижения ∈ [0,1] считается только функциями scoring.py; сводный сигнал — scoring.signal (соревнования + рейтинг).
Реестр ФСП подключается как ещё один провайдер того же вида: событие + строки протокола.
"""

import threading
import time
from datetime import UTC, datetime
from urllib.parse import urlparse

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Achievement, Candidate, Event

# CTFtime режет запросы без «браузерного» User-Agent
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36 fsp-career"
MIN_INTERVAL = {"codeforces.com": 2.0, "ctftime.org": 0.5}  # секунд между запросами к хосту
TIMEOUT = 15.0

_lock = threading.Lock()
_last: dict[str, float] = {}


class ExternalError(Exception):
    """Внешний сервис недоступен или ответил ошибкой. Текст — для пользователя, по-русски."""

    def __init__(self, message: str, status: int | None = None, payload=None):
        super().__init__(message)
        self.status, self.payload = status, payload


def get_json(url: str, params: dict | None = None, timeout: float = TIMEOUT):
    """GET с глобальным троттлингом по хосту. Любой сбой и любой HTTP ≥ 400 → ExternalError."""
    host = urlparse(url).hostname or ""
    # ponytail: троттлинг внутри одного процесса; при нескольких воркерах — Redis-токен-бакет
    with _lock:
        wait = _last.get(host, 0) + MIN_INTERVAL.get(host, 0) - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last[host] = time.monotonic()
    try:
        r = httpx.get(url, params=params, headers={"User-Agent": UA}, timeout=timeout, follow_redirects=True)
    except httpx.HTTPError as e:
        raise ExternalError(f"{host} недоступен: {type(e).__name__}") from e
    try:
        data = r.json()
    except ValueError:
        data = None
    if r.status_code >= 400:
        detail = data.get("comment") or data.get("detail") if isinstance(data, dict) else None
        raise ExternalError(f"{host} ответил HTTP {r.status_code}" + (f": {detail}" if detail else ""), r.status_code, data)
    if data is None:
        raise ExternalError(f"{host} вернул не JSON")
    return data


def upsert_event(db: Session, source: str, external_id: str, **fields) -> Event:
    ev = db.scalar(select(Event).where(Event.source == source, Event.external_id == str(external_id)))
    if not ev:
        ev = Event(source=source, external_id=str(external_id), tags=[])
        db.add(ev)
    for k, v in fields.items():
        if v is not None:
            setattr(ev, k, v)
    db.flush()
    return ev


def upsert_achievement(db: Session, cand: Candidate, source: str, event: Event | None, **fields) -> tuple[Achievement, bool]:
    """Одно достижение на (кандидат, событие); для достижений без события — на (кандидат, source, data.kind)."""
    q = select(Achievement).where(Achievement.candidate_id == cand.id, Achievement.source == source)
    if event is not None:
        ach = db.scalar(q.where(Achievement.event_id == event.id))
    else:
        kind = (fields.get("data") or {}).get("kind")
        ach = next((a for a in db.scalars(q.where(Achievement.event_id.is_(None))) if (a.data or {}).get("kind") == kind), None)
    created = ach is None
    if created:
        ach = Achievement(candidate_id=cand.id, source=source, event_id=event.id if event else None)
        db.add(ach)
    for k, v in fields.items():
        setattr(ach, k, v)
    db.flush()
    return ach, created


def ts(seconds: float | None) -> datetime | None:
    return datetime.fromtimestamp(seconds, UTC) if seconds else None
