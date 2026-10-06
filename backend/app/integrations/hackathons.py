"""Импорт протоколов хакатонов и этапов ФСП от организатора (доверенный источник → verified=True).

Формат: событие {source, external_id, title, level, discipline, date, participants, url, tags} + строки
[{email | fsp_id, team, place, role, result, rank}]. Кандидат ищется по почте входа или по ФСП ID.
  * discipline — дисциплина ФСП (catalog.DISCIPLINES, синонимы допустимы), level — описательно; на вес не влияют;
  * result — результативность: победитель | призёр | финалист | участник (или winner | prize | finalist |
    participant); пусто — выводится из места и числа участников (scoring.result_of);
  * rank — спортивный разряд/звание по протоколу (catalog.SPORT_RANKS: «КМС», «1 разряд»…), факт для карточки.
Идемпотентно: событие — по (source, external_id), достижение — по (кандидат, событие).

source='fsp' — заглушка реестра ФСП на том же формате; source='ctftime' (external_id = id события
CTFtime) подтверждает достижения, которые кандидат подтянул сам через CTFtime.
"""

import csv
import io
import re
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import catalog
from app.integrations import common
from app.integrations.scoring import place_weight, result_of
from app.models import Candidate, User
from app.services.matching import consent_ok

SOURCES = ("hackathon", "fsp", "ctftime")
LEVELS = ("international", "national", "regional", "local")  # описательно: иерархии в весах нет
MAX_ROWS = 5000  # строк протокола за один импорт


def _key(v: str) -> str:
    return re.sub(r"[\s\-.]+", " ", str(v).strip().lower().replace("ё", "е")).strip()


DISCIPLINE_ALIASES = {_key(a): name for name, aliases in catalog.DISCIPLINES.items() for a in (name, *aliases)}
RESULT_ALIASES = {_key(a): r for r, aliases in {
    "winner": ("победитель", "1 место"), "prize": ("призер", "призёр", "2 место", "3 место"),
    "finalist": ("финалист",), "participant": ("участник", "участник отбора"),
}.items() for a in (r, *aliases)}
RANK_ALIASES = {_key(r): r for r in catalog.SPORT_RANKS} | {_key(a): r for a, r in {
    "заслуженный мастер спорта": "ЗМС", "мастер спорта": "МС", "кандидат в мастера спорта": "КМС",
    "I разряд": "1 разряд", "II разряд": "2 разряд", "III разряд": "3 разряд",
    "1 юношеский": "1 юношеский разряд", "2 юношеский": "2 юношеский разряд", "3 юношеский": "3 юношеский разряд",
}.items()}


def _choice(v, aliases: dict, name: str, options) -> str | None:
    """Пусто → None; синоним → каноническое значение; иначе ValueError с перечнем допустимых."""
    if v in (None, ""):
        return None
    if (out := aliases.get(_key(v))) is None:
        raise ValueError(f"{name}: «{v}» — ожидается одно из: {', '.join(options)}")
    return out


def _int(v, name: str) -> int | None:
    if v in (None, ""):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name}: ожидается целое число, получено «{v}»") from None


def parse_csv(text: str) -> list[dict]:
    """CSV строк протокола: заголовок email,fsp_id,team,place,role,result,rank (разделитель «,» или «;», BOM допустим)."""
    text = text.lstrip("﻿")
    head = text.split("\n", 1)[0]
    reader = csv.DictReader(io.StringIO(text), delimiter=";" if head.count(";") > head.count(",") else ",")
    if not reader.fieldnames or not {"email", "fsp_id"} & {f.strip().lower() for f in reader.fieldnames}:
        raise ValueError("CSV: нужен заголовок с колонкой email или fsp_id (email,fsp_id,team,place,role,result,rank)")
    return [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in reader]


