"""Задачи на код в тест-квесте: банк (клоны, скрытые тесты, эталоны), слот в адаптивном выборе, поток ответа
с замоканной песочницей (засчитано / нет / песочница недоступна — void), «запуск на примерах», флаги, клиент песочницы.
Настоящая песочница (nsjail) проверяется своими тестами: sandbox/tests."""

import json
import os
import random
import secrets
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fsp:fsp@localhost:5432/fsp_code")
os.environ.setdefault("DEMO", "1")
os.environ.setdefault("LLM_BASE_URL", "")

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete, select  # noqa: E402

from app import config  # noqa: E402
from app.db import Base, SessionLocal, engine  # noqa: E402
from app.deps import issue_token  # noqa: E402
from app.models import Candidate, Item, QuestSession, User  # noqa: E402
from app.routers import quest  # noqa: E402
from app.services import code_items, irt, sandbox  # noqa: E402
from app.services.items import generate_bank, plan_for_need, seed_items  # noqa: E402

app = FastAPI()
app.include_router(quest.router)
MK = dict(spec="Backend", track="Python", grade_claimed="Middle", min_salary=200000, formats=[], city="Москва")


@pytest.fixture(scope="module")
def env():
    Base.metadata.create_all(engine)
    tag = secrets.token_hex(4)
    with SessionLocal() as db:
        seed_items(db)
        items = {it.id: it for it in db.scalars(select(Item).where(Item.spec == "Backend"))}
        users = [User(email=f"code{i}-{tag}@example.ru", role="candidate") for i in range(9)]
        db.add_all(users)
        db.flush()
        cands = [Candidate(public_id=f"K{i}-{tag}", user_id=u.id, name="Код", email=u.email, **MK) for i, u in enumerate(users)]
        db.add_all(cands)
        db.commit()
        clients = [TestClient(app, headers={"Authorization": f"Bearer {issue_token(db, u)}"}) for u in users]
        ids, uids = [c.id for c in cands], [u.id for u in users]
    yield {"items": items, "clients": clients, "cand_ids": ids}
    with SessionLocal() as db:
        db.execute(delete(Candidate).where(Candidate.id.in_(ids)))
        db.execute(delete(User).where(User.id.in_(uids)))
        db.commit()


@pytest.fixture
def box(monkeypatch):
    """Замоканная песочница: решение «верно», если в коде есть строка OK; запоминает вызовы."""
    calls = []
    monkeypatch.setattr(config, "SANDBOX_URL", "http://sandbox.test")
    monkeypatch.setattr(config, "SANDBOX_TOKEN", "secret")
    monkeypatch.setattr(sandbox, "ready", lambda: True)
    monkeypatch.setattr(quest, "RUN_GAP_S", 0)

    def fake(lang, code, entry, tests, *, time_ms, memory_mb, fail_fast=False, echo=False):
        calls.append(SimpleNamespace(lang=lang, code=code, entry=entry, tests=tests, fail_fast=fail_fast, echo=echo, time_ms=time_ms))
        if "DOWN" in code:
            raise sandbox.Unavailable("тест")
        if "BUSY" in code:
            raise sandbox.Busy("тест")
        if "REJECT" in code:
            raise sandbox.Rejected("тест")
        if "FAULTY" in code:
            raise sandbox.Faulty("тест")
        st = "ok" if "OK" in code else "wrong"
        res = [{"status": st if i == 0 or st == "ok" else "skip", "time_ms": 5, **({"got": "0"} if echo else {})} for i in range(len(tests))]
        return {"status": st, "passed": sum(r["status"] == "ok" for r in res), "total": len(tests), "results": res, "stderr": None if st == "ok" else "AssertionError"}

    monkeypatch.setattr(sandbox, "run", fake)
    return calls


def _no_leak(resp):
    """Ни ключа, ни сида клона, ни скрытых тестов и эталона, ни правильности; задание целиком — несколько КБ."""
    s = json.dumps(resp, ensure_ascii=False)
    for bad in ('"key"', '"correct"', '"answers"', '"seed"', '"ref"', '"tests"', '"solve"'):
        assert bad not in s, (bad, s[:300])
    assert len(s) < 20_000


