"""Отзыв кандидата о компании после принятия приглашения → квота работодателя (services/reputation.py).
Штраф (квота 3) по доле плохих отзывов за окно, полный блок по «вакансии не было» до ручной проверки. Своя БД (fsp_rep)."""

import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fsp:fsp@localhost:5432/fsp_rep")
os.environ.setdefault("DEMO", "1")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import catalog, deps
from app.db import Base, SessionLocal, engine
from app.deps import issue_token
from app.models import Application, AuditLog, Candidate, Company, Invitation, Task, User, Vacancy
from app.routers import candidate, employer, lottery, tasks, vacancies
from app.services import reputation
from app.services.chat import may_talk

NOW = datetime.now(UTC)
INN, INN2 = "7704123450", "7707083893"
H: dict[str, dict] = {}  # заголовки: c0…c7 — кандидаты, e — «Ладога», e2 — «Вторая»
INV: dict[str, int] = {}  # приглашение «Ладоги» каждому кандидату
INV2: dict[str, int] = {}  # приглашения «Второй» кандидатам c0–c2


def _cand(i: int, user_id: int) -> Candidate:
    return Candidate(
        public_id=f"R-{i:04d}", user_id=user_id, name=f"Имя {i}", email=f"c{i}@example.ru", consent_152=True, consent_publish=True,
        consent_version=catalog.CONSENT_VERSION, consent_publish_version=catalog.CONSENT_VERSION, spec="Backend", track="Python",
        grade_claimed="Middle", grade="Middle", theta=1.0, se=0.2, percentile=70, min_salary=200000, formats=["Гибрид"], city="Москва",
        skills_confirmed=["Python"], skills_claimed=["Python"], tested_at=NOW - timedelta(days=60),
    )


def _inv(co: Company, c: Candidate, status: str, accepted_days_ago: float | None) -> Invitation:
    at = NOW - timedelta(days=(accepted_days_ago or 0) + 1)
    return Invitation(company_id=co.id, candidate_id=c.id, role="Backend (Python)", salary_from=240000, salary_to=300000, format="Гибрид",
                      status=status, sent_at=at, responded_at=NOW - timedelta(days=accepted_days_ago) if accepted_days_ago is not None else None,
                      expires_at=at + timedelta(days=7))


@pytest.fixture(scope="module")
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        users = [User(email=f"c{i}@example.ru", role="candidate") for i in range(8)]
        eu, eu2 = User(email="hr@ladoga-pay.example", role="employer"), User(email="hr@second.example", role="employer")
        db.add_all([*users, eu, eu2])
        db.flush()
        cands = [_cand(i, u.id) for i, u in enumerate(users)]
        co = Company(user_id=eu.id, inn=INN, name="Ладога Пэй", site_domain="ladoga-pay.example", recruiter_name="HR", recruiter_email="hr@ladoga-pay.example", verified=True)
        co2 = Company(user_id=eu2.id, inn=INN2, name="Вторая", site_domain="second.example", recruiter_name="HR", recruiter_email="hr@second.example", verified=True)
        db.add_all([*cands, co, co2])
        db.flush()
        # c0–c5 приняли неделю с лишним назад; c6 — вчера (отзыв ещё закрыт); c7 отказал
        invs = [_inv(co, c, "accepted", 10) for c in cands[:6]] + [_inv(co, cands[6], "accepted", 1), _inv(co, cands[7], "declined", 10)]
        invs += [_inv(co2, c, "accepted", 10) for c in cands[:3]]
        db.add_all(invs)
        db.add(Invitation(company_id=co2.id, candidate_id=cands[5].id, role="Открытое", salary_from=240000, salary_to=300000, format="Гибрид",
                          status="sent", expires_at=NOW + timedelta(days=5)))
        db.add(Task(company_id=co2.id, title="Задача Второй", text="Опишите подход к задаче", spec="Backend"))
        db.add(Vacancy(company_id=co.id, title="Backend в платежи", spec="Backend", track="Python", grade="Middle", salary_from=240000, salary_to=300000, format="Гибрид"))
        db.commit()
        for i, (u, inv) in enumerate(zip(users, invs)):
            H[f"c{i}"] = {"Authorization": "Bearer " + issue_token(db, u)}
            INV[f"c{i}"] = inv.id
        for i, inv in enumerate(invs[8:]):
            INV2[f"c{i}"] = inv.id
        H["e"] = {"Authorization": "Bearer " + issue_token(db, eu)}
        H["e2"] = {"Authorization": "Bearer " + issue_token(db, eu2)}
    app = FastAPI()
    for r in (deps, candidate, employer, vacancies, tasks, lottery):
        app.include_router(r.router)
    yield TestClient(app)


