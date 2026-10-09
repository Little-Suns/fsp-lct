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
# задача на код — ровно одна за сессию, после четырёх рабочих заданий (θ уже грубо оценён):
# LLM решает такие задачи почти всегда, поэтому вес в тесте умеренный — одно задание из 6–12 и a ≈ 1,5–1,7
CODE_AT = 4


def is_code(it) -> bool:
    return getattr(it, "kind", None) == "code"
# экспресс-режим (знакомство за 3–5 минут): 5 заданий — контент-баланс next_item даёт по одному на 5 разных компетенций,
# остановки по SE нет, поэтому SE честно больше (≈ 0,45 против ≈ 0,33); грейд — тем же правилом θ − SE ≥ порог
EXPRESS_ITEMS = 5
# ревью с комментарием в минуту не укладывается; задача на код (kind = code) — тоже: написать и отладить функцию за 60 с
# нельзя (её лимит — 15 минут), а растягивать экспресс ради неё — терять смысл «знакомства за 3–5 минут». Слот choose
# в экспрессе не срабатывает: банк для выбора заранее отфильтрован по EXPRESS_KINDS (quest._serve, simulate_session)
EXPRESS_KINDS = ("choice", "mark")
SPEC_SE_MAX = 0.37  # самопроверка: средняя SE полного теста на банке любой специализации (цель — ≤ 0,35, у Backend ≈ 0,33)


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


def next_item(theta: float, bank, seen_ids: set, seen_families: set, rng: random.Random, top: int = TOP_K, focus: dict | None = None,
              code: bool = False):
    """Следующее задание: контент-баланс по компетенциям → максимум информации Фишера → случайное из top лучших семейств.
    focus — веса компетенций из вакансии (1.0–1.5): мягкий множитель информации, влияет только на выбор, не на оценку.
    code — выбирать только среди задач на код (их слот — choose), иначе только среди остальных."""
    pool = [it for it in bank if not it.pilot and is_code(it) == code and it.id not in seen_ids and it.family not in seen_families]
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
    clones.sort(key=lambda it: -info(theta, it.a, it.b) * (focus or {}).get(it.competency, 1.0))
    return rng.choice(clones[:top])


def pick_pilot(bank, seen_ids: set, seen_families: set, rng: random.Random):
    """Пилотное задание (на грейд не влияет). Пилотная задача на код занимает и слот задачи на код этой сессии."""
    pool = [it for it in bank if it.pilot and it.id not in seen_ids and it.family not in seen_families]
    return rng.choice(pool) if pool else None


def choose(theta: float, bank, seen_ids: set, seen_families: set, rng: random.Random, n_op: int, focus: dict | None = None):
    """Следующее рабочее задание: после CODE_AT рабочих — задача на код (если её ещё не было), иначе next_item."""
    if n_op >= CODE_AT and not any(is_code(it) for it in bank if it.id in seen_ids):
        it = next_item(theta, bank, seen_ids, seen_families, rng, code=True)
        if it:
            return it
    return next_item(theta, bank, seen_ids, seen_families, rng, focus=focus)


def should_stop(n: int, se: float, express: bool = False) -> bool:
    if express:
        return n >= EXPRESS_ITEMS
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


def grade_anchor(grade: str) -> float:
    """Точка на шкале θ для грейда: его порог (у Intern порога нет — берём середину между −∞ и Junior)."""
    return catalog.GRADE_TH[grade] if grade != "Intern" else catalog.GRADE_TH["Junior"] - 0.7


def start_prior(target_grade: str | None, rating: float | None) -> float:
    """Старт выбора заданий: порог заявленного грейда (информация максимальна там, где решается «подтвердил или нет»),
    при подтверждённом CF — среднее с CF-оценкой. В итоговую оценку не входит."""
    base = grade_anchor(target_grade) if target_grade in catalog.GRADES else 0.0
    return (base + cf_prior(rating)) / 2 if rating is not None else base