def _to_code(client, items, start=None) -> dict:
    """Начать тест и отвечать на обычные задания, пока не выдадут задачу на код."""
    r = client.post("/api/quest/start", json=start or {"story": False}).json()
    for _ in range(20):
        it = r["item"]
        assert it, r
        if it["kind"] == "code":
            return r
        item = items[it["id"]]
        keys = item.payload["key"] if isinstance(item.payload["key"], list) else [item.payload["key"]]
        r = client.post("/api/quest/answer", json={"item_id": it["id"], "response": keys[0], "ms": 60000})
        assert r.status_code == 200, r.text
        r = r.json()
    raise AssertionError("задача на код не выдана")


def _session(cand_id) -> QuestSession:
    with SessionLocal() as db:
        return db.scalar(select(QuestSession).where(QuestSession.candidate_id == cand_id).order_by(QuestSession.id.desc()))


# ---------- банк ----------

def test_bank_payload_and_hidden_tests():
    bank = [r for r in generate_bank() if r["kind"] == "code"]
    assert {r["spec"] for r in bank} == set(code_items.SPECS)
    fams = {r["family"] for r in bank}
    assert fams == set(code_items.FAMILIES) and any(r["pilot"] for r in bank)
    be = [r for r in bank if r["spec"] == "Backend"]
    for r in be:
        p = r["payload"]
        assert set(p["key"]) == {"seed"} and r["competency"] == "Алгоритмы" and p["time_limit_s"] == 900
        c = p["code"]
        assert set(c["entry"]) == {"python", "typescript"} and c["entry"]["typescript"] == code_items.camel(c["entry"]["python"])
        assert c["templates"]["python"].startswith(f"def {c['entry']['python']}(") and f"function {c['entry']['typescript']}(" in c["templates"]["typescript"]
        assert 1 <= len(c["examples"]) <= 2 and "TypeScript" in c["ts_note"]
        tests = code_items.hidden_tests(r["family"], p["key"]["seed"])
        assert tests == code_items.hidden_tests(r["family"], p["key"]["seed"])  # пересоздаются детерминированно
        assert tests[: len(c["examples"])] == c["examples"] and len(tests) >= 10
        assert max(len(json.dumps(t["args"])) for t in tests) > 100_000  # большой тест отсекает O(n·q)
        # эталон на Python проходит все скрытые тесты
        ns = {}
        exec(code_items.reference(r["family"], p["key"]["seed"], "python"), ns)  # noqa: S102 — свой эталон
        fn = ns[c["entry"]["python"]]
        assert all(json.dumps(fn(*t["args"])) == json.dumps(t["expected"]) for t in tests), (r["family"], c["entry"])
    # клоны различаются (защита от утечки): имена/условия и данные примеров
    for fam in fams:
        clones = [r["payload"] for r in be if r["family"] == fam]
        assert len({json.dumps(p["code"]["examples"]) for p in clones}) == len(clones)
        assert len({(p["prompt"], p["code"]["entry"]["python"]) for p in clones}) >= 2, fam


def test_seed_items_adds_missing_families(env):
    with SessionLocal() as db:
        n = db.query(Item).filter(Item.kind == "code", Item.spec == "Mobile").delete()
        db.commit()
        assert n and seed_items(db) == n and seed_items(db) == 0


def test_code_slot_in_selection():
    bank = [SimpleNamespace(id=i, **{k: r[k] for k in ("family", "competency", "kind", "a", "b", "pilot")})
            for i, r in enumerate(generate_bank()) if r["spec"] == "Backend"]
    rng = random.Random(3)
    for _ in range(30):
        seen, fams, kinds = set(), set(), []
        for n in range(10):
            it = irt.choose(0.0, bank, seen, fams, rng, n)
            seen.add(it.id)
            fams.add(it.family)
            kinds.append(it.kind)
        assert kinds.index("code") == irt.CODE_AT and kinds.count("code") == 1, kinds
    assert all(not irt.is_code(irt.next_item(0.0, bank, set(), set(), rng)) for _ in range(20))
    # пилотная задача на код занимает слот: после неё рабочей задачи на код нет
    pilot = next(it for it in bank if it.pilot and it.kind == "code")
    nxt = irt.choose(0.0, bank, {pilot.id}, {pilot.family}, rng, irt.CODE_AT)
    assert not irt.is_code(nxt)


