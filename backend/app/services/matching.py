"""Ранжирование кандидатов под потребность работодателя.

Конвейер (исследование, §1 и §5):
1. фильтр по категории: специализация; грейд потребности или на один ниже (со штрафом); статус «открыт»;
   тест пройден; профиль не скрыт от компании;
2. отбор: косинус эмбеддингов, если они есть у потребности и у всех кандидатов пула, иначе — вектор
   навыков по catalog.SKILLS; топ-RETRIEVE_K;
3. соответствие = W_THETA·θ(с поправкой на SE) + W_COVER·покрытие must/nice + W_ACH·достижения;
   × штрафы за соседний трек / грейд ниже; LLM-реранк топ-30 подмешивается, только если модель доступна;
4. взаимный интерес: итог = соответствие × (0,5 + 0,5·вероятность принятия) × поправка на нагрузку.

Персональные данные (ФИО, почта, Telegram, резюме целиком) в ранжировании не участвуют.
Варианты для валидации: "embed" — только отбор; "rerank" — + соответствие и LLM; "full" — + взаимный интерес.
"""

import json
import math
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime

import numpy as np
from sqlalchemy import and_, func, select, update
from sqlalchemy.orm import Session, selectinload

from app import catalog
from app.integrations import scoring
from app.models import Candidate, Company, Invitation, Need
from app.services import llm

W_THETA, W_COVER, W_ACH = 0.45, 0.45, 0.10
CREDIT_CONFIRMED, CREDIT_CLAIMED, CREDIT_ADJACENT = 1.0, 0.4, 0.3  # вклад навыка в покрытие
NICE_WEIGHT = 0.5  # желательный навык весит вдвое меньше обязательного
# грейд на ступень ниже — «стек совпал, грейд ниже» (оценка 1 из 3): показываем, но ниже своих грейдом
LOWER_GRADE_PEN = 0.6
# чужой трек той же специализации: навыки частично переносимы, но это другая категория
TRACK_PEN = 0.45
# вероятность принятия — шумная оценка; она двигает итог в пределах ×0,5…×1 и не перебивает соответствие
ACCEPT_FLOOR = 0.5
RETRIEVE_K = 200
RERANK_K = 30
LLM_BLEND = 0.3  # доля оценки LLM в соответствии
OPEN = ("sent", "seen")

# близкие навыки: опыт с одним частично покрывает другой («Kafka: опыт с RabbitMQ»)
ADJACENT = {
    "Kafka": ["RabbitMQ"],
    "RabbitMQ": ["Kafka"],
    "PostgreSQL": ["MySQL"],
    "MySQL": ["PostgreSQL"],
    "FastAPI": ["Django"],
    "Django": ["FastAPI"],
    "Java": ["Kotlin"],
    "Kotlin": ["Java"],
    "TypeScript": ["JavaScript"],
    "JavaScript": ["TypeScript"],
}


@dataclass
class Ranked:
    candidate: Candidate
    match: float
    accept: float
    load: int
    score: float
    explanation: dict


# фиксированное «сейчас» для валидации: нагрузка считается на дату засева, а не на сегодня. ContextVar — свой у каждого
# запроса/потока, поэтому прогон валидации не сдвигает часы параллельным запросам API
CLOCK: ContextVar[datetime | None] = ContextVar("matching_clock", default=None)


def _now() -> datetime:
    return CLOCK.get() or datetime.now(UTC)


def candidate_loads(db: Session, candidate_ids: list[int]) -> dict[int, int]:
    """Открытые приглашения (sent|seen, срок не истёк) по кандидатам."""
    out = dict.fromkeys(candidate_ids, 0)
    if candidate_ids:
        rows = db.execute(
            select(Invitation.candidate_id, func.count())
            .where(Invitation.candidate_id.in_(candidate_ids), Invitation.status.in_(OPEN), Invitation.expires_at > _now())
            .group_by(Invitation.candidate_id)
        ).all()
        out.update({cid: n for cid, n in rows})
    return out


