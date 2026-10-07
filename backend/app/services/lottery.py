"""Квалифицированная лотерея (threshold lottery, Frey & Osterloh): детерминированный порог → слепой жребий.

Зачем: внутри порога кандидаты статистически неразличимы (интервалы θ ± SE перекрываются), и попытка
их «доранжировать» — ложная точность, в которую просачиваются предубеждения и знакомства. Жребий среди
прошедших порог разносит приглашения шире (разнообразие, меньше завала у «звёзд»), исключает непотизм и
проверяем снаружи через commit–reveal. Квоту лотерея не тратит: квота списывается только при отправке
приглашений выбранным (обычный поток приглашений, Invitation.lottery_id = id лотереи).

Порог строится от потребности (effective_threshold): spec/track — из Need, grade_min ≥ грейд потребности − 1,
must_skills ⊇ need.must, fork_to ≤ need.salary_to, formats ⊂ {need.format}; клиент может только ужесточать.
Неподтверждённой компании лотерея тоже доступна: квота тратится только при отправке приглашений.

Порог (threshold, JSON):
  spec, track?, grade_min, theta_min? (θ − SE ≥ theta_min), must_skills[] (⊂ skills_confirmed),
  fork_to (min_salary ≤ fork_to), formats?[] (пересечение с форматами кандидата), require_free (нагрузка < CAP).
Всегда: статус open, действующие согласия на обработку и публикацию (matching.consent_ok), тест пройден, ИНН компании не в hidden_from, нет открытого приглашения от этой компании
и нет её отклонённого / истёкшего приглашения за последние 90 дней.
Тест обязателен, хотя в подборке и поиске не подтверждённые тестом видны: порог лотереи — квалификация, а жребий
уравнивает всех прошедших его. Заявленный грейд не проверен, и «Senior со слов» вытягивал бы приглашение наравне
с подтверждённым — тогда как в подборке он стоит строго ниже (matching.order_key).

Протокол: create — соль salt = token_hex(32) (наружу не отдаётся никогда), пул замораживается как отсортированные
псевдонимы p = sha256(salt + public_id)[:16]; seed = token_hex(32), публикуются sha256(seed) и commitment.
draw — seed раскрывается, порядок = sorted(pool, key=sha256(seed + p)), берутся первые draw_count.
Любой может повторить по псевдонимам: verify_draw(...). Псевдонимы не связать ни с карточкой кандидата, ни
с другими лотереями (у каждой своя соль); соответствие p → кандидат знает только сервер (для владельца).
"""

import hashlib
import json
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.catalog import CANDIDATE_CAP, GRADES
from app.models import Candidate, Company, Invitation, Lottery
from app.services.matching import consent_ok, published

COOLDOWN_DAYS = 90  # отказ или молчание (истёкшее приглашение) этой компании — не навязываемся 90 дней
POOL_MAX = 500  # ponytail: больше — порог слишком мягкий, просим сузить; пагинация пула, если понадобится


