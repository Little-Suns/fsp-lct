"""Интеграции достижений: CF, CTFtime, импорт протоколов. Внешние API подменяются через common.get_json.

Запуск: DATABASE_URL=postgresql+psycopg://fsp:fsp@localhost:5432/fsp_integ uv run pytest -q tests/test_integrations.py
Живой smoke (настоящие CF и CTFtime): LIVE=1 ... -k live
"""

import os
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import deps
from app.db import Base, SessionLocal, engine
from app.integrations import codeforces, common, ctftime, hackathons
from app.integrations.consent import set_external_consent
from app.integrations.scoring import combine, place_weight, rating_weight
from app.models import Achievement, Candidate, ExternalAccount, User
from app.routers import achievements

app = FastAPI()
app.include_router(deps.router)
app.include_router(achievements.router)
client = TestClient(app)


@pytest.fixture(scope="module", autouse=True)
def schema():
    if "fsp_integ" not in str(engine.url) and not os.environ.get("ALLOW_DROP"):
        pytest.skip("тест пересоздаёт схему — нужен отдельный DATABASE_URL (fsp_integ)")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def make_candidate(consent=True, fsp_id=None, synthetic=False) -> tuple[dict, str, int]:
    tag = uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        user = User(email=f"u{tag}@example.ru", role="candidate", token=f"t{tag}", fsp_id=fsp_id)
        db.add(user)
        db.flush()
        cand = Candidate(public_id=f"A-{tag[:6]}", user_id=user.id, name="Тест", email=f"Cand.{tag}@Example.ru",
                         spec="Backend", grade_claimed="Middle", min_salary=200000, city="Москва", consent_external=consent, is_synthetic=synthetic)
        db.add(cand)
        db.commit()
        return {"Authorization": f"Bearer t{tag}"}, cand.email, cand.id


def fake_api(routes: dict):
    """routes: {подстрока URL или 'method': ответ}. Возвращает подмену common.get_json и журнал вызовов."""
    calls = []

    def get_json(url, params=None, **_):
        calls.append((url, params))
        for key, resp in routes.items():
            if key in url:
                if isinstance(resp, Exception):
                    raise resp
                return resp(params) if callable(resp) else resp
        raise AssertionError(f"неожиданный запрос {url}")

    return get_json, calls


CF_HISTORY = [
    {"contestId": 1, "contestName": "Codeforces Round 900 (Div. 2)", "rank": 12, "ratingUpdateTimeSeconds": 1700000000, "oldRating": 1800, "newRating": 1890},
    {"contestId": 2, "contestName": "Codeforces Round 901 (Div. 1)", "rank": 450, "ratingUpdateTimeSeconds": 1700100000, "oldRating": 1890, "newRating": 1912},
]


def cf_routes(org: str):
    info = {"handle": "Dorlov", "rating": 1912, "rank": "candidate master", "maxRating": 1950, "organization": org}
    return {"user.info": {"status": "OK", "result": [info]}, "user.rating": {"status": "OK", "result": CF_HISTORY}}


def test_weights_sane():
    assert 0 < rating_weight(1912) < rating_weight(2400) < 1
    assert place_weight(1, 300, "national") > place_weight(30, 300, "national") > place_weight(250, 300, "national")
    assert codeforces.contest_level("Codeforces Round 1 (Div. 3)") == "regional"
    assert ctftime.level_by_weight(75) == "international" and ctftime.level_by_weight(5) == "local"
    assert combine([]) == 0.0


def test_consent_required():
    h, _, _ = make_candidate(consent=False)
    r = client.post("/api/achievements/codeforces/link", json={"handle": "dorlov"}, headers=h)
    assert r.status_code == 403 and "согласие" in r.json()["detail"]
    assert client.post("/api/achievements/consent", json={"value": True}, headers=h).json() == {"consent_external": True}