def expire_invites(db: Session, **where) -> None:
    """Ленивое истечение: открытые приглашения после expires_at → expired. where — фильтры по полям Invitation."""
    q = update(Invitation).where(Invitation.status.in_(OPEN), Invitation.expires_at <= _now())
    for k, v in where.items():
        q = q.where(getattr(Invitation, k) == v)
    if db.execute(q.values(status="expired")).rowcount:
        db.commit()


def achievement_signal(c: Candidate) -> float:
    """Только подтверждённые: результативность с убывающей отдачей по числу соревнований + рейтинг (scoring.signal)."""
    return scoring.signal(a for a in c.achievements if a.verified)


def fsp_title(c: Candidate) -> str | None:
    best = max((a for a in c.achievements if a.verified and a.source == "fsp"), key=lambda a: a.weight, default=None)
    return best.title if best else None


def badges(c: Candidate) -> list[dict]:
    """Бейджи анонимной карточки: лучшее подтверждённое достижение по каждому источнику (fsp, hackathon, ctftime, codeforces).

    Дисциплина, результат и разряд — факты из протокола, без ранжирования дисциплин.
    """
    best: dict[str, dict] = {}
    for a in sorted((a for a in c.achievements if a.verified), key=lambda a: -a.weight):
        best.setdefault(a.source, {"source": a.source, "title": a.title, "place": a.place, "result": a.result,
                                   "discipline": a.event.discipline if a.event else None, "rank": a.sport_rank})
    return list(best.values())


def sport_rank(achievements) -> str | None:
    """Высший спортивный разряд/звание из подтверждённых протоколов (catalog.SPORT_RANKS) — факт, в вес не входит."""
    ranks = [a.sport_rank for a in achievements if a.verified and a.sport_rank in catalog.SPORT_RANKS]
    return min(ranks, key=catalog.SPORT_RANKS.index, default=None)


def cf_account(c: Candidate):
    return next((a for a in c.accounts if a.provider == "codeforces" and a.verified_at), None)


def format_ok(formats: list[str], city: str | None, need_format: str | None, need_city: str | None) -> bool:
    if not need_format:
        return True
    if need_format not in (formats or []):
        return False
    return need_format == "Удалённо" or not need_city or not city or city == need_city


def format_text(formats: list[str], city: str | None) -> str:
    """['Гибрид', 'Удалённо'], 'Москва' → «Гибрид или удалённо, Москва»; только удалёнка — без города."""
    fs = [f for f in catalog.FORMATS if f in (formats or [])]
    if not fs:
        return city or ""
    s = " или ".join([fs[0]] + [f.lower() for f in fs[1:]])
    return f"{s}, {city}" if city and fs != ["Удалённо"] else s


def accept_prob(fork_to: int, min_salary: int, fmt_ok: bool, stack: float) -> float:
    """Вероятность принятия: логистическая по запасу вилки над минимумом, формату и интересу к стеку.

    r = (до − минимум) / минимум, обрезано до ±0,5; ниже минимума наклон вдвое круче.
    Калибровка по макету: r=0,30 → 0,83; r=−0,10 → ~0,13 («упадёт примерно до 0,15»).
    # ponytail: коэффициенты подобраны руками; дообучить логрегрессию на принятиях/отказах из воронки
    """
    r = max(-0.5, min(0.5, (fork_to - min_salary) / max(min_salary, 1)))
    z = -0.55 + 7 * r + (7 * r if r < 0 else 0) - (0 if fmt_ok else 1.2) - 1.4 * (1 - stack)
    return 1 / (1 + math.exp(-z))


def final_score(match: float, accept: float, load: int) -> float:
    """Итог варианта «full». Общий для выдачи и симуляции рынка в validation.py."""
    return match * (ACCEPT_FLOOR + (1 - ACCEPT_FLOOR) * accept) * catalog.load_penalty(load)


def norm_pct(t: float) -> int:
    """θ компетенции → перцентиль при θ ~ N(0, 1) в популяции."""
    return round(50 * (1 + math.erf(t / math.sqrt(2))))


def embed_text(spec: str, track: str | None, grade: str | None, skills: list[str]) -> str:
    """Текст для эмбеддинга — только структурные поля, без ФИО и резюме целиком (защита от смещений)."""
    return f"{spec} · {track or ''} · {grade or ''}. Навыки: {', '.join(skills)}"


