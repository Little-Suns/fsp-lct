"""Сценарий демо целиком: потребность → анонимная подборка → вилка → приглашение → принятие → контакты → отметка.
Плюс ёмкость кандидата, квота, истечение, скрытие. Своя БД (fsp_flows), LLM выключена — работают правила."""

import os
import re
from datetime import UTC, datetime, timedelta

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fsp:fsp@localhost:5432/fsp_flows")
os.environ["LLM_BASE_URL"] = ""
os.environ.setdefault("DEMO", "1")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config, deps
from app.db import Base, SessionLocal, engine
from app.models import Achievement, Candidate, Company, ExternalAccount, Invitation, Lottery, User
from app.routers import candidate, employer

config.LLM_BASE_URL = ""
NOW = datetime.now(UTC)
INN = "7704123450"
NEED_TEXT = "Ищем бэкендера на Python в команду платежей. Нужен опыт с PostgreSQL и Kafka, хорошо бы Kubernetes. Уровень — мидл, до 300 на руки. Гибрид, Москва."
COMP = [{"n": "Ревью кода", "t": 1.42, "se": 0.25}, {"n": "Алгоритмы", "t": 1.6, "se": 0.2}]


def _cand(pid, **kw) -> Candidate:
    base = dict(
        public_id=pid, name=f"Имя {pid}", email=f"{pid.lower()}@example.ru", tg=None, consent_152=True, spec="Backend", track="Python",
        grade_claimed="Middle", grade="Middle", theta=1.0, se=0.2, percentile=70, competencies=COMP, min_salary=230000,
        formats=["Гибрид"], city="Москва", skills_confirmed=["Python", "PostgreSQL", "Kafka"], skills_claimed=["Python", "PostgreSQL", "Kafka"],
        tested_at=NOW - timedelta(days=60),
    )
    return Candidate(**{**base, **kw})


@pytest.fixture(scope="module")
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        cu, eu, nu = User(email="d.orlov@example.ru", role="candidate", token="cand"), User(email="m.kovaleva@ladoga-pay.example", role="employer", token="emp"), User(email="new@example.ru", role="candidate", token="new")
        fake = User(email="hr.ladoga@gmail.com", role="employer", token="fake")  # почта входа не на домене компании
        db.add_all([cu, eu, nu, fake])
        db.flush()
        a = _cand(
            "A-1042", user_id=cu.id, name="Дмитрий Орлов", email="d.orlov@example.ru", tg="@dorlov_dev", theta=1.12, se=0.18, percentile=78,
            formats=["Гибрид", "Удалённо"], skills_confirmed=["Python", "PostgreSQL", "Kafka", "asyncio"], skills_claimed=["Python", "PostgreSQL", "Kafka", "Kubernetes"],
        )
        a.achievements = [Achievement(source="fsp", title="Финал Кубка России ФСП 2025", weight=0.8, verified=True)]
        a.accounts = [ExternalAccount(provider="codeforces", handle="dorlov", verify_code="FSP-7Q2K", verified_at=NOW, rating=1912, rank="Candidate Master")]
        busy = _cand("B-2318", theta=1.31, se=0.16, percentile=85, min_salary=280000, formats=["Удалённо"], skills_confirmed=["Python", "PostgreSQL", "Kafka", "Kubernetes"])
        db.add_all([
            a, busy,
            _cand("J-0003", grade="Junior", theta=0.1, percentile=60),
            _cand("Z-0001", status="off"),
            _cand("H-0002", hidden_from=[INN]),
            _cand("U-0004", grade=None, theta=None, se=None),
            _cand("G-0005", track="Go", spec="Backend"),
        ])
        db.add(Company(user_id=eu.id, inn=INN, name="Ладога Пэй", about="Финтех", site_domain="ladoga-pay.example", recruiter_name="Мария Ковалёва",
                       recruiter_email="m.kovaleva@ladoga-pay.example", recruiter_tg="@mkovaleva", verified=True))
        db.flush()
        for i in range(4):  # у B-2318 ёмкость заполнена чужими приглашениями
            co = Company(inn=f"10000000{i:02d}", name=f"Другая {i}", recruiter_name="R", recruiter_email="r@x.ru")
            db.add(co)
            db.flush()
            db.add(Invitation(company_id=co.id, candidate_id=busy.id, role="Backend", salary_from=280000, salary_to=330000, format="Удалённо", expires_at=NOW + timedelta(days=5)))
        db.commit()
    app = FastAPI()
    for r in (deps, candidate, employer):
        app.include_router(r.router)
    yield TestClient(app)