def test_cf_verify_code_missing_then_success(monkeypatch):
    h, _, cid = make_candidate()
    link = client.post("/api/achievements/codeforces/link", json={"handle": "dorlov"}, headers=h).json()
    code = link["code"]
    assert code.startswith("FSP-") and len(code) == 8 and code in link["instructions"]

    fake, _ = fake_api(cf_routes("ITMO University"))
    monkeypatch.setattr(common, "get_json", fake)
    r = client.post("/api/achievements/codeforces/verify", headers=h)
    assert r.status_code == 400 and code in r.json()["detail"] and "ITMO" in r.json()["detail"]

    fake, calls = fake_api(cf_routes(f"ООО Рога {code.lower()}"))  # регистр не важен
    monkeypatch.setattr(common, "get_json", fake)
    body = client.post("/api/achievements/codeforces/verify", headers=h).json()
    cf = body["codeforces"]
    assert cf["verified"] and cf["handle"] == "Dorlov" and cf["rating"] == 1912
    kinds = sorted(a["title"] for a in cf["achievements"])
    assert len(kinds) == 2  # рейтинг + Div.2 12-е место; 450-е место не «заметное»
    contest = next(a for a in cf["achievements"] if a["place"] == 12)
    assert contest["level"] == "national" and contest["weight"] == place_weight(12, None, "national")
    assert 0 < body["signal"] <= 1

    # повторный refresh в течение часа — из кеша, без запросов
    n = len(calls)
    assert client.post("/api/achievements/codeforces/refresh", headers=h).status_code == 200
    assert len(calls) == n

    # чужой кандидат не может забрать подтверждённый хэндл
    h2, _, _ = make_candidate()
    assert client.post("/api/achievements/codeforces/link", json={"handle": "DORLOV"}, headers=h2).status_code == 409

    # отзыв согласия удаляет привязку и CF-достижения
    client.post("/api/achievements/consent", json={"value": False}, headers=h)
    with SessionLocal() as db:
        assert not db.query(Achievement).filter_by(candidate_id=cid, source="codeforces").count()


def test_cf_upstream_failure_is_502(monkeypatch):
    h, _, _ = make_candidate()
    client.post("/api/achievements/codeforces/link", json={"handle": "nobody_here"}, headers=h)
    fake, _ = fake_api({"user.info": {"status": "FAILED", "comment": "handles: User with handle nobody_here not found"}})
    monkeypatch.setattr(common, "get_json", fake)
    r = client.post("/api/achievements/codeforces/verify", headers=h)
    assert r.status_code == 502 and "не найден" in r.json()["detail"]
    fake, _ = fake_api({"user.info": common.ExternalError("codeforces.com недоступен: ConnectTimeout")})
    monkeypatch.setattr(common, "get_json", fake)
    assert client.post("/api/achievements/codeforces/verify", headers=h).status_code == 502


CTF_RESULTS = {
    "100": {"title": "Big CTF", "time": 1700000000.0, "scores": [{"team_id": 9, "place": 1}, {"team_id": 77, "place": 2}] + [{"team_id": 1000 + i, "place": 3 + i} for i in range(98)]},
    "101": {"title": "Small CTF", "time": 1700000000.0, "scores": [{"team_id": 77, "place": 40}] + [{"team_id": 2000 + i, "place": i} for i in range(1, 40)]},
}


def test_ctftime_parse_and_link(monkeypatch):
    places = ctftime.team_places(77, {2025: CTF_RESULTS})
    assert [(p["event_id"], p["place"], p["participants"]) for p in places] == [(100, 2, 100), (101, 40, 40)]

    h, email, _ = make_candidate()
    fake, _ = fake_api({
        "teams/77": {"id": 77, "name": "Котики", "country": "RU", "rating": {"2025": {"rating_place": 120, "rating_points": 210.5}}},
        "results/": CTF_RESULTS,
        "events/100": {"title": "Big CTF 2025", "weight": 70.0, "participants": 900, "start": "2025-06-01T10:00:00+00:00", "ctftime_url": "https://ctftime.org/event/100/"},
        "events/101": {"title": "Small CTF 2025", "weight": 10.0, "participants": 40, "start": "2025-07-01T10:00:00+00:00"},
    })
    monkeypatch.setattr(common, "get_json", fake)
    body = client.post("/api/achievements/ctftime/link", json={"team_id": 77, "role": "pwn"}, headers=h).json()
    ct = body["ctftime"]
    assert ct["team"] == "Котики" and ct["rank"] == "#120 в мире, 2025"
    big = next(a for a in ct["achievements"] if a["place"] == 2)
    assert not big["verified"] and big["role"] == "pwn"
    assert big["weight"] == round(place_weight(2, 900, "international") * ctftime.UNVERIFIED_FACTOR, 3)

    # тиммейт привязывает ту же команду — уникальность (provider, handle, candidate_id) это допускает
    h_mate, _, _ = make_candidate()
    mate = client.post("/api/achievements/ctftime/link", json={"team_id": 77}, headers=h_mate)
    assert mate.status_code == 200 and mate.json()["ctftime"]["team_id"] == 77

    # организатор подтверждает участие протоколом с source=ctftime → verified и полный вес
    with SessionLocal() as db:
        rep = hackathons.import_protocol(db, {"source": "ctftime", "external_id": "100", "title": "Big CTF 2025"},
                                         [{"email": email, "team": "Котики", "place": 2, "role": "pwn"}])
    assert rep["matched"] == 1 and rep["updated"] == 1
    big = next(a for a in client.get("/api/achievements", headers=h).json()["ctftime"]["achievements"] if a["place"] == 2)
    assert big["verified"] and big["weight"] == place_weight(2, 900, "international")


