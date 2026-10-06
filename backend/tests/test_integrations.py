"""Интеграции достижений: CF, CTFtime, импорт протоколов. Внешние API подменяются через common.get_json.

Запуск: DATABASE_URL=postgresql+psycopg://fsp:fsp@localhost:5432/fsp_integ uv run pytest -q tests/test_integrations.py
Живой smoke (настоящие CF и CTFtime): LIVE=1 ... -k live
"""

import os
import threading
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import deps
from app.catalog import CONSENT_VERSION
from app.db import Base, SessionLocal, engine
from app.deps import hash_secret, issue_token
from app.integrations import codeforces, common, ctftime, hackathons
from app.integrations.consent import lock_candidate, set_external_consent
from app.integrations.scoring import RESULT_WEIGHT, combine, place_weight, rating_weight, result_of, signal
from app.models import Achievement, AuditLog, Candidate, ConsentEvent, ExternalAccount, User
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


def make_candidate(consent=True, fsp_id=None, synthetic=False, version=CONSENT_VERSION) -> tuple[dict, str, int]:
    """(заголовки, почта входа User.email, candidate.id). Candidate.email намеренно другой."""
    tag = uuid.uuid4().hex[:8]
    with SessionLocal() as db:
        user = User(email=f"u{tag}@example.ru", role="candidate", fsp_id=fsp_id)
        db.add(user)
        db.flush()
        cand = Candidate(public_id=f"A-{tag[:6]}", user_id=user.id, name="Тест", email=f"Cand.{tag}@Example.ru",
                         spec="Backend", grade_claimed="Middle", min_salary=200000, city="Москва", consent_external=consent, is_synthetic=synthetic,
                         consent_152=True, consent_version=version, consent_external_version=version if consent else None)
        db.add(cand)
        db.commit()
        tok = issue_token(db, user)
        return {"Authorization": f"Bearer {tok}"}, user.email, cand.id


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
    assert place_weight(1, 300) > place_weight(30, 300) > place_weight(250, 300) == place_weight(None, 300)
    assert [result_of(p, 300) for p in (1, 2, 3, 30, 31, None)] == ["winner", "prize", "prize", "finalist", "participant", "participant"]
    assert result_of(12, None) == "participant" and result_of(0, 10) == "participant"
    # иерархии соревнований нет: Div. 1 и Div. 4, большой и малый CTF весят одинаково при одинаковом результате
    assert codeforces.contest_result(1) == "winner" and codeforces.contest_result(57) == "finalist"
    assert place_weight(1, 40) == place_weight(1, 4000) == RESULT_WEIGHT["winner"]
    assert combine([]) == 0.0
    # убывающая отдача по числу соревнований: 30 онлайн-явок < один выход в финал < победа
    assert combine([RESULT_WEIGHT["participant"]] * 30) < combine([RESULT_WEIGHT["finalist"]]) < combine([RESULT_WEIGHT["winner"]])
    assert combine([0.8, 0.6]) > combine([0.8]) and combine([0.8, 0.6]) - combine([0.8]) < 0.6
    # рейтинг — отдельный сигнал без дисконта; signal разделяет их по data.kind
    rating = Achievement(weight=0.4, data={"kind": "rating"})
    win = Achievement(weight=0.8, data={"kind": "protocol"})
    assert signal([win, rating]) == combine([0.8], [0.4]) == round(1 - 0.2 * 0.6, 3)


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
    code = client.post("/api/achievements/codeforces/link", json={"handle": "dorlov"}, headers=h).json()["code"]
    assert code != link["code"]  # каждый link — новый код
    with SessionLocal() as db:  # в БД только sha256, срок 24 ч
        acc = db.query(ExternalAccount).filter_by(candidate_id=cid, provider="codeforces").one()
        assert acc.verify_code == hash_secret(code) and acc.verify_expires_at > datetime.now(UTC) + timedelta(hours=23)
    assert "code" not in client.get("/api/achievements", headers=h).json()["codeforces"]

    fake, _ = fake_api(cf_routes("ITMO University"))
    monkeypatch.setattr(common, "get_json", fake)
    r = client.post("/api/achievements/codeforces/verify", headers=h)
    assert r.status_code == 400 and "ITMO" in r.json()["detail"] and code not in r.json()["detail"]

    fake, calls = fake_api(cf_routes(f"ООО Рога fsp-zzzz {code.lower()}"))  # регистр не важен, лишние токены не мешают
    monkeypatch.setattr(common, "get_json", fake)
    body = client.post("/api/achievements/codeforces/verify", headers=h).json()
    cf = body["codeforces"]
    assert cf["verified"] and cf["handle"] == "Dorlov" and cf["rating"] == 1912 and "code" not in cf
    with SessionLocal() as db:
        acc = db.query(ExternalAccount).filter_by(candidate_id=cid, provider="codeforces").one()
        assert acc.verify_code == "" and acc.verify_expires_at is None
    kinds = sorted(a["title"] for a in cf["achievements"])
    assert len(kinds) == 2  # рейтинг + Div.2 12-е место; 450-е место не «заметное»
    contest = next(a for a in cf["achievements"] if a["place"] == 12)
    assert contest["level"] is None and contest["result"] == "finalist" and contest["weight"] == RESULT_WEIGHT["finalist"]
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

    h, email, cid = make_candidate()
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
    assert big["result"] == "prize" and big["weight"] == round(RESULT_WEIGHT["prize"] * ctftime.UNVERIFIED_FACTOR, 3)
    small = next(a for a in ct["achievements"] if a["place"] == 40)  # последнее место из 40 — «участник», почти ноль
    assert small["result"] == "participant" and small["weight"] == round(RESULT_WEIGHT["participant"] * ctftime.UNVERIFIED_FACTOR, 3)
    assert body["signal"] == 0  # в сигнал (как и в подборе) идут только подтверждённые

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
    assert big["verified"] and big["weight"] == RESULT_WEIGHT["prize"]

    # повторная синхронизация CTFtime не затирает результат из протокола организатора
    with SessionLocal() as db:
        rep = hackathons.import_protocol(db, {"source": "ctftime", "external_id": "100", "title": "Big CTF 2025"},
                                         [{"email": email, "team": "Котики", "place": 2, "result": "победитель"}])
        acc = db.query(ExternalAccount).filter_by(candidate_id=cid, provider="ctftime").one()
        acc.fetched_at = None
        db.commit()
    body = client.post("/api/achievements/ctftime/refresh", headers=h).json()
    big = next(a for a in body["ctftime"]["achievements"] if a["place"] == 2)
    assert big["verified"] and big["result"] == "winner" and big["weight"] == RESULT_WEIGHT["winner"]