def test_no_code_without_sandbox(env, monkeypatch):
    monkeypatch.setattr(config, "SANDBOX_URL", "")
    client, items = env["clients"][5], env["items"]
    r = client.post("/api/quest/start", json={"story": False}).json()
    seen = []
    while r["item"]:
        it = r["item"]
        seen.append(it["kind"])
        item = items[it["id"]]
        keys = item.payload["key"] if isinstance(item.payload["key"], list) else [item.payload["key"]]
        r = client.post("/api/quest/answer", json={"item_id": it["id"], "response": keys[0], "ms": 60000}).json()
    assert "code" not in seen and len(seen) >= irt.MIN_ITEMS
    assert all(f["kind"] != "code" for f in plan_for_need("Backend", ["Python"], [], "Middle")["families"])
    monkeypatch.setattr(config, "SANDBOX_URL", "http://sandbox.test")
    assert all(f["kind"] != "code" for f in plan_for_need("Backend", ["Python"], [], "Junior")["families"])  # без токена — выключена
    monkeypatch.setattr(config, "SANDBOX_TOKEN", "secret")
    plan = plan_for_need("Backend", ["Python"], [], "Junior")
    assert any(f["kind"] == "code" for f in plan["families"]) and plan["items_total"] <= irt.MAX_ITEMS


def test_express_has_no_code(env, box):
    """Экспресс (5 заданий по 60 с) задач на код не выдаёт даже с живой песочницей: код за минуту не написать."""
    client, items = env["clients"][8], env["items"]
    r = client.post("/api/quest/start", json={"mode": "express", "story": False}).json()
    seen = []
    while r["item"]:
        it = r["item"]
        seen.append(it["kind"])
        item = items[it["id"]]
        keys = item.payload["key"] if isinstance(item.payload["key"], list) else [item.payload["key"]]
        r = client.post("/api/quest/answer", json={"item_id": it["id"], "response": keys[0], "ms": 20000}).json()
    assert len(seen) == irt.EXPRESS_ITEMS > irt.CODE_AT and set(seen) <= set(irt.EXPRESS_KINDS), seen
    assert not box  # песочница не вызывалась
    bank = [SimpleNamespace(id=i, **{k: r[k] for k in ("family", "competency", "kind", "a", "b", "pilot")})
            for i, r in enumerate(generate_bank()) if r["spec"] == "Backend" and r["kind"] in irt.EXPRESS_KINDS]
    assert irt.simulate_session(bank, 0.5, random.Random(1), express=True)[2] == irt.EXPRESS_ITEMS


# ---------- поток ответа ----------

