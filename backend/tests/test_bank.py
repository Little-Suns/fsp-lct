"""Банк заданий: структура всех клонов всех специализаций, полнота банков и точность полного теста по специализациям.
БД не нужна."""

import random
from collections import Counter, defaultdict
from types import SimpleNamespace

import numpy as np
import pytest

from app import catalog
from app.services import irt
from app.services.items import FAMILIES, TIME_LIMIT, generate_bank

BANK = generate_bank()
PANELS = {"logs", "chart", "code"}
BANK_PREFIXES = ("be_", "fe_", "mob_", "mlds_", "dea_", "ops_", "qae_", "sec_")  # семейства services/bank/


def test_family_names_unique():
    names = [f["family"] for f in FAMILIES]
    assert len(names) == len(set(names)), [n for n, k in Counter(names).items() if k > 1]


@pytest.mark.parametrize("spec", catalog.SPECS)
def test_bank_size_per_competency(spec):
    """Не меньше 3 рабочих семейств на компетенцию; компетенции — из справочника специализации."""
    per = Counter(f["competency"] for f in FAMILIES if f["spec"] == spec and not f["pilot"])
    assert set(per) == set(catalog.COMPETENCIES[spec]), set(per) ^ set(catalog.COMPETENCIES[spec])
    assert min(per.values()) >= 3, per


def _check_panel(p: dict):
    assert p["type"] in PANELS, p
    if p["type"] == "logs":
        assert p["lines"] and all(set(x) == {"t", "src", "lvl", "msg"} and all(isinstance(v, str) for v in x.values()) for x in p["lines"])
    elif p["type"] == "code":
        assert p["lines"] and all(isinstance(x, str) for x in p["lines"]) and isinstance(p.get("lang", ""), str)
    else:
        n = len(p["x"])
        # фронт: серии слева делят одну шкалу, справа — не больше одной
        axes = [s["axis"] for s in p["series"]]
        assert 1 <= len(axes) <= 3 and axes.count("right") <= 1 and set(axes) <= {"left", "right"}, axes
        assert all(len(s["data"]) == n and s["name"] and s["max"] >= max(s["data"]) for s in p["series"])
        if p.get("marker"):
            assert 0 <= p["marker"]["i"] < n and p["marker"]["label"]


def test_every_clone_well_formed():
    for it in BANK:
        p = it["payload"]
        ctx = f"{it['family']}: {p.get('scene_title')}"
        assert it["kind"] in TIME_LIMIT and p["time_limit_s"] == TIME_LIMIT[it["kind"]], ctx
        for k in ("scene_title", "story", "prompt"):
            assert isinstance(p[k], str) and p[k].strip() and "⟨" not in p[k], ctx
        if p["panel"] is not None:
            _check_panel(p["panel"])
        if it["kind"] == "choice":
            opts = p["options"]
            assert len(opts) == 4 and len(set(opts)) == 4 and all(o.strip() and "⟨" not in o for o in opts), ctx
            assert isinstance(p["key"], int) and 0 <= p["key"] < 4, ctx
        else:
            assert p["panel"]["type"] == "code", ctx
            keys = p["key"] if isinstance(p["key"], list) else [p["key"]]
            assert keys and all(1 <= k <= len(p["panel"]["lines"]) for k in keys) and len(keys) < len(p["panel"]["lines"]), ctx
        assert 1.4 <= it["a"] <= 2.7 and -2.5 <= it["b"] <= 3.0, ctx


def _content(it) -> str:
    """Содержимое клона без ключа и без порядка вариантов (перемешивание вариантов — не другой клон)."""
    p = {k: v for k, v in it["payload"].items() if k != "key"}
    return repr({**p, "options": sorted(p.get("options") or [])})


def test_bank_deterministic_and_clones_differ():
    """Клоны сценарных семейств (Backend и bank/) отличаются данными: утечка одного не раскрывает остальные.
    # ponytail: «простые» шаблоны items.simple с одной-двумя подстановками сюда не входят — см. table.md"""
    assert generate_bank() == BANK
    by_fam = defaultdict(set)
    for it in BANK:
        by_fam[it["family"]].add(_content(it))
    scenic = {f["family"] for f in FAMILIES if f["spec"] == "Backend" or f["family"].startswith(BANK_PREFIXES)}
    poor = sorted(f for f in scenic if len(by_fam[f]) < (2 if f.startswith("be_") else 3))
    assert not poor, poor


def _key_longest(it) -> bool:
    o, k = it["payload"]["options"], it["payload"]["key"]
    return len(o[k]) > max(len(x) for i, x in enumerate(o) if i != k)


def test_key_not_systematically_longest():
    """Правильный вариант не выдаёт себя длиной: в новых банках он строго самый длинный не больше чем в 40 % клонов
    специализации и не больше чем в 60 % клонов каждого семейства (стратегия «выбери самый длинный» не решает задание)."""
    new = {f["family"] for f in FAMILIES if f["render"].__module__.startswith("app.services.bank.")}
    for prefix in BANK_PREFIXES:
        items = [it for it in BANK if it["family"].startswith(prefix) and it["family"] in new and it["kind"] == "choice"]
        assert sum(map(_key_longest, items)) <= 0.4 * len(items), (prefix, f"{sum(map(_key_longest, items))}/{len(items)}")
    by_fam = defaultdict(list)
    for it in BANK:
        if it["family"] in new and it["kind"] == "choice":
            by_fam[it["family"]].append(_key_longest(it))
    bad = sorted(f for f, v in by_fam.items() if sum(v) > 0.6 * len(v))
    assert not bad, bad


def test_non_backend_banks_have_context():
    """Не только «голые» вопросы: у каждой специализации есть логи/графики/код и задания-разметки строки кода."""
    for spec in catalog.SPECS:
        items = [it for it in BANK if it["spec"] == spec and not it["pilot"]]
        types = Counter((it["payload"]["panel"] or {}).get("type") for it in items)
        assert types["code"] and (types["logs"] or types["chart"]), (spec, types)
        assert any(it["kind"] != "choice" for it in items), spec
        assert sum(1 for it in items if it["payload"]["panel"]) >= len(items) / 2, (spec, types)


@pytest.mark.parametrize("spec", catalog.SPECS)
def test_full_test_precision_per_spec(spec):
    """Полный адаптивный тест на банке специализации: θ коррелирует с истинным, средняя SE в пределах цели."""
    bank = [SimpleNamespace(id=i, **{k: r[k] for k in ("family", "competency", "a", "b", "pilot")})
            for i, r in enumerate(BANK) if r["spec"] == spec and not r["pilot"]]
    rng = random.Random(f"bank:{spec}")
    true = [rng.gauss(0, 1) for _ in range(150)]
    runs = [irt.simulate_session(bank, t, rng) for t in true]
    corr = float(np.corrcoef(true, [r[0] for r in runs])[0, 1])
    se = float(np.mean([r[1] for r in runs]))
    assert corr > 0.88 and se <= 0.37, (spec, corr, se)
