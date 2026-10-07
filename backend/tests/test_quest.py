"""Тест-квест: сессия с симулированным кандидатом, ключ не утекает, кулдаун, тест на заявленный грейд,
история попыток, план теста под вакансию и фокус по приглашению."""

import io
import json
import os
import random
import runpy
import secrets
import threading
import warnings
from datetime import UTC, datetime, timedelta

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fsp:fsp@localhost:5432/fsp_quest")
os.environ.setdefault("DEMO", "1")
os.environ.setdefault("LLM_BASE_URL", "")  # разбор вакансии — правилами, без модели

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from pypdf import PdfReader  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402
from sqlalchemy.exc import IntegrityError  # noqa: E402

from app import catalog  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.deps import issue_token  # noqa: E402
from app.models import Candidate, Company, ExternalAccount, Invitation, Item, Need, QuestSession, User  # noqa: E402
from app.routers import candidate, quest  # noqa: E402
from app.services import irt, matching, profile_pdf  # noqa: E402
from app.services.items import generate_bank, plan_for_need, seed_items  # noqa: E402

NEED_TEXT = "Ищем бэкендера на Python в команду платежей. Нужен опыт с PostgreSQL и Kafka, хорошо бы Kubernetes. Уровень — мидл, до 300 на руки. Гибрид, Москва."
MK = dict(spec="Backend", track="Python", grade_claimed="Middle", min_salary=200000, formats=[], city="Москва")

app = FastAPI()
app.include_router(quest.router)
app.include_router(candidate.router)  # /me — пометка экспресс-оценки в кабинете


def _client(token: str | None = None) -> TestClient:
    return TestClient(app, headers={"Authorization": f"Bearer {token}"} if token else {})


@pytest.fixture(scope="module")
def env():
    Base.metadata.create_all(engine)
    tag = secrets.token_hex(4)
    with SessionLocal() as db:
        seed_items(db)
        assert seed_items(db) == 0  # повторный сид ничего не добавляет
        # новое семейство в уже засеянной базе докладывается (обновление стенда без --reset), остальные не трогаются
        fam = db.scalar(select(Item.family).where(Item.family.like("sec\\_%")))  # семейство из bank/
        n_fam = len(db.execute(delete(Item).where(Item.family == fam).returning(Item.id)).all())
        db.commit()
        assert seed_items(db) == n_fam > 0 and seed_items(db) == 0
        # изменённый шаблон: засеянные клоны обновляются на месте по номеру клона, id не меняются (на них ссылаются ответы)
        old = db.scalars(select(Item).where(Item.family == "be_inc_pool").order_by(Item.id)).all()
        ids = [it.id for it in old]
        want = [(r["payload"], r["b"]) for r in generate_bank() if r["family"] == "be_inc_pool"]
        old[0].payload, old[1].b = {"story": "текст прошлой версии шаблона"}, 0.0
        db.commit()
        assert seed_items(db) == 2 and seed_items(db) == 0
        db.expire_all()
        fresh = db.scalars(select(Item).where(Item.family == "be_inc_pool").order_by(Item.id)).all()
        assert [it.id for it in fresh] == ids and [(it.payload, it.b) for it in fresh] == want
        # то же через CLI (python -m app.services.items): семейства bank/ видны и из __main__
        n_fam = len(db.execute(delete(Item).where(Item.family == fam).returning(Item.id)).all())
        db.commit()
    with pytest.MonkeyPatch.context() as mp, warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)  # «found in sys.modules»
        mp.setattr("app.db.init_db", lambda: None)  # схема набора — create_all, миграции здесь не нужны
        runpy.run_module("app.services.items", run_name="__main__")
    with SessionLocal() as db:
        assert len(db.scalars(select(Item.id).where(Item.family == fam)).all()) == n_fam
        items = {it.id: it for it in db.scalars(select(Item).where(Item.spec == "Backend"))}
        users = [User(email=f"{r}-{tag}@example.ru", role=role) for r, role in (("q", "candidate"), ("qcf", "candidate"), ("emp", "employer"), ("emp2", "employer"))]
        db.add_all(users)
        db.flush()
        cand = Candidate(public_id=f"Q-{tag}", user_id=users[0].id, name="Тест", email=users[0].email, **MK)
        cand_cf = Candidate(public_id=f"C-{tag}", user_id=users[1].id, name="CF", email=users[1].email, **MK)
        rng = random.Random(1)
        peers = [Candidate(public_id=f"S{tag}{i:02d}", name="x", email="x@x", theta=rng.gauss(0, 1), se=0.3, grade="Middle", is_synthetic=True, **MK) for i in range(15)]
        comps = [Company(user_id=u.id, inn=f"77{secrets.randbelow(10**8):08d}", name=f"Компания {i}", recruiter_name="HR", recruiter_email=u.email) for i, u in enumerate(users[2:])]
        db.add_all([cand, cand_cf, *peers, *comps])
        db.flush()
        db.add(ExternalAccount(candidate_id=cand_cf.id, provider="codeforces", handle=f"cf{tag}", verify_code="x", verified_at=datetime.now(UTC), rating=2600))
        need = Need(company_id=comps[0].id, text=NEED_TEXT, spec="Backend", track="Python", grade="Middle", must=["Python", "PostgreSQL", "Kafka"], nice=["Kubernetes"])
        db.add(need)
        db.flush()
        inv = Invitation(company_id=comps[0].id, candidate_id=cand_cf.id, need_id=need.id, role="Backend", salary_from=240000, salary_to=300000,
                         format="Гибрид", expires_at=datetime.now(UTC) + timedelta(days=7))
        db.add(inv)
        db.commit()
        tokens = [issue_token(db, u) for u in users]
        ctx = {"items": items, "cand_id": cand.id, "cf_id": cand_cf.id, "need_id": need.id, "inv_id": inv.id,
               "client": _client(tokens[0]), "client_cf": _client(tokens[1]), "emp": _client(tokens[2]), "emp2": _client(tokens[3])}
        ids, uids, comp_ids = [cand.id, cand_cf.id, *(p.id for p in peers)], [u.id for u in users], [c.id for c in comps]
    yield ctx
    with SessionLocal() as db:
        db.execute(delete(Candidate).where(Candidate.id.in_(ids)))
        db.execute(delete(Company).where(Company.id.in_(comp_ids)))
        db.execute(delete(User).where(User.id.in_(uids)))
        db.commit()