def test_code_answer_flow(env, box):
    client, items, cand_id = env["clients"][0], env["items"], env["cand_ids"][0]
    r = _to_code(client, items)
    _no_leak(r)
    it = r["item"]
    assert it["kind"] == "code" and r["time_limit_s"] == 900 and "code" in it and "key" not in it
    n_before = r["progress"]["n"]
    ex = items[it["id"]].payload["code"]["examples"]

    # запуск на примерах: только открытые примеры, echo, на оценку не влияет
    run = client.post("/api/quest/run", json={"item_id": it["id"], "lang": "typescript", "code": "function x() {} // OK"})
    assert run.status_code == 200, run.text
    body = run.json()
    assert box[-1].tests == ex and box[-1].echo and box[-1].entry == it["code"]["entry"]["typescript"]
    assert body["passed"] == body["total"] == len(ex) and body["runs_left"] == quest.RUNS_MAX - 1
    assert body["results"][0]["expected"] == json.dumps(ex[0]["expected"], ensure_ascii=False) and body["results"][0]["got"] == "0"
    wrong = client.post("/api/quest/run", json={"item_id": it["id"], "lang": "python", "code": "def f(): pass"}).json()
    assert wrong["status"] == "wrong" and wrong["stderr"] == "AssertionError"
    assert _session(cand_id).answers[-1]["response"] is None  # всё ещё текущее задание

    # проверки ввода
    for bad, code in [({"lang": "ruby", "code": "x"}, 422), ({"lang": "python", "code": "   "}, 422),
                      ({"lang": "python", "code": "ы" * 10_001}, 422), ({"lang": "python", "code": "x" * 20_001}, 422),
                      ({"lang": "python", "code": "def f():\x00 return 1"}, 422)]:
        assert client.post("/api/quest/run", json={"item_id": it["id"], **bad}).status_code == code, bad
        assert client.post("/api/quest/answer", json={"item_id": it["id"], **bad}).status_code == code, bad
    assert client.post("/api/quest/run", json={"item_id": -1, "lang": "python", "code": "x"}).status_code == 409

    # отправка: скрытые тесты (больше примеров, с большим тестом), fail_fast, ответ без вердикта
    sub = client.post("/api/quest/answer", json={"item_id": it["id"], "lang": "python", "code": "def f(): return 1  # OK", "ms": 400_000, "pasted": 5})
    assert sub.status_code == 200, sub.text
    _no_leak(sub.json())
    call = box[-1]
    assert call.fail_fast and not call.echo and len(call.tests) > len(ex) and call.tests[: len(ex)] == ex
    assert call.time_ms == code_items.TIME_MS
    assert sub.json()["progress"]["n"] == n_before + 1 and (sub.json()["item"] or {}).get("id") != it["id"]
    rec = next(a for a in _session(cand_id).answers if a["item_id"] == it["id"])
    assert rec["response"] == "python" and rec["correct"] is True and rec["runs"] == 2 and rec["pasted"] == 5
    assert rec["tests"]["passed"] == rec["tests"]["total"] == len(call.tests) and set(rec["tests"]["statuses"]) == {"ok"}
    assert "args" not in json.dumps(rec["tests"])  # входы скрытых тестов в сессию не пишутся
    # повторная отправка того же задания — 409
    assert client.post("/api/quest/answer", json={"item_id": it["id"], "lang": "python", "code": "OK"}).status_code == 409


def test_wrong_and_late_code(env, box):
    client, items, cand_id = env["clients"][1], env["items"], env["cand_ids"][1]
    it = _to_code(client, items)["item"]
    sub = client.post("/api/quest/answer", json={"item_id": it["id"], "lang": "typescript", "code": "function f() { return 0; }"})
    assert sub.status_code == 200
    rec = next(a for a in _session(cand_id).answers if a["item_id"] == it["id"])
    assert rec["correct"] is False and rec["tests"]["statuses"][0] == "wrong" and rec["response"] == "typescript"

    # второй кандидат: ответ позже лимита — неверно без прогона в песочнице
    client, cand_id = env["clients"][2], env["cand_ids"][2]
    it = _to_code(client, items)["item"]
    with SessionLocal() as db:
        s = db.scalar(select(QuestSession).where(QuestSession.candidate_id == cand_id, QuestSession.finished_at.is_(None)))
        s.answers = [*s.answers[:-1], {**s.answers[-1], "served_at": (datetime.now(UTC) - timedelta(hours=1)).isoformat()}]
        db.commit()
    n = len(box)
    assert client.post("/api/quest/answer", json={"item_id": it["id"], "lang": "python", "code": "OK"}).status_code == 200
    rec = next(a for a in _session(cand_id).answers if a["item_id"] == it["id"])
    assert len(box) == n and rec["correct"] is False and rec["timeout"] is True and rec["tests"] is None


