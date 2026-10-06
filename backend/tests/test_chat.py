"""Внутренний чат: доступ по связи, согласие кандидата, раскрытие имени, непрочитанные, выгрузка и удаление. Своя БД (fsp_chat)."""

import asyncio
import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fsp:fsp@localhost:5432/fsp_chat")
os.environ["LLM_BASE_URL"] = ""
os.environ.setdefault("DEMO", "1")

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import catalog
from app.db import Base, SessionLocal, engine
from app.deps import issue_token
from app.main import app
from app.models import Application, AuditLog, Candidate, Company, Invitation, Message, User, Vacancy
from app.routers import chat as chat_router
from app.services.chat import MAX_LEN, RATE_LIMIT, hub

NOW = datetime.now(UTC)
H: dict[str, dict] = {}
IDS: dict[str, int] = {}


def _cand(pid, user_id, **kw) -> Candidate:
    base = dict(
        public_id=pid, user_id=user_id, name=f"Имя {pid}", email=f"{pid.lower()}@example.ru", tg=f"@{pid.lower()}",
        consent_152=True, consent_publish=True, consent_version=catalog.CONSENT_VERSION, consent_publish_version=catalog.CONSENT_VERSION,
        spec="Backend", track="Python", grade_claimed="Middle", grade="Middle", theta=1.0, se=0.2, percentile=70, min_salary=200_000,
        formats=["Удалённо"], city="Москва", tested_at=NOW - timedelta(days=10),
    )
    return Candidate(**{**base, **kw})


def _inv(co, cand, status) -> Invitation:
    return Invitation(company_id=co.id, candidate_id=cand.id, role="Dev", salary_from=250_000, salary_to=300_000, format="Удалённо",
                      sent_at=NOW, expires_at=NOW + timedelta(days=5), status=status)


@pytest.fixture(scope="module")
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        users = {k: User(email=f"{k}@example.ru", role=r) for k, r in [
            ("e1", "employer"), ("e2", "employer"), ("e0", "employer"), ("admin", "admin"),
            ("acc", "candidate"), ("dec", "candidate"), ("sent", "candidate"), ("app", "candidate"), ("rev", "candidate"), ("none", "candidate"),
        ]}
        db.add_all(users.values())
        db.flush()
        co1 = Company(user_id=users["e1"].id, inn="7704123450", name="Ладога Пэй", recruiter_name="М", recruiter_email="m@x.ru")
        co2 = Company(user_id=users["e2"].id, inn="500100732259", name="Чужая", recruiter_name="Ч", recruiter_email="c@x.ru")
        c = {k: _cand(pid, users[k].id, name=name) for k, pid, name in [
            ("acc", "A-0001", "Дмитрий Орлов"), ("dec", "A-0002", "Отказал Отказов"), ("sent", "A-0003", "Ждёт Ответа"),
            ("app", "A-0004", "Откликнулся Сам"), ("rev", "A-0005", "Отозвал Согласие"), ("none", "A-0006", "Без Связи"),
        ]}
        db.add_all([co1, co2, *c.values()])
        db.flush()
        v = Vacancy(company_id=co1.id, title="Python", spec="Backend", grade="Middle", salary_from=250_000, salary_to=300_000, format="Удалённо")
        db.add(v)
        db.flush()
        db.add_all([
            _inv(co1, c["acc"], "accepted"), _inv(co1, c["dec"], "declined"), _inv(co1, c["sent"], "sent"), _inv(co1, c["rev"], "accepted"),
            Application(vacancy_id=v.id, candidate_id=c["app"].id, status="sent"),
        ])
        db.commit()
        IDS.update(co1=co1.id, co2=co2.id, vac=v.id, **{k: x.id for k, x in c.items()})
        for k, u in users.items():
            H[k] = {"Authorization": f"Bearer {issue_token(db, u)}"}
    yield TestClient(app)


def pid(k):  # публичный id кандидата — peer работодателя
    return {"acc": "A-0001", "dec": "A-0002", "sent": "A-0003", "app": "A-0004", "rev": "A-0005", "none": "A-0006"}[k]


def say(client, who, peer, text="Привет"):
    return client.post(f"/api/chat/{peer}", json={"text": text}, headers=H[who])


