"""Сценарий демо целиком: потребность → анонимная подборка → вилка → приглашение → принятие → контакты → отметка.
Плюс ёмкость, квота, лотерея, истечение, неподтверждённая компания, поиск по банку, согласия и права по 152-ФЗ. Своя БД (fsp_flows), LLM выключена — работают правила."""

import base64
import io
import json
import os
import re
from datetime import UTC, datetime, timedelta

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fsp:fsp@localhost:5432/fsp_flows")
os.environ["LLM_BASE_URL"] = ""
os.environ.setdefault("DEMO", "1")

import httpx
import pytest
from sqlalchemy.exc import IntegrityError
from fastapi import FastAPI
from pypdf import PdfReader
from fastapi.testclient import TestClient
from fpdf import FPDF
from PIL import Image, ImageDraw

from sqlalchemy import select

from app import catalog, config, deps
from app.db import Base, SessionLocal, engine
from app.deps import issue_token
from app.models import Achievement, AuditLog, Candidate, Company, ConsentEvent, Event, ExternalAccount, Invitation, Need, RetiredPublicId, User, Vacancy
from app.routers import candidate, employer, lottery
from app.services import llm, matching, ocr, profile_pdf

config.LLM_BASE_URL = ""
NOW = datetime.now(UTC)
INN = "7704123450"
NEED_TEXT = "Ищем бэкендера на Python в команду платежей. Нужен опыт с PostgreSQL и Kafka, хорошо бы Kubernetes. Уровень — мидл, до 300 на руки. Гибрид, Москва."
COMP = [{"n": "Ревью кода", "t": 1.42, "se": 0.25}, {"n": "Алгоритмы", "t": 1.6, "se": 0.2}]


