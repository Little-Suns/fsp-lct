"""Валидация подбора и теста (сессия, §8): качество выдачи, симуляция рынка, «читер», стабильность,
разделяющая сила теста (отличает ли он один грейд от другого).

Правильные ответы — seed.gold.relevance по скрытой правде синтетики (Candidate.truth), без LLM.
Всё детерминировано по seed и дате засева (--today, как у seed.generate): «сейчас» подбора (открытые приглашения,
нагрузка) — полдень МСК этой даты, а не реальное время, поэтому цифры не плывут от дня ко дню.
В БД ничего не пишется (кроме засева банка заданий, если он пуст).

Запуск: uv run python -m app.services.validation [--k 10] [--seed 42] [--today 2026-10-05|now]
→ отчёт в консоль + backend/var/validation.json
"""

import argparse
import json
import random
import time
from collections import Counter, defaultdict
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app import catalog, config
from app.models import Candidate, ExternalAccount, Item, Need
from app.services import irt, matching
from app.services.items import seed_items
from seed.generate import DEMO_TODAY, THETA_BAND, anchor, parse_today
from seed.gold import relevance

OUT = Path(__file__).resolve().parents[2] / "var" / "validation.json"
REL_TH = 2  # «релевантен» = оценка ≥ 2
VARIANTS = [("embed", "Эмбеддинги / навыки"), ("rerank", "+ структурный реранк"), ("full", "+ взаимный интерес")]
KINDS = ("normal", "adjacent", "fork_low")
ROUNDS, PER_NEED = 4, 10  # недели симуляции; приглашений от потребности за неделю
N_CHEAT, N_HONEST, N_RETEST = 200, 200, 200
N_GRADE, N_CALIB = 200, 500  # разделяющая сила: симулированных кандидатов на грейд; калибровочная выборка для r_pb
RPB_POOR, A_LOW, A_HIGH = 0.2, 0.65, 1.35  # r_pb < 0,2 — задание слабо различает (Ebel); границы a — по Baker (2001)


# ───────────────────────── метрики ─────────────────────────

def precision_at_k(rels: list[int], k: int, th: int = REL_TH) -> float:
    """Стандартная P@k: релевантных (≥ th) в топ-k, делённое на k (недобор выдачи — штраф)."""
    return sum(r >= th for r in rels[:k]) / k


def dcg(rels: list[int], k: int) -> float:
    return float(sum((2**r - 1) / np.log2(i + 2) for i, r in enumerate(rels[:k])))


def ndcg_at_k(rels: list[int], all_rels: list[int], k: int) -> float | None:
    """nDCG@k: идеал — лучшие k оценок среди ВСЕХ допустимых кандидатов, а не только выданных."""
    ideal = dcg(sorted(all_rels, reverse=True), k)
    return dcg(rels, k) / ideal if ideal > 0 else None


def gini(x) -> float:
    x = np.sort(np.asarray(x, dtype=float))
    n, s = len(x), x.sum()
    return float(2 * np.sum(np.arange(1, n + 1) * x) / (n * s) - (n + 1) / n) if n and s > 0 else 0.0


def spearman(x, y) -> float | None:
    if len(x) < 3:
        return None
    return float(np.corrcoef(_ranks(x), _ranks(y))[0, 1])


def _ranks(v) -> np.ndarray:
    """Ранги со средним для совпадающих значений (как scipy.stats.rankdata)."""
    v = np.asarray(v, dtype=float)
    r = np.empty(len(v))
    r[np.argsort(v, kind="stable")] = np.arange(1, len(v) + 1)
    _, inv, cnt = np.unique(v, return_inverse=True, return_counts=True)
    return (np.bincount(inv, weights=r) / cnt)[inv]


# ───────────────────────── качество выдачи ─────────────────────────

def _pools(db: Session, needs: list[Need]) -> dict[int, list[Candidate]]:
    """Допустимые кандидаты (matching.eligible) по каждой потребности; запрос — один на (spec, grade)."""
    cache: dict[tuple, list[Candidate]] = {}
    out = {}
    for n in needs:
        key = (n.spec, n.grade, n.salary_to, n.city)  # грейд +1 в eligible() зависит от вилки и города
        if key not in cache:
            cache[key] = matching.eligible(db, n)
        inn = n.company.inn if n.company else None
        out[n.id] = [c for c in cache[key] if not (inn and inn in (c.hidden_from or []))]
    return out