def embed_need(n: Need) -> list[float] | None:
    vec = llm.embed([embed_text(n.spec, n.track, n.grade, list(n.must) + list(n.nice))])
    return vec[0] if vec else None


def embed_candidate(c: Candidate) -> list[float] | None:
    skills = list(dict.fromkeys((c.skills_confirmed or []) + (c.skills_claimed or [])))
    vec = llm.embed([embed_text(c.spec, c.track, c.grade or c.grade_claimed, skills)])
    return vec[0] if vec else None


# ---------- части оценки ----------

_SKILL_IDX = {s: i for i, s in enumerate(catalog.SKILLS)}


def _skill_vec(weights: dict[str, float]) -> np.ndarray:
    v = np.zeros(len(_SKILL_IDX))
    for s, w in weights.items():
        if s in _SKILL_IDX:
            v[_SKILL_IDX[s]] = max(v[_SKILL_IDX[s]], w)
    return v


def _cosine(m: np.ndarray, q: np.ndarray) -> np.ndarray:
    denom = np.linalg.norm(m, axis=1) * np.linalg.norm(q)
    return np.divide(m @ q, denom, out=np.zeros(len(m)), where=denom > 0)


def _retrieval(need: Need, cands: list[Candidate]) -> tuple[np.ndarray, str]:
    ne = need.embedding
    if ne and all(c.embedding and len(c.embedding) == len(ne) for c in cands):
        return _cosine(np.array([c.embedding for c in cands]), np.array(ne)), "embedding"
    q = _skill_vec({**{s: NICE_WEIGHT for s in need.nice}, **{s: 1.0 for s in need.must}})
    m = np.array([_skill_vec({**{s: 0.5 for s in c.skills_claimed or []}, **{s: 1.0 for s in c.skills_confirmed or []}}) for c in cands])
    return _cosine(m, q), "skills"


def _credit(skill: str, confirmed: set[str], claimed: set[str]) -> float:
    if skill in confirmed:
        return CREDIT_CONFIRMED
    if skill in claimed:
        return CREDIT_CLAIMED
    if any(a in confirmed for a in ADJACENT.get(skill, [])):
        return CREDIT_ADJACENT
    return 0.0


def gaps(c: Candidate, need: Need | None) -> list[str]:
    """Пробелы относительно потребности, человеческим языком, как в макете."""
    if not need:
        return []
    confirmed, claimed = set(c.skills_confirmed or []), set(c.skills_claimed or [])
    out = []
    for s in list(need.must) + [s for s in need.nice if s not in need.must]:
        if s in confirmed:
            continue
        if s in claimed:
            out.append(f"{s} не подтверждён тестом")
        elif adj := [a for a in ADJACENT.get(s, []) if a in confirmed]:
            out.append(f"{s}: опыт с {adj[0]}, близкий навык подтверждён")
        else:
            out.append(s)
    return out


def _theta_score(c: Candidate, grade: str) -> float:
    """θ − 0,5·SE относительно порога грейда потребности, через сигмоиду: на пороге 0,5, +0,5θ → 0,73."""
    th = max(catalog.GRADE_TH[grade], -1.5)
    return 1 / (1 + math.exp(-((c.theta or 0) - 0.5 * (c.se or 0) - th) / 0.5))


def _relevance(c: Candidate, need: Need) -> dict:
    confirmed, claimed = set(c.skills_confirmed or []), set(c.skills_claimed or [])
    weighted = [(s, 1.0) for s in need.must] + [(s, NICE_WEIGHT) for s in need.nice if s not in need.must]
    total = sum(w for _, w in weighted)
    cover = sum(w * _credit(s, confirmed, claimed) for s, w in weighted) / total if total else 1.0
    # интерес к стеку для вероятности принятия: заявленное тоже считается
    stack = sum(1 for s in need.must if s in confirmed | claimed) / len(need.must) if need.must else 1.0
    theta = _theta_score(c, need.grade)
    ach = achievement_signal(c)
    # грейд выше — без штрафа (эталон считает +1 релевантным; дороговизну учтёт вероятность принятия)
    grade_pen = LOWER_GRADE_PEN if catalog.GRADES.index(c.grade) < catalog.GRADES.index(need.grade) else 1.0
    track_pen = TRACK_PEN if need.track and c.track != need.track else 1.0
    match = (W_THETA * theta + W_COVER * cover + W_ACH * ach) * grade_pen * track_pen
    return {"theta": theta, "coverage": cover, "achievement": ach, "stack": stack, "grade_penalty": grade_pen, "track_penalty": track_pen, "match": match}