def _no_leak(resp):
    s = json.dumps(resp, ensure_ascii=False)
    assert '"key"' not in s and '"correct"' not in s and '"answers"' not in s, s[:300]


def _run(client, items, ok, start: dict | None = None) -> dict:
    """Пройти сессию; ok(item) → отвечать ли верно."""
    r = client.post("/api/quest/start", json=start or {"story": False})
    assert r.status_code == 200, r.text
    r = r.json()
    _no_leak(r)
    assert client.post("/api/quest/start", json={"story": False}).json()["session_id"] == r["session_id"]  # возобновление
    assert client.post("/api/quest/answer", json={"item_id": -1, "response": 0}).status_code == 409
    while not r["done"]:
        it = r["item"]
        item = items[it["id"]]
        keys = item.payload["key"] if isinstance(item.payload["key"], list) else [item.payload["key"]]
        if ok(item):
            resp = keys[0]
        elif item.kind == "choice":
            resp = (keys[0] + 1) % len(it["options"])
        else:
            resp = next(i for i in range(1, len(it["panel"]["lines"]) + 1) if i not in keys)
        r = client.post("/api/quest/answer", json={"item_id": it["id"], "response": resp, "ms": 60000, "comment": "повтор без ключа идемпотентности"})
        assert r.status_code == 200, r.text
        r = r.json()
        _no_leak(r)
    fin = client.post("/api/quest/finish")
    assert fin.status_code == 200, fin.text
    _no_leak(fin.json())
    return r | {"result": fin.json()}


