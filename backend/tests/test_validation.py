"""Валидация: метрики на посчитанных руками примерах + run() на маленькой засеянной БД (своя база fsp_validtest)."""

import math

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import DATABASE_URL
from app.db import get_db, reset_schema
from app.routers import validation as router_mod
from app.services import validation as V
from app.services.items import seed_items
from seed.generate import build

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
        build(s, 150, 18, 1)
        seed_items(s)
        yield s
    eng.dispose()


@pytest.mark.slow  # засев 150 кандидатов + прогон валидации
def test_run_shape(db, tmp_path, monkeypatch):
    res = V.run(db, k=5, seed=1)
    assert {"generated_at", "k", "dataset", "quality", "market", "cheater", "stability"} <= res.keys()
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
    assert r.status_code == 200
    assert cl.get("/api/validation").json()["quality"] == r.json()["quality"]