def quality(db: Session, needs: list[Need], pools: dict, k: int) -> tuple[dict, dict]:
    """precision@k и nDCG@k трёх вариантов; заодно — полный пул «full» для симуляции рынка."""
    per = {v: [] for v, _ in VARIANTS}
    kinds = {kd: {v: [] for v, _ in VARIANTS} for kd in KINDS}
    ranked_pool, skipped, ceiling = {}, 0, []
    unc = Counter()  # не подтверждённые тестом: в пуле, среди годных по эталону, в топ-k «full»
    for n in needs:
        pool = pools[n.id]
        rel = {c.id: relevance(c, n) for c in pool}
        full = matching.score_candidates(db, n, pool, variant="full", limit=matching.RETRIEVE_K)
        ranked_pool[n.id] = full
        if not any(r >= REL_TH for r in rel.values()):  # нет ни одного годного — нечего искать, метрика не определена
            skipped += 1
            continue
        n_rel = sum(r >= REL_TH for r in rel.values())
        unc.update(pool=len(pool), pool_u=sum(not matching.tested(c) for c in pool), rel=n_rel,
                   rel_u=sum(rel[c.id] >= REL_TH and not matching.tested(c) for c in pool),
                   top=len(full[:k]), top_u=sum(not matching.tested(r.candidate) for r in full[:k]))
        ceiling.append(min(k, n_rel) / k)  # лучшая достижимая precision@k для этой потребности
        tops = {
            "embed": [r.candidate for r in matching.score_candidates(db, n, pool, variant="embed", limit=k)],
            # «rerank» = тот же пул RETRIEVE_K, отсортированный по соответствию — ровно как score_candidates(variant="rerank"):
            # не подтверждённые тестом — после прошедших (matching.order_key)
            "rerank": [r.candidate for r in sorted(full, key=lambda r: (not matching.tested(r.candidate), -r.match, r.candidate.public_id))[:k]],
            "full": [r.candidate for r in full[:k]],
        }
        for v, top in tops.items():
            rels = [rel[c.id] for c in top]
            m = (precision_at_k(rels, k), ndcg_at_k(rels, list(rel.values()), k))
            per[v].append(m)
            kinds.setdefault(n.kind, {v: [] for v, _ in VARIANTS})[v].append(m)

    def avg(ms):
        return {"precision": round(float(np.mean([m[0] for m in ms])), 3) if ms else None,
                "ndcg": round(float(np.mean([m[1] for m in ms])), 3) if ms else None}

    return {
        "variants": [{"key": v, "label": lb, **avg(per[v])} for v, lb in VARIANTS],
        "by_kind": {kd: {v: avg(ms) for v, ms in d.items()} for kd, d in kinds.items()},
        "relevant_threshold": REL_TH,
        "precision_ideal": round(float(np.mean(ceiling)), 3) if ceiling else None,
        "needs_evaluated": len(per["full"]),
        "needs_skipped": skipped,
        # эталон считает не подтверждённых по правде синтетики (годный без теста — годный), подбор ставит их ниже
        # прошедших тест: доля среди годных против доли в топе — сколько честно годных подбор опускает
        "unconfirmed": {key: round(unc[f"{key}_u"] / unc[key], 3) if unc[key] else None for key in ("pool", "rel", "top")},
    }, ranked_pool


# ───────────────────────── симуляция рынка ─────────────────────────

def _stars(population: list[Candidate], share: float = 0.05) -> set[int]:
    """Топ-5 % по θ внутри специализации: глобальный топ — почти одни Lead, которых редко ищут, метрика была бы пустой.
    Не подтверждённые тестом в «звёзды» не попадают: их θ неизвестен."""
    by_spec = defaultdict(list)
    for c in filter(matching.tested, population):
        by_spec[c.spec].append(c)
    return {c.id for grp in by_spec.values() for c in sorted(grp, key=lambda c: -(c.theta or 0))[: max(1, round(share * len(grp)))]}


def _best_full(cand: list, load: Counter):
    return min(cand, key=lambda r: (-matching.final_score(r.match, r.accept, load[r.candidate.id]), r.candidate.public_id))