_LLM_SYSTEM = (
    "Ты технический рекрутер. Оцени соответствие каждого анонимного кандидата потребности по шкале 0..1. "
    "Учитывай только навыки, грейд и результаты теста (theta). Подтверждённые тестом навыки важнее заявленных. "
    'Ответ — JSON: {"scores": [{"id": "A-1042", "score": 0.83}, ...]} для всех кандидатов.'
)
_llm_cache: dict[tuple, dict[str, float] | None] = {}


def _llm_scores(need: Need, cands: list[Candidate]) -> dict[str, float] | None:
    # в модель уходят только структурные поля: ни текста потребности (там бывают «пол/возраст»), ни ФИО
    profiles = [
        {
            "id": c.public_id,
            "grade": c.grade,
            "track": c.track,
            "theta": round(c.theta or 0, 2),
            "confirmed": c.skills_confirmed or [],
            "claimed_only": [s for s in c.skills_claimed or [] if s not in (c.skills_confirmed or [])],
        }
        for c in cands
    ]
    key = (need.spec, need.track, need.grade, tuple(need.must), tuple(need.nice), tuple(p["id"] for p in profiles))
    if key in _llm_cache:
        return _llm_cache[key]
    body = {"need": {"spec": need.spec, "track": need.track, "grade": need.grade, "must": need.must, "nice": need.nice}, "candidates": profiles}
    out = llm.chat_json(_LLM_SYSTEM, json.dumps(body, ensure_ascii=False))
    scores = None
    if out and isinstance(out.get("scores"), list):
        scores = {}
        for s in out["scores"]:
            try:
                scores[str(s["id"])] = max(0.0, min(1.0, float(s["score"])))
            except (KeyError, TypeError, ValueError):
                continue
        scores = scores or None
    if out is not None:  # сбой модели не кэшируем — попробуем позже
        # ponytail: кэш в памяти процесса без вытеснения по времени; Redis/таблица, если процессов станет несколько
        if len(_llm_cache) > 256:
            _llm_cache.clear()
        _llm_cache[key] = scores
    return scores


def _effective_min(db: Session, cands: list[Candidate]) -> dict[int, int]:
    """Минимум с учётом отказов «Зарплата»: отказался от вилки до X — значит, ждёт больше X (+5 %)."""
    eff = {c.id: c.min_salary for c in cands}
    rows = db.execute(
        select(Invitation.candidate_id, func.max(Invitation.salary_to))
        .where(Invitation.candidate_id.in_(list(eff)), Invitation.status == "declined", Invitation.decline_reason == "salary")
        .group_by(Invitation.candidate_id)
    ).all()
    for cid, mx in rows:
        eff[cid] = max(eff[cid], round(mx * 1.05 / 5000) * 5000)
    return eff


def _why(c: Candidate, matched: list[str]) -> str:
    parts = []
    if matched:
        parts.append("совпадение стека " + ", ".join(matched))
    if c.competencies:
        top = max(c.competencies, key=lambda x: x.get("t", 0))
        parts.append(f"{top['n'].lower()} — {norm_pct(top['t'])}-й перцентиль")
    elif c.percentile is not None:
        parts.append(f"{c.percentile}-й перцентиль в категории")
    s = "; ".join(parts)
    return s[:1].upper() + s[1:]


