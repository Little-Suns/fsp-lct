"""События ATS (OutboxEvent): эмиссия из откликов, приглашений, истечения, отзыва доступа. Payload — только id и статусы.
Своя БД (fsp_ats)."""

import json
import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fsp:fsp@127.0.0.1:5432/fsp_ats")
os.environ.setdefault("DEMO", "1")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import catalog, deps
from app.db import Base, SessionLocal, engine
from app.deps import issue_token
from app.models import Application, Candidate, Company, Invitation, OutboxEvent, User, Vacancy
from app.routers import candidate, employer, vacancies
from app.services import matching, reputation

NOW = datetime.now(UTC)
H: dict[str, dict] = {}
ID: dict[str, int] = {}
REASON = next(iter(catalog.DECLINE_REASONS))
NAMES = ["app", "wd", "i_seen", "i_acc", "i_dec", "i_exp", "i_blk", "r_consent", "r_hidden", "r_del", "r_late"]


def _cand(i: int, user_id: int) -> Candidate:
    return Candidate(
        public_id=f"E-{i:04d}", user_id=user_id, name=f"Секретное Имя {i}", email=f"secret{i}@example.ru", tg=f"@secret{i}", consent_152=True,
        consent_publish=True, consent_version=catalog.CONSENT_VERSION, consent_publish_version=catalog.CONSENT_VERSION, spec="Backend",
        track="Python", grade_claimed="Middle", grade="Middle", theta=1.0, se=0.2, percentile=70, min_salary=200000, formats=["Гибрид"],
        city="Москва", skills_confirmed=["Python"], skills_claimed=["Python"], tested_at=NOW - timedelta(days=60),
    )


def _inv(co: Company, c: Candidate, status: str = "sent", expires: timedelta = timedelta(days=5)) -> Invitation:
    return Invitation(company_id=co.id, candidate_id=c.id, role="Backend (Python)", salary_from=240000, salary_to=300000, format="Гибрид",
                      status=status, sent_at=NOW - timedelta(days=1), expires_at=NOW + expires)


def _pid(name: str) -> str:
    return f"E-{NAMES.index(name):04d}"


@pytest.fixture(scope="module")
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        users = [User(email=f"{n}@example.ru", role="candidate") for n in NAMES]
        eu, eu2 = User(email="hr@one.example", role="employer"), User(email="hr@two.example", role="employer")
        db.add_all([*users, eu, eu2])
        db.flush()
        cands = [_cand(i, u.id) for i, u in enumerate(users)]
        co = Company(user_id=eu.id, inn="7704123450", name="Первая", site_domain="one.example", recruiter_name="HR", recruiter_email="hr@one.example", verified=True)
        co2 = Company(user_id=eu2.id, inn="7707083893", name="Вторая", site_domain="two.example", recruiter_name="HR", recruiter_email="hr@two.example", verified=True)
        db.add_all([*cands, co, co2])
        db.flush()
        by = dict(zip(NAMES, cands))
        v = Vacancy(company_id=co.id, title="Backend", spec="Backend", track="Python", grade="Middle", salary_from=240000, salary_to=300000, format="Гибрид")
        db.add(v)
        db.flush()
        ID.update(co=co.id, co2=co2.id, v=v.id, **{f"c_{n}": c.id for n, c in by.items()})
        invs = {
            "i_seen": _inv(co, by["i_seen"]), "i_acc": _inv(co, by["i_acc"]), "i_dec": _inv(co, by["i_dec"]),
            "i_exp": _inv(co, by["i_exp"], "seen", timedelta(days=-1)), "i_blk": _inv(co, by["i_blk"]),
            # r_*: у «Первой» принятое приглашение (контакты открыты), у «Второй» — только отправленное
            "r_consent": _inv(co, by["r_consent"], "accepted"), "r_hidden": _inv(co, by["r_hidden"], "accepted"),
            "r_del": _inv(co, by["r_del"], "accepted"), "r_hidden2": _inv(co2, by["r_hidden"]),
        }
        db.add_all(invs.values())
        db.flush()
        ID.update({f"inv_{k}": i.id for k, i in invs.items()})
        # r_late: принятый отклик на вакансию «Первой» — контакты открыты и по нему
        db.add(Application(vacancy_id=v.id, candidate_id=by["r_late"].id, status="accepted"))
        db.commit()
        for n, u in zip(NAMES, users):
            H[n] = {"Authorization": "Bearer " + issue_token(db, u)}
        H["e"] = {"Authorization": "Bearer " + issue_token(db, eu)}
    app = FastAPI()
    for r in (deps, candidate, employer, vacancies):
        app.include_router(r.router)
    yield TestClient(app)


def _events(**kw) -> list[OutboxEvent]:
    with SessionLocal() as db:
        q = select(OutboxEvent).order_by(OutboxEvent.id)
        for k, v in kw.items():
            q = q.where(getattr(OutboxEvent, k) == v)
        return list(db.scalars(q))