def market(needs: list[Need], ranked_pool: dict, population: list[Candidate], seed: int) -> dict:
    """Работодатели-агенты (синтетические потребности) × ROUNDS недель. Популяция — копия в памяти, БД не трогаем.

    no_limits: порядок по соответствию (rerank), до PER_NEED приглашений в неделю, квоты нет;
    with_limits: итог «full» с живой нагрузкой (пересчёт после каждого приглашения) + недельная квота компании
      + жёсткий CAP, как в продукте (409): кандидата с load ≥ CANDIDATE_CAP пропускаем, blocked_by_cap — сколько раз;
    quota_only (диагностика): порядок rerank + квота — тот же объём приглашений, что with_limits, без взаимного интереса.
    Кандидат (одинаков в обоих режимах): за неделю отвечает максимум на CANDIDATE_CAP приглашений — сначала
    с лучшей вилкой, остальные истекают; принимает, если вилка ≥ минимума и формат подходит, с вероятностью accept_prob.
    # ponytail: внимание кандидата = CANDIDATE_CAP ответов в неделю, найм не снимает с рынка; калибровать по воронке
    """
    company_of = {n.id: n.company_id for n in needs}
    quota_max = {n.company_id: n.company.quota_max for n in needs}
    out = {}
    for regime in ("no_limits", "quota_only", "with_limits"):
        rng = random.Random(f"{seed}:{regime}")
        invites, accepted, sent_total, blocked = Counter(), 0, 0, 0
        closed: set[int] = set()
        invited = defaultdict(set)  # потребность → уже приглашённые (повторно не зовём)
        co_sent, co_acc = Counter(), Counter()
        order = [n.id for n in needs if ranked_pool.get(n.id)]
        for _ in range(ROUNDS):
            load = Counter()  # открытые приглашения этой недели; срок 7 дней → к следующей неделе истекают
            inbox = defaultdict(list)
            co_used, need_used = Counter(), Counter()
            quota = {co: catalog.QUOTA_BONUS if co_sent[co] and co_acc[co] / co_sent[co] >= catalog.QUOTA_BONUS_AT
                     else mx for co, mx in quota_max.items()}
            rng.shuffle(order)
            progress = True
            while progress:  # круговой обход: каждая потребность шлёт по одному, чтобы живая нагрузка влияла на всех
                progress = False
                for nid in order:
                    co = company_of[nid]
                    if nid in closed or need_used[nid] >= PER_NEED or (regime != "no_limits" and co_used[co] >= quota[co]):
                        continue
                    cand = [r for r in ranked_pool[nid] if r.candidate.id not in invited[nid]]
                    if not cand:
                        continue
                    if regime != "with_limits":
                        best = min(cand, key=lambda r: (-r.match, r.candidate.public_id))
                    else:
                        free = [r for r in cand if load[r.candidate.id] < catalog.CANDIDATE_CAP]
                        blocked += len(free) < len(cand) and _best_full(cand, load).candidate.id not in {r.candidate.id for r in free}
                        if not free:
                            continue
                        best = _best_full(free, load)
                    cid = best.candidate.id
                    invited[nid].add(cid)
                    load[cid] += 1
                    invites[cid] += 1
                    need_used[nid] += 1
                    co_used[co] += 1
                    co_sent[co] += 1
                    sent_total += 1
                    inbox[cid].append((nid, best))
                    progress = True
            for cid, lst in inbox.items():
                lst.sort(key=lambda x: -x[1].explanation["fork"]["to"])
                for nid, r in lst[: catalog.CANDIDATE_CAP]:
                    e = r.explanation
                    ok = e["fork"]["to"] >= r.candidate.min_salary and e["format_ok"]
                    if ok and rng.random() < r.accept:
                        accepted += 1
                        closed.add(nid)
                        co_acc[company_of[nid]] += 1
        counts = np.array([invites[c.id] for c in population])
        top = _stars(population)
        out[regime] = {
            "accepted_share": accepted / sent_total if sent_total else 0.0,
            "coverage": float(np.mean(counts > 0)) if len(counts) else 0.0,
            "gini": gini(counts),
            "closed_needs": len(closed) / len(order) if order else 0.0,
            "top5": sum(invites[c] for c in top) / sent_total if sent_total else 0.0,
            "sent": sent_total,
            "blocked": blocked,
        }
    labels = {"accepted_share": "Доля принятых приглашений", "coverage": "Охват кандидатов",
              "gini": "Джини по приглашениям", "closed_needs": "Закрытые потребности"}
    r3 = lambda x: round(float(x), 3)  # noqa: E731
    return {
        "rows": [{"key": k, "label": lb, **{m: r3(out[m][k]) for m in out}} for k, lb in labels.items()],
        "top5_share": {m: r3(out[m]["top5"]) for m in out},
        "rounds": ROUNDS,
        "sent": {m: out[m]["sent"] for m in out},
        "blocked_by_cap": out["with_limits"]["blocked"],
    }