def _cand(pid, **kw) -> Candidate:
    base = dict(
        public_id=pid, name=f"Имя {pid}", email=f"{pid.lower()}@example.ru", tg=None, consent_152=True, consent_publish=True, consent_version=catalog.CONSENT_VERSION, consent_publish_version=catalog.CONSENT_VERSION, spec="Backend", track="Python",
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
        cu, eu, nu = User(email="d.orlov@example.ru", role="candidate"), User(email="m.kovaleva@ladoga-pay.example", role="employer", email_confirmed=True), User(email="new@example.ru", role="candidate")
        fake = User(email="hr.ladoga@gmail.com", role="employer", email_confirmed=True)  # почта входа не на домене компании
        late = User(email="late@example.ru", role="candidate")  # резюме загружает до создания профиля
        db.add_all([cu, eu, nu, fake, late])
        db.flush()
        a = _cand(
            "A-1042", user_id=cu.id, consent_external=True, consent_external_version=catalog.CONSENT_VERSION, name="Дмитрий Орлов", email="d.orlov@example.ru", tg="@dorlov_dev", theta=1.12, se=0.18, percentile=78,
            formats=["Гибрид", "Удалённо"], skills_confirmed=["Python", "PostgreSQL", "Kafka", "asyncio"], skills_claimed=["Python", "PostgreSQL", "Kafka", "Kubernetes"],
        )
        cup = Event(source="fsp", external_id="cup-2025", title="Финал Кубка России ФСП 2025", discipline="продуктовое программирование")
        a.achievements = [Achievement(source="fsp", event=cup, title=cup.title, weight=0.8, result="winner", sport_rank="КМС", verified=True),
                          # неподтверждённый разряд выше — не показывается
                          Achievement(source="fsp", title="Этап ФСП", weight=0.05, result="participant", sport_rank="МС", verified=False)]
        a.accounts = [ExternalAccount(provider="codeforces", handle="dorlov", verify_code="FSP-7Q2K", verified_at=NOW, rating=1912, rank="Candidate Master")]
        busy = _cand("B-2318", theta=1.31, se=0.16, percentile=85, min_salary=280000, formats=["Удалённо"], skills_confirmed=["Python", "PostgreSQL", "Kafka", "Kubernetes"])
        db.add_all([
            a, busy,
            _cand("J-0003", grade="Junior", theta=0.1, percentile=60),
            _cand("Z-0001", status="off"),
            _cand("H-0002", hidden_from=[INN]),
            # тест не пройден (заявлен Middle, остались устаревшие перцентиль и компетенции): работодатель не видит нигде
            _cand("U-0004", grade=None, theta=None, se=None, tested_at=None, skills_confirmed=[], skills_claimed=["Python", "PostgreSQL", "Kafka", "Kubernetes"]),
            _cand("G-0005", track="Go", spec="Backend"),
            _cand("S-0006", grade="Senior", theta=1.8, min_salary=290000),  # грейд +1, минимум в вилке до 300 → в подборке
            _cand("S-0007", grade="Senior", theta=1.8, min_salary=350000),  # грейд +1, дороже вилки → нет
            _cand("P-0008", consent_publish=False),  # не согласился на публикацию карточки
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
        for hdr, u in ((C, cu), (E, eu), (N, nu), (F, fake), (LATE, late)):
            hdr["Authorization"] = "Bearer " + issue_token(db, u)
    app = FastAPI()
    for r in (deps, candidate, employer, lottery):
        app.include_router(r.router)
    yield TestClient(app)


E, C, N, F, LATE = {}, {}, {}, {}, {}  # заголовки: работодатель, кандидат A-1042, новый кандидат, неподтверждённая компания, ещё один новый


def _pdf(*lines: str) -> bytes:
    """Минимальный PDF с текстовым слоем: строка — отдельная строка текста (ASCII, шрифт Helvetica)."""
    body = " 0 -16 Td ".join(f"({x}) Tj" for x in lines)
    stream = f"BT /F1 12 Tf 72 720 Td {body} ET".encode()
    return (
        b"%PDF-1.4\n1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Contents 4 0 R/Resources<</Font<</F1 5 0 R>>>>>>endobj\n"
        + f"4 0 obj<</Length {len(stream)}>>stream\n".encode() + stream
        + b"\nendstream endobj\n5 0 obj<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>endobj\ntrailer<</Root 1 0 R>>\nstartxref\n0\n%%EOF"
    )


def test_demo_flow(client):
    # 1. разбор потребности
    p = client.post("/api/employer/needs/parse", json={"text": NEED_TEXT}, headers=E).json()
    assert (p["spec"], p["track"], p["grade"], p["must"], p["nice"]) == ("Backend", "Python", "Middle", ["Python", "PostgreSQL", "Kafka"], ["Kubernetes"])
    assert (p["from"], p["to"], p["format"], p["city"]) == (240000, 300000, "Гибрид", "Москва")
    assert p["category"]["count"] == 3 and p["market"]["p25"] == 210000  # A, B, H: счётчик категории не учитывает скрытие, U без теста — не считается
    # категория поправлена вручную: рынок и счётчик — под новую категорию, без повторного разбора
    c = client.post("/api/employer/needs/category", json={"spec": "Backend", "track": "Go", "grade": "Senior", "city": "Москва", "salary_to": 300000}, headers=E).json()
    assert c["category"] == {**c["category"], "spec": "Backend", "track": "Go", "grade": "Senior"} and c["market"]["p50"] > p["market"]["p50"]
    assert c["market_hint"] and c["market"] == client.post("/api/employer/needs/category", json={"spec": "Backend", "grade": "Senior", "city": "Москва"}, headers=E).json()["market"]
    for bad in ({"spec": "Project Manager", "grade": "Middle"}, {"spec": "Backend", "track": "React", "grade": "Middle"}, {"spec": "Backend", "grade": "Гуру"}):
        assert client.post("/api/employer/needs/category", json=bad, headers=E).status_code == 422
    assert client.post("/api/employer/needs/category", json={"spec": "Backend", "grade": "Middle"}).status_code == 401
    need = client.post("/api/employer/needs", json={**p, "text": NEED_TEXT}, headers=E).json()

    # 2. подборка: анонимно, по взаимному интересу
    r = client.get(f"/api/employer/needs/{need['id']}/picks", headers=E)
    assert r.status_code == 200
    assert "Дмитрий" not in r.text and "d.orlov" not in r.text and "dorlov_dev" not in r.text
    picks = r.json()
    ids = [c["id"] for c in picks["items"]]
    # U-0004 без теста не попадает, хотя заявленный стек и грейд покрывают потребность
    assert ids[0] == "A-1042" and set(ids) == {"A-1042", "B-2318", "J-0003", "G-0005", "S-0006"}, ids
    a = picks["items"][0]
    assert a["sport_rank"] == "КМС" and a["badges"] == [{"source": "fsp", "title": "Финал Кубка России ФСП 2025", "place": None,
                                                          "result": "winner", "discipline": "продуктовое программирование", "rank": "КМС"}]
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
    for hidden in ("Z-0001", "H-0002", "P-0008"):
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
    assert d["status"] == "seen" and d["why"].startswith("Совпадение стека Python, PostgreSQL, Kafka") and d["recruiter"]["email"] == "m.kovaleva@ladoga-pay.example"  # контакт компании — до принятия
    row = client.get("/api/employer/pipeline", headers=E).json()["items"][0]
    assert row["status"] == "seen" and row["contact"] is None

    # 6. отказ без причины нельзя; принятие открывает контакты обеим сторонам
    assert client.post(f"/api/candidate/invites/{iid}/decline", json={"reason": "дорого"}, headers=C).status_code == 422
    acc = client.post(f"/api/candidate/invites/{iid}/accept", headers=C).json()
    assert acc["status"] == "accepted" and acc["recruiter"]["email"] == "m.kovaleva@ladoga-pay.example"
    assert client.post(f"/api/candidate/invites/{iid}/accept", headers=C).status_code == 409
    with SessionLocal() as db:
        log = db.query(AuditLog).filter(AuditLog.action == "contacts_revealed").one()
        assert log.detail["invitation_id"] == iid
    row = client.get("/api/employer/pipeline", headers=E).json()["items"][0]
    assert row["status"] == "ok" and row["contact"]["text"] == "Дмитрий Орлов · d.orlov@example.ru · @dorlov_dev"

    # 7. отметка после собеседования
    assert client.post(f"/api/employer/invites/{iid}/feedback", json={"value": "hired"}, headers=E).json()["fb"] == "наняли"
    assert client.post(f"/api/employer/invites/{iid}/feedback", json={"value": "confirmed"}, headers=E).status_code == 409
    me = client.get("/api/candidate/me", headers=C).json()
    assert me["employer_confirmed"] == 1 and me["name"] == "Дмитрий Орлов" and me["cf"]["rating"] == 1912 and me["invites_open"] == 0 and me["visible"]


def test_capacity_quota_expiry(client):
    need_id = client.get("/api/employer/needs", headers=E).json()[0]["id"]
    inv = {"need_id": need_id, "role": "Backend (Python)", "salary_from": 240000, "salary_to": 270000, "format": "Гибрид"}
    # ёмкость: у B-2318 4 открытых приглашения — жёсткий отказ
    r = client.post("/api/employer/invites", json={**inv, "candidate_id": "B-2318"}, headers=E)
    assert r.status_code == 409 and r.json()["detail"] == "У кандидата максимум открытых приглашений"
    # приглашение по жребию — через настоящий API лотереи (в ней псевдонимы): вторая потребность, порог до 280 тыс.
    # → пул ровно A-1042 и J-0003 (S-0006 дороже, B перегружен, H скрыт, P без согласия, G — другой трек,
    # U-0004 без теста работодателю не виден)
    jn = client.post("/api/employer/needs", json={"spec": "Backend", "track": "Python", "grade": "Junior", "must": ["Python"], "salary_to": 300000}, headers=E).json()["id"]
    lot = client.post("/api/lottery/", json={"need_id": jn, "threshold": {"fork_to": 280000}, "draw_count": 1}, headers=E).json()
    assert lot["pool_size"] == 2, lot
    drawn = client.post(f"/api/lottery/{lot['id']}/draw", headers=E).json()["drawn"][0]["public_id"]
    other = ({"A-1042", "J-0003"} - {drawn}).pop()
    lot_inv = {**inv, "need_id": None, "salary_from": 240000, "salary_to": 300000}
    assert client.post("/api/employer/invites", json={**lot_inv, "candidate_id": drawn, "lottery_id": 10**6}, headers=E).status_code == 404
    assert client.post("/api/employer/invites", json={**lot_inv, "candidate_id": other, "lottery_id": lot["id"]}, headers=E).status_code == 422
    # потребность приглашения обязана совпасть с потребностью лотереи
    assert client.post("/api/employer/invites", json={**lot_inv, "need_id": need_id, "candidate_id": drawn, "lottery_id": lot["id"]}, headers=E).status_code == 422
    r = client.post("/api/employer/invites", json={**lot_inv, "candidate_id": drawn, "lottery_id": lot["id"]}, headers=E).json()
    assert r["invite"]["lottery_id"] == lot["id"] and r["invite"]["need_id"] == jn
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
    rows = client.get("/api/employer/pipeline", headers=E).json()["items"]
    assert any(r["cid"] == drawn and r["lottery_id"] == lot["id"] and r["status"] == "exp" for r in rows) and "B-2318" not in {r["cid"] for r in rows}


def test_unverified_company(client):
    co = {"inn": "7707083893", "name": "Фейк", "site_domain": "ladoga2.example", "recruiter_name": "HR", "recruiter_email": "hr@ladoga2.example"}
    r = client.post("/api/employer/company", json=co, headers=F).json()
    assert r["verified"] is False  # домен проверяется по почте входа (gmail), а не по recruiter_email из формы
    assert (r["domain_confirmed"], r["inn_checksum_valid"]) == (False, True)
    # ИНН можно поправить, пока компания не проверена и ничего не начала; потом — нет
    assert client.post("/api/employer/company", json={**co, "inn": "500100732259"}, headers=F).json()["inn"] == "500100732259"
    with SessionLocal() as db:  # опубликованная вакансия — тоже «начало работы»
        fco = db.query(Company).filter(Company.inn == "500100732259").one()
        db.add(Vacancy(company_id=fco.id, title="Backend", spec="Backend", grade="Middle", salary_from=240000, salary_to=300000, format="Гибрид"))
        db.commit()
    assert client.post("/api/employer/company", json=co, headers=F).status_code == 409
    nid = client.post("/api/employer/needs", json={"spec": "Backend", "track": "Python", "grade": "Middle", "must": ["Python"], "salary_to": 300000}, headers=F).json()["id"]
    assert client.post("/api/employer/company", json=co, headers=F).status_code == 409
    # без проверки всё доступно, но квота урезана
    assert client.get(f"/api/employer/needs/{nid}/picks", headers=F).json()["quota"]["max"] == 3
    assert client.get("/api/employer/candidates/A-1042", headers=F).status_code == 200
    inv = {"role": "Backend", "salary_from": 240000, "salary_to": 300000, "format": "Гибрид"}
    # видимость (статус, согласие на публикацию) проверяется по строке, перечитанной под блокировкой
    assert client.post("/api/employer/invites", json={**inv, "candidate_id": "P-0008"}, headers=F).status_code == 404
    assert client.post("/api/employer/invites", json={**inv, "candidate_id": "Z-0001"}, headers=F).status_code == 404
    for pid in ("A-1042", "G-0005", "J-0003"):
        assert client.post("/api/employer/invites", json={**inv, "candidate_id": pid}, headers=F).status_code == 200, pid
    assert client.post("/api/employer/invites", json={**inv, "candidate_id": "S-0006", "salary_from": 330000, "salary_to": 400000}, headers=F).status_code == 429
    # кандидат видит, что компания не подтверждена
    items = client.get("/api/candidate/invites", headers=C).json()["items"]
    fake = next(i for i in items if i["company"] == "Фейк")
    assert (fake["domain_confirmed"], fake["inn_checksum_valid"]) == (False, True) and "verified" not in fake  # «почта на домене не подтверждена»
    ladoga = next(i for i in items if i["company"] == "Ладога Пэй")
    assert ladoga["domain_confirmed"] is True


def test_search(client):
    r = client.get("/api/employer/search?spec=Backend&skills=Kafka&fsp=1", headers=E)
    assert r.status_code == 200 and [c["id"] for c in r.json()["items"]] == ["A-1042"]
    assert "Дмитрий" not in r.text and "d.orlov" not in r.text
    s = client.get("/api/employer/search?grade=Middle&q=нужна кафка&limit=2", headers=E).json()
    ids = [c["id"] for c in s["items"]]
    # + G-0005; J — Junior, H скрыт, P без согласия, U-0004 без теста (заявлен Middle) — не виден
    assert s["skills"] == ["Kafka"] and s["total"] == 3 and ids == ["A-1042", "B-2318"], s
    assert {"H-0002", "P-0008", "Z-0001", "U-0004"}.isdisjoint(ids)
    assert s["facets"]["grade"]["Senior"] == 2 and s["facets"]["spec"] == {"Backend": 3}  # фасет грейда — без своего фильтра
    assert s["facets"]["grade"]["Middle"] == 3 and s["facets"]["grade"]["Junior"] == 1  # J-0003 — по тесту, U-0004 — нигде
    page2 = client.get("/api/employer/search?grade=Middle&q=кафка&limit=2&page=2", headers=E).json()
    assert [(c["id"], c["rank"]) for c in page2["items"]] == [("G-0005", 3)]
    assert "U-0004" not in client.get("/api/employer/search?limit=100", headers=E).text


def test_untested_invisible(client, monkeypatch):
    """Без теста (U-0004: заявлен Middle, в строке остались старые перцентиль и компетенции) кандидат работодателю не виден:
    ни в подборке (все варианты), ни в карточке, ни для приглашения, ни в счётчике категории, ни в LLM-реранке.
    Кандидат в кабинете видит, что скрыт до теста (visible = False)."""
    need_id = client.get("/api/employer/needs", headers=E).json()[-1]["id"]  # первая потребность: Backend · Python · Middle
    for variant in ("embed", "rerank", "full"):
        ids = [c["id"] for c in client.get(f"/api/employer/needs/{need_id}/picks?variant={variant}", headers=E).json()["items"]]
        assert "U-0004" not in ids and ids, (variant, ids)
    assert client.get(f"/api/employer/candidates/U-0004?need_id={need_id}", headers=E).status_code == 404
    r = client.post("/api/employer/invites", json={"candidate_id": "U-0004", "role": "Backend", "salary_from": 240000, "salary_to": 300000, "format": "Гибрид"}, headers=E)
    assert r.status_code == 404
    sent = []

    def fake_chat(system, user):
        sent.append(json.loads(user))
        return None

    monkeypatch.setattr(matching.llm, "chat_json", fake_chat)
    matching._llm_cache.clear()
    client.get(f"/api/employer/needs/{need_id}/picks", headers=E)
    assert sent and all(c["id"] != "U-0004" and c["theta"] is not None for c in sent[0]["candidates"])
    assert "grade_tested" not in sent[0]["candidates"][0]
    matching._llm_cache.clear()
    with SessionLocal() as db:  # счётчик категории — только прошедшие тест (U-0004 заявил Middle — не считается)
        assert employer._category_count(db, "Backend", "Python", "Junior") == 1
        u = db.scalar(select(Candidate).where(Candidate.public_id == "U-0004"))
        assert matching.category_grade(u) is None and not matching.visible(u)
        n = db.get(Need, need_id)
        assert all(matching.tested(c) for c in matching.eligible(db, n))
    # тест показал грейд ниже заявленного: категория по тесту, заявленный виден
    j = client.get("/api/employer/candidates/J-0003", headers=E).json()
    assert (j["grade"], j["grade_claimed"], j["pct"]) == ("Junior", "Middle", 60) and j["competencies"] and "grade_tested" not in j


def test_roles_soft_and_pdf_profile(client):
    """Роли и софт-скиллы: только из справочника, None — не менять; в анонимной карточке — без ПДн. PDF-профиль — только себе."""
    a = client.get("/api/candidate/me", headers=C).json()
    keys = ("name", "email", "tg", "spec", "track", "grade_claimed", "city", "formats", "skills_claimed")
    body = {**{k: a[k] for k in keys}, "min_salary": a["min"]}
    me = client.post("/api/candidate/profile", json={**body, "roles": ["Тимлид", "Космонавт", "Тимлид"], "soft_skills": ["Коммуникация", 1]}, headers=C)
    assert me.status_code == 422  # не строка — ошибка схемы
    me = client.post("/api/candidate/profile", json={**body, "roles": ["Тимлид", "Космонавт", "Тимлид"], "soft_skills": ["Коммуникация"]}, headers=C).json()
    assert (me["roles"], me["soft_skills"]) == (["Тимлид"], ["Коммуникация"])
    me = client.post("/api/candidate/profile", json=body, headers=C).json()  # поля не переданы — не трогаем
    assert (me["roles"], me["soft_skills"]) == (["Тимлид"], ["Коммуникация"])
    r = client.get("/api/employer/candidates/A-1042", headers=E)
    card = r.json()
    assert (card["roles"], card["soft"]) == (["Тимлид"], ["Коммуникация"]) and "Дмитрий" not in r.text and "d.orlov" not in r.text
    with SessionLocal() as db:  # места работы в PDF — из текста резюме
        db.query(Candidate).filter(Candidate.public_id == "A-1042").update({"cv_text": "2021 — н.в. Финтех, бэкенд\n2012 — 2016 Университет", "years_exp": 4.5})
        db.commit()

    r = client.get("/api/candidate/profile.pdf", headers=C)
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf" and r.content.startswith(b"%PDF")
    assert 'filename="fsp-career-A-1042.pdf"' in r.headers["content-disposition"] and r.headers["cache-control"] == "no-store"
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(r.content)).pages)
    for s in ("Дмитрий Орлов", "d.orlov@example.ru", "@dorlov_dev", "Backend · Python · Middle", "Перцентиль 78", "Ревью кода", "1,42 ± 0,25",
              "Kubernetes", "Тимлид", "Коммуникация", "стаж 4,5 г.", "2021 — н. в.", "Финтех, бэкенд", "Финал Кубка России ФСП 2025",
              "Codeforces: dorlov, рейтинг 1912", "230 000 ₽"):
        assert s in text, s
    assert "Университет" not in text and "распознаны автоматически" in text
    # в профиле кандидат видит ровно то, что попадёт в «Опыт», и может исключить: стаж остаётся, места работы — нет
    me = client.get("/api/candidate/me", headers=C).json()
    assert me["experience"] == [{"from": 2021, "to": None, "title": "Финтех, бэкенд"}] and me["pdf_experience"] is True
    assert client.patch("/api/candidate/pdf", json={"experience": False}, headers=C).json() == {"pdf_experience": False}
    me = client.get("/api/candidate/me", headers=C).json()
    assert me["pdf_experience"] is False and me["experience"]  # список виден и после исключения — можно вернуть
    assert client.post("/api/candidate/profile", json={**body, "years_exp": 4.5}, headers=C).json()["pdf_experience"] is False  # профиль флаг не трогает
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(client.get("/api/candidate/profile.pdf", headers=C).content)).pages)
    assert "стаж 4,5 г." in text and "Финтех" not in text and "распознаны автоматически" not in text
    assert client.patch("/api/candidate/pdf", json={"experience": True}, headers=E).status_code == 403
    client.patch("/api/candidate/pdf", json={"experience": True}, headers=C)
    # работодателю и тому, у кого нет профиля, — нельзя
    assert client.get("/api/candidate/profile.pdf", headers=E).status_code == 403
    assert client.get("/api/candidate/profile.pdf", headers=N).status_code == 403