def _fb(client, who: str, value: str, invite: int | None = None):
    return client.post(f"/api/candidate/invites/{invite or INV[who]}/company-feedback", json={"value": value}, headers=H[who])


def _quota(client, who="e") -> dict:
    return client.get("/api/employer/quota", headers=H[who]).json()


def test_feedback_rules(client):
    items = {i["id"]: i for i in client.get("/api/candidate/invites", headers=H["c0"]).json()["items"]}
    assert items[INV["c0"]]["feedback_open"] is True and items[INV["c0"]]["company_feedback"] is None
    # кандидату о репутации компании не отдаётся ничего
    assert not {"reputation", "penalty", "blocked"} & set(items[INV["c0"]])
    assert _fb(client, "c0", "great").status_code == 422
    r = _fb(client, "c6", "ok")  # принял вчера — рано
    assert r.status_code == 409 and "7 дней" in r.json()["detail"]
    assert _fb(client, "c7", "no_contact").status_code == 409  # отказал — отзыва нет
    assert _fb(client, "c1", "ok", invite=INV["c0"]).status_code == 404  # чужое приглашение
    r = _fb(client, "c0", "ok")
    assert r.status_code == 200 and r.json()["company_feedback"] == "ok" and r.json()["feedback_open"] is False
    assert _fb(client, "c0", "fraud").status_code == 409  # один раз
    with SessionLocal() as db:  # повторный отзыв мимо проверки роутера тоже не перезаписывает первый
        inv = db.get(Invitation, INV["c0"])
        assert reputation.save_feedback(db, inv, "fraud") is False and db.get(Invitation, INV["c0"]).company_feedback == "ok"


def test_penalty_by_share_and_window(client):
    rep = _quota(client)["reputation"]
    assert (rep["total"], rep["bad"], rep["penalty"], rep["counts"]) == (None, None, False, None)  # ни числа, ни разбивки — от трёх отзывов
    assert _fb(client, "c1", "no_contact").status_code == 200
    assert _fb(client, "c2", "mismatch").status_code == 200
    q = _quota(client)
    assert q["max"] == catalog.QUOTA_BONUS and q["reputation"]["penalty"] is False  # два плохих — мало
    assert q["reputation"]["counts"] == {"ok": 1, "no_contact": 1, "mismatch": 1, "fraud": 0}
    assert _fb(client, "c3", "no_contact").status_code == 200
    q = _quota(client)
    assert (q["max"], q["next_max"], q["reputation"]["penalty"]) == (3, 3, True)
    # доля: те же три плохих среди многих хороших штрафа не дают
    with SessionLocal() as db:
        co = db.query(Company).filter(Company.inn == INN).one()
        for i in range(4):
            db.add(Invitation(company_id=co.id, candidate_id=db.query(Candidate).filter(Candidate.public_id == "R-0004").one().id, role=f"r{i}",
                              salary_from=1, salary_to=2, format="Гибрид", status="accepted", expires_at=NOW, company_feedback="ok", company_feedback_at=NOW))
        db.commit()
        assert reputation.summary(db, co)["penalty"] is False
        db.query(Invitation).filter(Invitation.role.like("r_")).delete(synchronize_session=False)
        db.commit()
        assert reputation.summary(db, co)["penalty"] is True
        # окно скользящее: отзывы старше 30 дней не считаются — штраф снимается сам
        db.query(Invitation).filter(Invitation.company_id == co.id).update({"company_feedback_at": NOW - timedelta(days=catalog.FEEDBACK_WINDOW_DAYS + 1)})
        db.commit()
    q = _quota(client)
    assert (q["max"], q["reputation"]["total"], q["reputation"]["penalty"]) == (catalog.QUOTA_BONUS, None, False)


