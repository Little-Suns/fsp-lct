"""IRT 2PL для тест-квеста: оценка θ (EAP), подбор задания по информации Фишера, остановка, person-fit.

Задание в функциях — любой объект с полями id, family, competency, a, b, pilot (модель Item подходит).
Ответ — кортеж (a, b, u), u ∈ {0, 1}.
"""

import random
from collections import Counter

import numpy as np

from app import catalog

GRID = np.linspace(-4, 4, 161)
MIN_ITEMS, MAX_ITEMS, SE_STOP = 6, 12, 0.25
TOP_K = 3  # randomesque: случайное из трёх лучших семейств — ограничивает засвечивание
COMP_PRIOR_SD = 0.7  # априор компетенции — N(общий θ, 0.7): мало заданий → оценка стягивается к общему θ
TOO_FAST_SHARE, TOO_FAST_MIN = 0.15, 2  # флаг, если ≥2 ответов быстрее 15 % лимита времени
LZ_CUT = -1.96


def prob(theta, a, b):
    return 1.0 / (1.0 + np.exp(-a * (np.asarray(theta) - b)))


def info(theta, a, b) -> float:
    p = prob(theta, a, b)
    return a * a * p * (1 - p)


def eap(responses, prior_mean: float = 0.0, prior_sd: float = 1.0) -> tuple[float, float]:
    """EAP-оценка θ на сетке с нормальным априором. Возвращает (θ, SE = апостериорное SD)."""
    logw = -0.5 * ((GRID - prior_mean) / prior_sd) ** 2
    for a, b, u in responses:
        p = np.clip(prob(GRID, a, b), 1e-9, 1 - 1e-9)
        logw += np.log(p if u else 1 - p)
    w = np.exp(logw - logw.max())
    w /= w.sum()
    t = float(w @ GRID)
    return t, float(np.sqrt(w @ (GRID - t) ** 2))


def competency_estimates(responses_by_comp: dict[str, list], names: list[str], theta: float, prior_override: dict[str, float] | None = None) -> list[dict]:
    """θ ± SE по компетенциям: те же EAP, задания только своей компетенции, априор стянут к общему θ."""
    out = []
    for n in names:
        mean = (prior_override or {}).get(n, theta)
        t, se = eap(responses_by_comp.get(n, []), mean, COMP_PRIOR_SD)
        out.append({"n": n, "t": round(t, 2), "se": round(se, 2)})
    return out


def next_item(theta: float, bank, seen_ids: set, seen_families: set, rng: random.Random, top: int = TOP_K):
    """Следующее задание: контент-баланс по компетенциям → максимум информации Фишера → случайное из top лучших семейств."""
    pool = [it for it in bank if not it.pilot and it.id not in seen_ids and it.family not in seen_families]
    if not pool:
        return None
    seen_comp = Counter(it.competency for it in bank if it.id in seen_ids and not it.pilot)
    # каждая компетенция — хотя бы одно задание; дальше допускаем перекос на 1, чтобы точнее целиться в θ
    least = min(seen_comp[it.competency] for it in pool)
    slack = 0 if least == 0 else 1
    by_family: dict[str, list] = {}
    for it in pool:
        if seen_comp[it.competency] <= least + slack:
            by_family.setdefault(it.family, []).append(it)
    clones = [rng.choice(v) for v in by_family.values()]  # один случайный клон на семейство
    clones.sort(key=lambda it: -info(theta, it.a, it.b))
    return rng.choice(clones[:top])


def pick_pilot(bank, seen_ids: set, seen_families: set, rng: random.Random):
    pool = [it for it in bank if it.pilot and it.id not in seen_ids and it.family not in seen_families]
    return rng.choice(pool) if pool else None


def should_stop(n: int, se: float) -> bool:
    return n >= MAX_ITEMS or (n >= MIN_ITEMS and se < SE_STOP)


def lz(theta: float, responses) -> float | None:
    """Стандартизованная лог-правдоподобная статистика person-fit (Drasgow et al., 1985). Сильно < 0 — ответы несогласованны."""
    if len(responses) < MIN_ITEMS:
        return None
    a, b, u = (np.array(x, dtype=float) for x in zip(*responses))
    p = np.clip(prob(theta, a, b), 1e-9, 1 - 1e-9)
    q = 1 - p
    l0 = np.sum(u * np.log(p) + (1 - u) * np.log(q))
    e = np.sum(p * np.log(p) + q * np.log(q))
    v = np.sum(p * q * np.log(p / q) ** 2)
    return float((l0 - e) / np.sqrt(v)) if v > 0 else None