def test_profile_pdf_render_edge_cases():
    """Без теста — заявленный грейд; много компетенций и длинные строки — перенос и вторая страница; символ вне шрифта не роняет."""
    c = _cand("X-0001", name="Ева 🚀 Тестова", grade=None, theta=None, se=None, percentile=None, tested_at=None, skills_confirmed=[],
              competencies=[{"n": f"Компетенция с очень длинным названием № {i}", "t": i / 3 - 3, "se": 0.3} for i in range(40)],
              roles=["Ментор"], soft_skills=[], years_exp=None, cv_text=None)
    c.achievements = [Achievement(source="hackathon", title="Хакатон " + "очень длинное название " * 8, place=2, weight=0.3, verified=False)]
    pdf = profile_pdf.render(c)
    pages = PdfReader(io.BytesIO(pdf)).pages
    text = "\n".join(p.extract_text() for p in pages)
    assert len(pages) >= 2 and "Тест ещё не пройден: грейд Middle заявлен" in text and "не подтверждено" in text and "Ментор" in text
    assert "Опыт" not in text and "Софт-скиллы" not in text


def test_profile_pdf_fallback_glyphs(caplog):
    """Эмодзи, арабица, грузинский — из фолбэк-шрифта; CJK нет ни в одном шрифте — видимый «□», а не пропуск.
    В лог — только счётчик и анонимный код, не сами символы (они из ФИО)."""
    c = _cand("X-0002", name="Иван 😀 李 Петров", tg="@ivan_محمد", city="Тбилиси ა", skills_claimed=["Python"], cv_text="2020 — н.в. 株式会社 Акме\x07")
    with caplog.at_level("WARNING", logger="app.services.profile_pdf"):
        text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(profile_pdf.render(c))).pages)
    assert "Иван 😀 □ Петров" in text and "□□□□ Акме" in text and "ა" in text, text
    assert [r.getMessage() for r in caplog.records] == ["PDF-профиль X-0002: 5 символ(ов) вне шрифтов заменены на «□»"]
    assert "李" not in caplog.text


