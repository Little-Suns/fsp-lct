"""Тест-квест: сессия с симулированным кандидатом, ключ не утекает, кулдаун пересдачи."""

import json
import os
import random
import secrets
from datetime import UTC, datetime, timedelta

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fsp:fsp@localhost:5432/fsp_quest")
os.environ.setdefault("DEMO", "1")

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from app import catalog  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.models import Candidate, ExternalAccount, Item, QuestSession, User  # noqa: E402
from app.routers import quest  # noqa: E402
from app.services import irt  # noqa: E402
from app.services.items import seed_items  # noqa: E402


@pytest.fixture(scope="module")
def env():
    Base.metadata.create_all(engine)
    tag = secrets.token_hex(4)
    with SessionLocal() as db:
        seed_items(db)
        assert seed_items(db) == 0  # повторный сид ничего не добавляет
        items = {it.id: it for it in db.scalars(select(Item).where(Item.spec == "Backend"))}
        user = User(email=f"q-{tag}@example.ru", role="candidate", token=secrets.token_urlsafe(24))
        db.add(user)
        db.flush()
        mk = dict(spec="Backend", track="Python", grade_claimed="Middle", min_salary=200000, formats=[], city="Москва")
        cand = Candidate(public_id=f"Q-{tag}", user_id=user.id, name="Тест", email=user.email, **mk)
        user_cf = User(email=f"qcf-{tag}@example.ru", role="candidate", token=secrets.token_urlsafe(24))
        db.add(user_cf)
        db.flush()
        cand_cf = Candidate(public_id=f"C-{tag}", user_id=user_cf.id, name="CF", email=user_cf.email, **mk)
        rng = random.Random(1)
        peers = [Candidate(public_id=f"S{tag}{i:02d}", name="x", email="x@x", theta=rng.gauss(0, 1), se=0.3, grade="Middle", is_synthetic=True, **mk) for i in range(15)]
        db.add_all([cand, cand_cf, *peers])
        db.flush()
        db.add(ExternalAccount(candidate_id=cand_cf.id, provider="codeforces", handle=f"cf{tag}", verify_code="x", verified_at=datetime.now(UTC), rating=2600))
        db.commit()
        ids, uids, token = [cand.id, cand_cf.id, *(p.id for p in peers)], [user.id, user_cf.id], user.token
        token_cf = user_cf.token
    app = FastAPI()
    app.include_router(quest.router)
    client = TestClient(app, headers={"Authorization": f"Bearer {token}"})
    client_cf = TestClient(app, headers={"Authorization": f"Bearer {token_cf}"})
    yield client, items, ids[0], client_cf, ids[1]
    with SessionLocal() as db:
        db.execute(delete(Candidate).where(Candidate.id.in_(ids)))
        db.execute(delete(User).where(User.id.in_(uids)))
        db.commit()


def _no_leak(resp: dict):
    s = json.dumps(resp, ensure_ascii=False)
    assert '"key"' not in s and '"correct"' not in s and '"theta"' not in json.dumps(resp.get("item") or {}), s[:300]


def _run(client, items, ok) -> dict:
    """Пройти сессию; ok(item) → отвечать ли верно."""
    r = client.post("/api/quest/start", json={"story": False})
    assert r.status_code == 200, r.text
    r = r.json()
    _no_leak(r)
    assert client.post("/api/quest/start", json={"story": False}).json()["session_id"] == r["session_id"]  # возобновление
    assert client.post("/api/quest/answer", json={"item_id": -1, "response": 0}).status_code == 409
    while not r["done"]:
        it = r["item"]
        item = items[it["id"]]
        key = item.payload["key"]
        key = key[0] if isinstance(key, list) else key
        if ok(item):
            resp = key
        elif item.kind == "choice":
            resp = (key + 1) % len(it["options"])
        else:
            bad = item.payload["key"] if isinstance(item.payload["key"], list) else [key]
            resp = next(i for i in range(1, len(it["panel"]["lines"]) + 1) if i not in bad)
        r = client.post("/api/quest/answer", json={"item_id": it["id"], "response": resp, "ms": 60000, "comment": "повтор без ключа идемпотентности"})
        assert r.status_code == 200, r.text
        r = r.json()
        _no_leak(r)
    fin = client.post("/api/quest/finish")
    assert fin.status_code == 200, fin.text
    return r | {"result": fin.json()}