def test_access_matrix(client):
    co1 = IDS["co1"]
    # приняли приглашение: пишут обе стороны
    assert say(client, "e1", pid("acc"), "Здравствуйте!").status_code == 200
    assert say(client, "acc", co1, "Добрый день").status_code == 200
    # отказ: читать историю можно, писать нельзя
    r = client.get(f"/api/chat/{pid('dec')}", headers=H["e1"])
    assert r.status_code == 200 and r.json()["can_write"] is False
    assert client.get(f"/api/chat/{pid('acc')}", headers=H["e1"]).json()["can_write"] is True
    assert say(client, "e1", pid("dec")).status_code == 403
    assert say(client, "dec", co1).status_code == 403
    # приглашение без ответа: чата ещё нет ни у кого (кандидат мог бы написать до принятия — нельзя)
    assert say(client, "e1", pid("sent")).status_code == 403
    assert say(client, "sent", co1).status_code == 403
    # чужая компания и кандидат без связи
    assert client.get(f"/api/chat/{pid('acc')}", headers=H["e2"]).status_code == 403
    assert say(client, "e2", pid("acc")).status_code == 403
    assert client.get(f"/api/chat/{IDS['co2']}", headers=H["acc"]).status_code == 403
    assert say(client, "none", co1).status_code == 403
    # несуществующие адресаты, чужие роли, вход
    assert client.get("/api/chat/Z-9999", headers=H["e1"]).status_code == 404
    assert client.get("/api/chat/99999", headers=H["acc"]).status_code == 404
    assert client.get("/api/chat/abc", headers=H["acc"]).status_code == 404
    assert client.get("/api/chat/99999999999999999999", headers=H["acc"]).status_code == 404
    assert client.get("/api/chat/%C2%B2", headers=H["acc"]).status_code == 404  # «²» — isdigit, но не число
    assert client.get(f"/api/chat/{pid('acc')}", headers=H["admin"]).status_code == 403
    assert client.get("/api/chat/unread", headers=H["admin"]).status_code == 403
    assert client.get(f"/api/chat/{pid('acc')}", headers=H["e0"]).status_code == 403  # компания не зарегистрирована
    assert client.get(f"/api/chat/{pid('acc')}").status_code == 401


def test_application_link(client):
    co1 = IDS["co1"]
    assert say(client, "e1", pid("app")).status_code == 200  # отклик не закрыт — контакты открыты, можно писать
    assert say(client, "app", co1).status_code == 200
    with SessionLocal() as db:
        a = db.scalar(select(Application).where(Application.candidate_id == IDS["app"]))
        a.status = "declined"
        db.commit()
    assert say(client, "e1", pid("app")).status_code == 403
    assert client.get(f"/api/chat/{pid('app')}", headers=H["e1"]).status_code == 200
    with SessionLocal() as db:
        db.scalar(select(Application).where(Application.candidate_id == IDS["app"])).status = "withdrawn"
        db.commit()
    assert say(client, "app", co1).status_code == 403
    with SessionLocal() as db:
        db.scalar(select(Application).where(Application.candidate_id == IDS["app"])).status = "sent"
        db.commit()


def test_validation_and_rate_limit(client):
    assert say(client, "e1", pid("acc"), "   ").status_code == 422
    assert say(client, "e1", pid("acc"), "а" * (MAX_LEN + 1)).status_code == 422
    assert say(client, "e1", pid("acc"), "а\x00б").status_code == 422  # NUL не принимает Postgres
    assert say(client, "e1", pid("acc"), "а" * MAX_LEN).status_code == 200
    with SessionLocal() as db:  # чистое окно лимита: сообщения других тестов старше минуты
        for m in db.scalars(select(Message)):
            m.created_at = NOW - timedelta(hours=1)
        db.commit()
    codes = [say(client, "e1", pid("acc"), f"m{i}").status_code for i in range(RATE_LIMIT + 1)]
    assert codes[:RATE_LIMIT] == [200] * RATE_LIMIT and codes[-1] == 429
    assert say(client, "acc", IDS["co1"], "ответ").status_code == 200  # лимит на сторону, не на диалог


def test_pagination(client):
    with SessionLocal() as db:
        ids = [m.id for m in db.scalars(select(Message).where(Message.candidate_id == IDS["acc"]).order_by(Message.id))]
    r = client.get(f"/api/chat/{pid('acc')}?limit=2", headers=H["e1"]).json()
    assert [m["id"] for m in r["messages"]] == ids[-2:] and r["more"] is True
    older = client.get(f"/api/chat/{pid('acc')}?limit=2&before_id={ids[-2]}", headers=H["e1"]).json()
    assert [m["id"] for m in older["messages"]] == ids[-4:-2]
    newer = client.get(f"/api/chat/{pid('acc')}?limit=2&after_id={ids[0]}", headers=H["e1"]).json()
    assert [m["id"] for m in newer["messages"]] == ids[1:3] and newer["more"] is False
    whole = client.get(f"/api/chat/{pid('acc')}?limit=100", headers=H["e1"]).json()
    assert [m["id"] for m in whole["messages"]] == ids and whole["more"] is False
    assert client.get(f"/api/chat/{pid('acc')}?before_id=5&after_id=1", headers=H["e1"]).status_code == 422
    assert client.get(f"/api/chat/{pid('acc')}?limit=0", headers=H["e1"]).status_code == 422


