"""Квалифицированная лотерея: порог → пул → жребий → проверка. Всё в транзакции, откатывается в конце."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import models  # noqa: F401
from app.catalog import CONSENT_VERSION
from app.db import Base, engine, get_db
from app.deps import current_company
from app.models import Candidate, Company, Invitation, Lottery, Need
from app.routers import lottery
from app.services.lottery import draw_order, is_drawn, pseudonym

NOW = datetime.now(UTC)
TAG = "zz-" + uuid.uuid4().hex[:8]
INN = "99" + str(uuid.uuid4().int)[:8]  # уникальный «навык»: изолирует пул теста от засеянных данных


@pytest.fixture
def env():
    Base.metadata.create_all(engine)
    conn = engine.connect()
    tx = conn.begin()
    db = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    co = Company(inn=INN, name="Тест", recruiter_name="Р", recruiter_email="r@t.example")
    other = Company(inn=INN[:-1] + "x", name="Другая", recruiter_name="Р", recruiter_email="r2@t.example")
    needs = [Need(company=co, text="t", spec="Backend", track="Python", grade="Middle", must=["Python"], salary_to=300000,
                  format="Гибрид") for _ in range(2)]
    db.add_all([co, other, *needs])

    def cand(i, **kw):
        f = dict(public_id=f"T-{TAG[-4:]}{i:02d}"[:16], name=f"Иван Тестов{i}", email=f"t{i}@example.ru", tg=f"@t{i}",
                 spec="Backend", track="Python", grade_claimed="Middle", grade="Middle", theta=1.0, se=0.2,
                 percentile=70, min_salary=250000, formats=["Гибрид"], city="Москва", status="open", consent_publish=True,
                 consent_152=True, consent_version=CONSENT_VERSION, consent_publish_version=CONSENT_VERSION,
                 skills_confirmed=["Python", "PostgreSQL", TAG], tested_at=NOW)
        return Candidate(**{**f, **kw})

    good = [cand(i) for i in range(12)]
    bad = [
        cand(20, min_salary=400000),  # дороже вилки
        cand(21, grade="Junior", theta=0.3),  # ниже грейда
        cand(22, skills_confirmed=["Python", TAG]),  # нет обязательного навыка
        cand(23, status="off"),
        cand(24, hidden_from=[INN]),  # скрыт от этой компании
        cand(25, theta=0.6, se=0.3),  # θ − SE = 0.3 < theta_min
        cand(27, consent_publish=False),  # не согласился показывать карточку работодателям
        cand(28, consent_version="2020-01"),  # согласие на старую редакцию текста
        cand(26),  # у потолка нагрузки
    ]
    db.add_all(good + bad)
    for st in ("sent", "seen", "sent", "seen"):  # потолок: 4 открытых приглашения от другой компании
        db.add(Invitation(company=other, candidate=bad[-1], role="x", salary_from=1, salary_to=2, format="Удалённо",
                          status=st, expires_at=NOW + timedelta(days=3)))
    db.flush()
    NEED.update(a=needs[0].id, b=needs[1].id)

    app = FastAPI()
    app.include_router(lottery.router)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[current_company] = lambda: co
    yield TestClient(app), db, good, bad
    db.close()
    tx.rollback()
    conn.close()


NEED: dict[str, int] = {}
TH = {"spec": "Backend", "track": "Python", "grade_min": "Middle", "theta_min": 0.5, "must_skills": ["PostgreSQL"],
      "fork_to": 300000, "formats": ["Гибрид"], "require_free": True}


def test_lottery_flow(env):
    client, db, good, _ = env
    th = {**TH, "must_skills": ["PostgreSQL", TAG]}
    r = client.post("/api/lottery/", json={"need_id": NEED["a"], "threshold": th, "draw_count": 3})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["pool_size"] == len(good) and len(body["seed_hash"]) == 64

    state = client.get(f"/api/lottery/{body['id']}").json()
    assert state["status"] == "frozen" and state["seed"] is None  # до розыгрыша seed не раскрыт
    salt = db.get(Lottery, body["id"]).salt
    assert "salt" not in state and salt not in str(state)  # соль наружу не отдаётся
    assert state["pool_ids"] == sorted(pseudonym(salt, c.public_id) for c in good)  # в пуле только псевдонимы
    assert not any(c.public_id in str(state) for c in good)
    assert client.get(f"/api/lottery/{body['id']}/verify").status_code == 409

    d = client.post(f"/api/lottery/{body['id']}/draw").json()
    assert len(d["drawn"]) == 3
    assert [c["pseudonym"] for c in d["drawn"]] == draw_order(d["seed"], d["pool_ids"], 3)  # детерминизм
    assert all(c["pseudonym"] == pseudonym(salt, c["public_id"]) for c in d["drawn"])  # владельцу — карточки вытянутых
    lot = db.get(Lottery, body["id"])
    picked = {c["public_id"] for c in d["drawn"]}
    assert all(is_drawn(lot, c) == (c.public_id in picked) for c in good)
    assert [c["public_id"] for c in client.get(f"/api/lottery/{body['id']}").json()["drawn"]] == [c["public_id"] for c in d["drawn"]]
    pii = {"name", "email", "tg", "city", "user_id"}
    for card in d["drawn"]:
        assert not pii & set(card) and "Тестов" not in str(card)
    assert client.post(f"/api/lottery/{body['id']}/draw").status_code == 409  # повторно нельзя

    v = client.get(f"/api/lottery/{body['id']}/verify").json()
    assert v == {"ok": True, "hash_ok": True, "commitment_ok": True, "draw_ok": True,
                 "drawn_ids": [c["pseudonym"] for c in d["drawn"]]}


def test_pool_too_small(env):
    client, *_ = env
    r = client.post("/api/lottery/", json={"need_id": NEED["a"], "threshold": {**TH, "must_skills": ["PostgreSQL", TAG]}, "draw_count": 12})
    assert r.status_code == 422  # 12 прошли порог, жребий из 12 на 12 не нужен
    r = client.post("/api/lottery/", json={"need_id": NEED["a"], "threshold": {**TH, "spec": "Кулинария"}, "draw_count": 1})
    assert r.status_code == 422


def test_recent_decline_or_expiry_excluded(env):
    """Отклонил или промолчал на приглашение этой компании за 90 дней — в пул не попадает."""
    client, db, good, _ = env
    co = db.scalar(select(Company).where(Company.inn == INN))
    other = db.scalar(select(Company).where(Company.inn == INN[:-1] + "x"))

    def inv(company, c, status, days_ago):
        sent = NOW - timedelta(days=days_ago)
        db.add(Invitation(company=company, candidate=c, role="x", salary_from=1, salary_to=2, format="Гибрид",
                          status=status, sent_at=sent, responded_at=sent + timedelta(days=1) if status == "declined" else None,
                          expires_at=sent + timedelta(days=7)))

    inv(co, good[0], "declined", 10)  # недавний отказ → исключён
    inv(co, good[1], "expired", 20)  # недавно истекло → исключён
    inv(co, good[2], "sent", 30)  # истекло, но статус ещё не обновлён → тоже исключён
    inv(co, good[3], "declined", 120)  # отказ давно → снова в пуле
    inv(other, good[4], "declined", 5)  # отказ другой компании не мешает
    db.flush()
    r = client.post("/api/lottery/", json={"need_id": NEED["a"], "threshold": {**TH, "must_skills": ["PostgreSQL", TAG]}, "draw_count": 3})
    pool = client.get(f"/api/lottery/{r.json()['id']}").json()["pool_ids"]
    assert pool == sorted(pseudonym(db.get(Lottery, r.json()["id"]).salt, c.public_id) for c in good[3:])


def test_one_lottery_per_need(env):
    """Перебросить жребий на ту же потребность нельзя; need_id обязателен."""
    client, *_ = env
    body = {"need_id": NEED["a"], "threshold": {**TH, "must_skills": ["PostgreSQL", TAG]}, "draw_count": 3}
    assert client.post("/api/lottery/", json=body).status_code == 200
    r = client.post("/api/lottery/", json=body)
    assert r.status_code == 409 and "уже проведена" in r.json()["detail"]
    assert client.post("/api/lottery/", json={**body, "need_id": NEED["b"]}).status_code == 200
    assert client.post("/api/lottery/", json={k: v for k, v in body.items() if k != "need_id"}).status_code == 422


def test_commitment_checked(env):
    """Commitment фиксирует порог, пул и число мест: подмена любого из них после создания ловится проверкой."""
    client, db, *_ = env
    r = client.post("/api/lottery/", json={"need_id": NEED["a"], "threshold": {**TH, "must_skills": ["PostgreSQL", TAG]},
                                           "draw_count": 3}).json()
    assert len(r["commitment"]) == 64 and client.get(f"/api/lottery/{r['id']}").json()["commitment"] == r["commitment"]
    client.post(f"/api/lottery/{r['id']}/draw")
    lot = db.get(Lottery, r["id"])
    lot.pool_ids = lot.pool_ids[:-1]  # «тихо» выкинули кандидата из пула
    lot.drawn_ids = draw_order(lot.seed, lot.pool_ids, lot.draw_count)
    db.flush()
    v = client.get(f"/api/lottery/{r['id']}/verify").json()
    assert v["hash_ok"] and v["draw_ok"] and not v["commitment_ok"] and not v["ok"]


def test_public_view_without_auth(env):
    """Публичная проверка: без авторизации и без ПДн; seed — только после розыгрыша."""
    client, db, good, _ = env
    r = client.post("/api/lottery/", json={"need_id": NEED["a"], "threshold": {**TH, "must_skills": ["PostgreSQL", TAG]},
                                           "draw_count": 3}).json()
    anon = FastAPI()  # без подмены current_company: если бы эндпоинт требовал вход, был бы 401
    anon.include_router(lottery.router)
    anon.dependency_overrides[get_db] = lambda: db
    pub = TestClient(anon)
    assert pub.get(f"/api/lottery/{r['id']}").status_code == 401
    before = pub.get(f"/api/lottery/{r['id']}/public").json()
    assert before["seed"] is None and before["commitment"] == r["commitment"] and before["verify"] is None
    client.post(f"/api/lottery/{r['id']}/draw")
    after = pub.get(f"/api/lottery/{r['id']}/public").json()
    assert after["verify"]["ok"] and len(after["drawn_ids"]) == 3 and after["seed"]
    text = str(after)
    assert not {"need_id", "company_id", "name", "email", "tg"} & set(after)
    assert all(c.name not in text and c.email not in text and c.tg not in text and c.public_id not in text for c in good)
    assert "salt" not in after and db.get(Lottery, r["id"]).salt not in text and "drawn" not in after
    assert pub.get("/api/lottery/999999999/public").status_code == 404


def test_threshold_bound_to_need(env):
    """Порог строится от потребности: клиент может только ужесточать. Компания в фикстуре не подтверждена — лотерея доступна."""
    client, *_ = env
    base = {"need_id": NEED["a"], "draw_count": 3}
    for bad in ({"spec": "QA"}, {"track": "Go"}, {"grade_min": "Intern"}, {"fork_to": 350000}, {"formats": ["Удалённо"]}):
        r = client.post("/api/lottery/", json={**base, "threshold": {"must_skills": [TAG], **bad}})
        assert r.status_code == 422, (bad, r.text)
    r = client.post("/api/lottery/", json={**base, "threshold": {"must_skills": [TAG], "theta_min": 0.5}})
    assert r.status_code == 200, r.text
    th = r.json()["threshold"]
    assert th["spec"] == "Backend" and th["track"] == "Python" and th["grade_min"] == "Junior"
    assert th["must_skills"] == ["Python", TAG] and th["fork_to"] == 300000 and th["formats"] == ["Гибрид"]


def test_drawn_card_hidden_after_consent_revoked(env):
    """Отозвал согласие после жребия — владелец видит только {pseudonym, hidden}, без public_id и карточки."""
    client, db, good, _ = env
    r = client.post("/api/lottery/", json={"need_id": NEED["a"], "threshold": {**TH, "must_skills": ["PostgreSQL", TAG]},
                                           "draw_count": 3}).json()
    d = client.post(f"/api/lottery/{r['id']}/draw").json()
    first = next(c for c in good if c.public_id == d["drawn"][0]["public_id"])
    first.consent_publish = False
    db.flush()
    cards = client.get(f"/api/lottery/{r['id']}").json()["drawn"]
    assert cards[0] == {"pseudonym": d["drawn"][0]["pseudonym"], "hidden": True}
    assert all("public_id" in c and not c.get("hidden") for c in cards[1:])
    assert first.public_id not in str(cards)
    # второй сбросил тест сменой специализации после жребия — тоже скрыт
    second = next(c for c in good if c.public_id == d["drawn"][1]["public_id"])
    second.grade = second.theta = None
    db.flush()
    cards = client.get(f"/api/lottery/{r['id']}").json()["drawn"]
    assert cards[1] == {"pseudonym": d["drawn"][1]["pseudonym"], "hidden": True} and second.public_id not in str(cards)