def test_quest_flow(env):
    client, items, cand_id = env["client"], env["items"], env["cand_id"]
    rng = random.Random(42)
    assert client.post("/api/quest/start", json={"target_grade": "Guru"}).status_code == 422

    # 1) первое прохождение на заявленный грейд (Middle по умолчанию): кандидат с θ = 1.0
    first = _run(client, items, lambda it: rng.random() < irt.prob(1.0, it.a, it.b))
    res = first["result"]
    assert 6 <= first["progress"]["n"] <= irt.MAX_ITEMS + 1 and first["target_grade"] == "Middle"
    assert res["applied"] and res["category"]["spec"] == "Backend" and res["category"]["grade"] in catalog.GRADES
    t = res["target"]
    assert t["grade"] == "Middle" and t["result_grade"] == res["category"]["grade"]
    assert t["verdict"] == {-1: "below", 0: "confirmed", 1: "above"}[(catalog.GRADES.index(t["result_grade"]) > 2) - (catalog.GRADES.index(t["result_grade"]) < 2)]
    assert 0 <= res["percentile"] <= 100 and res["percentile_scope"] == "category"
    assert [c["n"] for c in res["competencies"]] == catalog.COMPETENCIES["Backend"]
    assert "too_fast" in res["flags"] and "review_required" in res["flags"]  # TestClient отвечает мгновенно
    assert res["upgrade"]["allowed_at"] and res["minutes"] is not None
    got = client.get("/api/quest/result").json()
    assert got["category"] == res["category"] and got["theta"] == res["theta"] and got["target"] == t
    with SessionLocal() as db:
        c = db.get(Candidate, cand_id)
        assert c.tested_at and c.percentile is not None and c.grade == res["category"]["grade"]
        assert (c.next_upgrade_at - datetime.now(UTC)).days in (89, 90)
        first_upgrade_at, grade1, theta1 = c.next_upgrade_at, c.grade, c.theta

    # 2) пересдача в кулдаун на Senior, всё верно: старт у порога Senior; результат выше — не применяется
    start = client.post("/api/quest/start", json={"story": True, "target_grade": "Senior"}).json()
    assert start["cooldown"]["active"] and "только понизить" in start["cooldown"]["note"] and start["target_grade"] == "Senior"
    with SessionLocal() as db:
        assert db.get(QuestSession, start["session_id"]).prior_mean == catalog.GRADE_TH["Senior"]
    up = _run(client, items, lambda it: True)["result"]
    assert not up["applied"] and up["attempt"]["theta"] > theta1 and up["category"]["grade"] == grade1 and up["note"]
    assert up["target"]["verdict"] in ("confirmed", "above")

    # 3) пересдача в кулдаун, всё неверно: понижение сразу, срок повышения не сдвигается
    down = _run(client, items, lambda it: False)["result"]
    assert down["applied"] and down["theta"] < theta1 and down["target"]["verdict"] == "below"
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

    # 6) история: 5 попыток, новые сверху, без ответов и ключей; применённость видна
    hist = client.get("/api/quest/history").json()
    _no_leak(hist)
    assert len(hist) == 5 and hist[0]["session_id"] > hist[-1]["session_id"]
    assert [h["applied"] for h in hist] == [True, True, True, False, True]
    assert [h["target_grade"] for h in hist][3] == "Senior" and all(h["items"] >= 6 and h["grade"] in catalog.GRADES for h in hist)
    with SessionLocal() as db:
        rows = db.scalars(select(QuestSession).where(QuestSession.candidate_id == cand_id).order_by(QuestSession.id.desc())).all()
        assert [r.applied for r in rows] == [h["applied"] for h in hist] and [r.grade for r in rows] == [h["grade"] for h in hist]
        assert rows[0].grade == up2["category"]["grade"]