def test_unread_contacts_read(client):
    co1 = IDS["co1"]
    u = client.get("/api/chat/unread", headers=H["acc"]).json()["unread_count"]
    assert u >= RATE_LIMIT  # то, что написал работодатель
    cs = client.get("/api/chat/contacts", headers=H["acc"]).json()["contacts"]
    assert [x["peer_id"] for x in cs] == [co1] and cs[0]["peer_name"] == "Ладога Пэй" and cs[0]["unread_count"] == u
    assert cs[0]["last_message"]["sender"] == "candidate"
    # прочитать чужие сообщения; свои остаются непрочитанными у собеседника
    assert client.post(f"/api/chat/{co1}/read", headers=H["acc"]).json() == {"ok": True}
    assert client.get("/api/chat/unread", headers=H["acc"]).json()["unread_count"] == 0
    msgs = client.get(f"/api/chat/{pid('acc')}?limit=100", headers=H["e1"]).json()["messages"]
    assert all(m["read_at"] for m in msgs if m["sender"] == "employer") and any(m["read_at"] is None for m in msgs if m["sender"] == "candidate")
    assert client.get("/api/chat/unread", headers=H["e1"]).json()["unread_count"] >= 2
    es = client.get("/api/chat/contacts", headers=H["e1"]).json()["contacts"]
    assert {x["peer_id"] for x in es} >= {pid("acc"), pid("app")}
    assert client.get("/api/chat/unread", headers=H["e0"]).status_code == 403


def test_candidate_name_follows_reveal_rules(client):
    # принятое приглашение — имя открыто
    assert client.get(f"/api/chat/{pid('acc')}", headers=H["e1"]).json()["peer"]["name"] == "Дмитрий Орлов"
    # отклик — имя открыто и раскрытие записано в журнал один раз, без ПДн в detail
    for _ in range(2):
        assert client.get(f"/api/chat/{pid('app')}", headers=H["e1"]).json()["peer"]["name"] == "Откликнулся Сам"
    client.get("/api/chat/contacts", headers=H["e1"])
    with SessionLocal() as db:
        logs = db.scalars(select(AuditLog).where(AuditLog.subject_candidate_id == IDS["app"], AuditLog.action == "contacts_revealed")).all()
        assert len(logs) == 1 and "Откликнулся" not in str([x.detail for x in logs])
        # после отказа в приглашении имя не открывается: кандидата зовут по публичному id
        db.add(Message(company_id=IDS["co1"], candidate_id=IDS["dec"], sender="employer", text="старое"))
        db.commit()
    assert client.get(f"/api/chat/{pid('dec')}", headers=H["e1"]).json()["peer"]["name"] == "Кандидат A-0002"
    names = {x["peer_id"]: x["peer_name"] for x in client.get("/api/chat/contacts", headers=H["e1"]).json()["contacts"]}
    assert names[pid("dec")] == "Кандидат A-0002" and names[pid("acc")] == "Дмитрий Орлов"


def test_consent_revoked_hides_dialog_from_employer(client):
    assert say(client, "e1", pid("rev"), "Расскажите о себе").status_code == 200
    assert client.get("/api/chat/unread", headers=H["rev"]).json()["unread_count"] == 1
    with SessionLocal() as db:
        db.get(Candidate, IDS["rev"]).consent_152 = False
        db.commit()
    assert client.get(f"/api/chat/{pid('rev')}", headers=H["e1"]).status_code == 403
    assert say(client, "e1", pid("rev")).status_code == 403
    assert client.post(f"/api/chat/{pid('rev')}/read", headers=H["e1"]).status_code == 403
    assert pid("rev") not in [x["peer_id"] for x in client.get("/api/chat/contacts", headers=H["e1"]).json()["contacts"]]
    # сам кандидат без действующего согласия не пишет, но свою переписку видит
    assert say(client, "rev", IDS["co1"]).status_code == 403
    assert client.get(f"/api/chat/{IDS['co1']}", headers=H["rev"]).status_code == 200
    # смена редакции текста согласия действует так же: версия не совпадает — доступа нет
    with SessionLocal() as db:
        k = db.get(Candidate, IDS["rev"])
        k.consent_152, k.consent_version = True, "2020-01"
        db.commit()
    assert client.get(f"/api/chat/{pid('rev')}", headers=H["e1"]).status_code == 403