def test_quest_flow(env):
    client, items, cand_id, _, _ = env
    rng = random.Random(42)

    # 1) первое прохождение: кандидат с θ = 1.0
    first = _run(client, items, lambda it: rng.random() < irt.prob(1.0, it.a, it.b))
    res = first["result"]
    _no_leak(res)
    assert 6 <= first["progress"]["n"] <= irt.MAX_ITEMS + 1
    assert res["applied"] and res["category"] == {"spec": "Backend", "track": "Python", "grade": res["category"]["grade"]}
    assert res["category"]["grade"] in catalog.GRADES
    assert 0 <= res["percentile"] <= 100 and res["percentile_scope"] == "category"
    assert [c["n"] for c in res["competencies"]] == catalog.COMPETENCIES["Backend"]
    assert all(c["se"] > 0 for c in res["competencies"])
    assert "too_fast" in res["flags"] and "review_required" in res["flags"]  # TestClient отвечает мгновенно
    assert res["upgrade"]["allowed_at"] and res["minutes"] is not None
    got = client.get("/api/quest/result").json()
    assert got["category"] == res["category"] and got["theta"] == res["theta"]
    with SessionLocal() as db:
        c = db.get(Candidate, cand_id)
        assert c.tested_at and c.percentile is not None and c.grade == res["category"]["grade"]
        assert (c.next_upgrade_at - datetime.now(UTC)).days in (89, 90)
        first_upgrade_at, grade1, theta1 = c.next_upgrade_at, c.grade, c.theta

    # 2) пересдача в кулдаун, всё верно: результат выше — не применяется
    start = client.post("/api/quest/start", json={"story": True}).json()
    assert start["cooldown"]["active"] and "только понизить" in start["cooldown"]["note"]
    up = _run(client, items, lambda it: True)["result"]
    assert not up["applied"] and up["attempt"]["theta"] > theta1 and up["category"]["grade"] == grade1 and up["note"]

    # 3) пересдача в кулдаун, всё неверно: понижение сразу, срок повышения не сдвигается
    down = _run(client, items, lambda it: False)["result"]
    assert down["applied"] and down["theta"] < theta1
    assert catalog.GRADES.index(down["category"]["grade"]) <= catalog.GRADES.index(grade1)
    with SessionLocal() as db:
        assert db.get(Candidate, cand_id).next_upgrade_at == first_upgrade_at

    # 4) кулдаун истёк; пересдача без повышения не продлевает его
    past = datetime.now(UTC) - timedelta(days=1)
    with SessionLocal() as db:
        db.get(Candidate, cand_id).next_upgrade_at = past
        db.commit()
    same = _run(client, items, lambda it: False)["result"]
    assert same["applied"] and same["category"]["grade"] == down["category"]["grade"]
    with SessionLocal() as db:
        assert db.get(Candidate, cand_id).next_upgrade_at == past

    # 5) фактическое повышение запускает новый кулдаун
    up2 = _run(client, items, lambda it: True)["result"]
    assert catalog.GRADES.index(up2["category"]["grade"]) > catalog.GRADES.index(down["category"]["grade"])
    with SessionLocal() as db:
        assert (db.get(Candidate, cand_id).next_upgrade_at - datetime.now(UTC)).days in (89, 90)


def test_cf_does_not_change_grade(env):
    """Одинаковые ответы → одинаковые θ и грейд, хотя у второго кандидата CF 2600 (prior только для подбора заданий)."""
    client, items, cand_id, client_cf, cf_id = env
    rng = random.Random(7)
    started = client_cf.post("/api/quest/start", json={}).json()
    with SessionLocal() as db:
        assert db.get(QuestSession, started["session_id"]).prior_mean > 0  # CF сдвинул старт
    a = _run(client_cf, items, lambda it: rng.random() < irt.prob(0.3, it.a, it.b))["result"]
    with SessionLocal() as db:
        src = db.scalar(select(QuestSession).where(QuestSession.candidate_id == cf_id).order_by(QuestSession.id.desc()))
        twin = Candidate(public_id=f"T-{secrets.token_hex(4)}", name="T", email="t@t", spec="Backend", track="Python", grade_claimed="Middle", min_salary=1, formats=[], city="Москва")
        tw_user = User(email=f"tw-{secrets.token_hex(4)}@example.ru", role="candidate", token=secrets.token_urlsafe(24))
        db.add(tw_user)
        db.flush()
        twin.user_id = tw_user.id
        db.add(twin)
        db.flush()
        db.add(QuestSession(candidate_id=twin.id, answers=src.answers, theta=0.0, se=1.0, flags=[]))
        db.commit()
        twin_id, tw_uid, tw_token = twin.id, tw_user.id, tw_user.token
    app = client_cf.app
    b = TestClient(app, headers={"Authorization": f"Bearer {tw_token}"}).post("/api/quest/finish").json()
    with SessionLocal() as db:
        db.execute(delete(Candidate).where(Candidate.id == twin_id))
        db.execute(delete(User).where(User.id == tw_uid))
        db.commit()
    assert (a["theta"], a["se"], a["category"]["grade"], a["competencies"]) == (b["theta"], b["se"], b["category"]["grade"], b["competencies"])