E = {"Authorization": "Bearer emp"}
C = {"Authorization": "Bearer cand"}


def test_demo_flow(client):
    # 1. разбор потребности
    p = client.post("/api/employer/needs/parse", json={"text": NEED_TEXT}, headers=E).json()
    assert (p["spec"], p["track"], p["grade"], p["must"], p["nice"]) == ("Backend", "Python", "Middle", ["Python", "PostgreSQL", "Kafka"], ["Kubernetes"])
    assert (p["from"], p["to"], p["format"], p["city"]) == (240000, 300000, "Гибрид", "Москва")
    assert p["category"]["count"] == 3 and p["market"]["p25"] == 210000  # A, B, H: счётчик категории не учитывает скрытие
    need = client.post("/api/employer/needs", json={**p, "text": NEED_TEXT}, headers=E).json()

    # 2. подборка: анонимно, по взаимному интересу
    r = client.get(f"/api/employer/needs/{need['id']}/picks", headers=E)
    assert r.status_code == 200
    assert "Дмитрий" not in r.text and "d.orlov" not in r.text and "dorlov_dev" not in r.text
    picks = r.json()
    ids = [c["id"] for c in picks["items"]]
    assert ids[0] == "A-1042" and set(ids) == {"A-1042", "B-2318", "J-0003", "G-0005"}, ids
    a = picks["items"][0]
    assert a["fsp"] and a["cf"] == 1912 and a["gaps"] == ["Kubernetes не подтверждён тестом"] and a["fmtOk"] and a["theta"] == "1.12 ± 0.18"
    assert abs(a["score"] - a["match"] * (0.5 + 0.5 * a["accept"]) * 1.0) < 0.01
    b = next(c for c in picks["items"] if c["id"] == "B-2318")
    assert b["load"] == 4 and b["busy"] and not b["fmtOk"] and b["score"] < a["score"]
    assert picks["categories"][0] == {**picks["categories"][0], "track": "Python", "grade": "Middle", "current": True}
    assert picks["quota"]["used"] == 0 and picks["quota"]["max"] == 10
    free = client.get(f"/api/employer/needs/{need['id']}/picks?filters=free,fmt", headers=E).json()
    assert "B-2318" not in [c["id"] for c in free["items"]]
    assert [c["id"] for c in client.get(f"/api/employer/needs/{need['id']}/picks?filters=fsp", headers=E).json()["items"]] == ["A-1042"]
    assert client.get(f"/api/employer/needs/{need['id']}/picks?filters=bad", headers=E).status_code == 422
    embed = client.get(f"/api/employer/needs/{need['id']}/picks?variant=embed", headers=E).json()
    assert all(c["accept"] == 1.0 for c in embed["items"])

    # 3. карточка кандидата
    card = client.get(f"/api/employer/candidates/A-1042?need_id={need['id']}", headers=E)
    assert card.status_code == 200 and "Дмитрий" not in card.text
    assert card.json()["breakdown"]["load_penalty"] == 1.0 and card.json()["competencies"]
    for hidden in ("Z-0001", "H-0002", "U-0004"):
        assert client.get(f"/api/employer/candidates/{hidden}", headers=E).status_code == 404

    # 4. вилка: ошибки блокируют, предупреждения нет
    inv = {"candidate_id": "A-1042", "need_id": need["id"], "role": "Backend-разработчик (Python), команда платежей", "format": "Гибрид", "description": "Платежи"}
    bad = client.post("/api/employer/invites", json={**inv, "salary_from": 150000, "salary_to": 300000}, headers=E)
    assert bad.status_code == 422 and len(bad.json()["detail"]["errors"]) == 2
    assert client.post("/api/employer/invites", json={**inv, "salary_to": 300000}, headers=E).status_code == 422
    ok = client.post("/api/employer/invites", json={**inv, "salary_from": 240000, "salary_to": 300000}, headers=E)
    assert ok.status_code == 200 and ok.json()["warnings"] == [] and ok.json()["quota"]["used"] == 1
    iid = ok.json()["invite"]["id"]
    assert client.post("/api/employer/invites", json={**inv, "salary_from": 240000, "salary_to": 300000}, headers=E).status_code == 409

    # 5. кандидат видит приглашение; открытие → «просмотрено»
    lst = client.get("/api/candidate/invites", headers=C).json()
    assert lst["open"] == 1 and lst["items"][0]["status"] == "new" and lst["items"][0]["due"] == 7 and not lst["items"][0]["below_min"]
    d = client.get(f"/api/candidate/invites/{iid}", headers=C).json()
    assert d["status"] == "seen" and d["why"].startswith("Совпадение стека Python, PostgreSQL, Kafka") and "recruiter" not in d
    row = client.get("/api/employer/pipeline", headers=E).json()["items"][0]
    assert row["status"] == "seen" and row["contact"] is None

    # 6. отказ без причины нельзя; принятие открывает контакты обеим сторонам
    assert client.post(f"/api/candidate/invites/{iid}/decline", json={"reason": "дорого"}, headers=C).status_code == 422
    acc = client.post(f"/api/candidate/invites/{iid}/accept", headers=C).json()
    assert acc["status"] == "accepted" and acc["recruiter"]["email"] == "m.kovaleva@ladoga-pay.example"
    assert client.post(f"/api/candidate/invites/{iid}/accept", headers=C).status_code == 409
    row = client.get("/api/employer/pipeline", headers=E).json()["items"][0]
    assert row["status"] == "ok" and row["contact"]["text"] == "Дмитрий Орлов · d.orlov@example.ru · @dorlov_dev"

    # 7. отметка после собеседования
    assert client.post(f"/api/employer/invites/{iid}/feedback", json={"value": "hired"}, headers=E).json()["fb"] == "наняли"
    assert client.post(f"/api/employer/invites/{iid}/feedback", json={"value": "confirmed"}, headers=E).status_code == 409
    me = client.get("/api/candidate/me", headers=C).json()
    assert me["employer_confirmed"] == 1 and me["name"] == "Дмитрий Орлов" and me["cf"]["rating"] == 1912 and me["invites_open"] == 0