def test_express_mode(env):
    """Экспресс: 5 заданий по минуте без ревью и пилота; предварительная категория с пометкой, только если грейда ещё нет;
    кулдаун не запускает, полный тест после него — первое присвоение; существующий грейд не меняет ни вверх, ни вниз."""
    items = env["items"]
    with SessionLocal() as db:
        u = User(email=f"ex-{secrets.token_hex(4)}@example.ru", role="candidate")
        db.add(u)
        db.flush()
        c = Candidate(public_id=f"E-{secrets.token_hex(4)}", user_id=u.id, name="Э", email=u.email, **MK)
        db.add(c)
        db.commit()
        cid, uid, client = c.id, u.id, _client(issue_token(db, u))
    try:
        assert client.post("/api/quest/start", json={"mode": "turbo"}).status_code == 422
        st = client.post("/api/quest/start", json={"mode": "express", "story": False}).json()
        assert st["mode"] == "express" and st["progress"]["total"] == irt.EXPRESS_ITEMS
        assert st["time_limit_s"] == quest.EXPRESS_TIME_LIMIT_S == st["item"]["time_limit_s"] and st["remaining_s"] <= 60
        resumed = client.post("/api/quest/start", json={"story": False}).json()  # режим продолжаемой сессии не меняется
        assert resumed["resumed"] and resumed["mode"] == "express" and resumed["session_id"] == st["session_id"]

        rng = random.Random(3)
        first = _run(client, items, lambda it: rng.random() < irt.prob(0.8, it.a, it.b), {"mode": "express", "story": False})
        res = first["result"]
        assert first["progress"]["n"] == irt.EXPRESS_ITEMS and first["done"]
        assert res["applied"] and res["express"] and res["mode"] == "express" and res["assessment_label"] == "экспресс-оценка"
        assert res["category"]["grade"] == catalog.grade_from_theta(res["theta"], res["se"]) and res["se"] > 0.35
        assert res["skills_confirmed"] == [] and res["upgrade"]["allowed_at"] is None
        with SessionLocal() as db:
            s = db.get(QuestSession, first["session_id"])
            assert s.mode == "express" and not any(a["pilot"] for a in s.answers)
            assert all(items[a["item_id"]].kind in irt.EXPRESS_KINDS for a in s.answers)
            c = db.get(Candidate, cid)
            assert c.grade_express and c.next_upgrade_at is None and c.tested_at
            assert matching.card(c)["express"] and matching.card(c)["grade"] == res["category"]["grade"]
            pdf = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(profile_pdf.render(c))).pages)
            assert "экспресс-оценка" in pdf and "тест пройден" not in pdf
            express_grade, express_se = c.grade, c.se
        assert client.get("/api/candidate/me").json()["grade_express"] is True

        # повторный экспресс (всё верно) предварительную категорию не повышает
        again = _run(client, items, lambda it: True, {"mode": "express", "story": False})["result"]
        assert not again["applied"] and "повторный экспресс" in again["note"] and again["category"]["grade"] == express_grade
        assert again["attempt"]["theta"] > res["theta"]

        # полный тест после экспресса — первое присвоение: без кулдауна и гистерезиса от экспресса, пометка снимается
        full = _run(client, items, lambda it: rng.random() < irt.prob(0.8, it.a, it.b))["result"]
        assert full["applied"] and not full["express"] and full["mode"] == "full" and full["assessment_label"] is None
        assert full["se"] < express_se and full["category"]["grade"] == catalog.grade_from_theta(full["theta"], full["se"])
        with SessionLocal() as db:
            c = db.get(Candidate, cid)
            assert not c.grade_express and (c.next_upgrade_at - datetime.now(UTC)).days in (89, 90)
            assert not matching.card(c)["express"] and "тест пройден" in "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(profile_pdf.render(c))).pages)
            full_grade, full_theta = c.grade, c.theta

        # экспресс после полного теста не меняет категорию даже вниз; ответ после лимита 60 с + запас — неверный
        st = client.post("/api/quest/start", json={"mode": "express", "story": False}).json()
        it = items[st["item"]["id"]]
        with SessionLocal() as db:
            s = db.get(QuestSession, st["session_id"])
            s.answers = [*s.answers[:-1], {**s.answers[-1], "served_at": (datetime.now(UTC) - timedelta(seconds=95)).isoformat()}]
            db.commit()
        key = it.payload["key"][0] if isinstance(it.payload["key"], list) else it.payload["key"]
        assert client.post("/api/quest/answer", json={"item_id": it.id, "response": key}).status_code == 200
        with SessionLocal() as db:
            a0 = db.get(QuestSession, st["session_id"]).answers[0]
            assert a0["timeout"] and not a0["correct"]
        low = _run(client, items, lambda it: False, {"mode": "express", "story": False})["result"]
        assert not low["applied"] and "полным тестом" in low["note"] and low["category"]["grade"] == full_grade and low["theta"] == round(full_theta, 2)
        assert not low["express"] and low["mode"] == "express"

        hist = client.get("/api/quest/history").json()
        assert [h["mode"] for h in hist] == ["express", "full", "express", "express"]
        assert [h["applied"] for h in hist] == [False, True, False, True] and [h["items"] for h in hist][2:] == [irt.EXPRESS_ITEMS] * 2
    finally:
        with SessionLocal() as db:
            db.execute(delete(Candidate).where(Candidate.id == cid))
            db.execute(delete(User).where(User.id == uid))
            db.commit()