def suspicion_flags(theta: float, responses, timings) -> list[str]:
    """inconsistent — сложные решены, простые нет (l_z < −1.96); too_fast — ответы быстрее 15 % лимита.
    timings: [(ms, time_limit_s)]."""
    flags = []
    z = lz(theta, responses)
    if z is not None and z < LZ_CUT:
        flags.append("inconsistent")
    if sum(1 for ms, lim in timings if ms is not None and ms < TOO_FAST_SHARE * lim * 1000) >= TOO_FAST_MIN:
        flags.append("too_fast")
    return flags


def cf_theta(rating: float) -> float:
    """Рейтинг Codeforces → θ на шкале «Алгоритмов». Мягко: 1500 → 0, ±600 → ±1, обрезка ±1.5."""
    return float(np.clip((rating - 1500) / 600, -1.5, 1.5))


def cf_prior(rating: float | None) -> float:
    """Стартовый априор θ для подбора заданий (старт ближе к уровню → тест короче). В итоговую оценку не входит."""
    return 0.5 * cf_theta(rating) if rating is not None else 0.0


def decide_grade(prev: str | None, theta: float, se: float, upgrade_allowed: bool = True) -> str:
    """Грейд с гистерезисом. Повышение — если θ − SE выше порога нового грейда (и не идёт кулдаун).
    Понижение — сразу, но только если θ + SE ниже порога текущего грейда (вся полоса погрешности ниже)."""
    up = catalog.grade_from_theta(theta, se)
    if prev not in catalog.GRADES:
        return up
    gi = catalog.GRADES.index
    if gi(up) > gi(prev):
        return up if upgrade_allowed else prev
    down = catalog.grade_from_theta(theta, -se)  # высший грейд, порог которого ниже θ + SE
    return down if gi(down) < gi(prev) else prev


def simulate_session(bank, true_theta: float, rng: random.Random, prior_mean: float = 0.0) -> tuple[float, float, int]:
    """Прогон адаптивной сессии симулированным кандидатом (без пилотных заданий)."""
    seen_ids, seen_fam, resp = set(), set(), []
    theta, se = prior_mean, 1.0
    while not should_stop(len(resp), se):
        it = next_item(theta, bank, seen_ids, seen_fam, rng)
        if it is None:
            break
        seen_ids.add(it.id)
        seen_fam.add(it.family)
        resp.append((it.a, it.b, int(rng.random() < prob(true_theta, it.a, it.b))))
        theta, se = eap(resp, prior_mean)
    return theta, se, len(resp)


if __name__ == "__main__":
    # самопроверка на реальном банке Backend: python -m app.services.irt
    from types import SimpleNamespace

    from app.services.items import generate_bank

    bank = [SimpleNamespace(id=i, **{k: r[k] for k in ("family", "competency", "a", "b", "pilot")})
            for i, r in enumerate(generate_bank()) if r["spec"] == "Backend"]
    rng = random.Random(7)
    true = np.array([rng.gauss(0, 1) for _ in range(200)])
    s1 = [simulate_session(bank, t, rng) for t in true]
    s2 = [simulate_session(bank, t, rng) for t in true]  # пересдача: другие клоны, другая траектория
    est = np.array([s[0] for s in s1])
    ses = np.array([s[1] for s in s1])
    corr = float(np.corrcoef(true, est)[0, 1])
    raw = np.mean([catalog.grade_from_theta(a[0], a[1]) == catalog.grade_from_theta(b[0], b[1]) for a, b in zip(s1, s2)])
    hyst = np.mean([decide_grade(catalog.grade_from_theta(a[0], a[1]), b[0], b[1]) == catalog.grade_from_theta(a[0], a[1]) for a, b in zip(s1, s2)])
    # честные кандидаты не должны массово ловить флаг несогласованности
    fp = np.mean([lz(true[i], [(it.a, it.b, int(rng.random() < prob(true[i], it.a, it.b))) for it in rng.sample(bank, 12)]) < LZ_CUT for i in range(200)])
    # «читер»: решает сложные (b > 1), проваливает простые (b < 0)
    cheat_resp = [[(it.a, it.b, int(it.b > 1)) for it in rng.sample([x for x in bank if x.b > 1 or x.b < 0], 12)] for _ in range(200)]
    caught = np.mean([lz(eap(r)[0], r) < LZ_CUT for r in cheat_resp])
    print(f"корреляция θ: {corr:.3f}; средняя SE: {ses.mean():.3f}; заданий в среднем: {np.mean([s[2] for s in s1]):.1f}")
    print(f"совпадение грейда при пересдаче: без гистерезиса {raw:.0%}, с гистерезисом {hyst:.0%}")
    print(f"флаг inconsistent: ложные срабатывания {fp:.0%}, пойманы «читеры» {caught:.0%}")
    assert corr > 0.85, corr
    assert ses.mean() < 0.35, ses.mean()
    assert hyst >= raw
    print("ok")
