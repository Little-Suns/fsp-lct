"""Тест-квест: адаптивная сессия на IRT → категория «специализация × трек × грейд».

Ответ сохраняется сразу; правильность и текущий θ до конца теста не отдаются. Ключ задания (payload.key) наружу не уходит.
Текущее (выданное, но не отвеченное) задание — последняя запись в QuestSession.answers с response = None.
"""

import random
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import catalog
from app.db import get_db
from app.deps import current_candidate
from app.models import Candidate, ExternalAccount, Item, QuestSession
from app.services import irt
from app.services.items import STORY

router = APIRouter(prefix="/api/quest", tags=["quest"])

PILOT_AT = 3  # пилотное задание выдаётся после трёх рабочих
TIMEOUT_GRACE_S = 30  # запас на сеть; позже — ответ засчитывается как неверный
PERCENTILE_MIN_N = 10  # меньше кандидатов в категории → перцентиль по специализации
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]

# компетенция → навыки, которые она подтверждает (канон catalog.SKILLS)
COMP_SKILLS = {
    "Базы данных и транзакции": ["PostgreSQL", "SQL"],
    "SQL": ["SQL"],
    "Пайплайны": ["Airflow"],
    "Kubernetes": ["Kubernetes", "Docker"],
    "Наблюдаемость": ["Prometheus"],
    "Сети": ["Linux"],
    "Автотесты": ["Selenium"],
    "Веб-уязвимости": ["Pentest"],
}
# язык/фреймворк трека подтверждается ревью кода
TRACK_SKILLS = {
    "Python": ["Python"], "Go": ["Go"], "Java / Kotlin": ["Java", "Kotlin"], "Node.js": ["Node.js"], "C# / .NET": ["C#"],
    "React": ["React", "JavaScript"], "Vue": ["Vue", "JavaScript"], "Angular": ["Angular", "TypeScript"],
    "iOS": ["Swift"], "Android": ["Kotlin"], "Flutter": ["Flutter"],
}


class StartIn(BaseModel):
    story: bool = True


class AnswerIn(BaseModel):
    item_id: int
    response: int  # choice — индекс варианта с 0; mark/review — номер строки кода с 1
    comment: str | None = None  # комментарий к ревью; на оценку пока не влияет
    ms: int | None = None  # время ответа по часам клиента


def _now() -> datetime:
    return datetime.now(UTC)