def _ev(type: str, **match) -> list[OutboxEvent]:
    return [e for e in _events(type=type) if all(e.payload.get(k) == v for k, v in match.items())]


def _revoked(name: str) -> list[tuple[int, str]]:
    return [(e.company_id, e.payload["why"]) for e in _ev("candidate.access_revoked", public_id=_pid(name))]


def test_application_flow(client):
    r = client.post(f"/api/vacancies/{ID['v']}/apply", json={}, headers=H["app"])
    assert r.status_code == 200
    aid = r.json()["id"]
    (e,) = _ev("application.created", application_id=aid)
    assert e.company_id == ID["co"]
    assert e.payload == {"application_id": aid, "vacancy_id": ID["v"], "status": "sent"}
    # дубль отклика — 409, второго события нет
    assert client.post(f"/api/vacancies/{ID['v']}/apply", json={}, headers=H["app"]).status_code == 409
    assert len(_ev("application.created", application_id=aid)) == 1
    st = f"/api/vacancies/applications/{aid}/status"
    assert client.post(st, json={"status": "seen"}, headers=H["e"]).status_code == 200
    (e,) = _ev("application.status", application_id=aid, status="seen")
    assert e.payload == {"application_id": aid, "vacancy_id": ID["v"], "status": "seen", "reason": None}
    # принятие: событие пишется вместе с раскрытием контактов (_reveal коммитит)
    assert client.post(st, json={"status": "accepted"}, headers=H["e"]).status_code == 200
    (e,) = _ev("application.status", application_id=aid, status="accepted")
    assert e.payload["reason"] is None
    # из accepted переходов нет: 409 и без нового события
    n = len(_events(type="application.status"))
    assert client.post(st, json={"status": "declined", "reason": REASON}, headers=H["e"]).status_code == 409
    assert len(_events(type="application.status")) == n


def test_application_declined_and_withdrawn(client):
    aid = client.post(f"/api/vacancies/{ID['v']}/apply", json={}, headers=H["wd"]).json()["id"]
    st = f"/api/vacancies/applications/{aid}/status"
    n = len(_events(type="application.status"))
    assert client.post(st, json={"status": "declined"}, headers=H["e"]).status_code == 422  # без причины
    assert len(_events(type="application.status")) == n
    assert client.post(st, json={"status": "declined", "reason": REASON}, headers=H["e"]).status_code == 200
    (e,) = _ev("application.status", application_id=aid, status="declined")
    assert e.payload["reason"] == REASON
    # отозвать после ответа нельзя — события нет
    assert client.post(f"/api/vacancies/applications/{aid}/withdraw", headers=H["wd"]).status_code == 409
    assert not _ev("application.withdrawn", application_id=aid)
    with SessionLocal() as db:
        db.get(Application, aid).status = "sent"
        db.commit()
    assert client.post(f"/api/vacancies/applications/{aid}/withdraw", headers=H["wd"]).status_code == 200
    (e,) = _ev("application.withdrawn", application_id=aid)
    assert e.company_id == ID["co"] and e.payload == {"application_id": aid, "vacancy_id": ID["v"], "status": "withdrawn"}


def test_invitation_seen_accept_decline(client):
    iid = ID["inv_i_seen"]
    assert client.get(f"/api/candidate/invites/{iid}", headers=H["i_seen"]).status_code == 200
    client.get(f"/api/candidate/invites/{iid}", headers=H["i_seen"])  # повторный просмотр — без события
    (e,) = _ev("invitation.seen", invitation_id=iid)
    assert e.company_id == ID["co"] and e.payload == {"invitation_id": iid, "status": "seen", "reason": None}

    iid = ID["inv_i_acc"]
    assert client.post(f"/api/candidate/invites/{iid}/accept", headers=H["i_acc"]).status_code == 200
    (e,) = _ev("invitation.accepted", invitation_id=iid)
    assert e.payload == {"invitation_id": iid, "status": "accepted", "reason": None}
    assert client.post(f"/api/candidate/invites/{iid}/accept", headers=H["i_acc"]).status_code == 409
    assert len(_ev("invitation.accepted", invitation_id=iid)) == 1

    iid = ID["inv_i_dec"]
    assert client.post(f"/api/candidate/invites/{iid}/decline", json={"reason": "nope"}, headers=H["i_dec"]).status_code == 422
    assert not _ev("invitation.declined", invitation_id=iid)
    assert client.post(f"/api/candidate/invites/{iid}/decline", json={"reason": REASON}, headers=H["i_dec"]).status_code == 200
    (e,) = _ev("invitation.declined", invitation_id=iid)
    assert e.payload == {"invitation_id": iid, "status": "declined", "reason": REASON}


def test_expiry(client):
    iid = ID["inv_i_exp"]
    assert client.post(f"/api/candidate/invites/{iid}/accept", headers=H["i_exp"]).status_code == 409  # срок вышел
    (e,) = _ev("invitation.expired", invitation_id=iid)
    assert e.company_id == ID["co"] and e.payload == {"invitation_id": iid, "status": "expired", "reason": None}
    with SessionLocal() as db:  # повторное истечение событие не плодит
        matching.expire_invites(db)
    assert len(_ev("invitation.expired", invitation_id=iid)) == 1


