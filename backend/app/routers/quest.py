"""Тест-квест: адаптивная сессия на IRT → категория «специализация × трек × грейд».

Ответ сохраняется сразу; правильность и текущий θ до конца теста не отдаются. Ключ задания (payload.key) наружу не уходит.
Текущее (выданное, но не отвеченное) задание — последняя запись в QuestSession.answers с response = None.

Экспресс-режим (mode="express") — знакомство за 3–5 минут, например для жюри: irt.EXPRESS_ITEMS заданий без ревью,
EXPRESS_TIME_LIMIT_S на каждое, тот же адаптивный выбор, без пилотного. SE честно больше, грейд — тем же правилом θ − SE.
Экспресс даёт только предварительную категорию (Candidate.grade_express): ставится, лишь если у кандидата ещё нет грейда,
не запускает кулдаун и не повышает и не понижает грейд — ни свой прошлый экспресс, ни полный тест (попытка уходит в историю
с applied = False). Полный тест после экспресса считается первым присвоением грейда: нейтральный априор, кулдаун с него.
"""

import random
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import catalog, config
from app.db import get_db
from app.deps import current_candidate, current_company
from app.models import Candidate, Company, ExternalAccount, Invitation, Item, Need, QuestSession
from app.services import irt
from app.services.items import STORY, plan_for_need
from app.services.parsing import parse_need

router = APIRouter(prefix="/api/quest", tags=["quest"])

PILOT_AT = 3  # пилотное задание выдаётся после трёх рабочих
MODES = ("full", "express")
EXPRESS_TIME_LIMIT_S = 60  # на задание в экспресс-режиме: 5 × 60 с — не дольше 5 минут
EXPRESS_LABEL = "экспресс-оценка"
TIMEOUT_GRACE_S = 30  # запас на сеть; позже — ответ засчитывается как неверный
PERCENTILE_MIN_N = 10  # меньше кандидатов в категории → перцентиль по специализации
PLAN_TEXT_MAX, PREVIEW_TEXT_MAX = 5000, 2000
VERDICT = {"confirmed": "Заявленный грейд подтверждён", "below": "Ниже заявленного грейда", "above": "Выше заявленного грейда"}
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
    mode: str = "full"  # full | express; у продолжаемой сессии режим не меняется
    target_grade: str | None = None  # грейд, на который проходит тест; по умолчанию — заявленный в профиле
    invitation_id: int | None = None  # тест по приглашению: выбор заданий смещается к компетенциям вакансии


class PlanIn(BaseModel):
    text: str | None = None
    need_id: int | None = None


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


def _active(db: Session, cand: Candidate, lock: bool = False) -> QuestSession | None:
    """Незавершённая сессия (по индексу uq_quest_active — не больше одной). lock — SELECT … FOR UPDATE до конца транзакции."""
    q = select(QuestSession).where(QuestSession.candidate_id == cand.id, QuestSession.finished_at.is_(None))
    if lock:
        q = q.with_for_update().execution_options(populate_existing=True)
    return db.scalar(q)


def _active_or_404(db: Session, cand: Candidate, lock: bool = False) -> QuestSession:
    sess = _active(db, cand, lock)
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


def _express(sess: QuestSession) -> bool:
    return sess.mode == "express"


def _limit(sess: QuestSession, item: Item) -> int:
    """Лимит времени на задание: из банка, в экспресс-режиме — EXPRESS_TIME_LIMIT_S."""
    return EXPRESS_TIME_LIMIT_S if _express(sess) else item.payload["time_limit_s"]


def _serve(sess: QuestSession, bank: dict[int, Item]) -> Item | None:
    """Выдать следующее задание (записывается в answers как ожидающее ответа) или None, если тест окончен."""
    rng = random.Random()
    express = _express(sess)
    items = [it for it in bank.values() if not express or it.kind in irt.EXPRESS_KINDS]
    seen = {a["item_id"] for a in sess.answers}
    fams = {bank[i].family for i in seen if i in bank}
    n_op = sum(1 for a in sess.answers if not a["pilot"])
    item = None
    if not express and n_op == PILOT_AT and not any(a["pilot"] for a in sess.answers):
        item = irt.pick_pilot(items, seen, fams, rng)
    if item is None and not irt.should_stop(n_op, sess.se, express):
        item = irt.next_item(sess.theta, items, seen, fams, rng, focus=sess.focus)
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
    if _express(sess):
        total = min(irt.EXPRESS_ITEMS, n_fam)
    else:
        total = min(irt.MAX_ITEMS, n_fam) + (1 if any(it.pilot for it in bank.values()) else 0)
    out = {"session_id": sess.id, "quest_title": STORY.get(spec, ("Тест",))[0], "mode": sess.mode,
           "story": sess.story, "target_grade": sess.target_grade, "focus": sess.focus, "done": pend is None, "progress": {"n": len(sess.answers), "total": max(total, len(sess.answers))},
           "item": None, "time_limit_s": None, "remaining_s": None}
    if pend and pend["item_id"] in bank:
        item = bank[pend["item_id"]]
        elapsed = (_now() - datetime.fromisoformat(pend["served_at"])).total_seconds()
        lim = _limit(sess, item)
        out |= {"item": {**_public(item, len(sess.answers)), "time_limit_s": lim}, "time_limit_s": lim, "remaining_s": max(0, round(lim - elapsed))}
    return out