def cf_theta(rating: float) -> float:
    """Рейтинг Codeforces → θ на шкале «Алгоритмов». Мягко: 1500 → 0, ±600 → ±1, обрезка ±1.5."""
    return float(np.clip((rating - 1500) / 600, -1.5, 1.5))


def cf_prior(rating: float | None) -> float:
    """Стартовый априор θ для подбора заданий (старт ближе к уровню → тест короче). В итоговую оценку не входит."""
    return 0.5 * cf_theta(rating) if rating is not None else 0.0


def decide_grade(prev: str | None, theta: float, se: float, upgrade_allowed: bool = True) -> str:
    """Грейд после попытки. Первое присвоение — по θ − SE. Дальше только вверх: повышение — если θ − SE выше порога
    нового грейда (и не идёт кулдаун). Принудительно грейд не понижается никогда: попытка ниже текущего грейда в профиль
    не идёт, кандидат может сам принять нижний грейд (quest.accept_lower)."""
    up = catalog.grade_from_theta(theta, se)
    if prev not in catalog.GRADES:
        return up
    return up if upgrade_allowed and catalog.GRADES.index(up) > catalog.GRADES.index(prev) else prev


def simulate_session(bank, true_theta: float, rng: random.Random, prior_mean: float = 0.0, express: bool = False) -> tuple[float, float, int]:
    """Прогон адаптивной сессии симулированным кандидатом (без пилотных заданий; задача на код — своим слотом, если она есть в банке)."""
    seen_ids, seen_fam, resp = set(), set(), []
    theta, se = prior_mean, 1.0
    if express:  # как quest._serve: в экспрессе только EXPRESS_KINDS
        bank = [it for it in bank if getattr(it, "kind", "choice") in EXPRESS_KINDS]
    while not should_stop(len(resp), se, express):
        it = choose(theta, bank, seen_ids, seen_fam, rng, len(resp))
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

    rows = generate_bank()

    def spec_bank(spec: str, kinds=None) -> list:
        return [SimpleNamespace(id=i, **{k: r[k] for k in ("family", "competency", "kind", "a", "b", "pilot")})
                for i, r in enumerate(rows) if r["spec"] == spec and (kinds is None or r["kind"] in kinds)]

    bank = spec_bank("Backend")
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

    # каждая специализация: полный тест и экспресс (5 заданий). Честность экспресса: SE больше, а грейд выше истинного
    # (по правде θ синтетического кандидата) он ставит не чаще полного теста — правило θ − SE с большой SE осторожнее
    gi = catalog.GRADES.index
    print("средняя SE и доля грейдов выше истинного: полный тест / экспресс")
    for spec in catalog.SPECS:
        full_bank, exp_bank = spec_bank(spec), spec_bank(spec, EXPRESS_KINDS)
        tt = [rng.gauss(0, 1) for _ in range(1000)]  # при 300 разница долей ±3 п. п. — шум, порог ниже срабатывал от любой правки банка
        full = [simulate_session(full_bank, t, rng) for t in tt]
        exp = [simulate_session(exp_bank, t, rng, express=True) for t in tt]
        se_full, se_exp = float(np.mean([s[1] for s in full])), float(np.mean([s[1] for s in exp]))
        over = [float(np.mean([gi(catalog.grade_from_theta(s[0], s[1])) > gi(catalog.grade_from_theta(t, 0)) for s, t in zip(runs, tt)]))
                for runs in (full, exp)]
        print(f"  {spec}: SE {se_full:.3f} / {se_exp:.3f}; выше истинного {over[0]:.0%} / {over[1]:.0%}")
        assert se_full <= SPEC_SE_MAX, (spec, se_full)
        assert se_exp > se_full and all(e[2] == EXPRESS_ITEMS for e in exp), spec
        assert over[1] <= over[0] + 0.03, (spec, over)
    print("ok")