def test_import_csv_matching_and_idempotency(monkeypatch):
    monkeypatch.setenv("ORGANIZER_TOKEN", "org-secret")
    h, email, cid = make_candidate()
    _, _, cid2 = make_candidate(fsp_id=f"FSP-{uuid.uuid4().hex[:6]}")
    _, nc_email, _ = make_candidate(consent=False)
    with SessionLocal() as db:
        # кандидат вписал в анкету чужую почту из протокола — по Candidate.email не сопоставляем
        db.get(Candidate, cid2).email = "winner@lct.example"
        db.commit()
    with SessionLocal() as db:
        fsp_id = db.get(User, db.get(Candidate, cid2).user_id).fsp_id
    csv_text = f"﻿email;fsp_id;team;place;role\n{email.upper()};;Сигма;1;backend\n;{fsp_id};Сигма;1;ML\nnobody@x.ru;;Альфа;7;\nwinner@lct.example;;Альфа;1;\n{nc_email};;Бета;2;\n"
    form = {"source": "hackathon", "external_id": "lct-2025", "title": "Лидеры цифровой трансформации 2025",
            "level": "national", "date": "2025-09-20", "participants": "300", "tags": "ML, Python"}
    org = {"Authorization": "Bearer org-secret"}

    assert client.post("/api/achievements/import", data=form, files={"file": ("p.csv", csv_text)}, headers=h).status_code == 403
    r1 = client.post("/api/achievements/import", data=form, files={"file": ("p.csv", csv_text)}, headers=org).json()
    assert r1["matched"] == 2 and r1["created"] == 2 and r1["no_consent"] == 1 and r1["unmatched"] == [
        {"row": 3, "email": "nobody@x.ru", "fsp_id": None, "reason": "кандидат не найден"},
        {"row": 4, "email": "winner@lct.example", "fsp_id": None, "reason": "кандидат не найден"},
        {"row": 5, "email": nc_email, "fsp_id": None, "reason": "нет согласия на внешние данные"}]
    r2 = client.post("/api/achievements/import", data=form, files={"file": ("p.csv", csv_text)}, headers=org).json()
    assert r2["created"] == 0 and r2["updated"] == 2 and r2["event_id"] == r1["event_id"]
    with SessionLocal() as db:
        logs = db.query(AuditLog).filter_by(action="protocol_imported").all()
        assert [lg.detail for lg in logs if lg.detail["event_id"] == r1["event_id"]] == [
            {"event_id": r1["event_id"], "matched": 2, "unmatched_count": 3}] * 2
    with SessionLocal() as db:
        assert db.query(Achievement).filter_by(candidate_id=cid, event_id=r1["event_id"]).count() == 1

    hk = client.get("/api/achievements", headers=h).json()["hackathons"]
    assert hk[0]["verified"] and hk[0]["weight"] == place_weight(1, 300) and hk[0]["role"] == "backend"
    assert hk[0]["result"] == "winner" and hk[0]["result_label"] == "победитель" and hk[0]["sport_rank"] is None
    ev = next(e for e in client.get("/api/achievements/events?source=hackathon").json() if e["id"] == r1["event_id"])
    assert ev["candidates"] == 2 and ev["tags"] == ["ML", "Python"]

    # JSON-вариант (ФСП) и ошибки формата
    rj = client.post("/api/achievements/import", headers=org, json={
        "event": {"source": "fsp", "external_id": "cup-2025-final", "title": "Финал Кубка России ФСП 2025", "level": "national"},
        "rows": [{"email": email, "place": 5, "team": "Сигма"}]})
    assert rj.json()["matched"] == 1

    # организатор-пользователь с ролью admin (токен хранится хэшем) — тоже может, actor попадает в журнал
    with SessionLocal() as db:
        admin = User(email=f"admin{uuid.uuid4().hex[:6]}@example.ru", role="admin")
        db.add(admin)
        db.commit()
        adm = {"Authorization": f"Bearer {issue_token(db, admin)}"}
        admin_id = admin.id
    ra = client.post("/api/achievements/import", headers=adm, json={"event": {"source": "fsp", "external_id": "adm-1", "title": "T"}, "rows": []})
    assert ra.status_code == 200
    with SessionLocal() as db:
        assert db.query(AuditLog).filter_by(action="protocol_imported", actor_user_id=admin_id).count() == 1
    bad = client.post("/api/achievements/import", headers=org, json={"event": {"source": "x", "external_id": "1", "title": "t"}, "rows": []})
    assert bad.status_code == 422 and "source" in bad.json()["detail"]


