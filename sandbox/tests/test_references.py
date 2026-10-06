"""Эталоны задач на код (backend/app/services/code_items.py) на обоих языках проходят все скрытые тесты в настоящей
песочнице и укладываются в лимиты на большом тесте; лобовое O(n·q) — нет.

Модуль банка монтируется в контейнер: docker run --privileged -v $PWD/backend/app/services/code_items.py:/srv/code_items.py:ro …
Без него набор пропускается (локальный прогон одной песочницы).
"""

import importlib.util
import os
import random
import sys
from pathlib import Path

import pytest

os.environ.setdefault("SANDBOX_TOKEN", "test-token")
os.environ.setdefault("SANDBOX_RUN_ROOT", "/tmp/sbx-test")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402

SRC = Path(os.environ.get("CODE_ITEMS", "/srv/code_items.py"))
if not SRC.exists():
    pytest.skip(f"нет {SRC}: смонтируйте backend/app/services/code_items.py", allow_module_level=True)
_spec = importlib.util.spec_from_file_location("code_items", SRC)
ci = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ci)
Path(os.environ["SANDBOX_RUN_ROOT"]).mkdir(parents=True, exist_ok=True)

CLONES = 4  # клонов на семейство: разные варианты условия


def _clones(fam):
    return [ci.render(fam, random.Random(f"{fam}:{i}")) for i in range(CLONES)]


@pytest.mark.parametrize("fam", sorted(ci.FAMILIES))
@pytest.mark.parametrize("lang", ["python", "typescript"])
def test_reference_passes_hidden_tests(fam, lang):
    for p in _clones(fam):
        seed = p["key"]["seed"]
        tests = ci.hidden_tests(fam, seed)
        req = {"lang": lang, "code": ci.reference(fam, seed, lang), "harness": {"entry": p["code"]["entry"][lang]}, "tests": tests,
               "fail_fast": True, "limits": {"time_ms": ci.TIME_MS, "memory_mb": ci.MEMORY_MB}}
        r = server.run(server.validate(req))
        assert r["status"] == "ok", (fam, lang, p["code"]["entry"][lang], r["results"], r["stderr"])
        # запас по времени: эталон на большом тесте — меньше половины лимита
        assert max(x["time_ms"] for x in r["results"]) < ci.TIME_MS / 2, r["results"]


def test_template_is_not_a_solution():
    """Шаблон из payload компилируется, но не решает задачу (ни на одном языке)."""
    for fam in ci.FAMILIES:
        p = _clones(fam)[0]
        tests = ci.hidden_tests(fam, p["key"]["seed"])
        for lang in ("python", "typescript"):
            r = server.run(server.validate({"lang": lang, "code": p["code"]["templates"][lang], "harness": {"entry": p["code"]["entry"][lang]},
                                            "tests": tests, "fail_fast": True}))
            assert r["results"][0]["status"] == "wrong", (fam, lang, r)


def test_naive_quadratic_is_too_slow():
    """Большой тест отсекает O(n·q): лобовой подсчёт на каждый запрос не укладывается в лимит."""
    fam = "code_binary_search"
    for p in _clones(fam):
        if p["code"]["entry"]["python"] in ("count_less", "below_count"):
            break
    else:
        pytest.skip("в первых клонах нет варианта «строго меньше»")
    name = p["code"]["entry"]["python"]
    naive_py = f"def {name}(a, queries):\n    return [sum(1 for v in a if v < x) for x in queries]\n"
    naive_ts = f"function {ci.camel(name)}(a: number[], qs: number[]): number[] {{ return qs.map(x => a.filter(v => v < x).length); }}"
    tests = ci.hidden_tests(fam, p["key"]["seed"])
    for lang, code in (("python", naive_py), ("typescript", naive_ts)):
        r = server.run(server.validate({"lang": lang, "code": code, "harness": {"entry": p["code"]["entry"][lang]}, "tests": tests,
                                        "fail_fast": True, "limits": {"time_ms": ci.TIME_MS}}))
        assert r["results"][-1]["status"] == "tle" and r["passed"] == len(tests) - 1, (lang, r["results"])