def test_cf_and_focus_do_not_change_grade(env):
    """Одинаковые ответы → одинаковые θ, грейд и компетенции, хотя у первого кандидата CF 2600 и фокус из приглашения
    (оба влияют только на выбор заданий)."""
    client_cf, items, cf_id = env["client_cf"], env["items"], env["cf_id"]
    assert env["client"].post("/api/quest/start", json={"invitation_id": env["inv_id"]}).status_code == 404  # чужое приглашение
    rng = random.Random(7)
    started = client_cf.post("/api/quest/start", json={"invitation_id": env["inv_id"]}).json()
    assert started["focus"]["Базы данных и транзакции"] > 1.0 and started["focus"]["Конкурентность"] > 1.0
    assert all(1.0 <= w <= 1.5 for w in started["focus"].values())
    with SessionLocal() as db:
        s = db.get(QuestSession, started["session_id"])
        assert s.prior_mean > catalog.GRADE_TH["Middle"]  # CF сдвинул старт выше порога Middle
    a = _run(client_cf, items, lambda it: rng.random() < irt.prob(0.3, it.a, it.b))["result"]
    with SessionLocal() as db:
        src = db.scalar(select(QuestSession).where(QuestSession.candidate_id == cf_id).order_by(QuestSession.id.desc()))
        tw_user = User(email=f"tw-{secrets.token_hex(4)}@example.ru", role="candidate")
        db.add(tw_user)
        db.flush()
        twin = Candidate(public_id=f"T-{secrets.token_hex(4)}", user_id=tw_user.id, name="T", email="t@t", **MK)
        db.add(twin)
        db.flush()
        db.add(QuestSession(candidate_id=twin.id, answers=src.answers, theta=0.0, se=1.0, flags=[], target_grade="Middle"))
        db.commit()
        twin_id, tw_uid, tw_token = twin.id, tw_user.id, issue_token(db, tw_user)
    b = _client(tw_token).post("/api/quest/finish").json()
    with SessionLocal() as db:
        db.execute(delete(Candidate).where(Candidate.id == twin_id))
        db.execute(delete(User).where(User.id == tw_uid))
        db.commit()
    assert (a["theta"], a["se"], a["category"]["grade"], a["competencies"]) == (b["theta"], b["se"], b["category"]["grade"], b["competencies"])


def test_focus_steers_selection():
    """Фокус — мягкий множитель информации: при равном контент-балансе выигрывает компетенция вакансии."""
    bank = [type("I", (), dict(id=i, pilot=False, **{k: r[k] for k in ("family", "competency", "a", "b")}))
            for i, r in enumerate(x for x in generate_bank() if x["spec"] == "Backend")]
    plain = irt.next_item(1.4, bank, set(), set(), random.Random(0), top=1)
    focus = {plain.competency: 1.0, "Базы данных и транзакции": 1.5}
    steered = irt.next_item(1.4, bank, set(), set(), random.Random(0), top=1, focus=focus)
    assert plain.competency != "Базы данных и транзакции" and steered.competency == "Базы данных и транзакции"


def test_plan_for_need(env):
    p = plan_for_need("Backend", ["Python", "PostgreSQL", "Kafka"], ["Kubernetes"], "Middle")
    w = {c["n"]: c for c in p["competencies"]}
    assert w["Базы данных и транзакции"]["weight"] == 1.25 and "PostgreSQL" in w["Базы данных и транзакции"]["why"]
    assert w["Конкурентность"]["weight"] == 1.25 and w["Диагностика инцидентов"]["why"] == ["Kubernetes"] and w["Алгоритмы"]["weight"] == 1.0
    assert p["difficulty"] == {"b_from": -0.5, "b_to": 1.5} and all(-0.5 <= f["b"] <= 1.5 for f in p["families"])
    assert p["families"][0]["competency"] in ("Базы данных и транзакции", "Конкурентность", "Ревью кода")
    assert p["items_total"] == irt.MAX_ITEMS and 30 <= p["minutes"] <= 60
    assert plan_for_need("DevOps / SRE", ["Kubernetes", "Terraform"], [], "Senior")["competencies"][0]["n"] in ("Kubernetes", "План отката")

    # публичный предпросмотр по тексту (для жюри) — без авторизации
    r = _client().post("/api/quest/plan/preview", json={"text": NEED_TEXT})
    assert r.status_code == 200, r.text
    body = r.json()
    _no_leak(body)
    assert body["need"]["spec"] == "Backend" and body["need"]["grade"] == "Middle" and "Kafka" in body["need"]["must"]
    assert body["plan"]["focus"]["Конкурентность"] == 1.25 and all("options" not in f for f in body["plan"]["families"])
    assert _client().post("/api/quest/plan/preview", json={"text": " "}).status_code == 422

    # план для работодателя: по своей потребности и по тексту; чужая потребность — 404; без входа — 401
    assert env["emp"].post("/api/quest/plan", json={"need_id": env["need_id"]}).json()["plan"] == plan_for_need("Backend", ["Python", "PostgreSQL", "Kafka"], ["Kubernetes"], "Middle")
    assert env["emp"].post("/api/quest/plan", json={"text": NEED_TEXT}).status_code == 200
    assert env["emp2"].post("/api/quest/plan", json={"need_id": env["need_id"]}).status_code == 404
    assert _client().post("/api/quest/plan", json={"text": NEED_TEXT}).status_code == 401
    assert env["client"].post("/api/quest/plan", json={"text": NEED_TEXT}).status_code == 403  # кандидат — не работодатель