@router.post("/start")
def start(body: StartIn, cand: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    """Начать тест или вернуться к незаконченной сессии (новая сессия не выдаёт новых заданий взамен уже показанных)."""
    if cand.spec not in catalog.COMPETENCIES:
        raise HTTPException(422, "В профиле не указана специализация")
    bank = _bank(db, cand.spec)
    if not bank:
        raise HTTPException(503, "Банк заданий пуст: запустите seed")
    if body.mode not in MODES:
        raise HTTPException(422, f"mode — одно из: {', '.join(MODES)}")
    target = body.target_grade or (cand.grade_claimed if cand.grade_claimed in catalog.GRADES else None)
    if target not in catalog.GRADES:
        raise HTTPException(422, f"target_grade — одно из: {', '.join(catalog.GRADES)}")
    focus = None
    if body.invitation_id is not None:
        inv = db.get(Invitation, body.invitation_id)
        if not inv or inv.candidate_id != cand.id:
            raise HTTPException(404, "Приглашение не найдено")
        if inv.need:
            focus = plan_for_need(cand.spec, inv.need.must, inv.need.nice, inv.need.grade)["focus"]
    sess = _active(db, cand)
    resumed = sess is not None
    if not sess:
        # старт выбора — у порога заявленного грейда (+ CF); итоговая оценка — с нейтральным априором, см. finish
        prior = irt.start_prior(target, _cf_rating(db, cand))
        sess = QuestSession(candidate_id=cand.id, story=body.story, prior_mean=prior, theta=prior, se=1.0, answers=[], flags=[],
                            target_grade=target, focus=focus, mode=body.mode)
        db.add(sess)
        try:
            db.flush()
        except IntegrityError:  # параллельный старт успел создать сессию (uq_quest_active) — продолжаем её
            db.rollback()
            sess, resumed = _active(db, cand), True
            if not sess:
                raise HTTPException(409, "Не удалось начать тест, повторите") from None
        else:
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
    sess = _active_or_404(db, cand, lock=True)  # проверки «текущее задание / не завершена» — под блокировкой
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
    timeout = server_ms > (_limit(sess, item) + TIMEOUT_GRACE_S) * 1000
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


def _target(sess: QuestSession | None, cand: Candidate) -> dict | None:
    """Итог относительно грейда, на который проходили тест: подтверждён / ниже / выше."""
    if not sess or not sess.target_grade or not sess.grade:
        return None
    got = sess.grade
    d = catalog.GRADES.index(got) - catalog.GRADES.index(sess.target_grade)
    verdict = "confirmed" if d == 0 else "below" if d < 0 else "above"
    return {"grade": sess.target_grade, "result_grade": got, "verdict": verdict, "label": VERDICT[verdict]}


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
        "flags": (sess.flags if sess else None) or [],
        "target": _target(sess, cand),
        "mode": sess.mode if sess else "full",  # режим последней попытки
        "express": bool(cand.grade_express),  # категория — предварительная экспресс-оценка
        "assessment_label": EXPRESS_LABEL if cand.grade_express else None,
        "tested_at": _utc(cand.tested_at).isoformat() if cand.tested_at else None,
        "review_passed": cand.review_passed,
    }