def test_hidden_from_company_closes_dialog(client):
    inn = "7704123450"
    with SessionLocal() as db:
        db.get(Candidate, IDS["app"]).hidden_from = [inn]
        db.commit()
    assert client.get(f"/api/chat/{pid('app')}", headers=H["e1"]).status_code == 403
    assert say(client, "e1", pid("app")).status_code == 403
    assert pid("app") not in [x["peer_id"] for x in client.get("/api/chat/contacts", headers=H["e1"]).json()["contacts"]]
    assert client.get(f"/api/chat/{IDS['co1']}", headers=H["app"]).status_code == 200  # свою переписку кандидат видит
    with SessionLocal() as db:
        db.get(Candidate, IDS["app"]).hidden_from = []
        db.commit()
    assert client.get(f"/api/chat/{pid('app')}", headers=H["e1"]).status_code == 200


def test_stream_notifies_on_new_message(client, monkeypatch):
    monkeypatch.setattr(chat_router, "KEEPALIVE", 0.05)
    assert client.get("/api/chat/stream").status_code == 401
    assert client.get("/api/chat/stream", headers=H["admin"]).status_code == 403

    class Req:
        gone = False

        async def is_disconnected(self):
            return self.gone

    async def run():
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.email == "acc@example.ru"))
            req = Req()
            resp = await chat_router.stream(req, user, db)
            it = resp.body_iterator
            assert await anext(it) == ": ok\n\n"
            assert ("candidate", IDS["acc"]) in hub.subs
            with SessionLocal() as db2:  # окно лимита чистое: сообщения прошлых тестов старше минуты
                for m in db2.scalars(select(Message)):
                    m.created_at = NOW - timedelta(hours=1)
                db2.commit()
            r = await asyncio.to_thread(say, client, "e1", pid("acc"), "для потока")
            assert r.status_code == 200
            frames = []
            for _ in range(100):  # между кадрами могут быть служебные строки
                frames.append(await asyncio.wait_for(anext(it), 5))
                if frames[-1] == "data: new\n\n":
                    break
            assert frames[-1] == "data: new\n\n"
            req.gone = True
            async for _ in it:  # поток сам заканчивается после обрыва клиента
                pass
            assert ("candidate", IDS["acc"]) not in hub.subs

    asyncio.run(run())


def test_chat_peer_in_lists(client):
    inv = {i["company"]: i for i in client.get("/api/candidate/invites", headers=H["acc"]).json()["items"]}
    assert inv["Ладога Пэй"]["chat_peer"] == IDS["co1"]
    assert client.get("/api/candidate/invites", headers=H["dec"]).json()["items"][0]["chat_peer"] is None
    assert client.get("/api/candidate/invites", headers=H["sent"]).json()["items"][0]["chat_peer"] is None
    one = client.get(f"/api/candidate/invites/{inv['Ладога Пэй']['id']}", headers=H["acc"]).json()
    assert one["chat_peer"] == IDS["co1"]
    pipe = {x["cid"]: x["chat_peer"] for x in client.get("/api/employer/pipeline", headers=H["e1"]).json()["items"]}
    assert pipe[pid("acc")] == pid("acc") and pipe[pid("dec")] is None and pipe[pid("sent")] is None
    assert client.get(f"/api/employer/candidates/{pid('acc')}", headers=H["e1"]).json()["chat_peer"] == pid("acc")
    assert client.get(f"/api/employer/candidates/{pid('none')}", headers=H["e1"]).json()["chat_peer"] is None
    apps = client.get(f"/api/vacancies/{IDS['vac']}/applications", headers=H["e1"]).json()["items"]
    assert apps[0]["chat_peer"] == pid("app")
    mine = client.get("/api/vacancies/applications/mine", headers=H["app"]).json()["items"]
    assert mine[0]["chat_peer"] == IDS["co1"]


def test_export_and_delete(client):
    out = client.get("/api/candidate/me/export", headers=H["acc"]).json()
    assert len(out["messages"]) >= 20 and {m["sender"] for m in out["messages"]} == {"employer", "candidate"}
    assert client.delete("/api/candidate/me", headers=H["acc"]).json() == {"deleted": True}
    with SessionLocal() as db:
        assert db.scalar(select(Message.id).where(Message.candidate_id == IDS["acc"])) is None
    assert client.get(f"/api/chat/{pid('acc')}", headers=H["e1"]).status_code == 404
    assert pid("acc") not in [x["peer_id"] for x in client.get("/api/chat/contacts", headers=H["e1"]).json()["contacts"]]
