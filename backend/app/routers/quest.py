"""Тест-квест: адаптивная сессия на IRT → категория «специализация × трек × грейд».

Ответ сохраняется сразу; правильность и текущий θ до конца теста не отдаются. Ключ задания (payload.key) наружу не уходит.
Текущее (выданное, но не отвеченное) задание — последняя запись в QuestSession.answers с response = None.

Задача на код (kind = code): ответ — {lang, code}; решение прогоняется в песочнице на скрытых тестах (пересоздаются из сида
клона), засчитано — все тесты пройдены (2PL, как остальные). В сессию пишется сводка по тестам без входных данных.
Песочница недоступна — 503, задание помечается void и не засчитывается ни в плюс, ни в минус.
"""

import json
import random
import threading
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import catalog, config
from app.db import get_db
from app.deps import current_candidate, current_company
from app.models import Candidate, Company, ExternalAccount, Invitation, Item, Need, QuestSession
from app.services import code_items, irt, sandbox
from app.services.items import STORY, plan_for_need
from app.services.parsing import parse_need

router = APIRouter(prefix="/api/quest", tags=["quest"])

PILOT_AT = 3  # пилотное задание выдаётся после трёх рабочих
TIMEOUT_GRACE_S = 30  # запас на сеть; позже — ответ засчитывается как неверный
PERCENTILE_MIN_N = 10  # меньше кандидатов в категории → перцентиль по специализации
PLAN_TEXT_MAX, PREVIEW_TEXT_MAX = 5000, 2000
VERDICT = {"confirmed": "Заявленный грейд подтверждён", "below": "Ниже заявленного грейда", "above": "Выше заявленного грейда"}
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
CODE_LANGS = ("python", "typescript")
CODE_MAX = 20_000  # байт решения (столько же принимает песочница)
RUNS_MAX = 20  # запусков «на примерах» на одну задачу
PASTE_SHARE = 0.5  # флаг code_pasted: верное решение, больше половины которого вставлено из буфера
SANDBOX_DOWN = "Песочница для проверки кода сейчас недоступна. Задание не засчитано ни в плюс, ни в минус — переходим к следующему."
SANDBOX_BUSY = "Песочница сейчас занята, решение не проверено. Отправьте его ещё раз через минуту: время ответа считается по первой отправке."
RUN_GAP_S = 3  # пауза между запусками на примерах

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
    target_grade: str | None = None  # грейд, на который проходит тест; по умолчанию — заявленный в профиле
    invitation_id: int | None = None  # тест по приглашению: выбор заданий смещается к компетенциям вакансии


class PlanIn(BaseModel):
    text: str | None = None
    need_id: int | None = None


class AnswerIn(BaseModel):
    item_id: int
    response: int | None = None  # choice — индекс варианта с 0; mark/review — номер строки кода с 1
    comment: str | None = None  # комментарий к ревью; на оценку пока не влияет
    ms: int | None = None  # время ответа по часам клиента
    lang: str | None = None  # задача на код: python | typescript
    code: str | None = Field(None, max_length=CODE_MAX)
    pasted: int | None = None  # задача на код: сколько символов вставлено из буфера (по данным клиента, для флага)


class RunIn(BaseModel):
    item_id: int
    lang: str
    code: str = Field(max_length=CODE_MAX)


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
    """Отвеченные задания; void (песочница не проверила решение) не засчитываются никак."""
    return [a for a in sess.answers if a["response"] is not None and not a.get("void") and a["item_id"] in bank]


def _items(bank: dict[int, Item], live: bool = False) -> list[Item]:
    """Задания, которые можно выдавать: задачи на код — только при настроенной песочнице (live — и живой сейчас)."""
    if not any(it.kind == "code" for it in bank.values()):
        return list(bank.values())
    code_ok = sandbox.ready() if live else sandbox.enabled()
    return [it for it in bank.values() if it.kind != "code" or code_ok]


_checking: set[int] = set()
_checking_lock = threading.Lock()


@contextmanager
def _one_check(session_id: int):
    """Одна проверка кода на сессию за раз (двойной клик, «Запустить» во время «Отправить»).
    ponytail: в памяти одного процесса; при нескольких воркерах — блокировка в Redis/Postgres."""
    with _checking_lock:
        if session_id in _checking:
            raise HTTPException(429, "Решение уже проверяется — дождитесь результата")
        _checking.add(session_id)
    try:
        yield
    finally:
        with _checking_lock:
            _checking.discard(session_id)