def test_import_fsp_discipline_result_rank(monkeypatch):
    """Протокол ФСП: дисциплина события, результат и разряд строки — факты; вес — только по результативности."""
    monkeypatch.setenv("ORGANIZER_TOKEN", "org-secret")
    org = {"Authorization": "Bearer org-secret"}
    h, email, _ = make_candidate()
    csv_text = f"email;place;result;rank\n{email};;финалист;I разряд\n"
    form = {"source": "fsp", "external_id": "reg-bas-2025", "title": "Региональный этап ФСП 2025, БАС",
            "level": "regional", "discipline": "Программирование БАС", "participants": "80"}
    r = client.post("/api/achievements/import", data=form, files={"file": ("p.csv", csv_text)}, headers=org)
    assert r.status_code == 200 and r.json()["matched"] == 1
    rj = client.post("/api/achievements/import", headers=org, json={
        "event": {"source": "fsp", "external_id": "champ-algo-2025", "title": "Чемпионат России ФСП 2025",
                  "level": "national", "discipline": "алгоритмическое", "participants": 400},
        "rows": [{"email": email, "place": 2, "rank": "кмс"}]})
    assert rj.status_code == 200

    body = client.get("/api/achievements", headers=h).json()
    fsp = {a["title"]: a for a in body["fsp"]}
    bas, algo = fsp["Региональный этап ФСП 2025, БАС"], fsp["Чемпионат России ФСП 2025"]
    assert bas["discipline"] == "программирование беспилотных авиационных систем" and bas["result"] == "finalist"
    assert bas["sport_rank"] == "1 разряд" and bas["weight"] == RESULT_WEIGHT["finalist"]  # result без места — из протокола
    assert algo["discipline"] == "алгоритмическое программирование" and algo["result"] == "prize" and algo["sport_rank"] == "КМС"
    assert body["sport_rank"] == "КМС"  # высший разряд по подтверждённым протоколам
    assert body["signal"] == combine([RESULT_WEIGHT["prize"], RESULT_WEIGHT["finalist"]])
    ev = next(e for e in client.get("/api/achievements/events?source=fsp").json() if e["external_id"] == "reg-bas-2025")
    assert ev["discipline"] == "программирование беспилотных авиационных систем" and ev["level"] == "regional"

    # уровень и дисциплина на вес не влияют: тот же результат на «региональном» этапе весит как на чемпионате
    assert bas["weight"] == place_weight(None, 80, "finalist") == place_weight(40, 400)

    for bad, field in [({"discipline": "шахматы"}, "discipline"), ({"level": "galactic"}, "level")]:
        r = client.post("/api/achievements/import", headers=org, json={
            "event": {"source": "fsp", "external_id": "x", "title": "x", **bad}, "rows": []})
        assert r.status_code == 422 and field in r.json()["detail"]
    for row, field in [({"result": "чемпион мира"}, "result"), ({"rank": "гроссмейстер"}, "rank")]:
        r = client.post("/api/achievements/import", headers=org, json={
            "event": {"source": "fsp", "external_id": "x", "title": "x"}, "rows": [{"email": email, **row}]})
        assert r.status_code == 422 and field in r.json()["detail"] and "строка 1" in r.json()["detail"]


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
    _, email, cid = make_candidate()
    for src in ("fsp", "hackathon"):
        with SessionLocal() as db:
            hackathons.import_protocol(db, {"source": src, "external_id": f"c-{cid}", "title": "T"}, [{"email": email, "place": 1}])
    with SessionLocal() as db:
        cand = db.get(Candidate, cid)
        db.add(ExternalAccount(candidate_id=cid, provider="ctftime", handle="1", verify_code=""))
        db.flush()
        assert db.query(Achievement).filter_by(candidate_id=cid).count() == 2
        set_external_consent(db, cand, False)
        db.commit()
        assert not cand.consent_external and not db.query(ExternalAccount).filter_by(candidate_id=cid).count()
        assert not db.query(Achievement).filter_by(candidate_id=cid).count()  # все внешние источники
        ce = db.query(ConsentEvent).filter_by(candidate_id=cid).one()
        assert ce.purpose == "external" and ce.granted is False and ce.version == CONSENT_VERSION
        log = db.query(AuditLog).filter_by(action="consent_changed", subject_candidate_id=cid).one()
        assert log.actor_user_id == cand.user_id and log.detail == {"consent": "external", "value": False}

    # гонка: проверка «чужой владелец» пропущена, уникальный индекс всё равно не даёт второго владельца → 409
    _, _, owner = make_candidate()
    h2, _, rival = make_candidate()
    with SessionLocal() as db:
        db.add_all([
            ExternalAccount(candidate_id=owner, provider="codeforces", handle="Racer", verify_code="", verified_at=datetime.now(UTC)),
            ExternalAccount(candidate_id=rival, provider="codeforces", handle="racer", verify_code=hash_secret("FSP-BBBB"),
                            verify_expires_at=datetime.now(UTC) + timedelta(hours=1)),
        ])
        db.commit()
    monkeypatch.setattr(achievements, "_cf_owned_by_other", lambda *a: None)
    fake, _ = fake_api(cf_routes("FSP-BBBB"))
    monkeypatch.setattr(common, "get_json", fake)
    r = client.post("/api/achievements/codeforces/verify", headers=h2)
    assert r.status_code == 409 and "подтверждён другим" in r.json()["detail"]


