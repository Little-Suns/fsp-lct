"""Квалифицированная лотерея (threshold lottery, Frey & Osterloh): детерминированный порог → слепой жребий.

Зачем: внутри порога кандидаты статистически неразличимы (интервалы θ ± SE перекрываются), и попытка
их «доранжировать» — ложная точность, в которую просачиваются предубеждения и знакомства. Жребий среди
прошедших порог разносит приглашения шире (разнообразие, меньше завала у «звёзд»), исключает непотизм и
проверяем снаружи через commit–reveal. Квоту лотерея не тратит: квота списывается только при отправке
приглашений выбранным (обычный поток приглашений, Invitation.lottery_id = id лотереи).

Порог (threshold, JSON):
  spec, track?, grade_min, theta_min? (θ − SE ≥ theta_min), must_skills[] (⊂ skills_confirmed),
  fork_to (min_salary ≤ fork_to), formats?[] (пересечение с форматами кандидата), require_free (нагрузка < CAP).
Всегда: статус open, тест пройден, ИНН компании не в hidden_from, нет открытого приглашения от этой компании
и нет её отклонённого / истёкшего приглашения за последние 90 дней.

Протокол: create — пул замораживается (отсортированные public_id), seed = token_hex(32), публикуется
sha256(seed); draw — seed раскрывается, порядок = sorted(pool, key=sha256(seed + public_id)), берутся
первые draw_count. Любой может повторить: verify_draw(seed, seed_hash, pool, drawn).
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

COOLDOWN_DAYS = 90  # отказ или молчание (истёкшее приглашение) этой компании — не навязываемся 90 дней
POOL_MAX = 500  # ponytail: больше — порог слишком мягкий, просим сузить; пагинация пула, если понадобится


def seed_hash(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


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
    q = select(Candidate).where(Candidate.spec == th["spec"], Candidate.status == "open", Candidate.theta.is_not(None))
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
    lot = Lottery(company_id=company.id, need_id=need_id, threshold=th, pool_ids=pool, draw_count=draw_count,
                  seed_hash=hashed, commitment=commitment(th, pool, draw_count, hashed), seed=seed)
    db.add(lot)
    try:
        db.commit()
    except IntegrityError as e:  # гонка двух одновременных запросов: сработал UniqueConstraint(company_id, need_id)
        db.rollback()
        raise LotteryExists("Для этой потребности жеребьёвка уже проведена — перебросить жребий нельзя") from e
    return lot


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
    """Обезличенное состояние для проверки кем угодно: без компании, потребности и ПДн (public_id анонимны)."""
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


def public_state(lot: Lottery) -> dict:
    return {**public_view(lot), "need_id": lot.need_id}


def result(db: Session, lot: Lottery) -> dict:
    loads = open_loads(db)
    by_pid = {c.public_id: c for c in db.scalars(select(Candidate).where(Candidate.public_id.in_(lot.drawn_ids or [])))}
    return {
        "id": lot.id,
        "drawn": [card(by_pid[p], loads.get(by_pid[p].id, 0)) for p in lot.drawn_ids or [] if p in by_pid],
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
    print("ok")