def _code_in(lang: str | None, code: str | None) -> tuple[str, str]:
    if lang not in CODE_LANGS:
        raise HTTPException(422, "Язык решения — python или typescript")
    if not code or not code.strip():
        raise HTTPException(422, "Пустое решение")
    if len(code.encode("utf-8")) > CODE_MAX:
        raise HTTPException(422, f"Решение длиннее {CODE_MAX // 1000} КБ")
    return lang, code


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
    items = _items(bank, live=True)
    seen = {a["item_id"] for a in sess.answers}
    fams = {bank[i].family for i in seen if i in bank}
    n_op = sum(1 for a in sess.answers if not a["pilot"] and not a.get("void"))
    item = None
    if n_op == PILOT_AT and not any(a["pilot"] for a in sess.answers):
        item = irt.pick_pilot(items, seen, fams, rng)
    if item is None and not irt.should_stop(n_op, sess.se):
        item = irt.choose(sess.theta, items, seen, fams, rng, n_op, focus=sess.focus)
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
    items = _items(bank)
    n_fam = len({it.family for it in items if not it.pilot and it.kind != "code"}) + any(it.kind == "code" and not it.pilot for it in items)
    total = min(irt.MAX_ITEMS, n_fam) + (1 if any(it.pilot for it in items) else 0)
    out = {"session_id": sess.id, "quest_title": STORY.get(spec, ("Тест",))[0],
           "story": sess.story, "target_grade": sess.target_grade, "focus": sess.focus, "done": pend is None, "progress": {"n": len(sess.answers), "total": max(total, len(sess.answers))},
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
                            target_grade=target, focus=focus)
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
    # задача на код: если песочница была занята, время ответа — по первой отправке (submitted_at), а не по повторной
    answered_at = datetime.fromisoformat(pend["submitted_at"]) if pend.get("submitted_at") else _now()
    server_ms = int((answered_at - datetime.fromisoformat(pend["served_at"])).total_seconds() * 1000)
    timeout = server_ms > (p["time_limit_s"] + TIMEOUT_GRACE_S) * 1000
    if item.kind == "code":
        return _answer_code(db, cand, sess, pend, item, body, server_ms, timeout)
    lo, n = (0, len(p["options"])) if item.kind == "choice" else (1, len(p["panel"]["lines"]))
    if body.response is None or not lo <= body.response < lo + n:
        raise HTTPException(422, "Некорректный ответ")
    key = p["key"] if isinstance(p["key"], list) else [p["key"]]
    done = {**pend, "response": body.response, "correct": not timeout and body.response in key, "timeout": timeout,
            "ms": body.ms, "server_ms": server_ms, "comment": (body.comment or "").strip()[:2000] or None}
    sess.answers = [*sess.answers[:-1], done]
    if not item.pilot:
        sess.theta, sess.se = irt.eap(_responses(sess, bank), sess.prior_mean)
    _serve(sess, bank)
    db.commit()
    return {"saved": True, **_state(sess, bank, cand.spec)}


def _answer_code(db: Session, cand: Candidate, sess: QuestSession, pend: dict, item: Item, body: AnswerIn, server_ms: int, timeout: bool):
    """Решение задачи на код. Песочница работает до минуты — блокировку сессии на это время отпускаем,
    после прогона берём снова и проверяем, что задание всё ещё текущее (served_at — отпечаток выдачи)."""
    lang, code = _code_in(body.lang, body.code)
    sid, served_at = sess.id, pend["served_at"]
    db.commit()
    submitted_at = pend.get("submitted_at") or _now().isoformat()
    res, down, busy = None, False, False
    if not timeout:  # опоздавший ответ — неверный, как у остальных заданий; песочницу не гоняем
        with _one_check(sid):
            try:
                res = sandbox.run(lang, code, item.payload["code"]["entry"][lang], code_items.hidden_tests(item.family, item.payload["key"]["seed"]),
                                  time_ms=code_items.TIME_MS, memory_mb=code_items.MEMORY_MB, fail_fast=True)
            except sandbox.Busy:
                busy = True
            except sandbox.Unavailable:
                down = True
    sess = _active(db, cand, lock=True)
    pend = _pending(sess) if sess else None
    if not pend or pend["item_id"] != item.id or pend["served_at"] != served_at:
        raise HTTPException(409, "Ответ на это задание уже сохранён")
    if busy:
        # перегрузка — не сбой: задание остаётся текущим, время ответа фиксируется по первой отправке
        sess.answers = [*sess.answers[:-1], {**pend, "submitted_at": submitted_at}]
        db.commit()
        raise HTTPException(503, SANDBOX_BUSY)
    bank = _bank(db, cand.spec)
    rec = {**pend, "lang": lang, "code": code, "pasted": max(0, min(body.pasted or 0, len(code))), "ms": body.ms, "server_ms": server_ms,
           "comment": None, "timeout": timeout}
    if down:
        sess.answers = [*sess.answers[:-1], {**rec, "response": "void", "void": True, "correct": None}]
        _serve(sess, bank)
        db.commit()
        raise HTTPException(503, SANDBOX_DOWN)
    tests = res and {"status": res["status"], "passed": res["passed"], "total": res["total"],
                     "statuses": [r["status"] for r in res["results"]], "max_ms": max((r["time_ms"] for r in res["results"]), default=0)}
    sess.answers = [*sess.answers[:-1], {**rec, "response": lang, "correct": bool(res) and res["status"] == "ok", "tests": tests}]
    if not item.pilot:
        sess.theta, sess.se = irt.eap(_responses(sess, bank), sess.prior_mean)
    _serve(sess, bank)
    db.commit()
    return {"saved": True, **_state(sess, bank, cand.spec)}