def test_rejected_solution_is_wrong_not_void(env, box):
    """Песочница отклонила решение (4xx) — неверный ответ, а не void: нарочно неприемлемым кодом задачу не пропустить."""
    client, items, cand_id = env["clients"][6], env["items"], env["cand_ids"][6]
    it = _to_code(client, items)["item"]
    assert client.post("/api/quest/run", json={"item_id": it["id"], "lang": "python", "code": "REJECT"}).status_code == 422
    r = client.post("/api/quest/answer", json={"item_id": it["id"], "lang": "python", "code": "REJECT"})
    assert r.status_code == 200, r.text
    rec = next(a for a in _session(cand_id).answers if a["item_id"] == it["id"])
    assert rec["correct"] is False and rec["rejected"] and not rec.get("void") and rec["tests"] is None

    # ответ песочницы — не вердикт (500, битый JSON): не void и не заморозка часов, задание остаётся текущим
    client, cand_id = env["clients"][7], env["cand_ids"][7]
    it = _to_code(client, items)["item"]
    r = client.post("/api/quest/answer", json={"item_id": it["id"], "lang": "python", "code": "FAULTY"})
    assert r.status_code == 503 and r.json()["detail"] == quest.SANDBOX_FAULTY
    pend = _session(cand_id).answers[-1]
    assert pend["item_id"] == it["id"] and pend["response"] is None and not pend.get("void") and not pend.get("submitted_at")


def test_sandbox_down_voids_item(env, box):
    client, items, cand_id = env["clients"][3], env["items"], env["cand_ids"][3]
    it = _to_code(client, items)["item"]
    assert client.post("/api/quest/run", json={"item_id": it["id"], "lang": "python", "code": "DOWN"}).status_code == 503
    r = client.post("/api/quest/answer", json={"item_id": it["id"], "lang": "python", "code": "DOWN", "ms": 1000})
    assert r.status_code == 503 and "не засчитано" in r.json()["detail"]
    s = _session(cand_id)
    rec = next(a for a in s.answers if a["item_id"] == it["id"])
    assert rec["void"] and rec["correct"] is None and rec["response"] == "void"
    cur = client.get("/api/quest/current").json()
    assert cur["item"] and cur["item"]["id"] != it["id"] and cur["item"]["kind"] != "code"  # дальше без кода: слот занят
    # до конца теста: void не входит ни в оценку, ни в число заданий
    while cur["item"]:
        item = items[cur["item"]["id"]]
        keys = item.payload["key"] if isinstance(item.payload["key"], list) else [item.payload["key"]]
        cur = client.post("/api/quest/answer", json={"item_id": item.id, "response": keys[0], "ms": 60000}).json()
        assert cur["item"] is None or cur["item"]["kind"] != "code"
    fin = client.post("/api/quest/finish")
    assert fin.status_code == 200, fin.text
    hist = client.get("/api/quest/history").json()[0]
    assert hist["items"] == sum(1 for a in _session(cand_id).answers if not a.get("void"))


def test_sandbox_busy_keeps_item(env, box, monkeypatch):
    """Перегрузка — не сбой: задание не void, запуск не списан, время ответа — по первой отправке."""
    client, items, cand_id = env["clients"][5], env["items"], env["cand_ids"][5]
    client.post("/api/quest/finish")  # сессия из test_no_code_without_sandbox
    it = _to_code(client, items)["item"]
    r = client.post("/api/quest/run", json={"item_id": it["id"], "lang": "python", "code": "BUSY"})
    assert r.status_code == 503 and "не засчитан" in r.json()["detail"]
    assert client.post("/api/quest/run", json={"item_id": it["id"], "lang": "python", "code": "OK"}).json()["runs_left"] == quest.RUNS_MAX - 1
    monkeypatch.setattr(quest, "RUN_GAP_S", 60)
    assert client.post("/api/quest/run", json={"item_id": it["id"], "lang": "python", "code": "OK"}).status_code == 429  # слишком часто
    r = client.post("/api/quest/answer", json={"item_id": it["id"], "lang": "python", "code": "BUSY"})
    assert r.status_code == 503 and r.json()["detail"] == quest.SANDBOX_BUSY
    pend = _session(cand_id).answers[-1]
    assert pend["item_id"] == it["id"] and pend["response"] is None and pend["submitted_at"] and pend["runs"] == 1
    # первая отправка — через 10 с после выдачи; повтор позже лимита не делает ответ опоздавшим
    served = datetime.now(UTC) - timedelta(hours=1)
    with SessionLocal() as db:
        s = db.scalar(select(QuestSession).where(QuestSession.candidate_id == cand_id, QuestSession.finished_at.is_(None)))
        s.answers = [*s.answers[:-1], {**s.answers[-1], "served_at": served.isoformat(), "submitted_at": (served + timedelta(seconds=10)).isoformat()}]
        db.commit()
    assert client.post("/api/quest/answer", json={"item_id": it["id"], "lang": "python", "code": "OK"}).status_code == 200
    rec = next(a for a in _session(cand_id).answers if a["item_id"] == it["id"])
    assert rec["correct"] is True and rec["timeout"] is False and 9_000 <= rec["server_ms"] <= 11_000