def score_candidates(db: Session, need: Need, cands: list[Candidate], *, variant: str = "full", limit: int = 50) -> list[Ranked]:
    """Оценка готового пула (без фильтра категории). rank() = фильтр + эта функция; карточка кандидата зовёт напрямую."""
    if variant not in ("embed", "rerank", "full"):
        raise ValueError(f"variant: embed | rerank | full, а не {variant}")
    if not cands:
        return []
    sims, mode = _retrieval(need, cands)
    order = sorted(range(len(cands)), key=lambda i: (-sims[i], cands[i].public_id))
    loads = candidate_loads(db, [c.id for c in cands])
    if variant == "embed":
        return [
            Ranked(cands[i], float(sims[i]), 1.0, loads[cands[i].id], float(sims[i]), {"retrieval": mode, "sim": round(float(sims[i]), 3)})
            for i in order[:limit]
        ]

    pool = [cands[i] for i in order[:RETRIEVE_K]]
    sim_of = {cands[i].id: float(sims[i]) for i in order[:RETRIEVE_K]}
    rel = {c.id: _relevance(c, need) for c in pool}

    llm_scores = None
    top = sorted(pool, key=lambda c: (-rel[c.id]["match"], c.public_id))[:RERANK_K]
    if need.must or need.nice:
        llm_scores = _llm_scores(need, top)
    if llm_scores:
        for c in top:
            if c.public_id in llm_scores:
                r = rel[c.id]
                r["llm"] = llm_scores[c.public_id]
                r["match"] = (1 - LLM_BLEND) * r["match"] + LLM_BLEND * r["llm"] * r["grade_penalty"] * r["track_penalty"]

    mkt = catalog.market(need.spec, need.grade, need.city)
    fork_to = need.salary_to or mkt["p50"]
    eff_min = _effective_min(db, pool)
    out = []
    for c in pool:
        r = rel[c.id]
        fmt = format_ok(c.formats, c.city, need.format, need.city)
        acc = accept_prob(fork_to, eff_min[c.id], fmt, r["stack"])
        load = loads[c.id]
        pen = catalog.load_penalty(load)
        score = final_score(r["match"], acc, load) if variant == "full" else r["match"]
        confirmed = set(c.skills_confirmed or [])
        matched = [s for s in list(need.must) + list(need.nice) if s in confirmed]
        cf = cf_account(c)
        expl = {
            "retrieval": mode,
            "sim": round(sim_of[c.id], 3),
            "confirmed": matched,
            "pct": c.percentile,
            "gaps": gaps(c, need),
            "fsp": fsp_title(c),
            "cf": cf.rating if cf else None,
            "fork": {"to": fork_to, "min": c.min_salary, "effective_min": eff_min[c.id], "ok": fork_to >= eff_min[c.id]},
            "format_ok": fmt,
            "load": load,
            "busy": load >= catalog.CANDIDATE_CAP,
            "parts": {
                **{k: round(v, 3) for k, v in r.items()},
                "accept": round(acc, 3),
                "load_penalty": round(pen, 3),
                "score": round(score, 3),
                "weights": {"theta": W_THETA, "coverage": W_COVER, "achievement": W_ACH},
            },
            "why": _why(c, matched),
        }
        out.append(Ranked(c, r["match"], acc, load, score, expl))
    out.sort(key=lambda x: (-x.score, x.candidate.public_id))
    return out[:limit]


def consent_ok(c: Candidate, purpose: str) -> bool:
    """Действующее согласие на цель: флаг И версия текста этой цели = catalog.CONSENT_VERSION.
    publish и external — производные: без действующего согласия на обработку они не действуют.
    Новая редакция → кандидат пропадает из выдачи, пока не подтвердит заново (каждую цель отдельно)."""
    v = catalog.CONSENT_VERSION
    processing = bool(c.consent_152) and c.consent_version == v
    if purpose == "processing":
        return processing
    if purpose == "publish":
        return processing and bool(c.consent_publish) and c.consent_publish_version == v
    if purpose == "external":
        return processing and bool(c.consent_external) and c.consent_external_version == v
    raise ValueError(purpose)


def published():
    """SQL-условие к consent_ok(c, "publish")."""
    v = catalog.CONSENT_VERSION
    return and_(Candidate.consent_152.is_(True), Candidate.consent_version == v, Candidate.consent_publish.is_(True), Candidate.consent_publish_version == v)


def visible(c: Candidate, company: Company | None = None) -> bool:
    """Кандидат виден работодателям: открыт, тест пройден, действующие согласия на обработку и публикацию, не скрыт от компании."""
    return (
        c.status == "open"
        and c.theta is not None
        and c.grade is not None
        and consent_ok(c, "publish")  # включает действующее согласие на обработку
        and not (company and company.inn in (c.hidden_from or []))
    )