def test_reconsent(client, monkeypatch):
    """Новая редакция текста согласия: кандидат пропадает из выдачи и не может принять приглашение, у компании
    скрыты контакты — пока не подтвердит заново."""
    assert client.get("/api/employer/candidates/A-1042", headers=E).status_code == 200
    current = catalog.CONSENT_VERSION
    monkeypatch.setattr(catalog, "CONSENT_VERSION", "2099-01")
    assert client.get("/api/employer/candidates/A-1042", headers=E).status_code == 404
    assert "A-1042" not in [c["id"] for c in client.get("/api/employer/search?skills=Kafka", headers=E).json()["items"]]
    me = client.get("/api/candidate/me", headers=C).json()
    assert me["needs_reconsent"] is True
    r = client.patch("/api/candidate/notif", json={"tg": True}, headers=C)
    assert r.status_code == 403 and r.json()["detail"].startswith("Текст согласия обновился")
    open_inv = next(i for i in client.get("/api/candidate/invites", headers=C).json()["items"] if i["status"] == "new")
    assert client.post(f"/api/candidate/invites/{open_inv['id']}/accept", headers=C).status_code == 403
    row = next(r for r in client.get("/api/employer/pipeline", headers=E).json()["items"] if r["cid"] == "A-1042" and r["status"] == "ok")
    assert row["contact"] is None and row["reason"] == "кандидат отозвал согласие"
    # повторное согласие на обработку не «оживляет» публикацию и внешние профили старой редакции
    ok = client.patch("/api/candidate/consents", json={"consent_152": True}, headers=C).json()
    assert ok["consent_version"] == "2099-01" and ok["valid"] == {"processing": True, "publish": False, "external": False} and ok["needs_reconsent"] is True
    assert client.get("/api/employer/candidates/A-1042", headers=E).status_code == 404
    # публикация — отдельное повторное согласие; внешние профили так и остаются на старой редакции
    ok = client.patch("/api/candidate/consents", json={"consent_publish": True}, headers=C).json()
    assert ok["valid"] == {"processing": True, "publish": True, "external": False} and ok["needs_reconsent"] is True
    with SessionLocal() as db:
        a_id = db.query(Candidate.id).filter(Candidate.public_id == "A-1042").scalar()
        ev = [(e.purpose, e.granted, e.version) for e in db.query(ConsentEvent).filter(ConsentEvent.candidate_id == a_id, ConsentEvent.version == "2099-01")]
        assert ev == [("processing", True, "2099-01"), ("publish", True, "2099-01")], ev
    assert client.get("/api/employer/candidates/A-1042", headers=E).status_code == 200
    row = next(r for r in client.get("/api/employer/pipeline", headers=E).json()["items"] if r["cid"] == "A-1042" and r["status"] == "ok")
    assert row["contact"]["name"] == "Дмитрий Орлов"
    with SessionLocal() as db:  # monkeypatch откатит редакцию — вернём её и кандидату, чтобы следующие тесты шли как раньше
        db.query(Candidate).filter(Candidate.id == a_id).update({"consent_version": current, "consent_publish_version": current, "consent_external_version": current})
        db.commit()