def _parallel(*calls):
    """Запустить вызовы одновременно, вернуть коды ответов по возрастанию."""
    out, gate = [], threading.Barrier(len(calls))

    def run(fn):
        gate.wait()
        out.append(fn().status_code)

    ts = [threading.Thread(target=run, args=(fn,)) for fn in calls]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    return sorted(out)


def test_races(env, monkeypatch):
    client, cand_id = env["client"], env["cand_id"]
    first = client.post("/api/quest/start", json={}).json()

    # одна незавершённая сессия на кандидата — на уровне БД
    with SessionLocal() as db:
        db.add(QuestSession(candidate_id=cand_id, answers=[], flags=[]))
        with pytest.raises(IntegrityError):
            db.commit()

    # параллельный старт: проверка «есть ли активная» проскочила, вставка упёрлась в индекс → продолжаем существующую
    real, calls = quest._active, []
    monkeypatch.setattr(quest, "_active", lambda db, cand, lock=False: None if not calls.append(1) and len(calls) == 1 else real(db, cand, lock))
    second = client.post("/api/quest/start", json={})
    monkeypatch.setattr(quest, "_active", real)
    assert second.status_code == 200 and second.json()["session_id"] == first["session_id"] and second.json()["resumed"]

    # два одинаковых ответа одновременно: засчитывается один, второй — 409
    it = first["item"]
    body = {"item_id": it["id"], "response": 0 if it["kind"] == "choice" else 1}
    assert _parallel(lambda: client.post("/api/quest/answer", json=body), lambda: client.post("/api/quest/answer", json=body)) == [200, 409]
    with SessionLocal() as db:
        s = db.get(QuestSession, first["session_id"])
        assert sum(1 for a in s.answers if a["item_id"] == it["id"]) == 1

    # довести до конца; параллельный finish — один 200, второй 409; повторный — тоже 409
    r = client.get("/api/quest/current").json()
    while not r["done"]:
        it = r["item"]
        r = client.post("/api/quest/answer", json={"item_id": it["id"], "response": 0 if it["kind"] == "choice" else 1}).json()
    assert _parallel(lambda: client.post("/api/quest/finish"), lambda: client.post("/api/quest/finish")) == [200, 409]
    assert client.post("/api/quest/finish").status_code == 409
    assert client.get("/api/quest/current").status_code == 404


def test_preview_limits(monkeypatch):
    anon = _client()
    quest._preview.cache_clear()
    assert anon.post("/api/quest/plan/preview", json={"text": NEED_TEXT}).status_code == 200
    assert anon.post("/api/quest/plan/preview", json={"text": "  " + NEED_TEXT.replace(" ", "   ")}).json()["need"]["parsed_by"] == "rules"
    assert quest._preview.cache_info().hits == 1  # нормализованный текст — из кэша
    assert anon.post("/api/quest/plan/preview", json={"text": "x" * (quest.PREVIEW_TEXT_MAX + 1)}).status_code == 422
    monkeypatch.setattr(quest.config, "DEMO", False)
    assert anon.post("/api/quest/plan/preview", json={"text": NEED_TEXT}).status_code == 404