def eligible(db: Session, need: Need, company: Company | None = None) -> list[Candidate]:
    """Фильтр категории: специализация; грейд потребности, на один ниже (со штрафом) или на один выше, если минимум
    кандидата помещается в верх вилки (нет верха — в медиану рынка); плюс visible()."""
    gi = catalog.GRADES.index(need.grade)
    grades = catalog.GRADES[max(0, gi - 1) : gi + 2]
    upper = catalog.GRADES[gi + 1] if gi + 1 < len(catalog.GRADES) else None
    ceiling = need.salary_to or catalog.market(need.spec, need.grade, need.city)["p50"]
    q = (
        select(Candidate)
        .where(Candidate.spec == need.spec, Candidate.status == "open", Candidate.grade.in_(grades), Candidate.theta.is_not(None), published())
        .options(selectinload(Candidate.achievements), selectinload(Candidate.accounts))
    )
    return [c for c in db.scalars(q) if visible(c, company) and not (c.grade == upper and c.min_salary > ceiling)]


def strength(c: Candidate, skills: list[str] | None = None) -> float:
    """Сила подтверждённого профиля для поиска по банку: θ − 0,5·SE + 0,5·достижения (+ покрытие навыков, если заданы)."""
    s = (c.theta or 0) - 0.5 * (c.se or 0) + 0.5 * achievement_signal(c)
    if skills:
        confirmed, claimed = set(c.skills_confirmed or []), set(c.skills_claimed or [])
        s += sum(_credit(k, confirmed, claimed) for k in skills) / len(skills)
    return s


def rank(db: Session, need: Need, *, variant: str = "full", limit: int = 50, company: Company | None = None) -> list[Ranked]:
    return score_candidates(db, need, eligible(db, need, company), variant=variant, limit=limit)


def months_ago(dt: datetime | None) -> str | None:
    if not dt:
        return None
    return f"{max(0, (_now() - dt).days // 30)} мес. назад"


def card(c: Candidate, *, ranked: Ranked | None = None, need: Need | None = None) -> dict:
    """Анонимная карточка в форме CANDS из макета. Только белый список полей: без ФИО, почты, Telegram, резюме."""
    confirmed = c.skills_confirmed or []
    need_skills = (list(need.must) + list(need.nice)) if need else []
    skills = [s for s in need_skills if s in confirmed] + [s for s in confirmed if s not in need_skills]
    cf = cf_account(c)
    e = ranked.explanation if ranked else {}
    fork_to = e.get("fork", {}).get("to") or (need.salary_to if need else None)
    load = ranked.load if ranked else None
    return {
        "id": c.public_id,
        "public_id": c.public_id,
        "spec": c.spec,
        "track": c.track,
        "grade": c.grade,
        "pct": c.percentile,
        "theta": f"{c.theta:.2f} ± {c.se:.2f}" if c.theta is not None and c.se is not None else None,
        "skills": skills,
        "claimed": [s for s in c.skills_claimed or [] if s not in confirmed],
        "roles": c.roles or [],  # справочные: со слов кандидата, в ранжировании не участвуют
        "soft": c.soft_skills or [],
        "gaps": e.get("gaps", gaps(c, need)),
        "fsp": fsp_title(c),
        "cf": cf.rating if cf else None,
        "badges": badges(c),
        "sport_rank": sport_rank(c.achievements),
        "salary": c.min_salary,
        "formats": c.formats or [],
        "city": c.city,
        "format": format_text(c.formats, c.city),
        "fmtOk": format_ok(c.formats, c.city, need.format, need.city) if need else None,
        "inFork": (fork_to >= e.get("fork", {}).get("effective_min", c.min_salary)) if fork_to else None,
        "load": load,
        "busy": load is not None and load >= catalog.CANDIDATE_CAP,
        "match": round(ranked.match, 3) if ranked else None,
        "accept": round(ranked.accept, 3) if ranked else None,
        "score": round(ranked.score, 3) if ranked else None,
        "confirmed": months_ago(c.tested_at),
        "trust": {"test": c.tested_at is not None, "review": c.review_passed, "employer_confirmed": c.employer_confirmed},
    }