def test_capacity_quota_expiry(client):
    need_id = client.get("/api/employer/needs", headers=E).json()[0]["id"]
    inv = {"need_id": need_id, "role": "Backend (Python)", "salary_from": 240000, "salary_to": 270000, "format": "Гибрид"}
    # ёмкость: у B-2318 4 открытых приглашения — жёсткий отказ
    r = client.post("/api/employer/invites", json={**inv, "candidate_id": "B-2318"}, headers=E)
    assert r.status_code == 409 and r.json()["detail"] == "У кандидата максимум открытых приглашений"
    # приглашение по жребию: только выбранным в своей лотерее
    with SessionLocal() as db:
        own = db.query(Company).filter(Company.inn == INN).one()
        lots = [Lottery(company_id=co_id, need_id=None, threshold={}, pool_ids=["G-0005", "J-0003"], draw_count=1, seed_hash="h", commitment="c", drawn_ids=["J-0003"])
                for co_id in (own.id, own.id + 1)]
        db.add_all(lots)
        db.commit()
        own_lot, foreign_lot = lots[0].id, lots[1].id
    lot_inv = {**inv, "need_id": None, "salary_from": 210000}
    # потребность приглашения обязана совпасть с потребностью лотереи (здесь — без потребности)
    assert client.post("/api/employer/invites", json={**lot_inv, "need_id": need_id, "candidate_id": "J-0003", "lottery_id": own_lot}, headers=E).status_code == 422
    assert client.post("/api/employer/invites", json={**lot_inv, "candidate_id": "J-0003", "lottery_id": foreign_lot}, headers=E).status_code == 404
    assert client.post("/api/employer/invites", json={**lot_inv, "candidate_id": "G-0005", "lottery_id": own_lot}, headers=E).status_code == 422
    r = client.post("/api/employer/invites", json={**lot_inv, "candidate_id": "J-0003", "lottery_id": own_lot}, headers=E).json()
    assert r["invite"]["lottery_id"] == own_lot
    # квота
    with SessionLocal() as db:
        db.query(Company).filter(Company.inn == INN).update({"quota_max": 2})
        db.commit()
    q = client.get("/api/employer/quota", headers=E).json()
    assert (q["used"], q["max"], q["accepted_share"]) == (2, 2, 1.0) and q["next_max"] == 12
    assert client.post("/api/employer/invites", json={**lot_inv, "candidate_id": "G-0005"}, headers=E).status_code == 429
    # истечение: просроченное приглашение лениво закрывается при чтении
    with SessionLocal() as db:
        db.query(Invitation).filter(Invitation.status == "sent", Invitation.role == "Backend (Python)").update({"expires_at": NOW - timedelta(hours=1)})
        db.commit()
    rows = {r["cid"]: r for r in client.get("/api/employer/pipeline", headers=E).json()["items"]}
    assert rows["J-0003"]["status"] == "exp" and "B-2318" not in rows