def test_import_csv_matching_and_idempotency(monkeypatch):
    monkeypatch.setenv("ORGANIZER_TOKEN", "org-secret")
    h, email, cid = make_candidate()
    _, _, cid2 = make_candidate(fsp_id=f"FSP-{uuid.uuid4().hex[:6]}")
    with SessionLocal() as db:
        fsp_id = db.get(User, db.get(Candidate, cid2).user_id).fsp_id
    csv_text = f"﻿email;fsp_id;team;place;role\n{email.upper()};;Сигма;1;backend\n;{fsp_id};Сигма;1;ML\nnobody@x.ru;;Альфа;7;\n"
    form = {"source": "hackathon", "external_id": "lct-2025", "title": "Лидеры цифровой трансформации 2025",
            "level": "national", "date": "2025-09-20", "participants": "300", "tags": "ML, Python"}
    org = {"Authorization": "Bearer org-secret"}

    assert client.post("/api/achievements/import", data=form, files={"file": ("p.csv", csv_text)}, headers=h).status_code == 403
    r1 = client.post("/api/achievements/import", data=form, files={"file": ("p.csv", csv_text)}, headers=org).json()
    assert r1["matched"] == 2 and r1["created"] == 2 and r1["unmatched"] == [
        {"row": 3, "email": "nobody@x.ru", "fsp_id": None, "reason": "кандидат не найден"}]
    r2 = client.post("/api/achievements/import", data=form, files={"file": ("p.csv", csv_text)}, headers=org).json()
    assert r2["created"] == 0 and r2["updated"] == 2 and r2["event_id"] == r1["event_id"]
    with SessionLocal() as db:
        assert db.query(Achievement).filter_by(candidate_id=cid, event_id=r1["event_id"]).count() == 1

    hk = client.get("/api/achievements", headers=h).json()["hackathons"]
    assert hk[0]["verified"] and hk[0]["weight"] == place_weight(1, 300, "national") and hk[0]["role"] == "backend"
    ev = next(e for e in client.get("/api/achievements/events?source=hackathon").json() if e["id"] == r1["event_id"])
    assert ev["candidates"] == 2 and ev["tags"] == ["ML", "Python"]

    # JSON-вариант (ФСП) и ошибки формата
    rj = client.post("/api/achievements/import", headers=org, json={
        "event": {"source": "fsp", "external_id": "cup-2025-final", "title": "Финал Кубка России ФСП 2025", "level": "national"},
        "rows": [{"email": email, "place": 5, "team": "Сигма"}]})
    assert rj.json()["matched"] == 1
    bad = client.post("/api/achievements/import", headers=org, json={"event": {"source": "x", "external_id": "1", "title": "t"}, "rows": []})
    assert bad.status_code == 422 and "source" in bad.json()["detail"]


def test_synthetic_never_calls_external_api(monkeypatch):
    h, _, cid = make_candidate(synthetic=True)
    with SessionLocal() as db:  # как засевает seed: подтверждённый CF и CTFtime с устаревшим fetched_at
        old = datetime.now(UTC) - timedelta(days=30)
        db.add_all([
            ExternalAccount(candidate_id=cid, provider="codeforces", handle="dorlov", verify_code="FSP-7Q2K",
                            verified_at=old, fetched_at=old, rating=1912, rank="Candidate Master"),
            ExternalAccount(candidate_id=cid, provider="ctftime", handle="77", verify_code="", fetched_at=old, data={"team_id": 77}),
        ])
        db.commit()
    fake, calls = fake_api({})
    monkeypatch.setattr(common, "get_json", fake)
    for path in ("codeforces/verify", "codeforces/refresh", "ctftime/refresh"):
        r = client.post(f"/api/achievements/{path}", headers=h)
        assert r.status_code == 200, (path, r.text)
    assert r.json()["codeforces"]["rating"] == 1912 and r.json()["codeforces"]["handle"] == "dorlov"
    assert calls == []