def seed_hash(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def pseudonym(salt: str, public_id: str) -> str:
    return hashlib.sha256((salt + public_id).encode()).hexdigest()[:16]


def draw_order(seed: str, pool: list[str], k: int) -> list[str]:
    return sorted(pool, key=lambda pid: hashlib.sha256((seed + pid).encode()).hexdigest())[:k]


def commitment(threshold: dict, pool_ids: list[str], draw_count: int, hashed: str) -> str:
    """sha256 канонического JSON: фиксирует порог, пул и число мест вместе с хешем зерна до розыгрыша."""
    doc = {"threshold": threshold, "pool_ids": pool_ids, "draw_count": draw_count, "seed_hash": hashed}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def verify_draw(seed: str, hashed: str, pool: list[str], drawn: list[str], *, threshold: dict, draw_count: int,
                committed: str) -> dict:
    hash_ok = secrets.compare_digest(seed_hash(seed), hashed)
    commitment_ok = secrets.compare_digest(commitment(threshold, pool, draw_count, hashed), committed)
    draw_ok = draw_order(seed, pool, draw_count) == drawn
    ok = hash_ok and commitment_ok and draw_ok
    return {"ok": ok, "hash_ok": hash_ok, "commitment_ok": commitment_ok, "draw_ok": draw_ok}


def verify(lot: Lottery) -> dict:
    return verify_draw(lot.seed, lot.seed_hash, lot.pool_ids, lot.drawn_ids, threshold=lot.threshold,
                       draw_count=lot.draw_count, committed=lot.commitment)


def effective_threshold(th: dict, need) -> dict:
    """Порог = потребность + ужесточения клиента. Ослабление (другая специализация, вилка выше, грейд ниже −1) → ValueError."""
    if th.get("spec") not in (None, need.spec):
        raise ValueError(f"Специализация порога должна совпадать с потребностью: {need.spec}")
    if th.get("track") and need.track and th["track"] != need.track:
        raise ValueError(f"Трек порога должен совпадать с потребностью: {need.track}")
    floor = max(0, GRADES.index(need.grade) - 1)
    grade_min = th.get("grade_min") or GRADES[floor]
    if grade_min not in GRADES or GRADES.index(grade_min) < floor:
        raise ValueError(f"Минимальный грейд — не ниже {GRADES[floor]} (грейд потребности − 1)")
    fork_to = th.get("fork_to") or need.salary_to
    if not fork_to:
        raise ValueError("Укажите верхнюю границу вилки")
    if need.salary_to and fork_to > need.salary_to:
        raise ValueError(f"Верх вилки в пороге не может превышать вилку потребности ({need.salary_to})")
    formats = th.get("formats") or ([need.format] if need.format else None)
    if need.format and not set(formats) <= {need.format}:
        raise ValueError(f"Формат порога — только формат потребности: {need.format}")
    return {
        "spec": need.spec,
        "track": th.get("track") or need.track,
        "grade_min": grade_min,
        "theta_min": th.get("theta_min"),
        "must_skills": list(dict.fromkeys([*(need.must or []), *(th.get("must_skills") or [])])),
        "fork_to": fork_to,
        "formats": formats,
        "require_free": th.get("require_free", True),
    }


class LotteryExists(Exception):
    """Одна жеребьёвка на потребность: иначе можно перебрасывать жребий до удобного результата."""


def open_loads(db: Session) -> dict[int, int]:
    """Открытые приглашения (sent|seen, не истёкшие) по кандидатам."""
    rows = db.execute(
        select(Invitation.candidate_id, func.count())
        .where(Invitation.status.in_(("sent", "seen")), Invitation.expires_at > datetime.now(UTC))
        .group_by(Invitation.candidate_id)
    )
    return dict(rows.all())


def passes(c: Candidate, th: dict, inn: str, load: int) -> bool:
    return (
        c.status == "open"
        and consent_ok(c, "processing")
        and consent_ok(c, "publish")
        and c.tested_at is not None
        and c.theta is not None
        and c.spec == th["spec"]
        and (not th.get("track") or c.track == th["track"])
        and c.grade in GRADES
        and GRADES.index(c.grade) >= GRADES.index(th["grade_min"])
        and (th.get("theta_min") is None or c.theta - (c.se or 0) >= th["theta_min"])
        and set(th.get("must_skills") or []) <= set(c.skills_confirmed or [])
        and c.min_salary <= th["fork_to"]
        and (not th.get("formats") or bool(set(th["formats"]) & set(c.formats or [])))
        and inn not in (c.hidden_from or [])
        and (not th.get("require_free", True) or load < CANDIDATE_CAP)
    )


def find_pool(db: Session, company: Company, th: dict) -> list[str]:
    loads = open_loads(db)
    since = datetime.now(UTC) - timedelta(days=COOLDOWN_DAYS)
    open_ = Invitation.status.in_(("sent", "seen")) & (Invitation.expires_at > datetime.now(UTC))
    declined = (Invitation.status == "declined") & (func.coalesce(Invitation.responded_at, Invitation.sent_at) >= since)
    expired = (Invitation.status.in_(("expired", "sent", "seen"))) & (Invitation.expires_at <= datetime.now(UTC)) & (
        Invitation.expires_at >= since
    )
    invited = set(
        db.scalars(select(Invitation.candidate_id).where(Invitation.company_id == company.id, or_(open_, declined, expired)))
    )
    q = select(Candidate).where(Candidate.spec == th["spec"], Candidate.status == "open", published(),
                                Candidate.theta.is_not(None))
    if th.get("track"):
        q = q.where(Candidate.track == th["track"])
    return sorted(
        c.public_id
        for c in db.scalars(q)
        if c.id not in invited and passes(c, th, company.inn, loads.get(c.id, 0))
    )


def create(db: Session, company: Company, th: dict, draw_count: int, need_id: int) -> Lottery:
    prev = db.scalar(select(Lottery.id).where(Lottery.company_id == company.id, Lottery.need_id == need_id))
    if prev:
        raise LotteryExists(f"Для этой потребности жеребьёвка уже проведена (№ {prev}) — перебросить жребий нельзя")
    pool = find_pool(db, company, th)
    if len(pool) < draw_count + 1:
        raise ValueError(f"Порог прошли {len(pool)} — жребий не нужен: смягчите порог или пригласите напрямую")
    if len(pool) > POOL_MAX:
        raise ValueError(f"Порог прошли {len(pool)} (> {POOL_MAX}) — ужесточите порог")
    seed = secrets.token_hex(32)
    # seed лежит в БД с момента создания, но API отдаёт его только после розыгрыша (см. public_state)
    # ponytail: оператор платформы технически видит seed заранее; апгрейд — внешний маяк случайности (drand) как seed
    hashed = seed_hash(seed)
    salt = secrets.token_hex(32)
    pool = sorted(pseudonym(salt, pid) for pid in pool)
    lot = Lottery(company_id=company.id, need_id=need_id, threshold=th, pool_ids=pool, draw_count=draw_count, salt=salt,
                  seed_hash=hashed, commitment=commitment(th, pool, draw_count, hashed), seed=seed)
    db.add(lot)
    try:
        db.commit()
    except IntegrityError as e:  # гонка двух одновременных запросов: сработал UniqueConstraint(company_id, need_id)
        db.rollback()
        raise LotteryExists("Для этой потребности жеребьёвка уже проведена — перебросить жребий нельзя") from e
    return lot


def drawn_candidates(db: Session, lot: Lottery) -> list[tuple[str, Candidate]]:
    """Псевдоним → кандидат для владельца, в порядке жребия. Удалённые кандидаты просто не сопоставляются."""
    if not lot.drawn_ids or not lot.salt:
        return []
    # ponytail: перебор всех public_id (≈мс на тысячи); на сотнях тысяч — хранить серверную таблицу lottery_id × candidate_id
    by_p = {pseudonym(lot.salt, pid): cid for cid, pid in db.execute(select(Candidate.id, Candidate.public_id))}
    ids = [by_p[p] for p in lot.drawn_ids if p in by_p]
    cands = {c.id: c for c in db.scalars(select(Candidate).where(Candidate.id.in_(ids)))}
    return [(p, cands[by_p[p]]) for p in lot.drawn_ids if p in by_p]


def is_drawn(lot: Lottery, candidate: Candidate) -> bool:
    """Кандидат вытянут в этой лотерее (для приглашения с lottery_id)."""
    return bool(lot.drawn_ids and lot.salt) and pseudonym(lot.salt, candidate.public_id) in lot.drawn_ids


def card(c: Candidate, load: int) -> dict:
    """Анонимная карточка: без ФИО, почты, tg, города."""
    return {
        "public_id": c.public_id,
        "category": {"spec": c.spec, "track": c.track, "grade": c.grade},
        "percentile": c.percentile,
        "theta": c.theta,
        "se": c.se,
        "skills_confirmed": c.skills_confirmed,
        "load": load,
    }


def draw(db: Session, lot: Lottery) -> dict:
    if lot.drawn_ids is not None:
        raise ValueError("Жребий уже брошен")
    lot.drawn_ids = draw_order(lot.seed, lot.pool_ids, lot.draw_count)
    lot.drawn_at = datetime.now(UTC)
    db.commit()
    return result(db, lot)


def public_view(lot: Lottery) -> dict:
    """Обезличенное состояние для проверки кем угодно: только псевдонимы, без соли, компании, потребности и ПДн."""
    drawn = lot.drawn_ids is not None
    return {
        "id": lot.id,
        "status": "drawn" if drawn else "frozen",
        "threshold": lot.threshold,
        "pool_size": len(lot.pool_ids),
        "pool_ids": lot.pool_ids,
        "draw_count": lot.draw_count,
        "seed_hash": lot.seed_hash,
        "commitment": lot.commitment,
        "seed": lot.seed if drawn else None,  # до розыгрыша — только хеш
        "drawn_ids": lot.drawn_ids,
        "created_at": lot.created_at,
        "drawn_at": lot.drawn_at,
        "verify": verify(lot) if drawn else None,
    }


def public_state(db: Session, lot: Lottery) -> dict:
    """Для владельца: псевдонимы + карточки вытянутых."""
    return {**public_view(lot), "need_id": lot.need_id, "drawn": _cards(db, lot)}


def _cards(db: Session, lot: Lottery) -> list[dict]:
    """Карточки вытянутых — только при действующем согласии на обработку и публикацию (могли отозвать после жребия);
    иначе {pseudonym, hidden: true} без public_id. Удалённые кандидаты тоже hidden."""
    loads = open_loads(db)
    found = dict(drawn_candidates(db, lot))
    return [{**card(c, loads.get(c.id, 0)), "pseudonym": p}
            if (c := found.get(p)) and consent_ok(c, "processing") and consent_ok(c, "publish")
            else {"pseudonym": p, "hidden": True}
            for p in lot.drawn_ids or []]


def result(db: Session, lot: Lottery) -> dict:
    return {
        "id": lot.id,
        "drawn": _cards(db, lot),
        "seed": lot.seed,
        "seed_hash": lot.seed_hash,
        "commitment": lot.commitment,
        "pool_ids": lot.pool_ids,
    }


if __name__ == "__main__":
    pool = sorted(f"X-{i:04d}" for i in range(50))
    s = "ab" * 32
    d = draw_order(s, pool, 5)
    assert d == draw_order(s, list(reversed(pool)), 5), "порядок не зависит от порядка пула"
    assert len(set(d)) == 5 and set(d) <= set(pool)
    assert d != draw_order("cd" * 32, pool, 5), "другой seed — другой жребий"
    th = {"spec": "Backend", "grade_min": "Middle", "fork_to": 300000, "theta_min": 0.5}
    cm = commitment(th, pool, 5, seed_hash(s))
    assert cm == commitment(dict(reversed(th.items())), pool, 5, seed_hash(s)), "канонический JSON не зависит от порядка ключей"
    kw = {"threshold": th, "draw_count": 5, "committed": cm}
    assert verify_draw(s, seed_hash(s), pool, d, **kw)["ok"]
    assert not verify_draw(s, seed_hash("x"), pool, d, **kw)["hash_ok"]
    assert not verify_draw(s, seed_hash(s), pool, d[::-1], **kw)["draw_ok"]
    assert not verify_draw(s, seed_hash(s), pool[:-1], d, **kw)["commitment_ok"], "подмена пула ловится"
    assert not verify_draw(s, seed_hash(s), pool, d, **{**kw, "threshold": {**th, "fork_to": 1}})["commitment_ok"]
    assert not verify_draw(s, seed_hash(s), pool, d, **{**kw, "draw_count": 6})["ok"]
    from types import SimpleNamespace

    s1, s2 = "11" * 32, "22" * 32
    assert pseudonym(s1, "A-1042") != pseudonym(s2, "A-1042") and len(pseudonym(s1, "A-1042")) == 16, "соль развязывает лотереи"
    lot = SimpleNamespace(salt=s1, drawn_ids=[pseudonym(s1, "A-1042")])
    assert is_drawn(lot, SimpleNamespace(public_id="A-1042")) and not is_drawn(lot, SimpleNamespace(public_id="B-2318"))

    need = SimpleNamespace(spec="Backend", track="Python", grade="Middle", must=["Python", "Kafka"], salary_to=300000, format="Гибрид")
    eff = effective_threshold({"spec": "Backend", "grade_min": "Junior", "must_skills": ["Redis"]}, need)
    assert eff["track"] == "Python" and eff["must_skills"] == ["Python", "Kafka", "Redis"] and eff["fork_to"] == 300000
    assert eff["formats"] == ["Гибрид"] and eff["grade_min"] == "Junior"
    for bad in ({"spec": "QA"}, {"track": "Go"}, {"grade_min": "Intern"}, {"fork_to": 350000}, {"formats": ["Удалённо"]}):
        try:
            effective_threshold(bad, need)
            raise AssertionError(bad)
        except ValueError:
            pass
    print("ok")