def test_concurrent_check_and_changed_session(env, box, monkeypatch):
    client, items, cand_id = env["clients"][4], env["items"], env["cand_ids"][4]
    it = _to_code(client, items)["item"]
    sid = _session(cand_id).id
    quest._checking.add(sid)
    try:
        assert client.post("/api/quest/run", json={"item_id": it["id"], "lang": "python", "code": "OK"}).status_code == 429
        assert client.post("/api/quest/answer", json={"item_id": it["id"], "lang": "python", "code": "OK"}).status_code == 429
    finally:
        quest._checking.discard(sid)
    # лимит запусков на примерах
    with SessionLocal() as db:
        s = db.get(QuestSession, sid)
        s.answers = [*s.answers[:-1], {**s.answers[-1], "runs": quest.RUNS_MAX}]
        db.commit()
    assert client.post("/api/quest/run", json={"item_id": it["id"], "lang": "python", "code": "OK"}).status_code == 429
    # пока шла проверка, задание ответили другим запросом — второй ответ не перетирает первый
    real = sandbox.run

    def racing(*a, **kw):
        with SessionLocal() as db:
            s = db.get(QuestSession, sid)
            s.answers = [*s.answers[:-1], {**s.answers[-1], "response": "python", "correct": False}]
            db.commit()
        return real(*a, **kw)

    monkeypatch.setattr(sandbox, "run", racing)
    r = client.post("/api/quest/answer", json={"item_id": it["id"], "lang": "python", "code": "OK"})
    assert r.status_code == 409 and next(a for a in _session(cand_id).answers if a["item_id"] == it["id"])["correct"] is False


def test_pasted_code_flag(env, box, monkeypatch):
    client, items = env["clients"][0], env["items"]
    # кандидат 0 уже ответил на задачу на код в test_code_answer_flow — доводим сессию с «вставленным» решением
    sess = _session(env["cand_ids"][0])
    with SessionLocal() as db:
        s = db.get(QuestSession, sess.id)
        s.answers = [{**a, "pasted": len(a["code"])} if a.get("code") else a for a in s.answers]
        db.commit()
    cur = client.get("/api/quest/current").json()
    while cur["item"]:
        item = items[cur["item"]["id"]]
        keys = item.payload["key"] if isinstance(item.payload["key"], list) else [item.payload["key"]]
        cur = client.post("/api/quest/answer", json={"item_id": item.id, "response": keys[0], "ms": 60000}).json()
    fin = client.post("/api/quest/finish").json()
    assert "code_pasted" in fin["flags"] and "review_required" in fin["flags"]


# ---------- клиент песочницы ----------