def test_code_expiry_and_stale_consent_version(monkeypatch):
    h, _, cid = make_candidate()
    client.post("/api/achievements/codeforces/link", json={"handle": "expired"}, headers=h)
    with SessionLocal() as db:
        db.query(ExternalAccount).filter_by(candidate_id=cid).one().verify_expires_at = datetime.now(UTC) - timedelta(minutes=1)
        db.commit()
    r = client.post("/api/achievements/codeforces/verify", headers=h)
    assert r.status_code == 400 and r.json()["detail"] == "Код истёк — запросите новый"

    # согласие дано на старую редакцию текста → не действует ни для привязки, ни для импорта
    h_old, email_old, _ = make_candidate(version="2020-01")
    assert client.post("/api/achievements/codeforces/link", json={"handle": "old_ver"}, headers=h_old).status_code == 403
    with SessionLocal() as db:
        rep = hackathons.import_protocol(db, {"source": "fsp", "external_id": "ver", "title": "T"}, [{"email": email_old, "place": 1}])
    assert rep["matched"] == 0 and rep["no_consent"] == 1


def _revoke(cid: int):
    with SessionLocal() as db:
        set_external_consent(db, db.get(Candidate, cid), False)
        db.commit()


def test_consent_revoked_during_fetch(monkeypatch):
    # CF refresh: отзыв пришёл, пока шли запросы к CF → 409, ничего не записано
    h, _, cid = make_candidate()
    old = datetime.now(UTC) - timedelta(days=2)
    with SessionLocal() as db:
        db.add(ExternalAccount(candidate_id=cid, provider="codeforces", handle="revoker", verify_code="", verified_at=old, fetched_at=old, rating=1500))
        db.commit()
    routes = cf_routes("x")
    info = routes["user.info"]
    routes["user.info"] = lambda _: (_revoke(cid), info)[1]
    fake, _ = fake_api(routes)
    monkeypatch.setattr(common, "get_json", fake)
    r = client.post("/api/achievements/codeforces/refresh", headers=h)
    assert r.status_code == 409 and "отозвано" in r.json()["detail"]
    with SessionLocal() as db:
        assert not db.query(Achievement).filter_by(candidate_id=cid).count()
        assert not db.query(ExternalAccount).filter_by(candidate_id=cid).count()

    # CTFtime link: то же — привязка не создаётся
    h2, _, cid2 = make_candidate()
    fake, _ = fake_api({"teams/": lambda _: (_revoke(cid2), {"id": 77, "name": "X"})[1], "results/": {}, "events/": {}})
    monkeypatch.setattr(common, "get_json", fake)
    assert client.post("/api/achievements/ctftime/link", json={"team_id": 77}, headers=h2).status_code == 409
    with SessionLocal() as db:
        assert not db.query(ExternalAccount).filter_by(candidate_id=cid2).count()