def test_profile_cv_privacy(client):
    body = {"name": "Новый", "spec": "Backend", "track": "Go", "grade_claimed": "Junior", "min_salary": 150000, "formats": ["Удалённо"], "city": "Казань", "skills_claimed": ["golang", "postgres"]}
    assert client.post("/api/candidate/profile", json=body, headers=N).status_code == 422  # без согласия 152-ФЗ
    me = client.post("/api/candidate/profile", json={**body, "consent_152": True}, headers=N).json()
    assert re.fullmatch(r"[A-Z]-\d{4}", me["id"]) and me["skills_claimed"] == ["Go", "PostgreSQL"] and me["grade"] is None
    assert me["consent_152_at"] and me["consent_version"] and me["consent_publish"] is False
    assert me["consents"]["processing"]["granted"] is True and me["consents"]["publish"]["granted"] is False and me["consents"]["external"] is None
    pdf = _pdf("Go, PostgreSQL, Redis. 3 years of experience")
    cv = client.post("/api/candidate/cv", files={"file": ("cv.pdf", pdf, "application/pdf")}, headers=N).json()
    assert cv["parsed"]["skills"] == ["Go", "PostgreSQL", "Redis"] and cv["parsed"]["years_exp"] == 3 and cv["parsed"]["track"] == "Go"
    assert "text" not in cv  # профиль есть — резюме сохранено на сервере, текст назад не нужен
    long = client.post("/api/candidate/cv", files={"file": ("y" * 300 + ".pdf", pdf, "application/pdf")}, headers=N).json()
    assert long["filename"] == "y" * 255  # имя обрезано под колонку String(255), а не 500
    assert client.post("/api/candidate/cv", files={"file": ("cv.txt", b"hello", "text/plain")}, headers=N).status_code == 422
    # отзыв согласия на внешние профили удаляет внешние аккаунты и достижения
    with SessionLocal() as db:
        a_id = db.query(Candidate.id).filter(Candidate.public_id == "A-1042").scalar()
        db.add(Achievement(candidate_id=a_id, source="codeforces", title="CF 1912", weight=0.4, verified=True))
        db.commit()
    a = client.get("/api/candidate/me", headers=C).json()
    assert a["cf"] and {x["source"] for x in a["achievements"]} == {"fsp", "codeforces"}
    keys = ("name", "email", "tg", "spec", "track", "grade_claimed", "city", "formats", "skills_claimed")
    assert client.post("/api/candidate/profile", json={**{k: a[k] for k in keys}, "min_salary": a["min"]}, headers=C).json()["cf"]  # поле не передано — не трогаем
    a = client.post("/api/candidate/profile", json={**{k: a[k] for k in keys}, "min_salary": a["min"], "consent_external": False}, headers=C).json()
    assert a["cf"] is None and a["achievements"] == [] and a["consents"]["external"]["granted"] is False  # consent.py удаляет все внешние источники, включая ФСП
    # «не ищу» → пропадает из подборки; скрытие от компании — тоже
    assert client.patch("/api/candidate/status", json={"status": "off"}, headers=C).json() == {"status": "off"}
    assert client.get("/api/employer/candidates/A-1042", headers=E).status_code == 404
    client.patch("/api/candidate/status", json={"status": "open"}, headers=C)
    assert client.patch("/api/candidate/hidden-from", json={"inns": [INN]}, headers=C).json()["companies"][0]["name"] == "Ладога Пэй"
    assert client.get("/api/employer/candidates/A-1042", headers=E).status_code == 404
    assert client.patch("/api/candidate/notif", json={"tg": False}, headers=C).json()["notif"] == {"mail": True, "tg": False}


def test_cv_before_profile(client):
    """Резюме до создания профиля: до согласия сервер ничего не хранит, текст возвращается и приходит в POST /profile."""
    with SessionLocal() as db:  # NUL в тексте (Postgres его не примет) вырезается, а не роняет запрос
        nul = User(email="nul@example.ru", role="candidate")
        db.add(nul)
        db.commit()
        hdr = {"Authorization": "Bearer " + issue_token(db, nul)}
        nul_id = nul.id
    r = client.post("/api/candidate/profile", headers=hdr, json={"name": "Нуль", "spec": "Backend", "grade_claimed": "Junior", "min_salary": 100000,
                                                                "formats": ["Удалённо"], "city": "Казань", "consent_152": True,
                                                                "cv_text": "2020 - 2022 A\x00B", "cv_filename": "a\x00.pdf"})
    assert r.status_code == 200 and r.json()["cv_filename"] == "a.pdf" and r.json()["visible"] is False  # без публикации не видна
    with SessionLocal() as db:
        assert db.query(Candidate.cv_text).filter(Candidate.user_id == nul_id).scalar() == "2020 - 2022 AB"
    pdf = _pdf("Go, PostgreSQL. 4 years", "2021 - 2023 Acme Pay, Go developer", "2023 - now Volna, backend")
    r = client.post("/api/candidate/cv", files={"file": ("late.pdf", pdf, "application/pdf")}, headers=LATE)
    cv = r.json()
    assert r.headers["cache-control"] == "no-store" and "2021 - 2023 Acme Pay" in cv["text"] and cv["parsed"]["experience"]
    with SessionLocal() as db:
        uid = db.query(User.id).filter(User.email == "late@example.ru").scalar()
        assert db.query(Candidate).filter(Candidate.user_id == uid).count() == 0
    body = {"name": "Поздний", "spec": "Backend", "track": "Go", "grade_claimed": "Middle", "min_salary": 200000, "formats": ["Удалённо"],
            "city": "Казань", "consent_152": True}
    too_long = client.post("/api/candidate/profile", json={**body, "cv_text": "x" * (candidate.CV_MAX_CHARS + 1)}, headers=LATE)
    assert too_long.status_code == 422
    me = client.post("/api/candidate/profile", json={**body, "cv_text": cv["text"], "cv_filename": cv["filename"]}, headers=LATE).json()
    assert me["cv_filename"] == "late.pdf" and me["pdf_experience"] is True
    assert [j["from"] for j in me["experience"]] == [2021, 2023] and me["experience"][0]["title"] == "Acme Pay, Go developer"
    # у существующего профиля поле игнорируется: резюме меняется только загрузкой
    again = client.post("/api/candidate/profile", json={**body, "cv_text": "2010 - 2012 Other"}, headers=LATE).json()
    assert [j["from"] for j in again["experience"]] == [2021, 2023]
    text = "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(client.get("/api/candidate/profile.pdf", headers=LATE).content)).pages)
    assert "Acme Pay" in text