def find_candidate(db: Session, email: str | None, fsp_id: str | None) -> Candidate | None:
    """Только по подтверждённым идентификаторам входа: User.email (код на почту) или User.fsp_id.

    Candidate.email не используем — его кандидат редактирует сам и мог бы вписать чужую почту из протокола.
    """
    user = None
    if email:
        user = db.scalar(select(User).where(func.lower(User.email) == email.strip().lower()))
    if not user and fsp_id:
        user = db.scalar(select(User).where(User.fsp_id == fsp_id.strip()))
    return db.scalar(select(Candidate).where(Candidate.user_id == user.id)) if user else None


def import_protocol(db: Session, event: dict, rows: list[dict]) -> dict:
    """Импортировать протокол и закоммитить. ValueError — ошибка формата (текст для пользователя).

    Строки кандидатов без действующего согласия (matching.consent_ok «external») не привязываются (попадают в unmatched, счётчик no_consent).
    Возвращает {"event_id", "matched", "created", "updated", "no_consent", "unmatched": [{"row", "email", "fsp_id", "reason"}]}.
    """
    source = event.get("source") or "hackathon"
    if source not in SOURCES:
        raise ValueError(f"source: одно из {', '.join(SOURCES)}")
    if not event.get("external_id") or not event.get("title"):
        raise ValueError("Событию нужны external_id и title")
    level = event.get("level") or None
    if level and level not in LEVELS:
        raise ValueError(f"level: одно из {', '.join(LEVELS)}")
    discipline = _choice(event.get("discipline"), DISCIPLINE_ALIASES, "discipline", catalog.DISCIPLINES)
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
        db, source, str(event["external_id"])[:64], title=str(event["title"])[:255], level=level, discipline=discipline,
        date=date or None, participants=participants, url=event.get("url") or None, tags=tags,
    )
    report = {"event_id": ev.id, "matched": 0, "created": 0, "updated": 0, "no_consent": 0, "unmatched": []}
    parsed = []
    for i, row in enumerate(rows, start=1):
        email, fsp_id = (row.get("email") or "").strip(), str(row.get("fsp_id") or "").strip()
        place = _int(row.get("place"), f"строка {i}, place")
        result = _choice(row.get("result"), RESULT_ALIASES, f"строка {i}, result", ("победитель", "призёр", "финалист", "участник"))
        rank = _choice(row.get("rank"), RANK_ALIASES, f"строка {i}, rank", catalog.SPORT_RANKS)
        parsed.append((i, row, email, fsp_id, place, result, rank, find_candidate(db, email, fsp_id)))
    # FOR UPDATE на всех найденных кандидатов в порядке id (без взаимоблокировок между импортами) и перечитывание
    # согласия: параллельный отзыв (set_external_consent тоже берёт FOR UPDATE) либо раньше — строка пропущена,
    # либо ждёт нашего commit и затем удалит записанное.
    ids = sorted({c.id for *_, c in parsed if c})
    if ids:
        db.scalars(select(Candidate).where(Candidate.id.in_(ids)).order_by(Candidate.id).with_for_update()
                   .execution_options(populate_existing=True)).all()
    for i, row, email, fsp_id, place, result, rank, cand in parsed:
        if not cand:
            reason = "нет email и fsp_id" if not (email or fsp_id) else "кандидат не найден"
            report["unmatched"].append({"row": i, "email": email or None, "fsp_id": fsp_id or None, "reason": reason})
            continue
        if not consent_ok(cand, "external"):
            report["no_consent"] += 1
            report["unmatched"].append({"row": i, "email": email or None, "fsp_id": fsp_id or None,
                                        "reason": "нет согласия на внешние данные"})
            continue
        result = result or result_of(place, ev.participants)
        _, created = common.upsert_achievement(
            db, cand, source, ev,
            title=ev.title, place=place, team=(row.get("team") or None), role=(row.get("role") or None),
            result=result, sport_rank=rank,
            verified=True, weight=place_weight(place, ev.participants, result),
            data={"kind": "protocol", "row": i},
        )
        report["matched"] += 1
        report["created" if created else "updated"] += 1
    db.commit()
    return report