def test_revoke_waits_for_lock():
    # set_external_consent ждёт FOR UPDATE, взятый импортом/синхронизацией, и выполняется после их commit
    _, _, cid = make_candidate()
    done = threading.Event()
    with SessionLocal() as a:
        lock_candidate(a, cid)
        t = threading.Thread(target=lambda: (_revoke(cid), done.set()))
        t.start()
        assert not done.wait(0.3)  # заблокирован
        a.commit()
    assert done.wait(5)
    t.join()


def test_consent_version_set_and_cleared():
    h, _, cid = make_candidate(consent=False)
    client.post("/api/achievements/consent", json={"value": True}, headers=h)
    with SessionLocal() as db:
        c = db.get(Candidate, cid)
        assert c.consent_external and c.consent_external_version == CONSENT_VERSION
    client.post("/api/achievements/consent", json={"value": False}, headers=h)
    with SessionLocal() as db:
        c = db.get(Candidate, cid)
        assert not c.consent_external and c.consent_external_version is None
        assert [e.granted for e in db.query(ConsentEvent).filter_by(candidate_id=cid).order_by(ConsentEvent.id)] == [True, False]


def test_link_rechecks_consent_under_lock(monkeypatch):
    # первая проверка (без блокировки) прошла, под FOR UPDATE согласие уже отозвано → привязка не создаётся
    h, _, cid = make_candidate()
    answers = iter([True, False])
    monkeypatch.setattr(achievements, "consent_ok", lambda c, p: next(answers))
    r = client.post("/api/achievements/codeforces/link", json={"handle": "locked_out"}, headers=h)
    assert r.status_code == 409
    with SessionLocal() as db:
        assert not db.query(ExternalAccount).filter_by(candidate_id=cid).count()