# ---------- OCR скана резюме (vLLM замокан) ----------

OCR_URL = "http://vllm.test/v1"
SCAN_TEXT = "Ivan Testov\nivan.testov@example.ru\nGo, PostgreSQL, Redis. 3 years of experience"  # синтетика


def _scan(pages: int = 1, size: tuple[int, int] = (1240, 1754), logo: bool = False) -> bytes:
    """PDF-скан без текстового слоя: на странице только растровая картинка (fpdf2 + Pillow, синтетика)."""
    pdf = FPDF(unit="pt", format=(612, 792))
    for i in range(pages):
        pdf.add_page()
        img = Image.new("L", size, 255)
        ImageDraw.Draw(img).text((60, 60 + i), "Go, PostgreSQL, Redis. 3 years", fill=0)
        pdf.image(img, x=0, y=0, w=612, h=792)
        if logo:  # мелкая картинка поверх — не страница, OCR её не берёт
            pdf.image(Image.new("RGB", (64, 64), (200, 0, 0)), x=10, y=10, w=20, h=20)
    return bytes(pdf.output())


def _fresh_user(email: str) -> dict:
    with SessionLocal() as db:
        u = User(email=email, role="candidate")
        db.add(u)
        db.commit()
        return {"Authorization": "Bearer " + issue_token(db, u)}


@pytest.fixture
def vllm(monkeypatch):
    """Свой vLLM: OCR_URL включён, httpx.post подменён; ответ — vllm.reply (str | Exception | httpx.Response)."""
    monkeypatch.setattr(config, "OCR_URL", OCR_URL)
    monkeypatch.setattr(config, "OCR_API_KEY", "")
    monkeypatch.setattr(config, "OCR_TIMEOUT", 30.0)

    class Fake:
        reply: object = ""
        calls: list = []
        llm_bodies: list = []

        def __call__(self, url, json=None, headers=None, timeout=None, **kw):
            req = httpx.Request("POST", url)
            if not url.startswith(OCR_URL):  # разбор резюме LLM (если тест её включил)
                self.llm_bodies.append(json)
                return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]}, request=req)
            self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
            if isinstance(self.reply, Exception):
                raise self.reply
            if isinstance(self.reply, httpx.Response):
                return self.reply
            return httpx.Response(200, json={"choices": [{"message": {"content": self.reply}}]}, request=req)

    fake = Fake()
    fake.calls, fake.llm_bodies = [], []
    monkeypatch.setattr(ocr.httpx, "post", fake)
    return fake


def _upload(client, hdr, pdf):
    return client.post("/api/candidate/cv", files={"file": ("scan.pdf", pdf, "application/pdf")}, headers=hdr)


def test_scan_without_ocr_is_422(client, monkeypatch):
    monkeypatch.setattr(config, "OCR_URL", "")
    pdf = _scan()
    assert "\n".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf)).pages).strip() == ""  # текстового слоя правда нет
    r = _upload(client, _fresh_user("scan-off@example.ru"), pdf)
    assert r.status_code == 422 and "нет текстового слоя" in r.json()["detail"]


def test_scan_recognized_and_parsed(client, vllm, caplog):
    vllm.reply = SCAN_TEXT
    caplog.set_level("DEBUG")
    r = _upload(client, _fresh_user("scan-on@example.ru"), _scan(logo=True))
    assert r.status_code == 200, r.text
    cv = r.json()
    assert cv["parsed"]["skills"] == ["Go", "PostgreSQL", "Redis"] and cv["parsed"]["years_exp"] == 3 and cv["text"] == SCAN_TEXT
    assert len(vllm.calls) == 1  # одна страница — один запрос; логотип не ушёл отдельной картинкой
    call = vllm.calls[0]
    assert call["url"] == OCR_URL + "/chat/completions" and call["headers"] == {} and 0 < call["timeout"] <= 30
    body = call["json"]
    assert body["model"] == config.OCR_MODEL and body["max_tokens"] == ocr.MAX_TOKENS
    image, prompt = body["messages"][0]["content"]
    assert prompt["type"] == "text" and image["type"] == "image_url"
    url = image["image_url"]["url"]
    assert url.startswith("data:image/jpeg;base64,")
    sent = Image.open(io.BytesIO(base64.b64decode(url.split(",", 1)[1])))
    assert sent.format == "JPEG" and max(sent.size) == ocr.MAX_SIDE  # страница, уменьшенная до лимита
    for secret in ("Ivan", "Testov", "ivan.testov", "PostgreSQL"):  # ни текста скана, ни ПДн в логах
        assert secret not in caplog.text


def test_scan_text_masked_before_llm(client, vllm, monkeypatch):
    """Распознанный текст идёт обычным путём: в LLM разбора уходит только после mask_pii."""
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai_compatible")
    monkeypatch.setattr(config, "LLM_BASE_URL", "http://llm.test/v1")
    monkeypatch.setattr(config, "LLM_MODEL", "test-chat")
    monkeypatch.setattr(config, "EMBED_MODEL", "")
    monkeypatch.setattr(llm, "_down_until", 0.0)
    vllm.reply = SCAN_TEXT
    r = _upload(client, _fresh_user("scan-llm@example.ru"), _scan())
    assert r.status_code == 200 and r.json()["parsed"]["contacts"]["email"] == "ivan.testov@example.ru"  # контакты — правилами, локально
    sent = json.dumps(vllm.llm_bodies, ensure_ascii=False)
    assert vllm.llm_bodies and "Testov" not in sent and "ivan.testov" not in sent


@pytest.mark.parametrize("reply", [
    httpx.ConnectError("нет соединения"),
    httpx.ReadTimeout("таймаут"),
    httpx.InvalidURL("кривой OCR_URL"),
    httpx.Response(500, text="Ivan Testov boom", request=httpx.Request("POST", OCR_URL)),
    httpx.Response(200, content=b"<html>", request=httpx.Request("POST", OCR_URL)),
    httpx.Response(200, json={"choices": []}, request=httpx.Request("POST", OCR_URL)),
    "   ",  # пустой ответ
], ids=["connect", "timeout", "bad-url", "http500", "not-json", "no-choices", "empty"])
def test_scan_model_failure_is_422(client, vllm, caplog, reply, request):
    vllm.reply = reply
    r = _upload(client, _fresh_user(f"scan-fail-{request.node.callspec.id}@example.ru"), _scan())
    assert r.status_code == 422 and "Не удалось распознать скан" in r.json()["detail"]
    assert "Ivan" not in caplog.text and "boom" not in caplog.text


