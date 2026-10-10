"""Интеграция с ATS: ключи API, входящий API /api/ats/v1, лента событий и демо-приёмник /mock-ats.
События кладём через ats.emit напрямую (эмиссию из роутеров проверяет test_ats_events). Своя БД (fsp_ats)."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fsp:fsp@127.0.0.1:5432/fsp_ats")
os.environ.setdefault("DEMO", "1")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import catalog, config, deps
from app.db import Base, SessionLocal, engine
from app.deps import hash_secret, issue_token
from app.models import ApiKey, Application, AtsLink, AuditLog, Candidate, Company, Invitation, OutboxEvent, User, Vacancy
from app.routers import ats as ats_router, candidate, employer, mock_ats, vacancies
from app.services import ats

NOW = datetime.now(UTC)
INN, INN2, INN3, INN4 = "7704123450", "7707083893", "7736050003", "7743013901"
H: dict[str, dict] = {}  # e — «Ладога», e2 — «Вторая», e3 — заблокированная, e4 — для лимита ключей
ID: dict[str, int] = {}  # company_id: co, co2, co3; candidate: c0, c1; application: app; invitation: inv, inv_open; vacancy: v
KEYS: dict[str, str] = {}
FORK = {"salary_from": 240000, "salary_to": 300000}
VAC = {"title": "Backend в платежи", "spec": "Backend", "track": "Python", "grade": "Middle", "format": "Гибрид", **FORK}


def _cand(i: int, user_id: int) -> Candidate:
    return Candidate(
        public_id=f"T-{i:04d}", user_id=user_id, name=f"Тест Имя{i}", email=f"cand{i}@example.ru", tg=f"@cand{i}", consent_152=True,
        consent_publish=True, consent_version=catalog.CONSENT_VERSION, consent_publish_version=catalog.CONSENT_VERSION, spec="Backend",
        track="Python", grade_claimed="Middle", grade="Middle", theta=1.0, se=0.2, percentile=70, min_salary=200000, formats=["Гибрид"],
        city="Москва", skills_confirmed=["Python"], skills_claimed=["Python"], tested_at=NOW - timedelta(days=60),
    )


def _co(user: User, inn: str, name: str, **kw) -> Company:
    return Company(user_id=user.id, inn=inn, name=name, site_domain=f"{name.lower()}.example", recruiter_name="HR",
                   recruiter_email=f"hr@{name.lower()}.example", verified=True, **kw)


@pytest.fixture(scope="module")
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        cu = [User(email=f"cand{i}@example.ru", role="candidate") for i in range(3)]
        eu = [User(email=f"hr{i}@co{i}.example", role="employer") for i in range(4)]
        db.add_all([*cu, *eu])
        db.flush()
        cands = [_cand(i, u.id) for i, u in enumerate(cu)]
        cos = [_co(eu[0], INN, "Ladoga"), _co(eu[1], INN2, "Vtoraya"), _co(eu[2], INN3, "Blocked", blocked_at=NOW), _co(eu[3], INN4, "Limit")]
        db.add_all([*cands, *cos])
        db.flush()
        v = Vacancy(company_id=cos[0].id, **VAC)
        db.add(v)
        db.flush()
        app = Application(vacancy_id=v.id, candidate_id=cands[0].id, status="sent")
        inv = Invitation(company_id=cos[0].id, candidate_id=cands[1].id, role="Backend (Python)", salary_from=240000, salary_to=300000,
                         format="Гибрид", status="accepted", sent_at=NOW - timedelta(days=2), responded_at=NOW - timedelta(days=1),
                         expires_at=NOW + timedelta(days=5))
        inv_open = Invitation(company_id=cos[0].id, candidate_id=cands[2].id, role="Backend (Go)", salary_from=240000, salary_to=300000,
                              format="Гибрид", status="sent", sent_at=NOW, expires_at=NOW + timedelta(days=7))
        db.add_all([app, inv, inv_open])
        db.commit()
        ID.update(co=cos[0].id, co2=cos[1].id, co3=cos[2].id, c0=cands[0].id, c1=cands[1].id, c2=cands[2].id, app=app.id, inv=inv.id,
                  inv_open=inv_open.id, v=v.id)
        for name, u in zip(("e", "e2", "e3", "e4"), eu):
            H[name] = {"Authorization": "Bearer " + issue_token(db, u)}
    app = FastAPI()
    for r in (deps, candidate, employer, vacancies, ats_router, mock_ats):
        app.include_router(r.router)
    app.include_router(ats_router.keys_router)
    yield TestClient(app)


def _issue(client, scopes, who="e", name="ATS"):
    r = client.post("/api/employer/api-keys", json={"name": name, "scopes": scopes}, headers=H[who])
    assert r.status_code == 200, r.text
    return r.json()


def _kh(key: str) -> dict:
    return {"X-Api-Key": key}


def _all_keys(client) -> str:
    """Ключ «Ладоги» со всеми областями — создаётся один раз."""
    if "all" not in KEYS:
        KEYS["all"] = _issue(client, list(ats.SCOPES))["key"]
    return KEYS["all"]


def _emit(co_id: int, type: str, **payload) -> int:
    with SessionLocal() as db:
        ats.emit(db, co_id, type, **payload)
        db.commit()
        return db.scalar(select(OutboxEvent.id).order_by(OutboxEvent.id.desc()))


def _set_cand(cid: int, **kw) -> None:
    with SessionLocal() as db:
        c = db.get(Candidate, cid)
        for k, v in kw.items():
            setattr(c, k, v)
        db.commit()


def _events(client, key=None, **params) -> dict:
    r = client.get("/api/ats/v1/events", params=params, headers=_kh(key or _all_keys(client)))
    assert r.status_code == 200, r.text
    return r.json()


# ---------- ключи ----------


def test_issue_list_revoke_key(client):
    k = _issue(client, ["applications:read", "applications:read", "invites:read"], name="  Хантфлоу ")
    assert k["key"].startswith("fsp_") and k["prefix"] == k["key"][:12] and k["name"] == "Хантфлоу"
    assert k["scopes"] == ["applications:read", "invites:read"]  # дубли убраны
    with SessionLocal() as db:
        row = db.get(ApiKey, k["id"])
        assert row.key_hash == hash_secret(k["key"]) and k["key"] not in str(row.__dict__)
        log = db.scalars(select(AuditLog).where(AuditLog.action == "api_key_issued")).all()[-1]
        assert log.detail == {"key_id": k["id"], "company_id": ID["co"]}
    listing = client.get("/api/employer/api-keys", headers=H["e"])
    assert listing.status_code == 200
    item = next(i for i in listing.json()["items"] if i["id"] == k["id"])
    assert "key" not in item and "key_hash" not in item and k["key"] not in listing.text and item["revoked_at"] is None
    assert set(listing.json()["scopes"]) == set(ats.SCOPES)
    assert not any(i["id"] == k["id"] for i in client.get("/api/employer/api-keys", headers=H["e2"]).json()["items"])  # чужие не видны

    assert client.delete(f"/api/employer/api-keys/{k['id']}", headers=H["e2"]).status_code == 404
    assert client.delete("/api/employer/api-keys/999999", headers=H["e"]).status_code == 404
    r = client.delete(f"/api/employer/api-keys/{k['id']}", headers=H["e"])
    assert r.status_code == 200 and r.json()["revoked_at"]
    assert client.delete(f"/api/employer/api-keys/{k['id']}", headers=H["e"]).status_code == 200  # повтор — без второго журнала
    with SessionLocal() as db:
        assert len(db.scalars(select(AuditLog).where(AuditLog.action == "api_key_revoked", AuditLog.detail["key_id"].as_integer() == k["id"])).all()) == 1
    assert client.get("/api/ats/v1/events", headers=_kh(k["key"])).status_code == 401  # отозванный не работает


def test_issue_validation_and_limit(client):
    post = lambda body, who="e": client.post("/api/employer/api-keys", json=body, headers=H[who])  # noqa: E731
    assert post({"name": "x", "scopes": ["nope"]}).status_code == 422
    assert post({"name": "x", "scopes": []}).status_code == 422
    assert post({"name": "", "scopes": ["invites:read"]}).status_code == 422
    assert post({"name": "x" * 65, "scopes": ["invites:read"]}).status_code == 422
    assert client.post("/api/employer/api-keys", json={"name": "x", "scopes": ["invites:read"]}).status_code == 401
    assert post({"name": "x", "scopes": ["invites:read"]}, "e3").status_code == 403  # заблокированная компания ключи не выпускает
    assert client.get("/api/employer/api-keys", headers=H["e3"]).status_code == 200  # а смотреть и отзывать может
    for _ in range(ats_router.KEY_LIMIT):
        assert post({"name": "k", "scopes": ["invites:read"]}, "e4").status_code == 200
    assert post({"name": "k", "scopes": ["invites:read"]}, "e4").status_code == 409
    first = client.get("/api/employer/api-keys", headers=H["e4"]).json()["items"][-1]["id"]
    assert client.delete(f"/api/employer/api-keys/{first}", headers=H["e4"]).status_code == 200
    assert post({"name": "k", "scopes": ["invites:read"]}, "e4").status_code == 200  # отзыв освобождает место


# ---------- доступ ----------


def test_key_auth_and_scopes(client):
    url = "/api/ats/v1/vacancies/AUTH-1"
    assert client.put(url, json=VAC).status_code == 401
    r = client.put(url, json=VAC, headers=_kh("fsp_wrong"))
    assert r.status_code == 401 and r.json()["detail"] == "Неверный ключ API"
    reader = _issue(client, ["applications:read"])
    r = client.put(url, json=VAC, headers=_kh(reader["key"]))
    assert r.status_code == 403 and "vacancies:write" in r.json()["detail"]
    assert client.post("/api/ats/v1/applications/1/status", json={"status": "seen"}, headers=_kh(reader["key"])).status_code == 403
    assert client.post("/api/ats/v1/invites/1/feedback", json={"value": "hired"}, headers=_kh(reader["key"])).status_code == 403
    writer = _issue(client, ["vacancies:write"])
    assert client.get("/api/ats/v1/events", headers=_kh(writer["key"])).status_code == 403  # чтение событий — отдельные области
    with SessionLocal() as db:
        assert db.get(ApiKey, writer["id"]).last_used_at is None
    assert client.put(url, json=VAC, headers=_kh(writer["key"])).status_code == 200
    with SessionLocal() as db:
        assert db.get(ApiKey, writer["id"]).last_used_at is not None
    # сессия кабинета ключом API не является, и наоборот
    assert client.put(url, json=VAC, headers=H["e"]).status_code == 401
    assert client.get("/api/employer/api-keys", headers=_kh(writer["key"])).status_code == 401


def test_blocked_company_cannot_write_but_can_read(client):
    with SessionLocal() as db:
        k = ApiKey(company_id=ID["co3"], name="b", key_hash=hash_secret("fsp_blocked"), prefix="fsp_blocked", scopes=list(ats.SCOPES))
        db.add(k)
        db.commit()
    h = _kh("fsp_blocked")
    r = client.put("/api/ats/v1/vacancies/B-1", json=VAC, headers=h)
    assert r.status_code == 403 and r.json()["detail"] == deps.BLOCKED
    assert client.post("/api/ats/v1/applications/1/status", json={"status": "seen"}, headers=h).status_code == 403
    assert client.get("/api/ats/v1/events", headers=h).status_code == 200


# ---------- вакансии ----------


def test_put_vacancy_creates_then_edits(client):
    h, url = _kh(_all_keys(client)), "/api/ats/v1/vacancies/ATS-1001"
    r = client.put(url, json=VAC, headers=h)
    assert r.status_code == 200, r.text
    first = r.json()
    assert first["external_id"] == "ATS-1001" and first["warnings"] is not None and first["company"]["id"] == ID["co"]
    r = client.put(url, json={**VAC, "title": "Backend-разработчик", "salary_to": 320000, "must": ["Python"]}, headers=h)
    assert r.status_code == 200
    assert r.json()["id"] == first["id"] and r.json()["title"] == "Backend-разработчик" and r.json()["to"] == 320000
    with SessionLocal() as db:
        assert len(db.scalars(select(Vacancy).where(Vacancy.title.like("Backend-разработчик"))).all()) == 1
        assert len(db.scalars(select(AtsLink).where(AtsLink.external_id == "ATS-1001")).all()) == 1
    # PUT — полная замена: необязательные поля, которых нет в теле, сбрасываются
    r = client.put(url, json={**VAC, "title": "Backend-разработчик"}, headers=h)
    assert r.json()["must"] == []
    # в кабинете вакансия видна
    mine = client.get("/api/vacancies/mine", headers=H["e"]).json()["items"]
    assert first["id"] in [v["id"] for v in mine]


def test_put_vacancy_validation(client):
    h = _kh(_all_keys(client))
    new, old = "/api/ats/v1/vacancies/BAD-NEW", "/api/ats/v1/vacancies/ATS-1001"
    for url in (new, old):  # и при создании, и при правке
        r = client.put(url, json={**VAC, "salary_from": None}, headers=h)
        assert r.status_code == 422 and "обе границы" in str(r.json()["detail"])
        assert client.put(url, json={**VAC, "salary_from": 300000, "salary_to": 240000}, headers=h).status_code == 422
        assert client.put(url, json={**VAC, "spec": "Нет такой"}, headers=h).status_code == 422
    with SessionLocal() as db:
        assert db.scalar(select(AtsLink).where(AtsLink.external_id == "BAD-NEW")) is None  # неудачный PUT связи не оставил
        assert db.scalar(select(Vacancy).where(Vacancy.salary_from.is_(None))) is None
    assert client.put("/api/ats/v1/vacancies/" + "x" * 129, json=VAC, headers=h).status_code == 422
    assert client.put("/api/ats/v1/vacancies/x", json={"title": "Нет полей"}, headers=h).status_code == 422


def test_put_vacancy_races_and_deleted(client):
    h, url = _kh(_all_keys(client)), "/api/ats/v1/vacancies/RACE-1"
    with ThreadPoolExecutor(2) as ex:
        codes = [f.result().status_code for f in [ex.submit(client.put, url, json=VAC, headers=h) for _ in range(2)]]
    assert codes == [200, 200]
    with SessionLocal() as db:
        link = db.scalar(select(AtsLink).where(AtsLink.external_id == "RACE-1"))
        assert len(db.scalars(select(Vacancy).where(Vacancy.id == link.internal_id)).all()) == 1
        total = len(db.scalars(select(AtsLink).where(AtsLink.external_id == "RACE-1")).all())
        old_id = link.internal_id
        db.delete(db.get(Vacancy, old_id))
        db.commit()
    assert total == 1
    r = client.put(url, json=VAC, headers=h)  # связанную вакансию удалили — создаётся заново, связь переезжает
    assert r.status_code == 200 and r.json()["id"] != old_id
    with SessionLocal() as db:
        assert db.scalar(select(AtsLink.internal_id).where(AtsLink.external_id == "RACE-1")) == r.json()["id"]


def test_put_vacancy_limit(client, monkeypatch):
    monkeypatch.setattr(catalog, "VACANCY_LIMIT_VERIFIED", 1)
    r = client.put("/api/ats/v1/vacancies/OVER-LIMIT", json=VAC, headers=_kh(_all_keys(client)))
    assert r.status_code == 409 and "лимит" in r.json()["detail"]
    with SessionLocal() as db:
        assert db.scalar(select(AtsLink).where(AtsLink.external_id == "OVER-LIMIT")) is None


def test_close_and_extend(client):
    h = _kh(_all_keys(client))
    for action in ("close", "extend"):
        assert client.post(f"/api/ats/v1/vacancies/UNKNOWN/{action}", headers=h).status_code == 404
    assert client.post("/api/ats/v1/vacancies/ATS-1001/extend", headers=h).status_code == 200
    r = client.post("/api/ats/v1/vacancies/ATS-1001/close", headers=h)
    assert r.status_code == 200 and r.json()["status"] == "closed"
    assert client.post("/api/ats/v1/vacancies/ATS-1001/extend", headers=h).status_code == 409  # закрытую не продлить, как в кабинете
    # чужой external_id у другой компании связи не имеет
    other = _issue(client, ["vacancies:write"], who="e2")["key"]
    assert client.post("/api/ats/v1/vacancies/ATS-1001/close", headers=_kh(other)).status_code == 404


# ---------- отклики и приглашения ----------


def test_application_status_and_idempotency(client):
    h, url = _kh(_all_keys(client)), f"/api/ats/v1/applications/{ID['app']}/status"
    assert client.post(url, json={"status": "sent"}, headers=h).status_code == 422
    assert client.post(url, json={"status": "declined"}, headers=h).status_code == 422  # без причины
    assert client.post("/api/ats/v1/applications/999999/status", json={"status": "seen"}, headers=h).status_code == 404
    r = client.post(url, json={"status": "seen"}, headers=h)
    assert r.status_code == 200 and r.json()["status"] == "seen" and r.json()["contacts"] is None
    assert client.post(url, json={"status": "seen"}, headers=h).json()["status"] == "seen"  # повтор — 200
    other = _issue(client, ["applications:write"], who="e2")["key"]
    assert client.post(url, json={"status": "seen"}, headers=_kh(other)).status_code == 404  # чужой отклик

    r = client.post(url, json={"status": "accepted"}, headers=h)
    assert r.status_code == 200 and r.json()["contacts"]["email"] == "cand0@example.ru"  # как в кабинете после принятия
    assert client.post(url, json={"status": "accepted"}, headers=h).status_code == 200
    assert client.post(url, json={"status": "declined", "reason": "salary"}, headers=h).status_code == 409
    assert client.post(url, json={"status": "seen"}, headers=h).status_code == 409
    with SessionLocal() as db:
        assert len(db.scalars(select(AuditLog).where(AuditLog.action == "contacts_revealed", AuditLog.detail["application_id"].as_integer() == ID["app"])).all()) == 1


def test_invite_feedback(client):
    h = _kh(_all_keys(client))
    url = lambda i: f"/api/ats/v1/invites/{i}/feedback"  # noqa: E731
    assert client.post(url(ID["inv"]), json={"value": "wat"}, headers=h).status_code == 422
    assert client.post(url(999999), json={"value": "hired"}, headers=h).status_code == 404
    assert client.post(url(ID["inv_open"]), json={"value": "hired"}, headers=h).status_code == 409  # приглашение не принято
    r = client.post(url(ID["inv"]), json={"value": "hired"}, headers=h)
    assert r.status_code == 200 and r.json()["feedback"] == "hired"
    assert client.post(url(ID["inv"]), json={"value": "hired"}, headers=h).status_code == 200  # повтор той же отметки
    assert client.post(url(ID["inv"]), json={"value": "confirmed"}, headers=h).status_code == 409
    other = _issue(client, ["invites:write"], who="e2")["key"]
    assert client.post(url(ID["inv"]), json={"value": "hired"}, headers=_kh(other)).status_code == 404
    with SessionLocal() as db:
        assert db.get(Candidate, ID["c1"]).employer_confirmed == 1  # повтор счётчик не удвоил


def test_invite_feedback_race(client):
    """Две параллельные отметки по одному приглашению: employer_confirmed растёт один раз, второй запрос — 409."""
    cid = _new_cand(30)
    with SessionLocal() as db:
        inv = Invitation(company_id=ID["co"], candidate_id=cid, role="Гонка", salary_from=240000, salary_to=300000, format="Гибрид",
                         status="accepted", sent_at=NOW, expires_at=NOW + timedelta(days=7))
        db.add(inv)
        db.commit()
        inv_id = inv.id
    h = _kh(_all_keys(client))
    call = lambda: client.post(f"/api/employer/invites/{inv_id}/feedback", json={"value": "hired"}, headers=H["e"])  # noqa: E731
    with ThreadPoolExecutor(2) as ex:
        codes = sorted(f.result().status_code for f in [ex.submit(call) for _ in range(2)])
    assert codes == [200, 409]
    with SessionLocal() as db:
        assert db.get(Candidate, cid).employer_confirmed == 1
    assert client.post(f"/api/ats/v1/invites/{inv_id}/feedback", json={"value": "hired"}, headers=h).status_code == 200  # повтор через API


# ---------- лента событий ----------


def test_events_cursor_and_filters(client):
    base = _events(client)["next"]
    a = _emit(ID["co"], "application.created", application_id=ID["app"], vacancy_id=ID["v"], status="sent")
    b = _emit(ID["co"], "invitation.seen", invitation_id=ID["inv_open"], status="seen", reason=None)
    c = _emit(ID["co"], "candidate.access_revoked", public_id="T-0001", why="consent")
    d = _emit(ID["co2"], "invitation.seen", invitation_id=ID["inv_open"], status="seen", reason=None)
    j = _events(client, after=base)
    assert [e["id"] for e in j["items"]] == [a, b, c] and j["next"] == c  # чужая компания не видна, порядок возрастающий
    assert [e["type"] for e in j["items"]] == ["application.created", "invitation.seen", "candidate.access_revoked"]
    assert j["items"][0]["at"]
    page = _events(client, after=base, limit=2)
    assert [e["id"] for e in page["items"]] == [a, b] and page["next"] == b
    assert _events(client, after=b, limit=2)["items"][0]["id"] == c
    empty = _events(client, after=c)
    assert empty == {"items": [], "next": c}

    apps_only = _issue(client, ["applications:read"])["key"]
    types = {e["type"] for e in _events(client, apps_only, after=base)["items"]}
    assert types == {"application.created", "candidate.access_revoked"}  # отзыв доступа видит любой ключ чтения
    invs_only = _issue(client, ["invites:read"])["key"]
    assert {e["type"] for e in _events(client, invs_only, after=base)["items"]} == {"invitation.seen", "candidate.access_revoked"}
    other = _issue(client, ["applications:read", "invites:read"], who="e2")["key"]
    assert [e["id"] for e in _events(client, other, after=base)["items"]] == [d]  # у компании 2 только её событие
    for bad in ({"limit": 0}, {"limit": 501}, {"after": -1}):
        assert client.get("/api/ats/v1/events", params=bad, headers=_kh(_all_keys(client))).status_code == 422


def test_events_application_privacy(client):
    ev = _emit(ID["co"], "application.created", application_id=ID["app"], vacancy_id=ID["v"], status="sent")
    with SessionLocal() as db:  # привязываем вакансию заявки к external_id, чтобы он попал в событие
        db.add(AtsLink(company_id=ID["co"], entity="vacancy", external_id="APP-VAC", internal_id=ID["v"]))
        db.commit()
    item = lambda: next(e for e in _events(client, after=ev - 1)["items"] if e["id"] == ev)["data"]  # noqa: E731

    # отклик принят в тесте выше: контакты видны, как в кабинете
    d = item()
    assert d["vacancy"] == {"id": ID["v"], "title": VAC["title"], "external_id": "APP-VAC"}
    assert d["candidate"]["public_id"] == "T-0000" and "name" not in d["candidate"] and "email" not in d["candidate"]
    assert d["contacts"] == {"name": "Тест Имя0", "email": "cand0@example.ru", "tg": "@cand0"}
    assert d["application_id"] == ID["app"] and d["status"] == "sent"

    with SessionLocal() as db:  # откатываем отклик до «sent»: до принятия контактов в ленте нет
        db.get(Application, ID["app"]).status = "sent"
        db.commit()
    d = item()
    assert d["contacts"] is None and d["candidate"]["public_id"] == "T-0000"
    with SessionLocal() as db:
        db.get(Application, ID["app"]).status = "accepted"
        db.commit()
    assert item()["contacts"]["email"] == "cand0@example.ru"

    _set_cand(ID["c0"], hidden_from=[INN])  # кандидат скрыл профиль от компании
    d = item()
    assert d["candidate"] is None and d["contacts"] is None
    _set_cand(ID["c0"], hidden_from=[])
    _set_cand(ID["c0"], consent_152=False)  # отозвал согласие на обработку
    d = item()
    assert d["candidate"] is None and d["contacts"] is None
    _set_cand(ID["c0"], consent_152=True)
    assert item()["contacts"] is not None

    gone = _emit(ID["co"], "application.withdrawn", application_id=999999, vacancy_id=999999, status="withdrawn")
    d = next(e for e in _events(client, after=gone - 1)["items"])["data"]  # отклика и вакансии нет — событие всё равно отдаётся
    assert d["candidate"] is None and d["contacts"] is None and d["vacancy"] == {"id": 999999, "title": None, "external_id": None}


def test_events_invitation_privacy(client):
    ev = _emit(ID["co"], "invitation.accepted", invitation_id=ID["inv"], status="accepted", reason=None)
    item = lambda: next(e for e in _events(client, after=ev - 1)["items"] if e["id"] == ev)["data"]  # noqa: E731
    d = item()
    assert d["invitation"] == {"id": ID["inv"], "role": "Backend (Python)", "salary_from": 240000, "salary_to": 300000,
                               "status": "accepted", "feedback": "hired"}
    assert d["candidate"] == {"public_id": "T-0001"}  # без карточки: её отдаёт /api/employer/candidates/{public_id} по своим правилам
    assert d["contacts"] == {"name": "Тест Имя1", "email": "cand1@example.ru", "tg": "@cand1"}

    _set_cand(ID["c1"], hidden_from=[INN])
    d = item()
    assert d["contacts"] is None and d["candidate"] == {"public_id": "T-0001"}  # только id, без карточки
    _set_cand(ID["c1"], hidden_from=[], consent_152=False)
    d = item()
    assert d["contacts"] is None and d["candidate"] == {"public_id": "T-0001"}
    _set_cand(ID["c1"], consent_152=True)
    with SessionLocal() as db:  # блок компании закрывает контакты, как чат
        db.get(Company, ID["co"]).blocked_at = NOW
        db.commit()
    assert item()["contacts"] is None
    with SessionLocal() as db:
        db.get(Company, ID["co"]).blocked_at = None
        db.commit()

    # приглашение не принято — контактов нет; удалённое приглашение — только payload
    ev2 = _emit(ID["co"], "invitation.seen", invitation_id=ID["inv_open"], status="seen", reason=None)
    d = next(e for e in _events(client, after=ev2 - 1)["items"])["data"]
    assert d["contacts"] is None and d["invitation"]["status"] == "sent"
    ev3 = _emit(ID["co"], "invitation.expired", invitation_id=999999, status="expired", reason=None)
    r = client.get("/api/ats/v1/events", params={"after": ev3 - 1}, headers=_kh(_all_keys(client)))
    d = r.json()["items"][0]["data"]
    assert d == {"invitation_id": 999999, "status": "expired", "reason": None, "invitation": None, "candidate": None, "contacts": None}
    assert "Тест" not in r.text and "example.ru" not in r.text


def test_events_deleted_candidate_has_no_pd(client):
    with SessionLocal() as db:
        u = User(email="gone@example.ru", role="candidate")
        db.add(u)
        db.flush()
        c = _cand(9, u.id)
        db.add(c)
        db.flush()
        inv = Invitation(company_id=ID["co"], candidate_id=c.id, role="Удалённый", salary_from=240000, salary_to=300000, format="Гибрид",
                         status="accepted", sent_at=NOW, expires_at=NOW + timedelta(days=7))
        db.add(inv)
        db.commit()
        inv_id, cid = inv.id, c.id
    ev = _emit(ID["co"], "invitation.accepted", invitation_id=inv_id, status="accepted", reason=None)
    emit_revoked = _emit(ID["co"], "candidate.access_revoked", public_id="T-0009", why="deleted")
    with SessionLocal() as db:
        db.delete(db.get(Candidate, cid))  # приглашения удаляются каскадом вместе с кандидатом
        db.commit()
    r = client.get("/api/ats/v1/events", params={"after": ev - 1}, headers=_kh(_all_keys(client)))
    items = r.json()["items"]
    assert [e["id"] for e in items] == [ev, emit_revoked]
    assert items[0]["data"]["candidate"] is None and items[0]["data"]["contacts"] is None
    assert items[1]["data"] == {"public_id": "T-0009", "why": "deleted"}
    assert "Удалённый" not in r.text and "gone@example.ru" not in r.text and "Тест" not in r.text


def _new_cand(n: int, **kw) -> int:
    with SessionLocal() as db:
        u = User(email=f"extra{n}@example.ru", role="candidate")
        db.add(u)
        db.flush()
        c = _cand(n, u.id)
        for k, v in kw.items():
            setattr(c, k, v)
        db.add(c)
        db.commit()
        return c.id


def _new_app(cid: int, status: str) -> int:
    with SessionLocal() as db:
        a = Application(vacancy_id=ID["v"], candidate_id=cid, status=status)
        db.add(a)
        db.commit()
        return a.id


def test_key_name_blank(client):
    r = client.post("/api/employer/api-keys", json={"name": "   ", "scopes": ["invites:read"]}, headers=H["e"])
    assert r.status_code == 422


def test_close_works_for_blocked_company(client):
    with SessionLocal() as db:
        v = Vacancy(company_id=ID["co3"], **VAC)
        db.add(v)
        db.flush()
        db.add_all([AtsLink(company_id=ID["co3"], entity="vacancy", external_id="B-CLOSE", internal_id=v.id),
                    ApiKey(company_id=ID["co3"], name="c", key_hash=hash_secret("fsp_blocked_close"), prefix="fsp_blocked_", scopes=["vacancies:write"])])
        db.commit()
    h = _kh("fsp_blocked_close")
    assert client.post("/api/ats/v1/vacancies/B-CLOSE/extend", headers=h).status_code == 403  # продлевать нельзя
    r = client.post("/api/ats/v1/vacancies/B-CLOSE/close", headers=h)  # закрыть — можно: сужает показ
    assert r.status_code == 200 and r.json()["status"] == "closed"


def test_decline_idempotency_checks_reason(client):
    h = _kh(_all_keys(client))
    r1, r2 = list(catalog.DECLINE_REASONS)[:2]
    aid = _new_app(_new_cand(20), "sent")
    url = f"/api/ats/v1/applications/{aid}/status"
    assert client.post(url, json={"status": "declined", "reason": r1}, headers=h).status_code == 200
    assert client.post(url, json={"status": "declined", "reason": r1}, headers=h).status_code == 200  # ретрай
    assert client.post(url, json={"status": "declined", "reason": r2}, headers=h).status_code == 409  # другая причина
    assert client.post(url, json={"status": "declined", "reason": "bad"}, headers=h).status_code == 422
    assert client.post(url, json={"status": "declined"}, headers=h).status_code == 422


def test_feed_logs_contacts_reveal_once(client):
    # отклик принят, пока согласие недействительно: контактов нет; после повторного согласия лента раскрывает их с записью в журнале
    cid = _new_cand(21, consent_152=False)
    aid = _new_app(cid, "accepted")
    ev = _emit(ID["co"], "application.created", application_id=aid, vacancy_id=ID["v"], status="sent")
    item = lambda: next(e for e in _events(client, after=ev - 1)["items"] if e["id"] == ev)["data"]  # noqa: E731
    audit = lambda: len(_audit(aid))  # noqa: E731
    assert item()["contacts"] is None and audit() == 0
    _set_cand(cid, consent_152=True)
    assert item()["contacts"]["email"] == "cand21@example.ru" and audit() == 1
    assert item()["contacts"] is not None and audit() == 1  # повторная выдача записей не добавляет


def test_status_retry_logs_reveal(client):
    cid = _new_cand(22, consent_152=False)
    aid = _new_app(cid, "accepted")
    url = f"/api/ats/v1/applications/{aid}/status"
    h = _kh(_all_keys(client))
    assert client.post(url, json={"status": "accepted"}, headers=h).json()["contacts"] is None
    _set_cand(cid, consent_152=True)
    assert client.post(url, json={"status": "accepted"}, headers=h).json()["contacts"]["email"] == "cand22@example.ru"
    assert len(_audit(aid)) == 1


def _audit(app_id: int) -> list:
    with SessionLocal() as db:
        return db.scalars(select(AuditLog).where(AuditLog.action == "contacts_revealed", AuditLog.detail["application_id"].as_integer() == app_id)).all()


def test_events_expire_invitations(client):
    cid = _new_cand(23)
    with SessionLocal() as db:
        inv = Invitation(company_id=ID["co"], candidate_id=cid, role="Backend (Python)", salary_from=240000, salary_to=300000, format="Гибрид",
                         status="sent", sent_at=NOW - timedelta(days=9), expires_at=NOW - timedelta(days=1))
        db.add(inv)
        db.commit()
        iid = inv.id
    items = _events(client)["items"]
    assert [e for e in items if e["type"] == "invitation.expired" and e["data"]["invitation_id"] == iid]  # лента сама отмечает истечение


def test_meta_exposes_ats_mock():
    from app.main import meta
    assert meta()["ats_mock"] is config.ATS_MOCK


# ---------- демо-приёмник ----------


def test_mock_ats_page(client, monkeypatch):
    monkeypatch.setattr(config, "ATS_MOCK", True)
    r = client.get("/mock-ats")
    assert r.status_code == 200 and "Mock ATS" in r.text and "не настоящая ATS" in r.text
    assert "/api/ats/v1" in r.text and "sessionStorage" in r.text and "'salary'" in r.text and "__REASON__" not in r.text
    assert "src=" not in r.text and "http://" not in r.text and "https://" not in r.text  # без внешних ресурсов
    assert "dataset.eventType" in r.text and "dataset.applicationId" in r.text and "revoked.delete(pid)" in r.text  # атрибуты для e2e, возврат доступа
    monkeypatch.setattr(config, "ATS_MOCK", False)
    assert client.get("/mock-ats").status_code == 404