def _utc(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt and dt.tzinfo is None else dt


def _ru_date(dt: datetime) -> str:
    return f"{dt.day} {MONTHS[dt.month - 1]} {dt.year}"


def _bank(db: Session, spec: str) -> dict[int, Item]:
    return {it.id: it for it in db.scalars(select(Item).where(Item.spec == spec))}


def _active(db: Session, cand: Candidate) -> QuestSession | None:
    return db.scalar(select(QuestSession).where(QuestSession.candidate_id == cand.id, QuestSession.finished_at.is_(None)).order_by(QuestSession.id.desc()))


def _active_or_404(db: Session, cand: Candidate) -> QuestSession:
    sess = _active(db, cand)
    if not sess:
        raise HTTPException(404, "Нет активной сессии теста: начните тест")
    return sess


def _pending(sess: QuestSession) -> dict | None:
    return sess.answers[-1] if sess.answers and sess.answers[-1]["response"] is None else None


def _answered(sess: QuestSession, bank: dict[int, Item]) -> list[dict]:
    return [a for a in sess.answers if a["response"] is not None and a["item_id"] in bank]


def _responses(sess: QuestSession, bank: dict[int, Item], comp: str | None = None) -> list[tuple]:
    """Рабочие (не пилотные) ответы как (a, b, u) для IRT."""
    return [(bank[a["item_id"]].a, bank[a["item_id"]].b, int(a["correct"])) for a in _answered(sess, bank)
            if not a["pilot"] and (comp is None or bank[a["item_id"]].competency == comp)]


def _cf_rating(db: Session, cand: Candidate) -> float | None:
    return db.scalar(select(ExternalAccount.rating).where(
        ExternalAccount.candidate_id == cand.id, ExternalAccount.provider == "codeforces",
        ExternalAccount.verified_at.is_not(None), ExternalAccount.rating.is_not(None)))


def _cooldown(cand: Candidate) -> dict:
    until = _utc(cand.next_upgrade_at)
    active = bool(cand.tested_at and until and until > _now())
    return {"active": active, "until": until.isoformat() if active else None,
            "note": f"Повышение грейда возможно с {_ru_date(until)}. Сейчас пересдача может только понизить результат." if active else None}


def _serve(sess: QuestSession, bank: dict[int, Item]) -> Item | None:
    """Выдать следующее задание (записывается в answers как ожидающее ответа) или None, если тест окончен."""
    rng = random.Random()
    items = list(bank.values())
    seen = {a["item_id"] for a in sess.answers}
    fams = {bank[i].family for i in seen if i in bank}
    n_op = sum(1 for a in sess.answers if not a["pilot"])
    item = None
    if n_op == PILOT_AT and not any(a["pilot"] for a in sess.answers):
        item = irt.pick_pilot(items, seen, fams, rng)
    if item is None and not irt.should_stop(n_op, sess.se):
        item = irt.next_item(sess.theta, items, seen, fams, rng)
    if item:
        sess.answers = [*sess.answers, {"item_id": item.id, "pilot": item.pilot, "served_at": _now().isoformat(),
                                        "response": None, "correct": None, "ms": None, "server_ms": None, "comment": None}]
    return item


def _public(item: Item, n: int) -> dict:
    p = {k: v for k, v in item.payload.items() if k != "key"}
    clock = STORY.get(item.spec, ("", []))[1]
    if clock:
        p["time"] = clock[min(n, len(clock)) - 1]  # «часы» сюжета идут по номеру сцены, а не по семейству
    return {"id": item.id, "kind": item.kind, "competency": item.competency, **p}


def _state(sess: QuestSession, bank: dict[int, Item], spec: str) -> dict:
    pend = _pending(sess)
    n_fam = len({it.family for it in bank.values() if not it.pilot})
    total = min(irt.MAX_ITEMS, n_fam) + (1 if any(it.pilot for it in bank.values()) else 0)
    out = {"session_id": sess.id, "quest_title": STORY.get(spec, ("Тест",))[0],
           "story": sess.story, "done": pend is None, "progress": {"n": len(sess.answers), "total": max(total, len(sess.answers))},
           "item": None, "time_limit_s": None, "remaining_s": None}
    if pend and pend["item_id"] in bank:
        item = bank[pend["item_id"]]
        elapsed = (_now() - datetime.fromisoformat(pend["served_at"])).total_seconds()
        lim = item.payload["time_limit_s"]
        out |= {"item": _public(item, len(sess.answers)), "time_limit_s": lim, "remaining_s": max(0, round(lim - elapsed))}
    return out


@router.post("/start")
def start(body: StartIn, cand: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    """Начать тест или вернуться к незаконченной сессии (новая сессия не выдаёт новых заданий взамен уже показанных)."""
    if cand.spec not in catalog.COMPETENCIES:
        raise HTTPException(422, "В профиле не указана специализация")
    bank = _bank(db, cand.spec)
    if not bank:
        raise HTTPException(503, "Банк заданий пуст: запустите seed")
    sess = _active(db, cand)
    resumed = sess is not None
    if not sess:
        prior = irt.cf_prior(_cf_rating(db, cand))
        sess = QuestSession(candidate_id=cand.id, story=body.story, prior_mean=prior, theta=prior, se=1.0, answers=[], flags=[])
        db.add(sess)
        db.flush()
        _serve(sess, bank)
    sess.story = body.story
    db.commit()
    return {**_state(sess, bank, cand.spec), "resumed": resumed, "cooldown": _cooldown(cand)}


@router.get("/current")
def current(cand: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    sess = _active_or_404(db, cand)
    return _state(sess, _bank(db, cand.spec), cand.spec)


@router.post("/answer")
def answer(body: AnswerIn, cand: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    sess = _active_or_404(db, cand)
    pend = _pending(sess)
    if not pend:
        raise HTTPException(409, "Все задания пройдены: завершите тест")
    if pend["item_id"] != body.item_id:
        raise HTTPException(409, "Ответ не на текущее задание")
    bank = _bank(db, cand.spec)
    item = bank.get(body.item_id)
    if not item:
        raise HTTPException(409, "Задание больше недоступно")
    p = item.payload
    lo, n = (0, len(p["options"])) if item.kind == "choice" else (1, len(p["panel"]["lines"]))
    if not lo <= body.response < lo + n:
        raise HTTPException(422, "Некорректный ответ")
    server_ms = int((_now() - datetime.fromisoformat(pend["served_at"])).total_seconds() * 1000)
    timeout = server_ms > (p["time_limit_s"] + TIMEOUT_GRACE_S) * 1000
    key = p["key"] if isinstance(p["key"], list) else [p["key"]]
    done = {**pend, "response": body.response, "correct": not timeout and body.response in key, "timeout": timeout,
            "ms": body.ms, "server_ms": server_ms, "comment": (body.comment or "").strip()[:2000] or None}
    sess.answers = [*sess.answers[:-1], done]
    if not item.pilot:
        sess.theta, sess.se = irt.eap(_responses(sess, bank), sess.prior_mean)
    _serve(sess, bank)
    db.commit()
    return {"saved": True, **_state(sess, bank, cand.spec)}


def _percentile(db: Session, cand: Candidate) -> tuple[int | None, str | None]:
    """Доля кандидатов с θ ниже, чем у кандидата: в категории spec × track × grade, при малой выборке — в специализации."""
    base = select(Candidate.theta).where(Candidate.id != cand.id, Candidate.theta.is_not(None), Candidate.spec == cand.spec)
    scope, others = "category", db.scalars(base.where(Candidate.track == cand.track, Candidate.grade == cand.grade)).all()
    if len(others) < PERCENTILE_MIN_N:
        scope, others = "spec", db.scalars(base).all()
    if not others:
        return None, None
    return round(100 * sum(t < cand.theta for t in others) / len(others)), scope


def _skills(cand: Candidate, comps: list[dict], grade: str) -> list[str]:
    th = max(catalog.GRADE_TH[grade] - 0.5, catalog.GRADE_TH["Junior"])
    out = []
    for c in comps:
        if c["t"] >= th:
            out += COMP_SKILLS.get(c["n"], [])
            if c["n"] == "Конкурентность" and cand.track == "Python":
                out.append("asyncio")
            if c["n"] == "Ревью кода":
                out += TRACK_SKILLS.get(cand.track or "", [])
    return list(dict.fromkeys(out))


def _result(cand: Candidate, sess: QuestSession | None, db: Session) -> dict:
    grades = catalog.GRADES
    gi = grades.index(cand.grade)
    nxt = grades[gi + 1] if gi + 1 < len(grades) else None
    pct, scope = _percentile(db, cand)
    comps = cand.competencies or []
    ranked = sorted(comps, key=lambda c: -c["t"])
    cd = _cooldown(cand)
    minutes = None
    if sess and sess.finished_at:
        minutes = round((_utc(sess.finished_at) - _utc(sess.started_at)).total_seconds() / 60)
    return {
        "category": {"spec": cand.spec, "track": cand.track, "grade": cand.grade},
        "percentile": pct,
        "percentile_scope": scope,  # category | spec | None
        "theta": round(cand.theta, 2),
        "se": round(cand.se, 2),
        "minutes": minutes,
        "competencies": comps,
        "strong": [c["n"] for c in ranked[:2]],
        "weak": [c["n"] for c in ranked[::-1][:2]],
        "skills_confirmed": cand.skills_confirmed or [],
        "upgrade": {
            "next_grade": nxt,
            "need_theta_minus_se": catalog.GRADE_TH[nxt] if nxt else None,
            "allowed_at": cd["until"],
            "review_required": bool(nxt) and gi + 1 >= grades.index(catalog.REVIEW_REQUIRED_FROM) and not cand.review_passed,
        },
        "flags": (sess.flags if sess else []) or [],
        "tested_at": _utc(cand.tested_at).isoformat() if cand.tested_at else None,
        "review_passed": cand.review_passed,
    }


@router.post("/finish")
def finish(cand: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    sess = _active_or_404(db, cand)
    if _pending(sess):
        raise HTTPException(409, "Тест ещё не завершён: ответьте на текущее задание")
    bank = _bank(db, cand.spec)
    resp = _responses(sess, bank)
    if not resp:
        raise HTTPException(409, "Нет ответов для оценки")
    # итог — с нейтральным априором N(0, 1): CF-рейтинг только ускоряет подбор заданий, на грейд/перцентиль/компетенции не влияет
    theta, se = irt.eap(resp)
    names = catalog.COMPETENCIES[cand.spec]
    comps = irt.competency_estimates({n: _responses(sess, bank, n) for n in names}, names, theta)
    timings = [(a["server_ms"], bank[a["item_id"]].payload["time_limit_s"]) for a in _answered(sess, bank) if not a["pilot"]]
    flags = irt.suspicion_flags(theta, resp, timings)

    now = _now()
    cooldown = _cooldown(cand)["active"]
    prev = cand.grade if cand.tested_at else None
    # в кулдаун пересдача может только понизить результат
    applied = not cooldown or cand.theta is None or theta < cand.theta
    note = None
    if applied:
        grade = irt.decide_grade(prev, theta, se, upgrade_allowed=not cooldown)
        # кулдаун 90 дней — только с первого присвоения грейда или фактического повышения
        if prev is None or catalog.GRADES.index(grade) > catalog.GRADES.index(prev):
            cand.next_upgrade_at = now + timedelta(days=catalog.UPGRADE_COOLDOWN_DAYS)
        cand.theta, cand.se, cand.grade, cand.competencies = theta, se, grade, comps
        cand.skills_confirmed = _skills(cand, comps, grade)
        cand.tested_at = now
        cand.percentile = _percentile(db, cand)[0]
    else:
        note = f"Результат не ниже текущего, поэтому категория не изменилась. Повышение возможно с {_ru_date(_utc(cand.next_upgrade_at))}."

    senior_plus = catalog.GRADES.index(cand.grade) >= catalog.GRADES.index(catalog.REVIEW_REQUIRED_FROM)
    if (senior_plus and not cand.review_passed) or {"inconsistent", "too_fast"} & set(flags):
        flags.append("review_required")  # ponytail: только флаг; асинхронный «разбор решения» (3–4 вопроса LLM) — отдельный сервис
    sess.theta, sess.se, sess.flags, sess.finished_at = theta, se, flags, now
    db.commit()
    return {**_result(cand, sess, db), "applied": applied, "note": note, "attempt": {"theta": round(theta, 2), "se": round(se, 2)}}


@router.get("/result")
def result(cand: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    if not cand.tested_at or cand.theta is None:
        raise HTTPException(404, "Тест ещё не пройден")
    sess = db.scalar(select(QuestSession).where(QuestSession.candidate_id == cand.id, QuestSession.finished_at.is_not(None)).order_by(QuestSession.id.desc()))
    return _result(cand, sess, db)
