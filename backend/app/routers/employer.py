"""Кабинет работодателя: компания, потребности, подборка, карточка кандидата, приглашения, воронка, квота."""

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from app import catalog
from app.db import get_db
from app.deps import current_company, current_user, current_verified_company
from app.models import Candidate, Company, Invitation, Lottery, Need, User
from app.services import matching
from app.services.parsing import canon_skills, parse_need

router = APIRouter(prefix="/api/employer", tags=["employer"])

MSK = ZoneInfo("Europe/Moscow")
MONTHS = ["янв", "фев", "мар", "апр", "мая", "июн", "июл", "авг", "сен", "окт", "ноя", "дек"]
PIPE_STATUS = {"sent": "sent", "seen": "seen", "accepted": "ok", "declined": "no", "expired": "exp"}
FILTERS = {"fmt", "free", "fsp", "cf"}


def rub(n: int) -> str:
    return f"{n:,}".replace(",", " ") + " ₽"


# ---------- правила (чистые функции) ----------


def inn_valid(inn: str) -> bool:
    """Контрольные цифры ИНН: 10 знаков — юрлицо, 12 — ИП/физлицо."""
    if not inn.isdigit() or len(inn) not in (10, 12):
        return False
    d = [int(x) for x in inn]

    def check(coefs: list[int]) -> int:
        return sum(a * b for a, b in zip(d, coefs)) % 11 % 10

    if len(d) == 10:
        return check([2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[9]
    return check([7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[10] and check([3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8]) == d[11]


def domain_match(email: str, site_domain: str | None) -> bool:
    if not site_domain or "@" not in email:
        return False
    dom = email.rsplit("@", 1)[1].lower()
    site = site_domain.lower().removeprefix("https://").removeprefix("http://").removeprefix("www.").strip("/")
    return dom == site or dom.endswith("." + site)


def validate_fork(salary_from: int | None, salary_to: int | None, *, p25: int, cand_min: int | None, grade: str) -> tuple[list[str], list[str]]:
    """Правила вилки приглашения → (ошибки, блокируют отправку; предупреждения, не блокируют)."""
    errors, warnings = [], []
    if not salary_from or not salary_to:
        return ["Укажите обе границы вилки."], warnings
    if salary_from > salary_to:
        errors.append("Нижняя граница больше верхней.")
    if salary_from < p25:
        errors.append(f"Нижняя граница ниже 25-го перцентиля рынка для {grade} ({rub(p25)}).")
    if (salary_to - salary_from) / salary_from > catalog.FORK_MAX_WIDTH:
        errors.append(f"Вилка слишком широкая: верхняя граница не больше нижней + {round(catalog.FORK_MAX_WIDTH * 100)} %.")
    if cand_min and salary_to < cand_min:
        p = f"{matching.accept_prob(salary_to, cand_min, True, 1.0):.2f}".replace(".", ",")
        warnings.append(f"Верхняя граница ниже минимума кандидата ({rub(cand_min)}). Вероятность принятия упадёт примерно до {p}.")
    return errors, warnings


# ---------- квота ----------


def _week_start(now: datetime) -> datetime:
    local = now.astimezone(MSK)
    return (local - timedelta(days=local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


def _accepted_share(db: Session, company_id: int, before: datetime | None = None) -> float | None:
    q = select(Invitation.status, func.count()).where(Invitation.company_id == company_id, Invitation.status.in_(("accepted", "declined", "expired")))
    if before:
        q = q.where(Invitation.sent_at < before)
    counts = dict(db.execute(q.group_by(Invitation.status)).all())
    total = sum(counts.values())
    return round(counts.get("accepted", 0) / total, 2) if total else None


def quota(db: Session, co: Company) -> dict:
    """Недельная квота (сброс в понедельник 00:00 МСК). Лимит растёт до QUOTA_BONUS, если в прошлые недели
    принято ≥ 50 % закрытых приглашений. Оплата — только за принятые."""
    start = _week_start(datetime.now(UTC))
    used = db.scalar(select(func.count()).select_from(Invitation).where(Invitation.company_id == co.id, Invitation.sent_at >= start))
    bonus = lambda share: max(co.quota_max, catalog.QUOTA_BONUS) if share is not None and share >= catalog.QUOTA_BONUS_AT else co.quota_max
    share = _accepted_share(db, co.id)
    mx = bonus(_accepted_share(db, co.id, before=start))
    paid = db.scalar(select(func.count()).select_from(Invitation).where(Invitation.company_id == co.id, Invitation.status == "accepted"))
    return {"used": used, "max": mx, "left": max(0, mx - used), "resets_at": start + timedelta(days=7), "accepted_share": share, "next_max": bonus(share), "paid_accepts": paid}


# ---------- компания ----------


class CompanyIn(BaseModel):
    inn: str
    name: str = Field(min_length=2, max_length=255)
    about: str | None = None
    color: str | None = Field(default=None, pattern=r"^#[0-9A-Fa-f]{6}$")
    site_domain: str | None = Field(default=None, max_length=128)
    recruiter_name: str = Field(min_length=1, max_length=255)
    recruiter_email: str | None = None  # по умолчанию — почта входа
    recruiter_tg: str | None = Field(default=None, max_length=64)


def _checks(co: Company, login_email: str) -> list[dict]:
    inn_ok = inn_valid(co.inn)
    dom_ok = domain_match(login_email, co.site_domain)  # почта входа подтверждена кодом, recruiter_email — нет
    return [
        {"key": "inn", "ok": inn_ok, "text": "ИНН: контрольные цифры верны" if inn_ok else "ИНН: контрольные цифры не сходятся"},
        # ponytail: ЕГРЮЛ не запрашивается; API ФНС (egrul.nalog.ru) или DaData, когда будет ключ
        {"key": "egrul", "ok": None, "text": "ЕГРЮЛ: проверка статуса организации не выполнялась (заглушка)"},
        {"key": "domain", "ok": dom_ok, "text": "Домен почты совпадает с сайтом компании" if dom_ok else "Домен почты не совпадает с сайтом компании"},
    ]


def _company_out(db: Session, co: Company) -> dict:
    return {
        "id": co.id,
        "inn": co.inn,
        "name": co.name,
        "about": co.about,
        "color": co.color,
        "site_domain": co.site_domain,
        "recruiter_name": co.recruiter_name,
        "recruiter_email": co.recruiter_email,
        "recruiter_tg": co.recruiter_tg,
        "verified": co.verified,
        "checks": _checks(co, db.get(User, co.user_id).email if co.user_id else ""),
        "quota": quota(db, co),
    }


@router.post("/company")
def save_company(body: CompanyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role != "employer":
        raise HTTPException(403, "Регистрация компании доступна только работодателям")
    inn = body.inn.strip()
    if not inn.isdigit() or len(inn) not in (10, 12):
        raise HTTPException(422, "ИНН — 10 или 12 цифр")
    other = db.scalar(select(Company).where(Company.inn == inn))
    co = db.scalar(select(Company).where(Company.user_id == user.id))
    if other and other is not co:
        raise HTTPException(409, "Компания с таким ИНН уже зарегистрирована")
    if co and co.inn != inn:
        raise HTTPException(409, "ИНН компании после регистрации менять нельзя")
    if not co:
        co = Company(user_id=user.id)
        db.add(co)
    co.inn, co.name, co.about = inn, body.name, body.about
    co.color = body.color or co.color or "#402FFF"
    co.site_domain, co.recruiter_name = body.site_domain, body.recruiter_name
    co.recruiter_email, co.recruiter_tg = body.recruiter_email or user.email, body.recruiter_tg
    co.verified = inn_valid(inn) and domain_match(user.email, co.site_domain)
    db.commit()
    return _company_out(db, co)


@router.get("/company")
def get_company(co: Company = Depends(current_company), db: Session = Depends(get_db)):
    return _company_out(db, co)


# ---------- потребности ----------


class ParseIn(BaseModel):
    text: str = Field(min_length=5, max_length=5000)


class NeedIn(BaseModel):
    text: str = ""
    spec: str
    track: str | None = None
    grade: str
    must: list[str] = []
    nice: list[str] = []
    salary_from: int | None = Field(default=None, gt=0)
    salary_to: int | None = Field(default=None, gt=0)
    format: str | None = None
    city: str | None = Field(default=None, max_length=64)
    parsed_by: str = "rules"


def _need_out(n: Need) -> dict:
    return {
        "id": n.id,
        "text": n.text,
        "spec": n.spec,
        "track": n.track,
        "grade": n.grade,
        "must": n.must,
        "nice": n.nice,
        "from": n.salary_from,
        "to": n.salary_to,
        "format": n.format,
        "city": n.city,
        "parsed_by": n.parsed_by,
        "created_at": n.created_at,
    }


def _category_count(db: Session, spec: str, track: str | None, grade: str) -> int:
    q = select(func.count()).select_from(Candidate).where(Candidate.spec == spec, Candidate.grade == grade, Candidate.status == "open", Candidate.theta.is_not(None))
    if track:
        q = q.where(Candidate.track == track)
    return db.scalar(q)


def _market_hint(salary_to: int | None, mkt: dict) -> str | None:
    if not salary_to:
        return None
    if salary_to >= mkt["p50"]:
        return f"Ваша вилка выше медианы рынка ({rub(mkt['p50'])})."
    if salary_to >= mkt["p25"]:
        return f"Верхняя граница ниже медианы рынка ({rub(mkt['p50'])}): часть кандидатов откажет по зарплате."
    return f"Верхняя граница ниже 25-го перцентиля рынка ({rub(mkt['p25'])}): приглашения не пройдут проверку вилки."


@router.post("/needs/parse")
def parse(body: ParseIn, co: Company = Depends(current_company), db: Session = Depends(get_db)):
    """Текст → структура для правки. Ничего не сохраняет."""
    n = parse_need(body.text)
    mkt = catalog.market(n["spec"], n["grade"], n["city"])
    return {
        **n,
        "text": body.text,
        "from": n["salary_from"],
        "to": n["salary_to"],
        "market": mkt,
        "category": {"spec": n["spec"], "track": n["track"], "grade": n["grade"], "count": _category_count(db, n["spec"], n["track"], n["grade"])},
        "market_hint": _market_hint(n["salary_to"], mkt),
    }


@router.post("/needs")
def create_need(body: NeedIn, co: Company = Depends(current_company), db: Session = Depends(get_db)):
    if body.spec not in catalog.SPECS:
        raise HTTPException(422, f"Специализация: одна из {', '.join(catalog.SPECS)}")
    if body.track and body.track not in catalog.TRACKS[body.spec]:
        raise HTTPException(422, f"Трек для {body.spec}: один из {', '.join(catalog.TRACKS[body.spec])}")
    if body.grade not in catalog.GRADES:
        raise HTTPException(422, f"Грейд: один из {', '.join(catalog.GRADES)}")
    if body.format and body.format not in catalog.FORMATS:
        raise HTTPException(422, f"Формат: один из {', '.join(catalog.FORMATS)}")
    if body.salary_from and body.salary_to and body.salary_from > body.salary_to:
        raise HTTPException(422, "Нижняя граница вилки больше верхней")
    must = canon_skills(body.must)
    n = Need(
        company_id=co.id,
        text=body.text,
        spec=body.spec,
        track=body.track,
        grade=body.grade,
        must=must,
        nice=[s for s in canon_skills(body.nice) if s not in must],
        salary_from=body.salary_from,
        salary_to=body.salary_to,
        format=body.format,
        city=body.city,
        parsed_by=body.parsed_by if body.parsed_by in ("rules", "llm") else "rules",
    )
    n.embedding = matching.embed_need(n)
    db.add(n)
    db.commit()
    return _need_out(n)


@router.get("/needs")
def list_needs(co: Company = Depends(current_company), db: Session = Depends(get_db)):
    return [_need_out(n) for n in db.scalars(select(Need).where(Need.company_id == co.id).order_by(Need.created_at.desc(), Need.id.desc()))]


def _own_need(db: Session, co: Company, need_id: int) -> Need:
    n = db.get(Need, need_id)
    if not n or n.company_id != co.id:
        raise HTTPException(404, "Потребность не найдена")
    return n


def _categories(db: Session, n: Need) -> list[dict]:
    """Рекомендованные категории: точная, соседние треки того же грейда, тот же трек грейдом выше/ниже."""
    gi = catalog.GRADES.index(n.grade)
    grades = catalog.GRADES[max(0, gi - 1) : gi + 2]
    rows = db.execute(
        select(Candidate.track, Candidate.grade, func.count())
        .where(Candidate.spec == n.spec, Candidate.grade.in_(grades), Candidate.status == "open", Candidate.theta.is_not(None))
        .group_by(Candidate.track, Candidate.grade)
    ).all()
    counts = {(t, g): k for t, g, k in rows}
    picks = [(n.track, n.grade)]
    picks += sorted(((t, g) for (t, g) in counts if g == n.grade and t != n.track), key=lambda k: -counts[k])[:2]
    picks += [(n.track, g) for g in grades if g != n.grade]
    out = []
    for t, g in picks:
        mkt = catalog.market(n.spec, g, n.city)
        fork_ok = (n.salary_from or 0) >= mkt["p25"]
        # «типичный минимум» кандидата категории ≈ p25 рынка; вилка до → оценка вероятности принятия
        acc = round(matching.accept_prob(n.salary_to or mkt["p50"], mkt["p25"], True, 1.0), 2)
        note = None
        if t != n.track:
            note = f"Соседний трек: стек {t}, навыки частично переносимы"
        elif g != n.grade and not fork_ok:
            note = f"Для {g} ваша вилка ниже рынка: вероятность принятия около {str(acc).replace('.', ',')}"
        elif g != n.grade:
            note = f"Грейд {g}: вилка в рынке"
        out.append({"spec": n.spec, "track": t, "grade": g, "count": counts.get((t, g), 0), "current": (t, g) == (n.track, n.grade), "fork_ok": fork_ok, "accept": acc, "note": note})
    return out


def _passes(card: dict, filters: set[str]) -> bool:
    return (
        ("fmt" not in filters or card["fmtOk"])
        and ("free" not in filters or not card["busy"])
        and ("fsp" not in filters or card["fsp"])
        and ("cf" not in filters or card["cf"])
    )


def _invited(db: Session, co: Company, candidate_ids: list[int]) -> dict[int, str]:
    if not candidate_ids:
        return {}
    rows = db.execute(
        select(Invitation.candidate_id, Invitation.status).where(Invitation.company_id == co.id, Invitation.candidate_id.in_(candidate_ids)).order_by(Invitation.sent_at)
    ).all()
    return {cid: PIPE_STATUS[st] for cid, st in rows}  # последнее приглашение побеждает


@router.get("/needs/{need_id}/picks")
def picks(
    need_id: int,
    filters: str = "",
    variant: str = Query("full", pattern="^(embed|rerank|full)$"),
    limit: int = Query(50, ge=1, le=500),
    co: Company = Depends(current_verified_company),
    db: Session = Depends(get_db),
):
    n = _own_need(db, co, need_id)
    active = {f for f in filters.split(",") if f}
    if active - FILTERS:
        raise HTTPException(422, f"Фильтры: {', '.join(sorted(FILTERS))}")
    ranked = matching.rank(db, n, variant=variant, limit=10**6, company=co)
    invited = _invited(db, co, [r.candidate.id for r in ranked])
    items = []
    for i, r in enumerate(ranked, 1):
        c = matching.card(r.candidate, ranked=r, need=n)
        if not _passes(c, active):
            continue  # фильтр сужает список, порядок сохраняется
        c["rank"] = i
        c["invited"] = invited.get(r.candidate.id)
        c["why"] = r.explanation.get("why")
        items.append(c)
        if len(items) >= limit:
            break
    return {
        "need": _need_out(n),
        "total": len(ranked),
        "items": items,
        "filters": sorted(active),
        "categories": _categories(db, n),
        "market": catalog.market(n.spec, n.grade, n.city),
        "quota": quota(db, co),
        "cap": catalog.CANDIDATE_CAP,
    }


def _visible(db: Session, co: Company, public_id: str) -> Candidate:
    c = db.scalar(
        select(Candidate).where(Candidate.public_id == public_id).options(selectinload(Candidate.achievements), selectinload(Candidate.accounts))
    )
    if not c or c.status != "open" or c.theta is None or co.inn in (c.hidden_from or []):
        raise HTTPException(404, "Кандидат не найден")
    return c


@router.get("/candidates/{public_id}")
def candidate_card(public_id: str, need_id: int | None = None, co: Company = Depends(current_verified_company), db: Session = Depends(get_db)):
    c = _visible(db, co, public_id)
    n = _own_need(db, co, need_id) if need_id else None
    r = matching.score_candidates(db, n, [c], limit=1)[0] if n else None
    out = matching.card(c, ranked=r, need=n)
    if r is None:
        out["load"] = matching.candidate_loads(db, [c.id])[c.id]
        out["busy"] = out["load"] >= catalog.CANDIDATE_CAP
    out["competencies"] = c.competencies or []
    out["explanation"] = r.explanation if r else None
    out["breakdown"] = r.explanation["parts"] if r else None
    out["market"] = catalog.market(c.spec, c.grade, n.city if n else c.city)
    out["invited"] = _invited(db, co, [c.id]).get(c.id)
    out["cap"] = catalog.CANDIDATE_CAP
    return out


# ---------- приглашения ----------


class InviteIn(BaseModel):
    candidate_id: str  # public_id, например «A-1042»
    need_id: int | None = None
    role: str = Field(min_length=3, max_length=255)
    salary_from: int | None = None
    salary_to: int | None = None
    format: str = Field(max_length=64)  # «Гибрид» или «Гибрид, Москва, 2 дня в офисе»
    description: str = Field(default="", max_length=5000)
    task: str | None = Field(default=None, max_length=2000)
    lottery_id: int | None = None  # приглашение по жребию: кандидат должен быть среди выбранных


def _row(inv: Invitation) -> dict:
    c = inv.candidate
    contact = None
    if inv.status == "accepted":
        contact = {"name": c.name, "email": c.email, "tg": c.tg, "text": " · ".join(x for x in (c.name, c.email, c.tg) if x)}
    sent = inv.sent_at.astimezone(MSK)
    return {
        "id": inv.id,
        "cid": c.public_id,
        "need_id": inv.need_id,
        "lottery_id": inv.lottery_id,
        "role": inv.role,
        "from": inv.salary_from,
        "to": inv.salary_to,
        "format": inv.format,
        "status": PIPE_STATUS[inv.status],
        "reason": catalog.DECLINE_REASONS.get(inv.decline_reason),  # комментарий кандидата компании не показываем
        "when": f"{sent.day} {MONTHS[sent.month - 1]}",
        "sent_at": inv.sent_at,
        "expires_at": inv.expires_at,
        "contact": contact,
        "fb": catalog.FEEDBACK.get(inv.feedback),
        "feedback": inv.feedback,
    }


@router.post("/invites")
def send_invite(body: InviteIn, co: Company = Depends(current_verified_company), db: Session = Depends(get_db)):
    c = _visible(db, co, body.candidate_id)
    n = _own_need(db, co, body.need_id) if body.need_id else None
    lot = None
    if body.lottery_id is not None:
        lot = db.get(Lottery, body.lottery_id)
        if not lot or lot.company_id != co.id:
            raise HTTPException(404, "Лотерея не найдена")
        if c.public_id not in (lot.drawn_ids or []):
            raise HTTPException(422, {"errors": ["Кандидат не выбран жребием в этой лотерее"], "warnings": []})
        if body.need_id is not None and body.need_id != lot.need_id:
            raise HTTPException(422, {"errors": ["Потребность приглашения не совпадает с потребностью лотереи"], "warnings": []})
        n = _own_need(db, co, lot.need_id) if lot.need_id else None
    base_fmt = next((f for f in catalog.FORMATS if body.format.startswith(f)), None)
    if not base_fmt:
        raise HTTPException(422, {"errors": [f"Формат начинается с одного из: {', '.join(catalog.FORMATS)}"], "warnings": []})
    mkt = catalog.market(c.spec, c.grade, (n.city if n else None) or c.city)
    errors, warnings = validate_fork(body.salary_from, body.salary_to, p25=mkt["p25"], cand_min=c.min_salary, grade=c.grade)
    if errors:
        raise HTTPException(422, {"errors": errors, "warnings": warnings})
    if not matching.format_ok(c.formats, c.city, base_fmt, (n.city if n else None) or c.city):
        warnings.append(f"Кандидат не рассматривает формат «{base_fmt}»: вероятность принятия ниже.")

    matching.expire_invites(db, candidate_id=c.id)  # коммитит, поэтому до блокировок
    # строки компании и кандидата блокируются до commit: параллельные запросы не обойдут квоту и ёмкость
    db.execute(select(Company.id).where(Company.id == co.id).with_for_update())
    db.execute(select(Candidate.id).where(Candidate.id == c.id).with_for_update())
    dup = db.scalar(
        select(Invitation).where(
            Invitation.company_id == co.id,
            Invitation.candidate_id == c.id,
            or_(Invitation.status.in_(matching.OPEN), Invitation.need_id == n.id) if n else Invitation.status.in_(matching.OPEN),
        )
    )
    if dup:
        raise HTTPException(409, "Кандидат уже приглашён")
    if matching.candidate_loads(db, [c.id])[c.id] >= catalog.CANDIDATE_CAP:
        raise HTTPException(409, "У кандидата максимум открытых приглашений")
    q = quota(db, co)
    if q["used"] >= q["max"]:
        raise HTTPException(429, f"Квота на неделю исчерпана ({q['used']} из {q['max']}). Обновится в понедельник")

    now = datetime.now(UTC)
    inv = Invitation(
        company_id=co.id,
        candidate_id=c.id,
        need_id=n.id if n else None,
        lottery_id=lot.id if lot else None,
        role=body.role,
        salary_from=body.salary_from,
        salary_to=body.salary_to,
        format=body.format,
        description=body.description,
        task=body.task,
        status="sent",
        sent_at=now,
        expires_at=now + timedelta(days=catalog.INVITE_TTL_DAYS),
    )
    db.add(inv)
    db.commit()
    # ponytail: уведомления (почта/Telegram) не отправляются; очередь + бот, когда появятся ключи
    return {"invite": _row(inv), "warnings": warnings, "quota": quota(db, co)}


@router.get("/pipeline")
def pipeline(co: Company = Depends(current_company), db: Session = Depends(get_db)):
    matching.expire_invites(db, company_id=co.id)
    invs = db.scalars(
        select(Invitation).where(Invitation.company_id == co.id).options(selectinload(Invitation.candidate)).order_by(Invitation.sent_at.desc(), Invitation.id.desc())
    ).all()
    return {"items": [_row(i) for i in invs], "quota": quota(db, co)}


class FeedbackIn(BaseModel):
    value: str


@router.post("/invites/{invite_id}/feedback")
def feedback(invite_id: int, body: FeedbackIn, co: Company = Depends(current_verified_company), db: Session = Depends(get_db)):
    if body.value not in catalog.FEEDBACK:
        raise HTTPException(422, f"Отметка: одна из {', '.join(catalog.FEEDBACK)}")
    inv = db.get(Invitation, invite_id)
    if not inv or inv.company_id != co.id:
        raise HTTPException(404, "Приглашение не найдено")
    if inv.status != "accepted":
        raise HTTPException(409, "Отметка доступна после принятия приглашения")
    if inv.feedback:
        raise HTTPException(409, "Отметка уже поставлена")
    inv.feedback = body.value
    if body.value in ("confirmed", "hired"):
        inv.candidate.employer_confirmed += 1
    # ponytail: «не подтвердился» только сохраняется; очередь перепроверки заданий кандидата — в модуле теста
    db.commit()
    return _row(inv)


@router.get("/quota")
def get_quota(co: Company = Depends(current_company), db: Session = Depends(get_db)):
    return quota(db, co)


if __name__ == "__main__":
    assert inn_valid("7704123450") and not inn_valid("7704123456") and inn_valid("500100732259")
    assert domain_match("m@ladoga-pay.example", "https://www.ladoga-pay.example/") and not domain_match("m@gmail.com", "ladoga-pay.example")
    p25 = catalog.market("Backend", "Middle", "Москва")["p25"]
    assert validate_fork(240000, 300000, p25=p25, cand_min=230000, grade="Middle") == ([], [])
    e, w = validate_fork(None, 300000, p25=p25, cand_min=230000, grade="Middle")
    assert e == ["Укажите обе границы вилки."]
    e, w = validate_fork(310000, 300000, p25=p25, cand_min=None, grade="Middle")
    assert e == ["Нижняя граница больше верхней."], e
    e, w = validate_fork(150000, 300000, p25=p25, cand_min=None, grade="Middle")
    assert len(e) == 2 and "25-го перцентиля" in e[0] and "широкая" in e[1], e
    e, w = validate_fork(220000, 250000, p25=p25, cand_min=280000, grade="Middle")
    assert e == [] and len(w) == 1 and "ниже минимума кандидата" in w[0], w
    print("ok")