# ───────────────────────── IRT: «читер» и стабильность ─────────────────────────

def _bank(db: Session, spec: str = "Backend") -> list[SimpleNamespace]:
    seed_items(db)
    return [SimpleNamespace(id=it.id, family=it.family, competency=it.competency, kind=it.kind, a=it.a, b=it.b, pilot=it.pilot,
                            ctx=(it.payload.get("panel") or {}).get("type") in ("logs", "chart"))
            for it in db.scalars(select(Item).where(Item.spec == spec, Item.pilot.is_(False)).order_by(Item.id))]


def _session(bank, p_correct, rng: random.Random, prior_mean: float = 0.0):
    """Адаптивная сессия как irt.simulate_session, но с произвольной моделью ответа p_correct(item).
    prior_mean — старт выбора заданий (в продукте — порог заявленного грейда); θ в ответе — с этим априором."""
    seen_ids, seen_fam, resp = set(), set(), []
    theta, se = prior_mean, 1.0
    while not irt.should_stop(len(resp), se):
        it = irt.next_item(theta, bank, seen_ids, seen_fam, rng)
        if it is None:
            break
        seen_ids.add(it.id)
        seen_fam.add(it.family)
        resp.append((it.a, it.b, int(rng.random() < p_correct(it))))
        theta, se = irt.eap(resp, prior_mean)
    return theta, se, resp


def _cheater_p(it) -> float:
    """LLM-«читер» (модель ответа, без реального прогона LLM): варианты без контекста — 0,9 независимо от b;
    ревью/разметка кода с тонкими багами — как человек с θ = −0,5; логи и графики — как θ = −0,3.
    # ponytail: вероятности заданы руками; заменить долями верных ответов реальной 32B-модели на банке"""
    if it.kind in ("review", "mark"):
        return float(irt.prob(-0.5, it.a, it.b))
    if it.ctx:
        return float(irt.prob(-0.3, it.a, it.b))
    return 0.9


def cheater(bank, seed: int) -> dict:
    subsets = [
        ("choice", "Вопросы с вариантами", [it for it in bank if it.kind == "choice" and not it.ctx]),
        ("review", "Ревью кода с тонкими багами", [it for it in bank if it.kind in ("review", "mark")]),
        ("context", "Задачи с контекстом (логи, графики)", [it for it in bank if it.ctx]),
        ("mixed", "Смешанный боевой тест", bank),
    ]
    rows, mixed = [], []
    for key, label, sub in subsets:
        rng = random.Random(f"{seed}:cheat:{key}")
        runs = [_session(sub, _cheater_p, rng) for _ in range(N_CHEAT)]
        t, se = float(np.mean([r[0] for r in runs])), float(np.mean([r[1] for r in runs]))
        rows.append({"key": key, "label": label, "grade": catalog.grade_from_theta(t, se), "theta": round(t, 2), "se": round(se, 2)})
        if key == "mixed":
            mixed = runs
    rng = random.Random(f"{seed}:honest")
    honest = []
    for _ in range(N_HONEST):
        tt = rng.gauss(0, 1)
        honest.append(_session(bank, lambda it, tt=tt: float(irt.prob(tt, it.a, it.b)), rng))
    flagged = lambda runs: float(np.mean(["inconsistent" in irt.suspicion_flags(t, r, []) for t, _, r in runs]))  # noqa: E731
    return {"simulated": True, "rows": rows, "caught": round(flagged(mixed), 3), "false_alarm": round(flagged(honest), 3)}