@router.post("/finish")
def finish(cand: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    # порядок блокировок: кандидат → сессия; параллельный finish дождётся и получит 409
    cand = db.scalar(select(Candidate).where(Candidate.id == cand.id).with_for_update().execution_options(populate_existing=True))
    sess = _active(db, cand, lock=True)
    if not sess:
        if db.scalar(select(QuestSession.id).where(QuestSession.candidate_id == cand.id).limit(1)):
            raise HTTPException(409, "Тест уже завершён: начните новый")
        raise HTTPException(404, "Нет активной сессии теста: начните тест")
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
    timings = [(a["server_ms"], _limit(sess, bank[a["item_id"]])) for a in _answered(sess, bank) if not a["pilot"]]
    flags = irt.suspicion_flags(theta, resp, timings)

    now = _now()
    express, provisional = _express(sess), bool(cand.grade_express)
    cooldown = _cooldown(cand)["active"]
    # предварительный экспресс-грейд не считается присвоенным: полный тест после него — первое присвоение
    prev = cand.grade if cand.tested_at and not provisional else None
    note = None
    if express:
        # экспресс — только предварительная категория тому, у кого грейда ещё нет; существующий не меняет ни вверх, ни вниз
        applied = not cand.tested_at
        if not applied:
            note = ("Предварительная категория уже выставлена по экспресс-тесту, повторный экспресс её не меняет. Уточнить грейд — полным тестом."
                    if provisional else "Экспресс-оценка не меняет категорию, подтверждённую полным тестом.")
    else:
        # в кулдаун пересдача может только понизить результат
        applied = not cooldown or cand.theta is None or theta < cand.theta
        if not applied:
            note = f"Результат не ниже текущего, поэтому категория не изменилась. Повышение возможно с {_ru_date(_utc(cand.next_upgrade_at))}."
    if applied:
        grade = irt.decide_grade(prev, theta, se, upgrade_allowed=not cooldown)
        # кулдаун 90 дней — только с первого присвоения грейда полным тестом или фактического повышения
        if not express and (prev is None or catalog.GRADES.index(grade) > catalog.GRADES.index(prev)):
            cand.next_upgrade_at = now + timedelta(days=catalog.UPGRADE_COOLDOWN_DAYS)
        cand.theta, cand.se, cand.grade, cand.competencies = theta, se, grade, comps
        # по одному заданию на компетенцию навыки не подтверждаются: в экспресс-оценке — только заявленные
        cand.skills_confirmed = [] if express else _skills(cand, comps, grade)
        cand.grade_express = express
        cand.tested_at = now
        cand.percentile = _percentile(db, cand)[0]

    senior_plus = catalog.GRADES.index(cand.grade) >= catalog.GRADES.index(catalog.REVIEW_REQUIRED_FROM)
    if (senior_plus and not cand.review_passed) or {"inconsistent", "too_fast"} & set(flags):
        flags.append("review_required")  # ponytail: только флаг; асинхронный «разбор решения» (3–4 вопроса LLM) — отдельный сервис
    # грейд попытки: присвоенный (с гистерезисом), а если не применён — измеренный самой попыткой
    sess.grade = cand.grade if applied else catalog.grade_from_theta(theta, se)
    sess.applied = applied
    sess.theta, sess.se, sess.flags, sess.finished_at = theta, se, flags, now
    db.commit()
    return {**_result(cand, sess, db), "applied": applied, "note": note, "attempt": {"theta": round(theta, 2), "se": round(se, 2)}}


@router.get("/result")
def result(cand: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    if not cand.tested_at or cand.theta is None:
        raise HTTPException(404, "Тест ещё не пройден")
    sess = db.scalar(select(QuestSession).where(QuestSession.candidate_id == cand.id, QuestSession.finished_at.is_not(None)).order_by(QuestSession.id.desc()))
    return _result(cand, sess, db)


@router.get("/history")
def history(cand: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    """История попыток. Ответы и ключи не отдаются; θ незаконченной попытки — тоже (он выдал бы правильность)."""
    out = []
    for s in db.scalars(select(QuestSession).where(QuestSession.candidate_id == cand.id).order_by(QuestSession.id.desc())):
        done = s.finished_at is not None
        out.append({
            "session_id": s.id,
            "started_at": _utc(s.started_at).isoformat() if s.started_at else None,
            "finished_at": _utc(s.finished_at).isoformat() if done else None,
            "target_grade": s.target_grade,
            "mode": s.mode,
            "story": s.story,
            "focus": bool(s.focus),
            "theta": round(s.theta, 2) if done else None,
            "se": round(s.se, 2) if done else None,
            "grade": s.grade if done else None,
            "applied": s.applied if done else None,
            "flags": s.flags or [],
            "items": sum(1 for a in s.answers if a["response"] is not None),
        })
    return out


def _plan(need: dict) -> dict:
    try:
        plan = plan_for_need(need["spec"], need["must"], need["nice"], need["grade"])
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    keep = ("spec", "track", "grade", "must", "nice", "parsed_by", "hints")
    return {"need": {k: need[k] for k in keep if k in need}, "plan": plan}


def _clean_text(text: str | None, limit: int) -> str:
    text = " ".join((text or "").split())
    if not text:
        raise HTTPException(422, "Нужен текст вакансии")
    if len(text) > limit:
        raise HTTPException(422, f"Текст длиннее {limit} символов")
    return text


@router.post("/plan")
def plan(body: PlanIn, comp: Company = Depends(current_company), db: Session = Depends(get_db)):
    """План теста под потребность работодателя: по тексту или по своей сохранённой потребности."""
    if body.need_id is not None:
        need = db.get(Need, body.need_id)
        if not need or need.company_id != comp.id:
            raise HTTPException(404, "Потребность не найдена")
        return _plan({"spec": need.spec, "track": need.track, "grade": need.grade, "must": need.must, "nice": need.nice, "parsed_by": need.parsed_by})
    return _plan(parse_need(_clean_text(body.text, PLAN_TEXT_MAX)))


class PreviewIn(BaseModel):
    text: str


@router.post("/plan/preview")
def plan_preview(body: PreviewIn):
    """Публичный предпросмотр для демо (только DEMO=1): текст вакансии → как будет собран тест. Ничего не сохраняет, без LLM."""
    if not config.DEMO:
        raise HTTPException(404)
    return _preview(_clean_text(body.text, PREVIEW_TEXT_MAX))


@lru_cache(maxsize=256)
def _preview(text: str) -> dict:
    # ponytail: кэш в памяти процесса; общий кэш (Redis) — если воркеров станет несколько
    return _plan(parse_need(text, use_llm=False))
