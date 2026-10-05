"""Импорт протоколов хакатонов и этапов ФСП от организатора (доверенный источник → verified=True).

Формат: событие {source, external_id, title, level, date, participants, url, tags} + строки
[{email | fsp_id, team, place, role}]. Кандидат ищется по почте (анкета или аккаунт) или по ФСП ID.
Идемпотентно: событие — по (source, external_id), достижение — по (кандидат, событие).

source='fsp' — заглушка реестра ФСП на том же формате; source='ctftime' (external_id = id события
CTFtime) подтверждает достижения, которые кандидат подтянул сам через CTFtime.
"""

import csv
import io
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.integrations import common
from app.integrations.scoring import LEVEL, place_weight
from app.models import Candidate, User

SOURCES = ("hackathon", "fsp", "ctftime")
MAX_ROWS = 5000  # строк протокола за один импорт


def _int(v, name: str) -> int | None:
    if v in (None, ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name}: ожидается целое число, получено «{v}»") from None


def parse_csv(text: str) -> list[dict]:
    """CSV строк протокола: заголовок email,fsp_id,team,place,role (разделитель «,» или «;», BOM допустим)."""
    text = text.lstrip("﻿")
    head = text.split("\n", 1)[0]
    reader = csv.DictReader(io.StringIO(text), delimiter=";" if head.count(";") > head.count(",") else ",")
    if not reader.fieldnames or not {"email", "fsp_id"} & {f.strip().lower() for f in reader.fieldnames}:
        raise ValueError("CSV: нужен заголовок с колонкой email или fsp_id (email,fsp_id,team,place,role)")
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in reader]


def find_candidate(db: Session, email: str | None, fsp_id: str | None) -> Candidate | None:
    if email:
        e = email.strip().lower()
        cand = db.scalar(select(Candidate).where(func.lower(Candidate.email) == e))
        if cand:
            return cand
        user = db.scalar(select(User).where(func.lower(User.email) == e))
        if user:
            return db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    if fsp_id:
        user = db.scalar(select(User).where(User.fsp_id == fsp_id.strip()))
        if user:
            return db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    return None


def import_protocol(db: Session, event: dict, rows: list[dict]) -> dict:
    """Импортировать протокол и закоммитить. ValueError — ошибка формата (текст для пользователя).

    Возвращает {"event_id", "matched", "created", "updated", "unmatched": [{"row", "email", "fsp_id", "reason"}]}.
    """
    source = event.get("source") or "hackathon"
    if source not in SOURCES:
        raise ValueError(f"source: одно из {', '.join(SOURCES)}")
    if not event.get("external_id") or not event.get("title"):
        raise ValueError("Событию нужны external_id и title")
    level = event.get("level") or None
    if level and level not in LEVEL:
        raise ValueError(f"level: одно из {', '.join(LEVEL)}")
    date = event.get("date")
    if isinstance(date, str) and date:
        try:
            date = datetime.fromisoformat(date)
        except ValueError:
            raise ValueError("date: ожидается ISO-дата, например 2025-11-20") from None
    tags = event.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]
    participants = _int(event.get("participants"), "participants")
    if len(rows) > MAX_ROWS:
        raise ValueError(f"Слишком большой протокол: {len(rows)} строк, максимум {MAX_ROWS}")

    ev = common.upsert_event(
        db, source, str(event["external_id"])[:64], title=str(event["title"])[:255], level=level,
        date=date or None, participants=participants, url=event.get("url") or None, tags=tags,
    )
    report = {"event_id": ev.id, "matched": 0, "created": 0, "updated": 0, "unmatched": []}
    for i, row in enumerate(rows, start=1):
        email, fsp_id = (row.get("email") or "").strip(), str(row.get("fsp_id") or "").strip()
        place = _int(row.get("place"), f"строка {i}, place")
        cand = find_candidate(db, email, fsp_id)
        if not cand:
            reason = "нет email и fsp_id" if not (email or fsp_id) else "кандидат не найден"
            report["unmatched"].append({"row": i, "email": email or None, "fsp_id": fsp_id or None, "reason": reason})
            continue
        _, created = common.upsert_achievement(
            db, cand, source, ev,
            title=ev.title, place=place, team=(row.get("team") or None), role=(row.get("role") or None),
            verified=True, weight=place_weight(place, ev.participants, ev.level),
            data={"kind": "protocol", "row": i},
        )
        report["matched"] += 1
        report["created" if created else "updated"] += 1
    db.commit()
    return report
