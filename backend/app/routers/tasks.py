"""Регулярные задания от работодателей: короткая задача «решить или предложить подход».

Без механик давления: ни серий, ни пушей. Задание приходит вместе с конкретным приглашением или лежит на витрине,
куда кандидат заходит сам. Оценка работодателя — свежий сигнал для других работодателей («решил задачу N дней назад,
оценка…»); на грейд и место в выдаче она не влияет. Контакты по решению не раскрываются — только анонимная карточка.

Задание с эталоном (answer_type ≠ open) система проверяет сама при отправке (services/autocheck): кандидат видит
«совпало / не совпало», работодатель — результат в списке решений и может переоценить вручную (оценка работодателя
главнее автопроверки в сигнале). Эталон отдаётся только компании-автору в её списках; кандидату и другим компаниям — никогда.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import object_session, Session, selectinload

from app import catalog
from app.db import get_db
from app.deps import active_company, current_candidate, current_company
from app.models import Candidate, Company, Invitation, Need, Task, TaskSubmission
from app.routers.employer import company_trust  # employer импортирует tasks лениво — цикла нет
from app.services import autocheck, matching

router = APIRouter(prefix="/api/tasks", tags=["tasks"])

REVIEWS = {"strong": "сильное решение", "ok": "нормально", "weak": "слабо"}
REVIEW_SCORE = {"strong": 3, "ok": 2, "weak": 1}


def _now() -> datetime:
    return datetime.now(UTC)


def task_signal(db: Session, candidate_id: int) -> dict | None:
    """Последнее оценённое решение кандидата — сигнал для карточки у работодателя. В ранжирование не идёт.

    Оценка — работодателя (source=employer) или верный ответ по эталону (source=auto); ручная оценка главнее автопроверки.
    Неверный автоответ в сигнал не идёт: одна неудачная попытка не вытесняет прежнюю оценку у всех работодателей —
    её видит только компания-автор в списке решений.
    """
    at = func.coalesce(TaskSubmission.reviewed_at, TaskSubmission.created_at)
    s = db.scalar(
        select(TaskSubmission)
        .where(TaskSubmission.candidate_id == candidate_id, or_(TaskSubmission.review.is_not(None), TaskSubmission.auto_ok.is_(True)))
        .options(selectinload(TaskSubmission.task).selectinload(Task.company))
        .order_by(at.desc(), TaskSubmission.id.desc())
    )
    if not s:
        return None
    by_employer = s.review is not None
    return {"days_ago": max(0, (_now() - (s.reviewed_at if by_employer else s.created_at)).days), "source": "employer" if by_employer else "auto",
            "review": s.review, "review_text": REVIEWS[s.review] if by_employer else "верный ответ", "auto_ok": s.auto_ok,
            "company_verified": s.task.company.verified, **company_trust(db, s.task.company)}


def _task_out(t: Task, own: bool = False) -> dict:
    """Задание наружу. Эталон — только компании-автору (own=True); кандидату уходят тип ответа и варианты."""
    out = {
        "id": t.id,
        "title": t.title,
        "text": t.text,
        "spec": t.spec,
        "competency": t.competency,
        "kind": t.kind,
        "minutes": t.minutes,
        "public": t.public,
        "need_id": t.need_id,
        "answer_type": t.answer_type,
        "options": t.options,
        "created_at": t.created_at,
        "company": {"id": t.company.id, "name": t.company.name, "color": t.company.color, "verified": t.company.verified,
                    **company_trust(object_session(t), t.company)},
    }
    if own:
        out["reference"] = t.reference
    return out


def _auto(t: Task, s: TaskSubmission | None) -> dict:
    """Результат автопроверки решения: без эталона, только «совпало / не совпало»."""
    return {"auto_ok": s.auto_ok if s else None, "auto_feedback": autocheck.feedback(t.answer_type, s.auto_ok) if s else None}


# ---------- работодатель ----------


class TaskIn(BaseModel):
    title: str = Field(min_length=3, max_length=255)
    text: str = Field(min_length=10, max_length=5000)
    spec: str
    competency: str | None = None
    kind: str = Field(default="approach", pattern="^(solve|approach)$")
    minutes: int = Field(default=45, ge=5, le=240)
    public: bool = True
    need_id: int | None = None
    answer_type: str = "open"
    options: list[str] | None = Field(default=None, max_length=autocheck.OPTIONS_MAX)
    reference: "ReferenceIn | None" = None


class ReferenceIn(BaseModel):
    """Эталон: answers (+exact) — text, value и tolerance — number, correct (номера с 0) — choice / multi, pattern — regex."""

    answers: list[str] | None = Field(default=None, max_length=autocheck.ANSWERS_MAX)
    exact: bool = False
    value: float | None = Field(default=None, allow_inf_nan=False)
    tolerance: float = Field(default=0, ge=0, allow_inf_nan=False)
    correct: list[int] | None = Field(default=None, max_length=autocheck.OPTIONS_MAX)
    pattern: str | None = Field(default=None, max_length=autocheck.PATTERN_LEN)


TaskIn.model_rebuild()


@router.post("")
def create_task(body: TaskIn, co: Company = Depends(active_company), db: Session = Depends(get_db)):
    if body.spec not in catalog.SPECS:
        raise HTTPException(422, f"Специализация: одна из {', '.join(catalog.SPECS)}")
    if body.competency and body.competency not in catalog.COMPETENCIES[body.spec]:
        raise HTTPException(422, f"Компетенция для {body.spec}: одна из {', '.join(catalog.COMPETENCIES[body.spec])}")
    if body.need_id is not None:
        n = db.get(Need, body.need_id)
        if not n or n.company_id != co.id:
            raise HTTPException(404, "Потребность не найдена")
    try:
        options, reference = autocheck.build(body.answer_type, body.options, body.reference.model_dump() if body.reference else None)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    t = Task(company_id=co.id, **body.model_dump(exclude={"options", "reference"}), options=options, reference=reference)
    t.company = co
    db.add(t)
    db.commit()
    return _task_out(t, own=True)


@router.get("/mine")
def my_tasks(co: Company = Depends(current_company), db: Session = Depends(get_db)):
    ts = db.scalars(select(Task).where(Task.company_id == co.id).options(selectinload(Task.company)).order_by(Task.created_at.desc(), Task.id.desc())).all()
    rows = db.execute(
        select(TaskSubmission.task_id, TaskSubmission.review, TaskSubmission.auto_ok, func.count())
        .where(TaskSubmission.task_id.in_([t.id for t in ts]))
        .group_by(TaskSubmission.task_id, TaskSubmission.review, TaskSubmission.auto_ok)
    ).all()
    stats: dict[int, dict] = {t.id: {"submissions": 0, "reviewed": 0, "sum": 0, "auto_checked": 0, "auto_passed": 0} for t in ts}
    for tid, review, auto_ok, n in rows:
        st = stats[tid]
        st["submissions"] += n
        if review:
            st["reviewed"] += n
            st["sum"] += REVIEW_SCORE[review] * n
        if auto_ok is not None:
            st["auto_checked"] += n
            st["auto_passed"] += n if auto_ok else 0
    return [
        {**_task_out(t, own=True), "submissions": st["submissions"], "reviewed": st["reviewed"],
         "avg_review": round(st["sum"] / st["reviewed"], 2) if st["reviewed"] else None,  # 1 — слабо … 3 — сильно
         "auto_checked": st["auto_checked"], "auto_passed": st["auto_passed"]}
        for t in ts
        for st in [stats[t.id]]
    ]


def _own_task(db: Session, co: Company, task_id: int) -> Task:
    t = db.get(Task, task_id)
    if not t or t.company_id != co.id:
        raise HTTPException(404, "Задание не найдено")
    return t


def _published(c: Candidate, co: Company) -> bool:
    """Решение видно работодателю, только пока кандидат согласен на обработку ПДн и публикацию карточки и не скрылся от компании."""
    return matching.consent_ok(c, "processing") and matching.consent_ok(c, "publish") and co.inn not in (c.hidden_from or [])


def _submission_row(s: TaskSubmission, co: Company) -> dict:
    shown = _published(s.candidate, co)
    return {
        "id": s.id,
        "task_id": s.task_id,
        "invitation_id": s.invitation_id,
        "hidden": not shown,  # «кандидат скрыл профиль»: ни ответа, ни карточки
        "answer": s.answer if shown else None,
        "review": s.review,
        "review_comment": s.review_comment,
        **_auto(s.task, s if shown else None),
        "created_at": s.created_at,
        "reviewed_at": s.reviewed_at,
        "candidate": matching.card(s.candidate) if shown else None,  # анонимно: контакты — только через приглашение или отклик
    }


@router.get("/{task_id}/submissions")
def task_submissions(task_id: int, co: Company = Depends(current_company), db: Session = Depends(get_db)):
    t = _own_task(db, co, task_id)
    subs = db.scalars(
        select(TaskSubmission).where(TaskSubmission.task_id == t.id)
        .options(selectinload(TaskSubmission.candidate).selectinload(Candidate.achievements), selectinload(TaskSubmission.candidate).selectinload(Candidate.accounts))
        .order_by(TaskSubmission.created_at.desc(), TaskSubmission.id.desc())
    ).all()
    return {"task": _task_out(t, own=True), "items": [_submission_row(s, co) for s in subs]}


class ReviewIn(BaseModel):
    review: str
    comment: str | None = Field(default=None, max_length=2000)


@router.post("/submissions/{submission_id}/review")
def review_submission(submission_id: int, body: ReviewIn, co: Company = Depends(active_company), db: Session = Depends(get_db)):
    if body.review not in REVIEWS:
        raise HTTPException(422, f"Оценка: одна из {', '.join(REVIEWS)}")
    s = db.get(TaskSubmission, submission_id)
    if not s or s.task.company_id != co.id or not _published(s.candidate, co):
        raise HTTPException(404, "Решение не найдено")
    s.review, s.review_comment, s.reviewed_at = body.review, body.comment, _now()
    db.commit()
    return _submission_row(s, co)


# ---------- кандидат ----------


def _live(inv: Invitation) -> bool:
    """Приглашение действует: принято или ещё ждёт ответа и не истекло (истечение ленивое — проверяем срок)."""
    return inv.status == "accepted" or (inv.status in matching.OPEN and inv.expires_at > _now())


def _via_invite(t: Task, inv: Invitation) -> bool:
    """Непубличное задание доступно по приглашению той же потребности."""
    return t.need_id is not None and inv.need_id == t.need_id and inv.company_id == t.company_id and _live(inv)


def _can_see(db: Session, c: Candidate, t: Task) -> bool:
    """Публичное задание своей специализации или задание из действующего приглашения по той же потребности.
    Задания заблокированной компании (services/reputation.py) не видны."""
    if t.company.blocked_at:
        return False
    if t.public and t.spec == c.spec:
        return True
    if t.need_id is None:
        return False
    invs = db.scalars(select(Invitation).where(Invitation.candidate_id == c.id, Invitation.need_id == t.need_id))
    return any(_via_invite(t, i) for i in invs)


def _submitted(db: Session, c: Candidate) -> dict[int, TaskSubmission]:
    return {s.task_id: s for s in db.scalars(select(TaskSubmission).where(TaskSubmission.candidate_id == c.id))}


@router.get("/showcase")
def showcase(c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    """Витрина: публичные задания своей специализации. Кандидат заходит сам — уведомлений нет."""
    ts = db.scalars(
        select(Task).join(Company).where(Task.public.is_(True), Task.spec == c.spec, Company.blocked_at.is_(None)).options(selectinload(Task.company)).order_by(Task.created_at.desc(), Task.id.desc())
    ).all()
    return _for_candidate(ts, _submitted(db, c))


def _for_candidate(ts: list[Task], mine: dict[int, TaskSubmission]) -> list[dict]:
    return [{**_task_out(t), "submitted": t.id in mine, "review": mine[t.id].review if t.id in mine else None, **_auto(t, mine.get(t.id))}
            for t in ts]


def _my_submission(s: TaskSubmission) -> dict:
    return {"id": s.id, "task": _task_out(s.task), "invitation_id": s.invitation_id, "answer": s.answer, "review": s.review,
            "review_comment": s.review_comment, **_auto(s.task, s), "created_at": s.created_at, "reviewed_at": s.reviewed_at}


@router.get("/submissions/mine")
def my_submissions(c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    subs = db.scalars(
        select(TaskSubmission).where(TaskSubmission.candidate_id == c.id)
        .options(selectinload(TaskSubmission.task).selectinload(Task.company))
        .order_by(TaskSubmission.created_at.desc(), TaskSubmission.id.desc())
    ).all()
    return [_my_submission(s) for s in subs]


@router.get("/for-invitation/{invitation_id}")
def tasks_for_invitation(invitation_id: int, c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    """Задания из приглашения: задания той же компании по потребности приглашения. Чужое или неактивное → 404."""
    inv = db.get(Invitation, invitation_id)
    if not inv or inv.candidate_id != c.id or not _live(inv):
        raise HTTPException(404, "Приглашение не найдено")
    if inv.need_id is None or inv.company.blocked_at:
        return []
    ts = db.scalars(
        select(Task).where(Task.company_id == inv.company_id, Task.need_id == inv.need_id)
        .options(selectinload(Task.company)).order_by(Task.created_at.desc(), Task.id.desc())
    ).all()
    return _for_candidate(ts, _submitted(db, c))


@router.get("/{task_id}")
def get_task(task_id: int, c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    t = db.get(Task, task_id)
    if not t or not _can_see(db, c, t):
        raise HTTPException(404, "Задание не найдено")
    return _for_candidate([t], _submitted(db, c))[0]


class SubmitIn(BaseModel):
    answer: str = Field(default="", max_length=5000)  # для choice / multi не нужен — выбор передаётся в choices
    choices: list[int] | None = Field(default=None, max_length=autocheck.OPTIONS_MAX)  # номера вариантов с 0
    invitation_id: int | None = None


@router.post("/{task_id}/submit")
def submit(task_id: int, body: SubmitIn, c: Candidate = Depends(current_candidate), db: Session = Depends(get_db)):
    t = db.get(Task, task_id)
    if not t or t.company.blocked_at:
        raise HTTPException(404, "Задание не найдено")
    if body.invitation_id is not None:
        # ponytail: задание «из приглашения» = та же потребность; явная связь Invitation.task_id, если понадобится точность
        inv = db.get(Invitation, body.invitation_id)
        if not inv or inv.candidate_id != c.id or inv.company_id != t.company_id or not _live(inv):
            raise HTTPException(404, "Приглашение не найдено")
        if not (_via_invite(t, inv) or (t.public and t.spec == c.spec)):
            raise HTTPException(404, "Задание не найдено")
    elif not _can_see(db, c, t):
        raise HTTPException(404, "Задание не найдено")
    if not matching.consent_ok(c, "processing"):
        raise HTTPException(403, "Нужно согласие на обработку персональных данных")
    if db.scalar(select(TaskSubmission.id).where(TaskSubmission.task_id == t.id, TaskSubmission.candidate_id == c.id)):
        raise HTTPException(409, "Решение уже отправлено")  # до сверки: повтор не тратит время на шаблон
    try:
        answer = autocheck.answer_text(t.answer_type, t.options, body.answer, body.choices)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    auto_ok = autocheck.check(t.answer_type, t.options, t.reference, body.answer, body.choices)
    s = TaskSubmission(task_id=t.id, candidate_id=c.id, invitation_id=body.invitation_id, answer=answer, auto_ok=auto_ok)
    db.add(s)
    try:
        db.commit()  # дубль ловит уникальный индекс (task_id, candidate_id) — и при гонке двух запросов
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Решение уже отправлено") from None
    return _my_submission(s)