def stability(db: Session, bank, seed: int) -> dict:
    """Пересдача (как самопроверка irt): та же правда θ, другие клоны и траектория."""
    rng = random.Random(f"{seed}:retest")
    true = np.array([rng.gauss(0, 1) for _ in range(N_RETEST)])
    s1 = [irt.simulate_session(bank, t, rng) for t in true]
    s2 = [irt.simulate_session(bank, t, rng) for t in true]
    g1 = [catalog.grade_from_theta(t, se) for t, se, _ in s1]
    raw = np.mean([g == catalog.grade_from_theta(t, se) for g, (t, se, _) in zip(g1, s2)])
    hyst = np.mean([irt.decide_grade(g, t, se) == g for g, (t, se, _) in zip(g1, s2)])
    corr = float(np.corrcoef(true, [s[0] for s in s1])[0, 1])

    fam = defaultdict(list)
    for f, b in db.execute(select(Item.family, Item.b)):
        fam[f].append(b)
    spread = float(np.mean([np.std(v) for v in fam.values() if len(v) > 1])) if fam else None

    rows = db.execute(
        select(Candidate.competencies, ExternalAccount.rating)
        .join(ExternalAccount, ExternalAccount.candidate_id == Candidate.id)
        .where(ExternalAccount.provider == "codeforces", ExternalAccount.rating.is_not(None))
    ).all()
    pairs = [(next(x["t"] for x in comps if x["n"] == "Алгоритмы"), rt) for comps, rt in rows
             if any(x.get("n") == "Алгоритмы" for x in comps or [])]
    rho = spearman([p[0] for p in pairs], [p[1] for p in pairs])
    return {
        "retest_same_grade": round(float(hyst), 3),
        "retest_same_grade_no_hysteresis": round(float(raw), 3),
        "cf_spearman": round(rho, 3) if rho is not None else None,
        "cf_n": len(pairs),
        "clone_b_spread": round(spread, 3) if spread is not None else None,
        "theta_corr": round(corr, 3),
    }


# ───────────────────────── разделяющая сила теста ─────────────────────────

def _auc(lo, hi) -> float:
    """P(θ̂ кандидата старшего грейда > θ̂ младшего), ничьи — пополам (Манн — Уитни)."""
    r = _ranks(np.concatenate([lo, hi]))
    n0, n1 = len(lo), len(hi)
    return float((r[n0:].sum() - n1 * (n1 + 1) / 2) / (n0 * n1))


def _overlap(x, y, step: float = 0.25) -> float:
    """Площадь пересечения гистограмм θ̂ двух грейдов (0 — не пересекаются, 1 — совпадают)."""
    bins = np.arange(irt.GRID[0], irt.GRID[-1] + step, step)
    p, q = (np.histogram(np.clip(v, bins[0], bins[-1]), bins)[0] / len(v) for v in (x, y))
    return float(np.minimum(p, q).sum())


def _qwk(conf: np.ndarray) -> float:
    """Каппа Коэна с квадратичными весами: согласие истинного и тестового грейда с поправкой на случайное."""
    conf = np.asarray(conf)
    k, n = len(conf), conf.sum()
    i, j = np.indices((k, k))
    w = (i - j) ** 2 / (k - 1) ** 2
    e = np.outer(conf.sum(1), conf.sum(0)) / n
    return float(1 - (w * conf).sum() / (w * e).sum())


def _quart(x) -> dict:
    x = np.asarray(x, dtype=float)
    return {"min": round(float(x.min()), 3), "q1": round(float(np.percentile(x, 25)), 3), "median": round(float(np.median(x)), 3),
            "q3": round(float(np.percentile(x, 75)), 3), "max": round(float(x.max()), 3)}


def _items(banks: dict, seed: int) -> dict:
    """Дискриминативность заданий: параметр a (2PL) и точечно-бисериальная корреляция ответа с суммой остальных
    (item-rest) на калибровочной выборке: N_CALIB симулированных θ ~ N(0, 1) отвечают на все задания банка.
    В адаптивной сессии у разных людей разные задания — классическая item-total там не определена."""
    a = np.array([it.a for b in banks.values() for it in b])
    rng = np.random.default_rng(seed)
    rpb = []
    for bank in banks.values():
        th = rng.normal(0, 1, N_CALIB)
        A, B = np.array([it.a for it in bank]), np.array([it.b for it in bank])
        U = (rng.random((N_CALIB, len(bank))) < irt.prob(th[:, None], A, B)).astype(float)
        rest = U.sum(1)[:, None] - U
        rpb += [float(np.corrcoef(U[:, j], rest[:, j])[0, 1]) for j in range(len(bank)) if 0 < U[:, j].mean() < 1]
    return {"n": int(len(a)), "a": _quart(a),
            "a_bins": {"low": int((a < A_LOW).sum()), "moderate": int(((a >= A_LOW) & (a < A_HIGH)).sum()), "high": int((a >= A_HIGH).sum())},
            "rpb": _quart(rpb), "rpb_poor": round(float(np.mean(np.array(rpb) < RPB_POOR)), 3), "calib_n": N_CALIB}