def test_fraud_block_and_manual_review(client, capsys):
    # другая компания: «вакансии не было» от одного кандидата — ещё не блок
    assert _fb(client, "c0", "fraud", invite=INV2["c0"]).status_code == 200
    assert _quota(client, "e2")["reputation"]["blocked"] is False
    tasks_before = {t["title"] for t in client.get("/api/tasks/showcase", headers=H["c5"]).json()}
    assert "Задача Второй" in tasks_before
    assert _fb(client, "c1", "fraud", invite=INV2["c1"]).status_code == 200
    q = _quota(client, "e2")
    assert q["reputation"]["blocked"] is True and (q["max"], q["next_max"]) == (0, 0)
    with SessionLocal() as db:
        co = db.query(Company).filter(Company.inn == INN2).one()
        assert db.query(AuditLog).filter(AuditLog.action == "company_blocked").count() == 1
        assert reputation.check_block(db, co) is True  # уже заблокирована — повторно не пишется
        cand = db.query(Candidate).filter(Candidate.public_id == "R-0000").one()
        assert may_talk(cand, co) is False  # чат закрыт в обе стороны
        db.add(Vacancy(company_id=co.id, title="Приманка", spec="Backend", grade="Middle", salary_from=240000, salary_to=300000, format="Гибрид"))
        db.commit()
        bait = db.query(Vacancy).filter(Vacancy.title == "Приманка").one().id
    # всё, что доходит до кандидатов, закрыто
    e2 = H["e2"]
    inv = {"candidate_id": "R-0005", "role": "Backend", "salary_from": 240000, "salary_to": 300000, "format": "Гибрид"}
    assert client.post("/api/employer/invites", json=inv, headers=e2).status_code == 403
    vac = {"title": "Backend", "spec": "Backend", "grade": "Middle", "salary_from": 240000, "salary_to": 300000, "format": "Гибрид"}
    assert client.post("/api/vacancies", json=vac, headers=e2).status_code == 403
    assert client.patch(f"/api/vacancies/{bait}", json={"title": "Backend 2"}, headers=e2).status_code == 403
    task = {"title": "Задача", "text": "Опишите подход к задаче", "spec": "Backend"}
    assert client.post("/api/tasks", json=task, headers=e2).status_code == 403
    assert client.post("/api/lottery/", json={"need_id": 1, "threshold": {}, "draw_count": 1}, headers=e2).status_code == 403
    assert client.post("/api/lottery/1/draw", headers=e2).status_code == 403
    titles = {v["title"] for v in client.get("/api/vacancies").json()["items"]}
    assert "Приманка" not in titles and "Backend в платежи" in titles
    assert client.post(f"/api/vacancies/{bait}/apply", json={}, headers=H["c5"]).status_code == 409
    assert client.get(f"/api/vacancies/{bait}").status_code == 404
    # открытые приглашения истекли: кандидат видит нейтральное «истекло», принять и раскрыть контакты нельзя
    open_inv = next(i for i in client.get("/api/candidate/invites", headers=H["c5"]).json()["items"] if i["role"] == "Открытое")
    assert open_inv["status"] == "expired" and not {"reputation", "blocked"} & set(open_inv)
    assert client.post(f"/api/candidate/invites/{open_inv['id']}/accept", headers=H["c5"]).status_code == 409
    with SessionLocal() as db:  # приглашение, оставшееся открытым (гонка с блоком), при принятии истекает
        db.query(Invitation).filter(Invitation.id == open_inv["id"]).update({"status": "sent"})
        db.commit()
    r = client.post(f"/api/candidate/invites/{open_inv['id']}/accept", headers=H["c5"])
    assert r.status_code == 409 and r.json()["detail"] == "Срок ответа истёк"
    with SessionLocal() as db:
        assert db.get(Invitation, open_inv["id"]).status == "expired"
        assert db.get(Invitation, open_inv["id"]).responded_at is None  # «истекло», а не «ответил»
    # задания скрыты с витрины и не принимают решения
    assert "Задача Второй" not in {t["title"] for t in client.get("/api/tasks/showcase", headers=H["c5"]).json()}
    with SessionLocal() as db:
        tid = db.query(Task).filter(Task.title == "Задача Второй").one().id
        db.add(Application(vacancy_id=bait, candidate_id=db.query(Candidate).filter(Candidate.public_id == "R-0005").one().id, status="sent"))
        db.commit()
        app_id = db.query(Application).filter(Application.vacancy_id == bait).one().id
    assert client.get(f"/api/tasks/{tid}", headers=H["c5"]).status_code == 404
    assert client.post(f"/api/tasks/{tid}/submit", json={"answer": "подход"}, headers=H["c5"]).status_code == 404
    assert client.post(f"/api/vacancies/applications/{app_id}/status", json={"status": "seen"}, headers=e2).status_code == 403
    assert client.post("/api/tasks/submissions/1/review", json={"review": "ok"}, headers=e2).status_code == 403
    assert client.post(f"/api/employer/invites/{INV2['c0']}/feedback", json={"value": "hired"}, headers=e2).status_code == 403
    # контакты принятых приглашений скрыты, причина — блок, а не «кандидат закрыл доступ»
    row = next(r for r in client.get("/api/employer/pipeline", headers=e2).json()["items"] if r["id"] == INV2["c0"])
    assert row["contact"] is None and row["reason"] == "компания заблокирована до ручной проверки"
    # кабинет работодателя открывается: блок виден в квоте
    assert client.get("/api/employer/quota", headers=e2).status_code == 200
    # ручная проверка: CLI
    assert reputation.main(["blocked"]) == 0 and INN2 in capsys.readouterr().out
    assert reputation.main(["unblock", "0000000000"]) == 1
    assert reputation.main(["unblock", INN]) == 1  # не заблокирована: reviewed_at не сдвигается
    assert reputation.main([]) == 2
    assert reputation.main(["unblock", INN2]) == 0
    q = _quota(client, "e2")
    assert q["reputation"]["blocked"] is False and q["max"] == catalog.QUOTA_BONUS
    assert client.post("/api/employer/invites", json=inv, headers=e2).status_code == 200
    # отзывы до проверки блок не возвращают; нужен новый «вакансии не было» от двух разных кандидатов
    with SessionLocal() as db:
        co = db.query(Company).filter(Company.inn == INN2).one()
        assert reputation.check_block(db, co) is False
    assert _fb(client, "c2", "fraud", invite=INV2["c2"]).status_code == 200
    assert _quota(client, "e2")["reputation"]["blocked"] is False
    with SessionLocal() as db:  # тот же кандидат по второму приглашению — не второй голос
        co = db.query(Company).filter(Company.inn == INN2).one()
        cid = db.query(Candidate).filter(Candidate.public_id == "R-0002").one().id
        db.add(Invitation(company_id=co.id, candidate_id=cid, role="ещё", salary_from=1, salary_to=2, format="Гибрид", status="accepted",
                          expires_at=NOW, company_feedback="fraud", company_feedback_at=NOW))
        db.commit()
        assert reputation.check_block(db, co) is False