def test_expiry_on_block_before_accept(client):
    iid = ID["inv_i_blk"]
    with SessionLocal() as db:
        db.get(Company, ID["co"]).blocked_at = NOW
        db.commit()
    try:
        assert client.post(f"/api/candidate/invites/{iid}/accept", headers=H["i_blk"]).status_code == 409
    finally:
        with SessionLocal() as db:
            db.get(Company, ID["co"]).blocked_at = None
            db.commit()
    (e,) = _ev("invitation.expired", invitation_id=iid)
    assert e.payload["status"] == "expired"
    assert not _ev("invitation.accepted", invitation_id=iid)


def test_expiry_on_company_block():
    with SessionLocal() as db:
        co = db.get(Company, ID["co2"])
        open_ids = set(db.scalars(select(Invitation.id).where(Invitation.company_id == co.id, Invitation.status.in_(("sent", "seen")))))
        assert open_ids
        # блок по отзывам: два разных кандидата с «вакансии не было»
        for name in ("app", "wd"):
            db.add(Invitation(company_id=co.id, candidate_id=ID[f"c_{name}"], role="Backend", salary_from=1, salary_to=2, format="Гибрид", status="accepted",
                              company_feedback="fraud", company_feedback_at=NOW, sent_at=NOW, expires_at=NOW))
        db.flush()
        assert reputation.check_block(db, co) is True
        db.commit()
    for inv_id in open_ids:
        (e,) = _ev("invitation.expired", invitation_id=inv_id)
        assert e.company_id == ID["co2"]


def test_access_revoked(client):
    # отзыв согласия на обработку: событие только «Первой» (у неё принятое приглашение), «Второй» ничего не открыто
    assert client.patch("/api/candidate/consents", json={"consent_152": False}, headers=H["r_consent"]).status_code == 200
    assert _revoked("r_consent") == [(ID["co"], "consent")]
    client.patch("/api/candidate/consents", json={"consent_152": False}, headers=H["r_consent"])  # повтор — без нового события
    assert _revoked("r_consent") == [(ID["co"], "consent")]

    # скрытие: только от компаний по новым ИНН; «Вторая» контактов не видела — события нет
    assert client.patch("/api/candidate/hidden-from", json={"inns": ["7707083893"]}, headers=H["r_hidden"]).status_code == 200
    assert _revoked("r_hidden") == []
    both = {"inns": ["7707083893", "7704123450"]}
    assert client.patch("/api/candidate/hidden-from", json=both, headers=H["r_hidden"]).status_code == 200
    assert _revoked("r_hidden") == [(ID["co"], "hidden")]
    client.patch("/api/candidate/hidden-from", json=both, headers=H["r_hidden"])  # те же ИНН — без события
    assert _revoked("r_hidden") == [(ID["co"], "hidden")]

    # удаление аккаунта: событие остаётся в ленте
    assert client.delete("/api/candidate/me", headers=H["r_del"]).status_code == 200
    assert _revoked("r_del") == [(ID["co"], "deleted")]


def test_access_revoked_by_application(client):
    # принятый отклик тоже открывает контакты — отзыв согласия уходит компании вакансии
    assert client.patch("/api/candidate/consents", json={"consent_152": False}, headers=H["r_late"]).status_code == 200
    assert _revoked("r_late") == [(ID["co"], "consent")]


def test_no_pii_and_rollback(client):
    blob = json.dumps([e.payload for e in _events()], ensure_ascii=False).lower()
    for bad in ("secret", "@example.ru", "имя"):
        assert bad not in blob
    # откат: отклик на закрытую вакансию — 409, события нет
    with SessionLocal() as db:
        db.get(Vacancy, ID["v"]).status = "closed"
        db.commit()
    n = len(_events())
    assert client.post(f"/api/vacancies/{ID['v']}/apply", json={}, headers=H["i_seen"]).status_code == 409
    assert len(_events()) == n


def test_emit_takes_company_advisory_lock():
    """Порядок коммитов событий компании = порядок id: emit берёт advisory-блокировку компании до INSERT."""
    from sqlalchemy import text
    from app.services import ats
    q = text("select count(*) from pg_locks where locktype='advisory' and classid=:ns and objid=:cid and pid=pg_backend_pid()")
    with SessionLocal() as db:
        assert db.scalar(q, {"ns": ats.LOCK_NS, "cid": ID["co"]}) == 0
        ats.emit(db, ID["co"], "invitation.seen", invitation_id=1, status="seen", reason=None)
        assert db.scalar(q, {"ns": ats.LOCK_NS, "cid": ID["co"]}) == 1
        db.rollback()
        assert db.scalar(q, {"ns": ats.LOCK_NS, "cid": ID["co"]}) == 0  # снимается с концом транзакции