def separation(db: Session, seed: int) -> dict:
    """Отличает ли тест один грейд от другого: N_GRADE симулированных кандидатов на грейд, истинный θ — равномерно в полосе
    грейда (как у синтетики, seed.generate.THETA_BAND), банки всех специализаций по кругу. Сессия — как в продукте:
    выбор заданий стартует у порога заявленного грейда (заявлен истинный), итог — EAP с нейтральным априором N(0, 1),
    грейд — θ − SE ≥ порога (catalog.grade_from_theta), поэтому ошибки смещены вниз; accuracy_point — тот же прогон
    с грейдом по самой оценке θ̂ (без запаса SE), чтобы отделить точность теста от осторожности правила.
    confusion[i][j] — сколько кандидатов истинного грейда i тест отнёс к грейду j."""
    G = catalog.GRADES
    banks = {s: b for s in catalog.SPECS if (b := _bank(db, s))}
    specs, rng = list(banks), random.Random(f"{seed}:separation")
    conf = np.zeros((len(G), len(G)), dtype=int)
    est, ses, point = defaultdict(list), defaultdict(list), []
    per_spec = defaultdict(lambda: defaultdict(list))  # спец. → hit / near / items / se
    for gi, g in enumerate(G):
        lo, hi = THETA_BAND[g]
        for i in range(N_GRADE):
            spec, tt = specs[i % len(specs)], rng.uniform(lo, hi)
            *_, resp = _session(banks[spec], lambda it, tt=tt: float(irt.prob(tt, it.a, it.b)), rng, irt.start_prior(g, None))
            t, se = irt.eap(resp)
            gj = G.index(catalog.grade_from_theta(t, se))
            conf[gi, gj] += 1
            est[g].append(t)
            ses[g].append(se)
            point.append(catalog.grade_from_theta(t, 0.0) == g)
            for key, v in (("hit", gj == gi), ("near", abs(gj - gi) <= 1), ("items", len(resp)), ("se", se)):
                per_spec[spec][key].append(v)
    n, hit = int(conf.sum()), int(np.trace(conf))
    dist = np.abs(np.subtract.outer(np.arange(len(G)), np.arange(len(G))))
    r3 = lambda x: round(float(x), 3)  # noqa: E731
    return {
        "simulated": True,
        "n_per_grade": N_GRADE,
        "specs": len(specs),
        "grades": G,
        "confusion": conf.tolist(),
        "per_grade": [{"grade": g, "n": int(conf[i].sum()), "accuracy": r3(conf[i, i] / conf[i].sum()),
                       "under": r3(conf[i, :i].sum() / conf[i].sum()), "over": r3(conf[i, i + 1:].sum() / conf[i].sum()),
                       "theta_mean": round(float(np.mean(est[g])), 2), "theta_sd": round(float(np.std(est[g])), 2),
                       "se_mean": round(float(np.mean(ses[g])), 2)} for i, g in enumerate(G)],
        "accuracy": r3(hit / n),
        "accuracy_point": r3(np.mean(point)),
        "within_one": r3(conf[dist <= 1].sum() / n),
        "adjacent_error_share": r3(conf[dist == 1].sum() / (n - hit)) if n > hit else None,
        "qwk": r3(_qwk(conf)),
        "adjacent": [{"lo": a, "hi": b, "auc": r3(_auc(np.array(est[a]), np.array(est[b]))), "overlap": r3(_overlap(est[a], est[b]))}
                     for a, b in zip(G, G[1:])],
        "by_spec": [{"spec": s, "families": len({it.family for it in banks[s]}), "accuracy": r3(np.mean(d["hit"])),
                     "within_one": r3(np.mean(d["near"])), "items": round(float(np.mean(d["items"])), 1),
                     "se_mean": round(float(np.mean(d["se"])), 2)} for s, d in per_spec.items()],
        "items": _items(banks, seed),
    }


# ───────────────────────── сборка ─────────────────────────