def test_http_errors_and_shapes(monkeypatch):
    # любой HTTP ≥ 400 — ошибка, даже если тело — JSON-объект
    def fake_get(url, **kw):
        status = 404 if "teams/" in url else 429
        return httpx.Response(status, json={"detail": "Not found."}, request=httpx.Request("GET", url))

    monkeypatch.setattr(common.httpx, "get", fake_get)
    with pytest.raises(common.ExternalError) as e:
        common.get_json("https://example.test/x")
    assert e.value.status == 429
    h, _, _ = make_candidate()
    r = client.post("/api/achievements/ctftime/link", json={"team_id": 5}, headers=h)
    assert r.status_code == 502 and "команда 5 не найдена" in r.json()["detail"]
    monkeypatch.undo()

    # неожиданная форма ответа → 502, а не 500
    fake, _ = fake_api({"teams/": {"id": 5, "name": "X"}, "results/": {"1": {"title": "t", "scores": [{"team_id": "5"}]}}})
    monkeypatch.setattr(common, "get_json", fake)
    r = client.post("/api/achievements/ctftime/link", json={"team_id": 5}, headers=h)
    assert r.status_code == 502 and "формат" in r.json()["detail"]
    fake, _ = fake_api({"user.info": {"status": "OK", "result": []}})
    monkeypatch.setattr(common, "get_json", fake)
    with pytest.raises(common.ExternalError):
        codeforces.user_info("x")


def test_ctftime_sync_deadline(monkeypatch):
    def slow(resp):
        def f(_):
            time.sleep(0.05)
            return resp
        return f

    fake, calls = fake_api({"teams/": slow({"id": 5, "name": "X"}), "results/": slow(CTF_RESULTS),
                            "events/": slow({"title": "E", "weight": 10})})
    monkeypatch.setattr(common, "get_json", fake)
    monkeypatch.setattr(ctftime, "SYNC_DEADLINE", 0.12)
    h, _, _ = make_candidate()
    r = client.post("/api/achievements/ctftime/link", json={"team_id": 77}, headers=h)
    assert r.status_code == 502 and "не уложилась" in r.json()["detail"]
    assert len(calls) < 5


def test_consent_function_and_verify_race(monkeypatch):
    # set_external_consent без commit: вызывающий решает
    _, _, cid = make_candidate()
    with SessionLocal() as db:
        cand = db.get(Candidate, cid)
        db.add(ExternalAccount(candidate_id=cid, provider="ctftime", handle="1", verify_code=""))
        db.flush()
        set_external_consent(db, cand, False)
        db.commit()
        assert not cand.consent_external and not db.query(ExternalAccount).filter_by(candidate_id=cid).count()

    # гонка: проверка «чужой владелец» пропущена, уникальный индекс всё равно не даёт второго владельца → 409
    _, _, owner = make_candidate()
    h2, _, rival = make_candidate()
    with SessionLocal() as db:
        db.add_all([
            ExternalAccount(candidate_id=owner, provider="codeforces", handle="Racer", verify_code="FSP-AAAA", verified_at=datetime.now(UTC)),
            ExternalAccount(candidate_id=rival, provider="codeforces", handle="racer", verify_code="FSP-BBBB"),
        ])
        db.commit()
    monkeypatch.setattr(achievements, "_cf_owned_by_other", lambda *a: None)
    fake, _ = fake_api(cf_routes("FSP-BBBB"))
    monkeypatch.setattr(common, "get_json", fake)
    r = client.post("/api/achievements/codeforces/verify", headers=h2)
    assert r.status_code == 409 and "подтверждён другим" in r.json()["detail"]


def test_import_limits(monkeypatch):
    monkeypatch.setenv("ORGANIZER_TOKEN", "org-secret")
    org = {"Authorization": "Bearer org-secret"}
    ev = {"source": "hackathon", "external_id": "big", "title": "Big"}
    r = client.post("/api/achievements/import", headers=org, json={"event": ev, "rows": [{"email": "a@b.ru"}] * 5001})
    assert r.status_code == 422 and "5000" in r.json()["detail"]
    big = "email\n" + "x" * (2 * 1024 * 1024)
    r = client.post("/api/achievements/import", headers=org, data={**ev}, files={"file": ("p.csv", big)})
    assert r.status_code == 413


@pytest.mark.skipif(os.environ.get("LIVE") != "1", reason="LIVE=1 — запросы к настоящим Codeforces и CTFtime")
def test_live_smoke():
    info = codeforces.user_info("tourist")
    assert info["handle"] == "tourist" and info["rating"] > 3000
    team = ctftime.team(1)
    assert team["id"] == 1 and team["name"]