def test_scan_limits(vllm, monkeypatch):
    """Лимит страниц, мелкие картинки, общий срок на документ, ключ vLLM, выключенный OCR."""
    assert len(ocr.page_images(_scan(pages=ocr.MAX_PAGES + 2))) == ocr.MAX_PAGES
    assert ocr.page_images(_scan(size=(200, 280))) == []  # только мелкая картинка — не скан страницы
    assert ocr.recognize(_scan(size=(200, 280))) is None and vllm.calls == []
    monkeypatch.setattr(ocr, "MAX_PIXELS", 1_000_000)  # страница 1240×1754 больше лимита — не декодируется, а не грузит память
    assert ocr.page_images(_scan()) == []
    monkeypatch.setattr(ocr, "MAX_PIXELS", 40_000_000)
    vllm.reply = "text"
    monkeypatch.setattr(config, "OCR_API_KEY", "k")
    assert ocr.recognize(_scan(pages=2)) == "text\ntext" and vllm.calls[0]["headers"] == {"Authorization": "Bearer k"}
    monkeypatch.setattr(config, "OCR_TIMEOUT", 0.0)  # срок истёк до первого запроса — None, без запроса
    n = len(vllm.calls)
    assert ocr.recognize(_scan()) is None and len(vllm.calls) == n
    monkeypatch.setattr(config, "OCR_URL", "")
    assert ocr.recognize(_scan()) is None and len(vllm.calls) == n


def test_consents_export_delete(client, monkeypatch):
    assert client.patch("/api/candidate/consents", json={"consent_publish": True}, headers=N).json()["consent_publish"] is True
    assert client.get("/api/candidate/me", headers=N).json()["consents"]["publish"]["granted"] is True
    with SessionLocal() as db:  # внешний профиль, эмбеддинг и открытое приглашение — чтобы проверить отзыв и экспорт
        n = db.query(Candidate).filter(Candidate.name == "Новый").one()
        n.consent_external, n.consent_external_version, n.embedding = True, catalog.CONSENT_VERSION, [0.1, 0.2, 0.3]
        db.add(ExternalAccount(candidate_id=n.id, provider="codeforces", handle="newbie", verify_code="FSP-0000", verified_at=NOW, rating=1500))
        ladoga = db.query(Company).filter(Company.inn == INN).one()
        inv = Invitation(company_id=ladoga.id, candidate_id=n.id, role="Go", salary_from=150000, salary_to=180000, format="Удалённо", expires_at=NOW + timedelta(days=7))
        db.add(inv)
        db.commit()
        n_id, inv_id = n.id, inv.id
    assert client.get("/api/candidate/me", headers=N).json()["consents_valid"] == {"processing": True, "publish": True, "external": True}
    # отзыв обработки: снимает публикацию и внешние профили (данные удаляются), профиль скрыт
    off = client.patch("/api/candidate/consents", json={"consent_152": False}, headers=N).json()
    assert (off["consent_152"], off["consent_publish"], off["consent_external"], off["status"]) == (False, False, False, "off")
    assert off["valid"] == {"processing": False, "publish": False, "external": False}
    with SessionLocal() as db:
        assert db.query(ExternalAccount).filter(ExternalAccount.candidate_id == n_id).count() == 0
    assert client.post(f"/api/candidate/invites/{inv_id}/accept", headers=N).status_code == 403  # принять после отзыва нельзя
    assert client.patch("/api/candidate/consents", json={"consent_publish": True}, headers=N).status_code == 422
    # места работы из PDF исключить можно и после отзыва (сужение обработки), вернуть — нет
    assert client.patch("/api/candidate/pdf", json={"experience": False}, headers=N).json() == {"pdf_experience": False}
    assert client.patch("/api/candidate/pdf", json={"experience": True}, headers=N).status_code == 403
    # после отзыва — никакой записи ПДн
    body = {"name": "Новый", "spec": "Backend", "grade_claimed": "Junior", "min_salary": 150000, "formats": ["Удалённо"], "city": "Казань", "consent_152": True, "consent_publish": True}
    for r in (
        client.post("/api/candidate/profile", json=body, headers=N),
        client.post("/api/candidate/cv", files={"file": ("cv.pdf", b"%PDF-1.4", "application/pdf")}, headers=N),
        client.patch("/api/candidate/notif", json={"tg": False}, headers=N),
        client.patch("/api/candidate/hidden-from", json={"inns": []}, headers=N),
    ):
        assert r.status_code == 403 and r.json()["detail"].startswith("Согласие на обработку отозвано"), r.text
    with SessionLocal() as db:
        assert db.get(Candidate, n_id).consent_publish is False  # save_profile с consent_publish=True после отзыва ничего не включил
    # экспорт полный: с вектором эмбеддинга и собственной записью data_exported
    ex = client.get("/api/candidate/me/export", headers=N)
    assert ex.status_code == 200 and ex.headers["cache-control"] == "no-store" and {"account", "profile", "embedding", "consents", "audit", "achievements", "invitations", "applications", "task_submissions", "quest_sessions"} <= set(ex.json())
    e = ex.json()
    assert e["account"]["email"] == "new@example.ru" and e["account"]["role"] == "candidate" and "token" not in e["account"]
    assert e["profile"]["name"] == "Новый" and e["profile"]["truth"] is None and "embedding" not in e["profile"]
    assert e["embedding"] == {"vector": [0.1, 0.2, 0.3], "dim": 3}
    assert [(x["purpose"], x["granted"]) for x in e["consents"]] == [
        ("processing", True), ("publish", False), ("publish", True), ("publish", False), ("external", False), ("processing", False)]
    assert [x["action"] for x in e["audit"]] == ["consent_changed", "consent_changed", "consent_changed", "data_exported"]
    assert "otp" not in str(e).lower() and "verify_code" not in str(e)
    # восстановление согласия снова разрешает запись
    assert client.patch("/api/candidate/consents", json={"consent_152": True}, headers=N).json()["consent_152"] is True
    assert client.patch("/api/candidate/notif", json={"tg": False}, headers=N).status_code == 200
    me_id, pid = e["profile"]["id"], e["profile"]["public_id"]
    assert client.delete("/api/candidate/me", headers=N).json() == {"deleted": True}
    # public_id удалённого не выдаётся повторно: генератор пропускает его и берёт следующий
    letters, nums = iter([pid[0], "Q"]), iter([int(pid[2:]) - 1000, 234])
    monkeypatch.setattr(candidate.secrets, "choice", lambda _: next(letters))
    monkeypatch.setattr(candidate.secrets, "randbelow", lambda _: next(nums))
    with SessionLocal() as db:
        assert db.get(RetiredPublicId, pid) and candidate._new_public_id(db) == "Q-1234"
    assert client.get("/api/candidate/me", headers=N).status_code == 401
    with SessionLocal() as db:
        assert db.get(Candidate, me_id) is None and db.query(User).filter(User.email == "new@example.ru").count() == 0
        acts = [a.action for a in db.query(AuditLog).filter(AuditLog.subject_candidate_id == me_id).order_by(AuditLog.id)]
        assert acts == ["consent_changed"] * 3 + ["data_exported", "consent_changed", "account_deleted"], acts
        assert all("Новый" not in str(a.detail) for a in db.query(AuditLog).all())
        assert db.query(ConsentEvent).filter(ConsentEvent.candidate_id == me_id).count() == 7  # журнал согласий переживает удаление