def dataset(db: Session) -> dict:
    synth = Candidate.is_synthetic.is_(True)
    n = db.scalar(select(func.count(Candidate.id)).where(synth)) or 0
    ach = db.scalar(select(func.count(Candidate.id)).where(synth, Candidate.achievements.any())) or 0
    cf = db.scalar(select(func.count(Candidate.id)).where(synth, Candidate.accounts.any(ExternalAccount.provider == "codeforces"))) or 0
    untested = db.scalar(select(func.count(Candidate.id)).where(synth, Candidate.theta.is_(None))) or 0
    return {"candidates": n, "needs": db.scalar(select(func.count(Need.id)).where(Need.is_synthetic.is_(True))) or 0,
            "with_achievements": round(ach / n, 3) if n else 0.0, "with_cf": round(cf / n, 3) if n else 0.0,
            "untested": round(untested / n, 3) if n else 0.0,
            "gold_experts": None, "kappa": None}


def run(db: Session, *, k: int = 10, seed: int = 42, today: date | None = DEMO_TODAY) -> dict:
    """today — дата засева (seed.generate --today): на её полдень МСК считаются открытые приглашения и нагрузка;
    None — реальное время (засев с --today now, прогон сразу после него)."""
    # LLM-реранк выключен на время прогона: метрики детерминированы и меряют структурный реранк (как в подписи).
    # ponytail: глобальный флаг процесса — параллельные запросы API на ~5 с прогона тоже идут без LLM;
    # чисто — параметр use_llm=False в matching.score_candidates (сейчас matching.py правят параллельно, не трогаю)
    saved, config.LLM_BASE_URL = config.LLM_BASE_URL, ""
    clock = matching.CLOCK.set(anchor(today))
    try:
        needs = list(db.scalars(select(Need).where(Need.is_synthetic.is_(True), Need.kind.is_not(None))
                                .options(selectinload(Need.company)).order_by(Need.id)))
        pools = _pools(db, needs)
        q, ranked_pool = quality(db, needs, pools, k)
        population = list(db.scalars(select(Candidate).where(Candidate.status == "open")))  # с не подтверждёнными: они в выдаче
        mk = market(needs, ranked_pool, population, seed)
    finally:
        config.LLM_BASE_URL = saved
        matching.CLOCK.reset(clock)
    bank = _bank(db)
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "k": k,
        "seed": seed,
        "today": today.isoformat() if today else None,
        "dataset": dataset(db),
        "quality": q,
        "market": mk,
        "cheater": cheater(bank, seed),
        "stability": stability(db, bank, seed),
        "separation": separation(db, seed),
    }


def save(res: dict, path: Path | None = None) -> Path:
    path = path or OUT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, ensure_ascii=False, indent=1))
    return path