def test_sandbox_client(monkeypatch):
    tests = [{"args": [1], "expected": 2}]
    monkeypatch.setattr(config, "SANDBOX_URL", "")
    with pytest.raises(sandbox.Unavailable, match="не настроена"):
        sandbox.run("python", "x", "f", tests, time_ms=1000, memory_mb=128)
    monkeypatch.setattr(config, "SANDBOX_URL", "http://sandbox.test")
    monkeypatch.setattr(config, "SANDBOX_TOKEN", "secret")
    sent = {}
    good = {"status": "ok", "passed": 1, "total": 1, "results": [{"status": "ok", "time_ms": 3}], "stderr": None}

    def post(url, json, headers, timeout, reply):
        sent.update(url=url, body=json, headers=headers)
        if isinstance(reply, Exception):
            raise reply
        return httpx.Response(reply[0], content=reply[1] if isinstance(reply[1], bytes) else __import__("json").dumps(reply[1]).encode())

    for reply, ok in [((200, good), True), ((503, {"detail": "x"}), False), ((200, b"not json"), False),
                      ((200, {**good, "results": []}), False), ((200, {**good, "passed": 0}), False),
                      ((200, {**good, "results": [{"status": "pwned"}]}), False), (httpx.ConnectError("x"), False), ((429, {"detail": "x"}), "busy"),
                      ((422, {"detail": "x"}), "rejected"), ((500, {"detail": "x"}), "faulty")]:
        monkeypatch.setattr(httpx, "post", lambda url, json, headers, timeout, reply=reply: post(url, json, headers, timeout, reply))
        if ok == "faulty":
            with pytest.raises(sandbox.Faulty):
                sandbox.run("python", "code", "f", tests, time_ms=1000, memory_mb=128)
        elif ok == "rejected":
            with pytest.raises(sandbox.Rejected):
                sandbox.run("python", "code", "f", tests, time_ms=1000, memory_mb=128)
        elif ok == "busy":
            with pytest.raises(sandbox.Busy):
                sandbox.run("python", "code", "f", tests, time_ms=1000, memory_mb=128)
        elif ok:
            assert sandbox.run("python", "code", "f", tests, time_ms=1000, memory_mb=128, fail_fast=True) == good
            assert sent["url"] == "http://sandbox.test/run" and sent["headers"] == {"X-Sandbox-Token": "secret"}
            assert sent["body"]["harness"] == {"entry": "f"} and sent["body"]["fail_fast"] and sent["body"]["limits"] == {"time_ms": 1000, "memory_mb": 128}
        else:
            with pytest.raises(sandbox.Unavailable):
                sandbox.run("python", "code", "f", tests, time_ms=1000, memory_mb=128)


def test_sandbox_api_slots(monkeypatch):
    """Все слоты API заняты — Busy сразу, без запроса и без занятого потока на минуту."""
    monkeypatch.setattr(config, "SANDBOX_URL", "http://sandbox.test")
    monkeypatch.setattr(config, "SANDBOX_TOKEN", "secret")
    monkeypatch.setattr(httpx, "post", lambda *a, **kw: pytest.fail("запроса быть не должно"))
    taken = 0
    while sandbox._slots.acquire(blocking=False):
        taken += 1
    try:
        assert taken == config.SANDBOX_API_SLOTS
        with pytest.raises(sandbox.Busy):
            sandbox.run("python", "code", "f", [{"args": [], "expected": 1}], time_ms=1000, memory_mb=128)
    finally:
        for _ in range(taken):
            sandbox._slots.release()


def test_sandbox_ready_is_cached(monkeypatch):
    monkeypatch.setattr(config, "SANDBOX_URL", "http://sandbox.test")
    monkeypatch.setattr(config, "SANDBOX_TOKEN", "secret")
    monkeypatch.setitem(sandbox._health, "at", -1e9)
    gets = []

    def get(url, timeout, fail=False):
        gets.append(url)
        if fail:
            raise httpx.ConnectError("нет")
        return httpx.Response(200, json={"ok": True})

    monkeypatch.setattr(httpx, "get", get)
    assert sandbox.ready() and sandbox.ready() and gets == ["http://sandbox.test/health"]  # второй раз — из кэша
    monkeypatch.setitem(sandbox._health, "at", -1e9)  # кэш протух, песочница упала
    monkeypatch.setattr(httpx, "get", lambda url, timeout: get(url, timeout, fail=True))
    assert not sandbox.ready()
    monkeypatch.setattr(config, "SANDBOX_TOKEN", "")
    assert not sandbox.ready() and not sandbox.enabled()