def test_profile_waits_for_withdrawal(client):
    """Гонка save_profile × отзыв: пока отзыв держит строку кандидата (FOR UPDATE), save_profile ждёт,
    затем перечитывает согласие и получает 403 — «прочитал до отзыва, записал после» невозможно."""
    import threading
    import time

    from app.integrations.consent import lock_candidate

    with SessionLocal() as db:
        u = User(email="race@example.ru", role="candidate")
        db.add(u)
        db.flush()
        c = _cand("R-0009", user_id=u.id, consent_publish=False, consent_publish_version=None)
        db.add(c)
        db.commit()
        hdr, cid = {"Authorization": "Bearer " + issue_token(db, u)}, c.id
    body = {"name": "Гонка", "spec": "Backend", "grade_claimed": "Middle", "min_salary": 200000, "formats": ["Гибрид"], "city": "Москва", "consent_publish": True}
    out = {}
    with SessionLocal() as db:
        cand = lock_candidate(db, cid)  # «отзыв» начался и держит строку
        t = threading.Thread(target=lambda: out.update(r=client.post("/api/candidate/profile", json=body, headers=hdr)))
        t.start()
        time.sleep(0.5)
        assert t.is_alive()  # save_profile ждёт блокировку
        cand.consent_152, cand.consent_publish, cand.status = False, False, "off"
        db.commit()
    t.join(10)
    assert out["r"].status_code == 403, out["r"].text
    with SessionLocal() as db:
        assert db.get(Candidate, cid).consent_publish is False


def test_salary_upper_bound(client):
    """Сумма больше catalog.SALARY_MAX — 422 с русским сообщением во всех входах, а не 500 «integer out of range»."""
    huge = 10_000_000_000

    def too_big(r):
        assert r.status_code == 422, r.text
        assert any(e["type"] == "salary_max" and "10 000 000 ₽" in e["msg"] for e in r.json()["detail"]), r.text

    with SessionLocal() as db:
        u = User(email="rich@example.ru", role="candidate")
        db.add(u)
        db.commit()
        hdr = {"Authorization": "Bearer " + issue_token(db, u)}
    body = {"name": "Богач", "spec": "Backend", "grade_claimed": "Middle", "min_salary": huge, "formats": ["Гибрид"], "city": "Москва", "consent_152": True}
    too_big(client.post("/api/candidate/profile", json=body, headers=hdr))
    ok = client.post("/api/candidate/profile", json={**body, "min_salary": catalog.SALARY_MAX}, headers=hdr)  # граница включительно и влезает в integer
    assert ok.status_code == 200, ok.text
    with SessionLocal() as db:
        assert db.query(Candidate.min_salary).filter(Candidate.user_id == u.id).scalar() == catalog.SALARY_MAX
    need = {"spec": "Backend", "grade": "Middle", "salary_from": 240000, "salary_to": 300000}
    too_big(client.post("/api/employer/needs", json={**need, "salary_to": huge}, headers=E))
    too_big(client.post("/api/employer/needs", json={**need, "salary_from": huge}, headers=E))
    too_big(client.post("/api/employer/needs/category", json={"spec": "Backend", "grade": "Middle", "salary_to": huge}, headers=E))
    inv = {"candidate_id": "A-1042", "role": "Backend-разработчик", "format": "Гибрид", "salary_from": 240000, "salary_to": huge}
    too_big(client.post("/api/employer/invites", json=inv, headers=E))
    too_big(client.post("/api/employer/invites", json={**inv, "salary_from": huge}, headers=E))
    too_big(client.post("/api/lottery/", json={"need_id": 1, "threshold": {"fork_to": huge}, "draw_count": 1}, headers=E))


def test_reinvite(client):
    """Повтор той же компании: открытое — 409, истёкшее — можно, отказ — пауза REINVITE_AFTER_DECLINE_DAYS, принятое по потребности — никогда."""
    with SessionLocal() as db:
        db.query(Company).filter(Company.inn == INN).update({"quota_max": 10})
        db.add_all([_cand("V-0011"), _cand("V-0012")])
        db.commit()
    need_id = client.get("/api/employer/needs", headers=E).json()[-1]["id"]
    card = lambda pid, **q: client.get(f"/api/employer/candidates/{pid}", params=q, headers=E).json()  # noqa: E731
    inv = {"need_id": need_id, "role": "Backend (Python)", "salary_from": 240000, "salary_to": 300000, "format": "Гибрид"}
    post = lambda pid, **kw: client.post("/api/employer/invites", json={**inv, "candidate_id": pid, **kw}, headers=E)  # noqa: E731

    acc = post("V-0012").json()["invite"]["id"]
    with SessionLocal() as db:
        db.get(Invitation, acc).status = "accepted"
        db.commit()
    accepted = "Кандидат уже принял приглашение по этой потребности"
    assert card("V-0012", need_id=need_id)["invite_block"] == accepted
    assert post("V-0012").json()["detail"] == accepted
    assert card("V-0012")["invite_block"] is None  # без потребности или по другой — можно

    first = post("V-0011").json()["invite"]["id"]
    assert post("V-0011").json()["detail"] == "Кандидат уже приглашён"
    assert post("V-0011", need_id=None).json()["detail"] == "Кандидат уже приглашён"  # одно открытое на пару при любой потребности
    assert card("V-0011", need_id=need_id)["invite_block"] == "Кандидат уже приглашён"
    with SessionLocal() as db:  # две открытые строки по одной потребности не пропустит и сама база
        dup = Invitation(**{k: getattr(db.get(Invitation, first), k) for k in ("company_id", "candidate_id", "need_id", "role", "salary_from", "salary_to", "format", "expires_at")})
        db.add(dup)
        with pytest.raises(IntegrityError):
            db.commit()

    # истекло без ответа → «Пригласить снова», та же потребность, квота тратится заново
    with SessionLocal() as db:
        db.get(Invitation, first).expires_at = NOW - timedelta(hours=1)
        db.commit()
    c = card("V-0011", need_id=need_id)
    assert (c["invited"], c["invite_block"]) == ("exp", None)
    used = client.get("/api/employer/quota", headers=E).json()["used"]
    r = post("V-0011")
    assert r.status_code == 200 and r.json()["quota"]["used"] == used + 1
    second = r.json()["invite"]["id"]
    rows = [x for x in client.get("/api/employer/pipeline", headers=E).json()["items"] if x["cid"] == "V-0011"]
    assert [(x["id"], x["status"]) for x in rows] == [(second, "sent"), (first, "exp")]

    # отказ → пауза по любой потребности; после неё — снова можно
    with SessionLocal() as db:
        db.get(Invitation, second).status, db.get(Invitation, second).responded_at = "declined", NOW
        db.commit()
    for q in ({}, {"need_id": None}):
        r = post("V-0011", **q)
        assert r.status_code == 409 and r.json()["detail"].startswith("Кандидат отклонил приглашение; повторно — не раньше "), r.json()
    assert card("V-0011")["invite_block"].startswith("Кандидат отклонил приглашение")
    with SessionLocal() as db:
        db.get(Invitation, second).responded_at = NOW - timedelta(days=catalog.REINVITE_AFTER_DECLINE_DAYS + 1)
        db.commit()
    assert card("V-0011", need_id=need_id)["invite_block"] is None
    assert post("V-0011").status_code == 200