def test_accept_races_with_block(client, monkeypatch):
    """Блок истёк приглашение между проверкой и принятием: условный UPDATE не перезапишет «истекло», журнал не пишется."""
    with SessionLocal() as db:
        co = db.query(Company).filter(Company.inn == INN).one()
        cid = db.query(Candidate).filter(Candidate.public_id == "R-0006").one().id
        inv = Invitation(company_id=co.id, candidate_id=cid, role="Гонка", salary_from=240000, salary_to=300000, format="Гибрид",
                         status="sent", expires_at=NOW + timedelta(days=5))
        db.add(inv)
        db.commit()
        iid = inv.id
    orig = candidate._respond

    def respond_then_block(*a, **kw):
        r = orig(*a, **kw)
        with SessionLocal() as other:  # параллельный check_block уже закоммитил «истекло»
            other.query(Invitation).filter(Invitation.id == iid).update({"status": "expired"})
            other.commit()
        return r

    monkeypatch.setattr(candidate, "_respond", respond_then_block)
    r = client.post(f"/api/candidate/invites/{iid}/accept", headers=H["c6"])
    assert r.status_code == 409 and r.json()["detail"] == "Срок ответа истёк"
    with SessionLocal() as db:
        assert db.get(Invitation, iid).status == "expired"
        assert not [a for a in db.query(AuditLog).filter(AuditLog.action == "contacts_revealed") if (a.detail or {}).get("invitation_id") == iid]