def test_unverified_company(client):
    F = {"Authorization": "Bearer fake"}
    co = {"inn": "7707083893", "name": "Фейк", "site_domain": "ladoga2.example", "recruiter_name": "HR", "recruiter_email": "hr@ladoga2.example"}
    r = client.post("/api/employer/company", json=co, headers=F).json()
    assert r["verified"] is False  # домен проверяется по почте входа (gmail), а не по recruiter_email из формы
    assert client.post("/api/employer/company", json={**co, "inn": "500100732259"}, headers=F).status_code == 409  # ИНН не меняется
    need = client.post("/api/employer/needs", json={"spec": "Backend", "track": "Python", "grade": "Middle", "must": ["Python"]}, headers=F)
    assert need.status_code == 200 and client.get("/api/employer/quota", headers=F).status_code == 200
    nid = need.json()["id"]
    assert client.get(f"/api/employer/needs/{nid}/picks", headers=F).status_code == 403
    assert client.get("/api/employer/candidates/A-1042", headers=F).status_code == 403
    inv = {"candidate_id": "G-0005", "role": "Backend", "salary_from": 240000, "salary_to": 300000, "format": "Гибрид"}
    assert client.post("/api/employer/invites", json=inv, headers=F).status_code == 403


def test_profile_cv_privacy(client):
    N = {"Authorization": "Bearer new"}
    body = {"name": "Новый", "spec": "Backend", "track": "Go", "grade_claimed": "Junior", "min_salary": 150000, "formats": ["Удалённо"], "city": "Казань", "skills_claimed": ["golang", "postgres"]}
    assert client.post("/api/candidate/profile", json=body, headers=N).status_code == 422  # без согласия 152-ФЗ
    me = client.post("/api/candidate/profile", json={**body, "consent_152": True}, headers=N).json()
    assert re.fullmatch(r"[A-Z]-\d{4}", me["id"]) and me["skills_claimed"] == ["Go", "PostgreSQL"] and me["grade"] is None
    stream = b"BT /F1 12 Tf 72 720 Td (Go, PostgreSQL, Redis. 3 years of experience) Tj ET"
    pdf = (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        + f"4 0 obj<</Length {len(stream)}>>stream\n".encode() + stream
        + b"\nendstream endobj\n5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\ntrailer<</Root 1 0 R>>\nstartxref\n0\n%%EOF"
    )
    cv = client.post("/api/candidate/cv", files={"file": ("cv.pdf", pdf, "application/pdf")}, headers=N).json()
    assert cv["parsed"]["skills"] == ["Go", "PostgreSQL", "Redis"] and cv["parsed"]["years_exp"] == 3 and cv["parsed"]["track"] == "Go"
    assert client.post("/api/candidate/cv", files={"file": ("cv.txt", b"hello", "text/plain")}, headers=N).status_code == 422
    # отзыв согласия на внешние профили удаляет CF и его достижения, ФСП остаётся
    with SessionLocal() as db:
        a_id = db.query(Candidate.id).filter(Candidate.public_id == "A-1042").scalar()
        db.add(Achievement(candidate_id=a_id, source="codeforces", title="CF 1912", weight=0.4, verified=True))
        db.commit()
    a = client.get("/api/candidate/me", headers=C).json()
    assert a["cf"] and {x["source"] for x in a["achievements"]} == {"fsp", "codeforces"}
    keys = ("name", "email", "tg", "spec", "track", "grade_claimed", "city", "formats", "skills_claimed")
    a = client.post("/api/candidate/profile", json={**{k: a[k] for k in keys}, "min_salary": a["min"], "consent_external": False}, headers=C).json()
    assert a["cf"] is None and [x["source"] for x in a["achievements"]] == ["fsp"]
    # «не ищу» → пропадает из подборки; скрытие от компании — тоже
    assert client.patch("/api/candidate/status", json={"status": "off"}, headers=C).json() == {"status": "off"}
    assert client.get("/api/employer/candidates/A-1042", headers=E).status_code == 404
    client.patch("/api/candidate/status", json={"status": "open"}, headers=C)
    assert client.patch("/api/candidate/hidden-from", json={"inns": [INN]}, headers=C).json()["companies"][0]["name"] == "Ладога Пэй"
    assert client.get("/api/employer/candidates/A-1042", headers=E).status_code == 404
    assert client.patch("/api/candidate/notif", json={"tg": False}, headers=C).json()["notif"] == {"mail": True, "tg": False}