@router.post("/run")
def run_examples(body: RunIn, cand: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    """«Запустить на примерах»: только открытые примеры из условия, на оценку не влияет, до RUNS_MAX раз на задачу.
    Возвращает статусы, вывод функции и короткий фрагмент ошибки — по открытым примерам это ничего не раскрывает."""
    sess = _active_or_404(db, cand, lock=True)
    pend = _pending(sess)
    if not pend or pend["item_id"] != body.item_id:
        raise HTTPException(409, "Это не текущее задание")
    item = db.get(Item, body.item_id)
    if not item or item.kind != "code":
        raise HTTPException(409, "Запуск на примерах — только для задач на код")
    lang, code = _code_in(body.lang, body.code)
    runs = pend.get("runs", 0)
    if runs >= RUNS_MAX:
        raise HTTPException(429, f"Запусков на примерах уже {RUNS_MAX} — отправьте решение")
    last = pend.get("run_at")
    if last and (_now() - datetime.fromisoformat(last)).total_seconds() < RUN_GAP_S:
        raise HTTPException(429, "Слишком часто: подождите пару секунд")
    sid, served_at = sess.id, pend["served_at"]
    db.commit()  # блокировку на время прогона отпускаем; запуск засчитывается только удачный (ниже)
    ex = item.payload["code"]["examples"]
    with _one_check(sid):
        try:
            res = sandbox.run(lang, code, item.payload["code"]["entry"][lang], ex, time_ms=code_items.TIME_MS, memory_mb=code_items.MEMORY_MB, echo=True)
        except sandbox.Busy:
            raise HTTPException(503, "Песочница сейчас занята — запустите ещё раз через минуту. Запуск не засчитан.") from None
        except sandbox.Unavailable:
            raise HTTPException(503, "Песочница сейчас недоступна, запуск на примерах не удался. Решение можно отправить: при сбое проверки задание не засчитается.") from None
    sess = _active(db, cand, lock=True)
    pend = _pending(sess) if sess else None
    if pend and pend["item_id"] == item.id and pend["served_at"] == served_at:
        runs = pend.get("runs", 0)
        sess.answers = [*sess.answers[:-1], {**pend, "runs": runs + 1, "run_at": _now().isoformat()}]
        db.commit()
    return {"status": res["status"], "passed": res["passed"], "total": res["total"], "stderr": res.get("stderr"), "runs_left": max(0, RUNS_MAX - runs - 1),
            "results": [{"status": r["status"], "time_ms": r["time_ms"], "got": r.get("got"), "expected": json.dumps(e["expected"], ensure_ascii=False)}
                        for r, e in zip(res["results"], ex)]}


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
    timings = [(a["server_ms"], bank[a["item_id"]].payload["time_limit_s"]) for a in _answered(sess, bank) if not a["pilot"]]
    flags = irt.suspicion_flags(theta, resp, timings)
    # верное решение задачи на код, больше половины которого вставлено из буфера (данные клиента — обходится, только сигнал)
    if any(a.get("correct") and a.get("pasted", 0) >= PASTE_SHARE * len(a.get("code") or "") > 0
           for a in _answered(sess, bank) if bank[a["item_id"]].kind == "code"):
        flags.append("code_pasted")

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
    if (senior_plus and not cand.review_passed) or {"inconsistent", "too_fast", "code_pasted"} & set(flags):
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
            "story": s.story,
            "focus": bool(s.focus),
            "theta": round(s.theta, 2) if done else None,
            "se": round(s.se, 2) if done else None,
            "grade": s.grade if done else None,
            "applied": s.applied if done else None,
            "flags": s.flags or [],
            "items": sum(1 for a in s.answers if a["response"] is not None and not a.get("void")),
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
