"""Валидация: метрики на посчитанных руками примерах + run() на маленькой засеянной БД (своя база fsp_validtest)."""

import math
from datetime import UTC, date, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import DATABASE_URL
from app.db import get_db, reset_schema
from app.routers import validation as router_mod
from app.services import matching
from app.services import validation as V
from app.services.items import seed_items
from seed import generate
from seed.generate import DEMO_TODAY, build

URL = DATABASE_URL.rsplit("/", 1)[0] + "/fsp_validtest"  # тот же сервер, что у набора (PG из test.sh)


def test_metrics_by_hand():
    assert V.precision_at_k([3, 2, 1, 0], 4) == 0.5
    assert V.precision_at_k([3, 0], 10) == 0.1  # стандартная P@k: делим на k, недобор выдачи штрафуется
    assert V.precision_at_k([], 10) == 0.0
    # DCG [3, 0, 2] = 7/1 + 0 + 3/2; идеал из всего пула [3, 2, 2, 0] → 7 + 3/log2(3) + 3/2
    dcg = 7 + 3 / 2
    idcg = 7 + 3 / math.log2(3) + 3 / 2
    assert V.ndcg_at_k([3, 0, 2], [3, 2, 2, 0, 0], 3) == pytest.approx(dcg / idcg)
    assert V.ndcg_at_k([3, 2], [3, 2, 0], 2) == pytest.approx(1.0)
    assert V.ndcg_at_k([0, 0], [0, 1], 2) == pytest.approx(0.0)
    assert V.ndcg_at_k([0], [0, 0], 1) is None  # годных нет — метрика не определена
    assert V.gini([1, 1, 1, 1]) == pytest.approx(0.0)
    assert V.gini([0, 0, 0, 1]) == pytest.approx(0.75)
    assert V.gini([0, 0, 0]) == 0.0
    assert V.spearman([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)
    assert V.spearman([1, 1, 2], [1, 2, 3]) == pytest.approx(0.866, abs=1e-3)  # ties → средние ранги [1.5, 1.5, 3]
    assert V.spearman([1, 2], [2, 1]) is None
    # разделяющая сила: AUC, перекрытие гистограмм, взвешенная каппа
    assert V._auc([0, 1], [2, 3]) == 1.0 and V._auc([2, 3], [0, 1]) == 0.0
    assert V._auc([1, 2], [1, 2]) == pytest.approx(0.5)  # ничьи — пополам
    assert V._overlap([0.1, 0.2], [0.1, 0.2]) == pytest.approx(1.0) and V._overlap([-2.0], [2.0]) == 0.0
    assert V._qwk([[5, 0], [0, 5]]) == pytest.approx(1.0)
    assert V._qwk([[0, 5], [5, 0]]) == pytest.approx(-1.0)
    assert V._quart([1, 2, 3, 4, 5]) == {"min": 1.0, "q1": 2.0, "median": 3.0, "q3": 4.0, "max": 5.0}


def test_demo_clock():
    """«Сегодня» синтетики: полдень МСК даты демо; неделя квоты — с понедельника 00:00 МСК; now — реальное время."""
    assert generate.anchor(date(2026, 10, 5)) == datetime(2026, 10, 5, 9, tzinfo=UTC)
    assert generate.parse_today("now") is None and generate.parse_today("2026-10-08") == date(2026, 10, 8)
    generate.set_clock(date(2026, 10, 8))  # четверг
    try:
        assert generate.NOW == datetime(2026, 10, 8, 9, tzinfo=UTC)
        assert generate.WEEK_START == datetime(2026, 10, 4, 21, tzinfo=UTC)  # пн 00:00 МСК
    finally:
        generate.set_clock(None)
    assert abs(generate.NOW - datetime.now(UTC)) < timedelta(minutes=1)


@pytest.fixture(scope="module")
def db():
    admin = create_engine(URL.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        if not c.scalar(text("select 1 from pg_database where datname = 'fsp_validtest'")):
            c.execute(text("create database fsp_validtest"))
    admin.dispose()
    eng = create_engine(URL)
    reset_schema(eng)  # пустая схема + миграции
    with Session(eng, expire_on_commit=False) as s:
        build(s, 150, 18, 1, DEMO_TODAY)  # та же дата, что у валидации по умолчанию
        seed_items(s)
        yield s
    eng.dispose()


def _seeded(name: str, today: date):
    """Отдельная база с засевом от заданной даты (для сравнения прогонов)."""
    admin = create_engine(URL.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        if not c.scalar(text("select 1 from pg_database where datname = :n"), {"n": name}):
            c.execute(text(f"create database {name}"))
    admin.dispose()
    eng = create_engine(URL.rsplit("/", 1)[0] + "/" + name)
    reset_schema(eng)
    s = Session(eng, expire_on_commit=False)
    build(s, 150, 18, 1, today)
    seed_items(s)
    return eng, s


def _numbers(res: dict) -> dict:
    return {k: v for k, v in res.items() if k not in ("generated_at", "today")}


class _Shifted(datetime):
    """Реальные часы matching, сдвинутые на 40 дней вперёд: все приглашения синтетики к этому дню истекли бы."""

    @classmethod
    def now(cls, tz=None):
        return datetime.now(tz) + timedelta(days=40)


@pytest.mark.slow  # засев 150 кандидатов + прогон валидации
def test_run_shape(db, tmp_path, monkeypatch):
    monkeypatch.setattr(V, "N_GRADE", 40)  # разделяющая сила: 40 симуляций на грейд вместо 200 — форма та же, быстрее
    res = V.run(db, k=5, seed=1)
    assert {"generated_at", "k", "today", "dataset", "quality", "market", "cheater", "stability", "separation"} <= res.keys()
    assert res["today"] == DEMO_TODAY.isoformat()
    assert res["dataset"]["candidates"] == 150 and res["dataset"]["needs"] == 18
    assert [v["key"] for v in res["quality"]["variants"]] == ["embed", "rerank", "full"]
    assert set(res["quality"]["by_kind"]) == {"normal", "adjacent", "fork_low"}
    # не подтверждённые тестом: доли в пуле, среди годных по эталону и в топ-k (там их нет — идут после прошедших)
    u = res["quality"]["unconfirmed"]
    assert set(u) == {"pool", "rel", "top"} and 0 < u["pool"] < 1 and 0 < res["dataset"]["untested"] < 1
    assert [r["key"] for r in res["market"]["rows"]] == ["accepted_share", "coverage", "gini", "closed_needs"]
    assert all({"no_limits", "with_limits"} <= r.keys() for r in res["market"]["rows"])
    assert {"no_limits", "with_limits"} <= res["market"]["top5_share"].keys()
    assert isinstance(res["market"]["blocked_by_cap"], int)
    assert [r["key"] for r in res["cheater"]["rows"]] == ["choice", "review", "context", "mixed"]
    assert 0 <= res["cheater"]["caught"] <= 1 and 0 <= res["cheater"]["false_alarm"] <= 1
    assert {"retest_same_grade", "retest_same_grade_no_hysteresis", "cf_spearman", "cf_n", "clone_b_spread", "theta_corr"} <= res["stability"].keys()
    sp = res["separation"]
    assert sp["grades"] == list(V.catalog.GRADES) and sp["n_per_grade"] == 40 and sp["specs"] == len(V.catalog.SPECS)
    assert [sum(row) for row in sp["confusion"]] == [40] * 5 and len(sp["confusion"][0]) == 5
    assert [p["grade"] for p in sp["per_grade"]] == sp["grades"]
    for i, p in enumerate(sp["per_grade"]):
        assert p["accuracy"] == pytest.approx(sp["confusion"][i][i] / 40, abs=1e-3)
        assert p["under"] + p["accuracy"] + p["over"] == pytest.approx(1.0, abs=2e-3)
    assert sp["accuracy"] == pytest.approx(sum(sp["confusion"][i][i] for i in range(5)) / 200, abs=1e-3)
    assert sp["accuracy"] <= sp["within_one"] <= 1 and 0 <= sp["accuracy_point"] <= 1 and -1 <= sp["qwk"] <= 1
    assert 0 <= sp["adjacent_error_share"] <= 1
    assert [(p["lo"], p["hi"]) for p in sp["adjacent"]] == list(zip(sp["grades"], sp["grades"][1:]))
    assert all(0.5 < p["auc"] <= 1 and 0 <= p["overlap"] <= 1 for p in sp["adjacent"])  # θ̂ старшего грейда в среднем выше
    assert sp["per_grade"][0]["theta_mean"] < sp["per_grade"][-1]["theta_mean"]
    assert {r["spec"] for r in sp["by_spec"]} == set(V.catalog.SPECS) and all(r["families"] > 0 and r["items"] >= 1 for r in sp["by_spec"])
    it = sp["items"]
    assert it["n"] == sum(it["a_bins"].values()) and it["calib_n"] == V.N_CALIB
    assert it["a"]["min"] <= it["a"]["median"] <= it["a"]["max"] and -1 <= it["rpb"]["min"] <= it["rpb"]["max"] <= 1
    assert 0 <= it["rpb_poor"] <= 1
    assert "Разделяющая сила теста" in V.report(res) and "AUC" in V.report(res)
    assert V.run(db, k=5, seed=1)["market"] == res["market"]  # детерминировано

    # API: до прогона — 404, пересчёт — только организатору, потом GET отдаёт сохранённое
    monkeypatch.setattr(V, "OUT", tmp_path / "validation.json")
    monkeypatch.setenv("ORGANIZER_TOKEN", "org-secret")
    app = FastAPI()
    app.include_router(router_mod.router)
    app.dependency_overrides[get_db] = lambda: db
    cl = TestClient(app)
    assert cl.get("/api/validation").status_code == 404
    assert cl.post("/api/validation/run?k=5&seed=1").status_code == 401
    assert cl.post("/api/validation/run?k=5&seed=1", headers={"Authorization": "Bearer nope"}).status_code == 401  # неизвестный токен — не авторизован
    r = cl.post("/api/validation/run?k=5&seed=1", headers={"Authorization": "Bearer org-secret"})
    assert r.status_code == 200 and r.json()["today"] == DEMO_TODAY.isoformat()
    assert cl.get("/api/validation").json()["quality"] == r.json()["quality"]
    org = {"Authorization": "Bearer org-secret"}
    assert cl.post("/api/validation/run?k=5&seed=1&today=вчера", headers=org).status_code == 422
    assert cl.post("/api/validation/run?k=5&seed=1&today=now", headers=org).json()["today"] is None  # засев от реального времени


@pytest.mark.slow  # два прогона валидации + второй засев
def test_same_numbers_any_day(db, monkeypatch):
    """Воспроизводимость: на засеве от даты демо цифры не зависят ни от реального дня прогона, ни от дня недели засева."""
    monkeypatch.setattr(V, "N_GRADE", 20)
    base = V.run(db, k=5, seed=1)
    monkeypatch.setattr(matching, "datetime", _Shifted)  # прогон «через 40 дней»: и часы подбора, и «now» засева
    monkeypatch.setattr(generate, "datetime", _Shifted)
    assert _numbers(V.run(db, k=5, seed=1)) == _numbers(base)
    assert matching.CLOCK.get() is None  # фиксированные часы сняты после прогона
    # контроль: без фиксированной даты реальные часы через 40 дней дают другие цифры (приглашения истекли)
    assert _numbers(V.run(db, k=5, seed=1, today=None)) != _numbers(base)
    monkeypatch.undo()
    monkeypatch.setattr(V, "N_GRADE", 20)
    # засев от четверга той же недели: в неделю квоты попадает другое число демо-приглашений, а данные — те же
    thu = DEMO_TODAY + timedelta(days=3)
    eng, s = _seeded("fsp_validday", thu)
    try:
        assert _numbers(V.run(s, k=5, seed=1, today=thu)) == _numbers(base)
    finally:
        s.close()
        eng.dispose()