def test_binding_changed_during_fetch(monkeypatch):
    # CF verify: пока шёл запрос, кандидат запросил новый код → 409, подтверждение не записано
    h, _, cid = make_candidate()
    code = client.post("/api/achievements/codeforces/link", json={"handle": "relinker"}, headers=h).json()["code"]

    def relink(db_id):
        with SessionLocal() as db:
            db.query(ExternalAccount).filter_by(candidate_id=db_id).one().verify_code = hash_secret("FSP-NEW1")
            db.commit()

    routes = cf_routes(code)
    info = routes["user.info"]
    routes["user.info"] = lambda _: (relink(cid), info)[1]
    fake, _ = fake_api(routes)
    monkeypatch.setattr(common, "get_json", fake)
    r = client.post("/api/achievements/codeforces/verify", headers=h)
    assert r.status_code == 409 and "Привязка изменилась" in r.json()["detail"]
    with SessionLocal() as db:
        assert db.query(ExternalAccount).filter_by(candidate_id=cid).one().verified_at is None

    # CTFtime refresh: за время запроса команда перепривязана → 409, достижения не пишутся
    h2, _, cid2 = make_candidate()
    old = datetime.now(UTC) - timedelta(days=2)
    with SessionLocal() as db:
        db.add(ExternalAccount(candidate_id=cid2, provider="ctftime", handle="77", verify_code="", fetched_at=old, data={"team_id": 77}))
        db.commit()

    def reteam():
        with SessionLocal() as db:
            acc = db.query(ExternalAccount).filter_by(candidate_id=cid2).one()
            acc.handle, acc.data = "88", {"team_id": 88}
            db.commit()

    fake, _ = fake_api({"teams/": lambda _: (reteam(), {"id": 77, "name": "X"})[1], "results/": {}, "events/": {}})
    monkeypatch.setattr(common, "get_json", fake)
    r = client.post("/api/achievements/ctftime/refresh", headers=h2)
    assert r.status_code == 409 and "Привязка изменилась" in r.json()["detail"]
    with SessionLocal() as db:
        assert not db.query(Achievement).filter_by(candidate_id=cid2).count()


def test_verify_attempts_limit(monkeypatch):
    h, _, _ = make_candidate()
    client.post("/api/achievements/codeforces/link", json={"handle": "guesser"}, headers=h)
    fake, calls = fake_api(cf_routes("нет кода"))
    monkeypatch.setattr(common, "get_json", fake)
    codes = [client.post("/api/achievements/codeforces/verify", headers=h).status_code for _ in range(6)]
    assert codes == [400] * 5 + [429]
    assert len(calls) == 5  # шестая проверка во внешний API не ходит
    r = client.post("/api/achievements/codeforces/verify", headers=h)
    assert r.json()["detail"] == "Слишком много проверок — получите новый код"
    client.post("/api/achievements/codeforces/link", json={"handle": "guesser"}, headers=h)  # новый код — счётчик с нуля
    assert client.post("/api/achievements/codeforces/verify", headers=h).status_code == 400


def test_external_consent_requires_processing():
    h, _, cid = make_candidate(consent=False)
    with SessionLocal() as db:
        db.get(Candidate, cid).consent_152 = False
        db.commit()
    r = client.post("/api/achievements/consent", json={"value": True}, headers=h)
    assert r.status_code == 403 and "согласие на обработку" in r.json()["detail"]
    with SessionLocal() as db:
        c = db.get(Candidate, cid)
        assert not c.consent_external and c.consent_external_version is None
        assert not db.query(ConsentEvent).filter_by(candidate_id=cid).count()


def test_relink_before_attempt_charge(monkeypatch):
    # новый код выдан между чтением аккаунта и списанием попытки → 409, попытка нового кода не списана
    h, _, cid = make_candidate()
    client.post("/api/achievements/codeforces/link", json={"handle": "switcher"}, headers=h)

    def relink(*_):
        with SessionLocal() as db:
            acc = db.query(ExternalAccount).filter_by(candidate_id=cid).one()
            acc.verify_code, acc.verify_attempts = hash_secret("FSP-NEW2"), 0
            db.commit()

    monkeypatch.setattr(achievements, "_cf_owned_by_other", relink)
    fake, calls = fake_api(cf_routes("FSP-NEW2"))
    monkeypatch.setattr(common, "get_json", fake)
    r = client.post("/api/achievements/codeforces/verify", headers=h)
    assert r.status_code == 409 and r.json()["detail"] == "Привязка изменилась — повторите" and calls == []
    with SessionLocal() as db:
        acc = db.query(ExternalAccount).filter_by(candidate_id=cid).one()
        assert acc.verify_attempts == 0 and acc.verified_at is None


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