def report(res: dict) -> str:
    f = lambda x: "—" if x is None else f"{x:.3f}"  # noqa: E731
    d, q, m, ch, st, k = res["dataset"], res["quality"], res["market"], res["cheater"], res["stability"], res["k"]
    L = [f"Валидация ФСП Карьеры · {res['generated_at']} · k = {k}, seed = {res.get('seed')}, дата засева = {res.get('today') or 'сейчас'}",
         f"Данные: {d['candidates']} синтетических кандидатов, {d['needs']} потребностей; с достижениями {d['with_achievements']:.0%}, с CF {d['with_cf']:.0%}, "
         f"без теста {d.get('untested', 0):.0%}",
         "",
         f"Качество выдачи (релевантен = оценка ≥ {q['relevant_threshold']}; потребностей {q['needs_evaluated']}, без годных кандидатов пропущено {q['needs_skipped']})",
         f"  потолок precision@{k} (все годные наверху): {f(q['precision_ideal'])}",
         f"  {'вариант':<26}{'precision@' + str(k):>14}{'nDCG@' + str(k):>10}"]
    L += [f"  {v['label']:<26}{f(v['precision']):>14}{f(v['ndcg']):>10}" for v in q["variants"]]
    u = q.get("unconfirmed") or {}
    pc = lambda x: "—" if x is None else f"{x:.1%}"  # noqa: E731
    L.append(f"  не подтверждённые тестом (идут после прошедших): в пуле {pc(u.get('pool'))}, среди годных по эталону {pc(u.get('rel'))}, "
             f"в топ-{k} {pc(u.get('top'))}")
    L.append("  по типам потребностей (precision / nDCG):")
    for kd, d2 in q["by_kind"].items():
        L.append(f"    {kd:<10}" + "  ".join(f"{v}: {f(d2[v]['precision'])} / {f(d2[v]['ndcg'])}" for v, _ in VARIANTS))
    L += ["", f"Симуляция рынка ({m['rounds']} недели; приглашений: {m['sent']['no_limits']} / {m['sent']['quota_only']} / {m['sent']['with_limits']}; упёрлись в CAP: {m['blocked_by_cap']})",
          f"  {'метрика':<30}{'без лимитов':>12}{'только квота':>14}{'квота+ёмкость':>15}"]
    L += [f"  {r['label']:<30}{f(r['no_limits']):>12}{f(r['quota_only']):>14}{f(r['with_limits']):>15}" for r in m["rows"]]
    t5 = m["top5_share"]
    L.append(f"  {'Доля у топ-5 % по θ (в спец.)':<30}{f(t5['no_limits']):>12}{f(t5['quota_only']):>14}{f(t5['with_limits']):>15}")
    L += ["", "LLM-«читер» (симуляция), Backend:"]
    L += [f"  {r['label']:<38}{r['grade']:>8}   θ = {r['theta']:+.2f} ± {r['se']:.2f}" for r in ch["rows"]]
    L.append(f"  поймано проверкой на несогласованность: {ch['caught']:.0%}; ложные тревоги у честных: {ch['false_alarm']:.0%}")
    L += ["", "Стабильность:",
          f"  тот же грейд при пересдаче: {st['retest_same_grade']:.0%} с гистерезисом, {st['retest_same_grade_no_hysteresis']:.0%} без",
          f"  корреляция истинного и оценённого θ: {f(st['theta_corr'])}",
          f"  Спирмен θ «Алгоритмы» × рейтинг CF: {f(st['cf_spearman'])} (n = {st['cf_n']})",
          f"  разброс b внутри семейства (среднее SD): {f(st['clone_b_spread'])}"]
    sp = res["separation"]
    G, it = sp["grades"], sp["items"]
    L += ["", f"Разделяющая сила теста (симуляция: {sp['n_per_grade']} на грейд, банков {sp['specs']}; строки — истинный грейд, столбцы — грейд теста)",
          "  " + " " * 8 + "".join(f"{g:>8}" for g in G) + f"{'точность':>10}"]
    L += [f"  {g:<8}" + "".join(f"{x:>8}" for x in row) + f"{pg['accuracy']:>10.0%}" for g, row, pg in zip(G, sp["confusion"], sp["per_grade"])]
    L += [f"  точно: {sp['accuracy']:.0%} (по θ̂ без запаса SE — {sp['accuracy_point']:.0%}), ±1 грейд: {sp['within_one']:.0%}, "
          f"доля ошибок в соседний грейд: {f(sp['adjacent_error_share'])}, κ с квадратичными весами: {f(sp['qwk'])}",
          "  по специализациям (семейств · точно · ±1 · заданий · SE): " + "; ".join(
              f"{r['spec']} {r['families']} · {r['accuracy']:.0%} · {r['within_one']:.0%} · {r['items']} · {r['se_mean']}" for r in sp["by_spec"]),
          "  соседние грейды (AUC θ̂ / перекрытие): " + "; ".join(f"{p['lo']}|{p['hi']} {p['auc']:.3f} / {p['overlap']:.2f}" for p in sp["adjacent"]),
          f"  задания ({it['n']}): a — медиана {it['a']['median']:.2f} (Q1–Q3 {it['a']['q1']:.2f}–{it['a']['q3']:.2f}); "
          f"r_pb item-rest — медиана {it['rpb']['median']:.2f}, слабых (< {RPB_POOR}) {it['rpb_poor']:.0%}"]
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="Валидация подбора и теста")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--today", type=parse_today, default=DEMO_TODAY,
                    help=f"дата засева, как у seed.generate --today (по умолчанию {DEMO_TODAY}); now — реальное время")
    a = ap.parse_args()
    from app.db import SessionLocal

    t0 = time.time()
    with SessionLocal() as db:
        res = run(db, k=a.k, seed=a.seed, today=a.today)
    print(report(res))
    print(f"\n{time.time() - t0:.1f} с → {save(res)}")


if __name__ == "__main__":
    main()
