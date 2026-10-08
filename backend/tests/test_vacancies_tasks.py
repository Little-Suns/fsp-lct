"""Вакансии и отклики, регулярные задания. Своя БД (fsp_vac), LLM выключена."""

import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fsp:fsp@localhost:5432/fsp_vac")
os.environ["LLM_BASE_URL"] = ""
os.environ.setdefault("DEMO", "1")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import catalog, config, deps
from app.db import Base, SessionLocal, engine
from app.deps import issue_token
from app.models import Application, AuditLog, Candidate, Company, Invitation, Need, User, Vacancy
from app.routers import candidate, tasks, vacancies

config.LLM_BASE_URL = ""
NOW = datetime.now(UTC)
H: dict[str, dict] = {}
IDS: dict[str, int] = {}


def _cand(pid, user_id, **kw) -> Candidate:
    base = dict(
        public_id=pid, user_id=user_id, name=f"Имя {pid}", email=f"{pid.lower()}@example.ru", tg=f"@{pid.lower()}", consent_152=True, consent_publish=True, consent_version=catalog.CONSENT_VERSION, consent_publish_version=catalog.CONSENT_VERSION,
        spec="Backend", track="Python", grade_claimed="Middle", grade="Middle", theta=1.0, se=0.2, percentile=70, min_salary=230000,
        formats=["Гибрид"], city="Москва", skills_confirmed=["Python", "PostgreSQL"], skills_claimed=["Python"], tested_at=NOW - timedelta(days=10),
    )
    return Candidate(**{**base, **kw})


@pytest.fixture(scope="module")
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        users = {k: User(email=f"{k}@example.ru", role=r) for k, r in
                 [("emp", "employer"), ("emp2", "employer"), ("cand", "candidate"), ("busy", "candidate"), ("raw", "candidate"), ("ml", "candidate"),
                  ("shy", "candidate"), ("gone", "candidate")]}
        db.add_all(users.values())
        db.flush()
        co = Company(user_id=users["emp"].id, inn="7704123450", name="Ладога Пэй", recruiter_name="М", recruiter_email="m@x.ru", verified=False)
        co2 = Company(user_id=users["emp2"].id, inn="500100732259", name="Чужая", recruiter_name="Ч", recruiter_email="c@x.ru", verified=True)
        cand = _cand("A-1042", users["cand"].id, name="Дмитрий Орлов", email="d.orlov@example.ru", tg="@dorlov")
        busy = _cand("B-0001", users["busy"].id)
        raw = _cand("U-0002", users["raw"].id, grade=None, theta=None, se=None, tested_at=None)
        ml = _cand("M-0003", users["ml"].id, spec="ML / DS", track="NLP / LLM")
        users["old"] = User(email="old@example.ru", role="candidate")
        db.add(users["old"])
        db.flush()
        old = _cand("O-0006", users["old"].id, consent_version="2020-01")  # согласие на старую редакцию — недействительно
        shy = _cand("S-0004", users["shy"].id, consent_publish=False)  # карточку работодателям не публикует
        gone = _cand("G-0005", users["gone"].id, name="Отозвал Согласие", email="gone@example.ru")
        db.add_all([co, co2, cand, busy, raw, ml, shy, gone, old])
        db.flush()
        need2 = Need(company_id=co2.id, text="x", spec="Backend", grade="Middle")
        need3 = Need(company_id=co2.id, text="y", spec="Backend", grade="Middle")
        db.add_all([need2, need3])
        db.flush()
        # у busy уже лимит откликов за неделю — на вакансии чужой компании
        for i in range(catalog.APPLICATIONS_PER_WEEK):
            v = Vacancy(company_id=co2.id, title=f"V{i}", spec="Backend", grade="Middle", salary_from=250000, salary_to=300000, format="Гибрид")
            db.add(v)
            db.flush()
            db.add(Application(vacancy_id=v.id, candidate_id=busy.id, status="sent"))
        def _inv(cand_, need, **kw):
            return Invitation(**{"company_id": co2.id, "candidate_id": cand_.id, "need_id": need.id, "role": "Backend", "salary_from": 250000,
                                 "salary_to": 300000, "format": "Гибрид", "expires_at": NOW + timedelta(days=5), **kw})
        inv = _inv(cand, need2)  # действует, та же потребность, что у закрытого задания
        inv_other = _inv(busy, need2, status="declined")  # отказ — доступа нет
        inv_ml = _inv(ml, need3)  # другая потребность
        db.add_all([inv, inv_other, inv_ml, _inv(raw, need2, expires_at=NOW - timedelta(hours=1))])  # последнее — истекло
        db.commit()
        IDS.update(co=co.id, cand=cand.id, gone=gone.id, need2=need2.id, inv=inv.id, inv_other=inv_other.id, inv_ml=inv_ml.id)
        for k, u in users.items():
            H[k] = {"Authorization": f"Bearer {issue_token(db, u)}"}
    app = FastAPI()
    for r in (deps, vacancies, tasks, candidate):
        app.include_router(r.router)
    yield TestClient(app)


VAC = {"title": "Python-разработчик в платежи", "description": "Платёжный шлюз", "spec": "Backend", "track": "Python", "grade": "Middle",
       "must": ["python", "postgres"], "salary_from": 250000, "salary_to": 300000, "format": "Гибрид", "city": "Москва"}


def test_vacancy_create_validation(client):
    r = client.post("/api/vacancies", json={**VAC, "salary_from": 100000, "salary_to": 300000}, headers=H["emp"])
    assert r.status_code == 422 and len(r.json()["detail"]["errors"]) == 2  # ниже p25 и слишком широкая
    assert client.post("/api/vacancies", json={**VAC, "salary_from": None}, headers=H["emp"]).status_code == 422
    assert client.post("/api/vacancies", json={**VAC, "spec": "Cobol"}, headers=H["emp"]).status_code == 422
    assert client.post("/api/vacancies", json={**VAC, "format": "Где угодно"}, headers=H["emp"]).status_code == 422
    huge = client.post("/api/vacancies", json={**VAC, "salary_to": 10_000_000_000}, headers=H["emp"])  # больше SALARY_MAX — 422, а не 500 от integer
    assert huge.status_code == 422 and huge.json()["detail"][0]["type"] == "salary_max"
    assert client.get("/api/vacancies", params={"salary_min": 10_000_000_000}).status_code == 422
    assert client.post("/api/vacancies", json=VAC, headers=H["cand"]).status_code == 403
    r = client.post("/api/vacancies", json=VAC, headers=H["emp"])
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["company"]["verified"] is False and v["must"] == ["Python", "PostgreSQL"] and v["status"] == "open"
    IDS["vac"] = v["id"]


def test_edit_close_own_only(client):
    vid = IDS["vac"]
    assert client.patch(f"/api/vacancies/{vid}", json={"title": "Чужая правка"}, headers=H["emp2"]).status_code == 404
    assert client.post(f"/api/vacancies/{vid}/close", headers=H["emp2"]).status_code == 404
    assert client.get(f"/api/vacancies/{vid}/applications", headers=H["emp2"]).status_code == 404
    assert client.patch(f"/api/vacancies/{vid}", json={"salary_to": 900000}, headers=H["emp"]).status_code == 422  # шире 40 %
    assert client.patch(f"/api/vacancies/{vid}", json={"salary_from": 10_000_000_000}, headers=H["emp"]).json()["detail"][0]["type"] == "salary_max"
    r = client.patch(f"/api/vacancies/{vid}", json={"title": "Python-разработчик (платежи)", "salary_to": 320000}, headers=H["emp"])
    assert r.status_code == 200 and r.json()["to"] == 320000 and r.json()["updated_at"]


def test_list_sorted_by_fit(client):
    pub = client.get("/api/vacancies").json()
    assert pub["sort"] == "new" and pub["items"][0]["fit"] is None
    r = client.get("/api/vacancies", headers=H["cand"]).json()
    assert r["sort"] == "fit" and r["items"][0]["fit"] is not None and r["items"][0]["fork_vs_min"] is True
    assert [i["fit"] for i in r["items"]] == sorted((i["fit"] for i in r["items"]), reverse=True)
    assert client.get("/api/vacancies", params={"q": "платежи"}).json()["total"] == 1
    assert client.get("/api/vacancies", params={"salary_min": 310000}).json()["total"] == 1
    assert client.get("/api/vacancies", params={"spec": "QA"}).json()["total"] == 0


def test_apply_reveals_contacts_and_logs(client):
    vid = IDS["vac"]
    assert client.post(f"/api/vacancies/{vid}/apply", json={"note": "x" * 301}, headers=H["cand"]).status_code == 422
    assert client.post(f"/api/vacancies/{vid}/apply", json={}, headers=H["raw"]).status_code == 403  # не прошёл тест
    assert client.post(f"/api/vacancies/{vid}/apply", json={}, headers=H["old"]).status_code == 403  # согласие на старую редакцию
    r = client.post(f"/api/vacancies/{vid}/apply", json={"note": "Делал платёжный шлюз"}, headers=H["cand"])
    assert r.status_code == 200 and r.json()["status"] == "sent"
    IDS["app"] = r.json()["id"]
    assert client.post(f"/api/vacancies/{vid}/apply", json={}, headers=H["cand"]).status_code == 409
    assert client.get(f"/api/vacancies/{vid}", headers=H["cand"]).json()["applied"] == "sent"

    for _ in range(2):  # повторный просмотр не плодит записи журнала
        rows = client.get(f"/api/vacancies/{vid}/applications", headers=H["emp"]).json()["items"]
    assert rows[0]["contacts"] == {"name": "Дмитрий Орлов", "email": "d.orlov@example.ru", "tg": "@dorlov"}
    assert rows[0]["candidate"]["id"] == "A-1042" and "name" not in rows[0]["candidate"]
    with SessionLocal() as db:
        logs = db.scalars(select(AuditLog).where(AuditLog.action == "contacts_revealed")).all()
    assert len(logs) == 1 and logs[0].detail == {"application_id": IDS["app"], "vacancy_id": vid, "basis": "application"}
    assert logs[0].subject_candidate_id == IDS["cand"]
    with SessionLocal() as db:
        assert db.get(Application, IDS["app"]).contacts_revealed_at is not None


def test_weekly_limit(client):
    r = client.post(f"/api/vacancies/{IDS['vac']}/apply", json={}, headers=H["busy"])
    assert r.status_code == 429 and "откликов" in r.json()["detail"]
    assert client.get("/api/vacancies/applications/mine", headers=H["busy"]).json()["limit"]["used"] == catalog.APPLICATIONS_PER_WEEK


def test_status_flow_both_sides(client):
    aid = IDS["app"]
    assert client.post(f"/api/vacancies/applications/{aid}/status", json={"status": "seen"}, headers=H["emp2"]).status_code == 404
    assert client.post(f"/api/vacancies/applications/{aid}/withdraw", headers=H["busy"]).status_code == 404
    assert client.post(f"/api/vacancies/applications/{aid}/status", json={"status": "declined"}, headers=H["emp"]).status_code == 422
    assert client.post(f"/api/vacancies/applications/{aid}/status", json={"status": "hired"}, headers=H["emp"]).status_code == 422
    assert client.post(f"/api/vacancies/applications/{aid}/status", json={"status": "seen"}, headers=H["emp"]).json()["status"] == "seen"
    mine = client.get("/api/vacancies/applications/mine", headers=H["cand"]).json()["items"]
    assert mine[0]["status"] == "seen" and mine[0]["vacancy"]["id"] == IDS["vac"]
    r = client.post(f"/api/vacancies/applications/{aid}/status", json={"status": "declined", "reason": "stack"}, headers=H["emp"])
    assert r.json()["status"] == "declined"
    assert client.get("/api/vacancies/applications/mine", headers=H["cand"]).json()["items"][0]["reason"] == "Стек"
    assert client.post(f"/api/vacancies/applications/{aid}/status", json={"status": "accepted"}, headers=H["emp"]).status_code == 409
    assert client.post(f"/api/vacancies/applications/{aid}/withdraw", headers=H["cand"]).status_code == 409
    counts = client.get("/api/vacancies/mine", headers=H["emp"]).json()[0]["applications"]
    assert counts["declined"] == 1 and counts["total"] == 1


def test_withdraw_hides_contacts_and_close(client):
    r = client.post("/api/vacancies", json={**VAC, "title": "Второй бэкенд"}, headers=H["emp"])
    vid = r.json()["id"]
    aid = client.post(f"/api/vacancies/{vid}/apply", json={}, headers=H["cand"]).json()["id"]
    assert client.post(f"/api/vacancies/applications/{aid}/withdraw", headers=H["cand"]).json()["status"] == "withdrawn"
    row = client.get(f"/api/vacancies/{vid}/applications", headers=H["emp"]).json()["items"][0]
    assert row["status"] == "withdrawn" and row["contacts"] is None
    assert client.post(f"/api/vacancies/applications/{aid}/status", json={"status": "accepted"}, headers=H["emp"]).status_code == 409
    assert client.post(f"/api/vacancies/{vid}/close", headers=H["emp"]).json()["status"] == "closed"
    assert client.post(f"/api/vacancies/{vid}/apply", json={}, headers=H["ml"]).status_code == 409
    assert all(i["id"] != vid for i in client.get("/api/vacancies").json()["items"])


def test_consent_revoked_hides_application(client):
    vid = client.post("/api/vacancies", json={**VAC, "title": "Третий бэкенд"}, headers=H["emp"]).json()["id"]
    aid = client.post(f"/api/vacancies/{vid}/apply", json={}, headers=H["gone"]).json()["id"]
    assert client.post(f"/api/vacancies/applications/{aid}/status", json={"status": "accepted"}, headers=H["emp"]).json()["status"] == "accepted"
    assert client.post(f"/api/vacancies/applications/{aid}/withdraw", headers=H["gone"]).status_code == 409  # после ответа не отозвать
    with SessionLocal() as db:
        db.get(Candidate, IDS["gone"]).consent_152 = False
        db.commit()
    r = client.get(f"/api/vacancies/{vid}/applications", headers=H["emp"])
    row = r.json()["items"][0]
    assert row["hidden"] is True and row["candidate"] is None and row["contacts"] is None and "Отозвал" not in r.text
    with SessionLocal() as db:
        assert not db.scalars(select(AuditLog).where(AuditLog.subject_candidate_id == IDS["gone"])).all()


TASK = {"title": "Идемпотентность платежа", "text": "Как не списать деньги дважды при ретрае?", "spec": "Backend",
        "competency": "Проектирование API", "kind": "approach", "minutes": 30, "public": True}


def test_tasks_flow(client):
    assert client.post("/api/tasks", json={**TASK, "kind": "essay"}, headers=H["emp"]).status_code == 422
    assert client.post("/api/tasks", json={**TASK, "competency": "Вязание"}, headers=H["emp"]).status_code == 422
    assert client.post("/api/tasks", json={**TASK, "need_id": IDS["need2"]}, headers=H["emp"]).status_code == 404  # чужая потребность
    pub = client.post("/api/tasks", json=TASK, headers=H["emp"]).json()
    priv = client.post("/api/tasks", json={**TASK, "title": "Закрытое", "public": False, "need_id": IDS["need2"]}, headers=H["emp2"]).json()
    client.post("/api/tasks", json={**TASK, "title": "ML-задача", "spec": "ML / DS", "competency": None}, headers=H["emp"])

    show = client.get("/api/tasks/showcase", headers=H["cand"]).json()
    assert [t["id"] for t in show] == [pub["id"]] and show[0]["submitted"] is False and show[0]["company"]["verified"] is False
    assert client.get(f"/api/tasks/{priv['id']}", headers=H["ml"]).status_code == 404  # приглашён по другой потребности
    assert client.get(f"/api/tasks/{priv['id']}", headers=H["raw"]).status_code == 404  # приглашение истекло
    assert client.get(f"/api/tasks/{priv['id']}", headers=H["busy"]).status_code == 404  # приглашение отклонено
    assert client.get(f"/api/tasks/{priv['id']}", headers=H["cand"]).status_code == 200  # действующее приглашение по той же потребности
    assert client.get(f"/api/tasks/{pub['id']}", headers=H["ml"]).status_code == 404  # публичное, но чужая специализация
    fi = client.get(f"/api/tasks/for-invitation/{IDS['inv']}", headers=H["cand"]).json()
    assert [t["id"] for t in fi] == [priv["id"]] and fi[0]["submitted"] is False
    assert client.get(f"/api/tasks/for-invitation/{IDS['inv']}", headers=H["busy"]).status_code == 404  # чужое приглашение
    assert client.get(f"/api/tasks/for-invitation/{IDS['inv_other']}", headers=H["busy"]).status_code == 404  # отклонено
    assert client.get(f"/api/tasks/for-invitation/{IDS['inv_ml']}", headers=H["ml"]).json() == []  # по потребности заданий нет

    assert client.post(f"/api/tasks/{pub['id']}/submit", json={"answer": "x" * 5001}, headers=H["cand"]).status_code == 422
    assert client.post(f"/api/tasks/{pub['id']}/submit", json={"answer": "a"}, headers=H["old"]).status_code == 403  # старая редакция согласия
    r = client.post(f"/api/tasks/{pub['id']}/submit", json={"answer": "Ключ идемпотентности + уникальный индекс"}, headers=H["cand"])
    assert r.status_code == 200
    assert client.post(f"/api/tasks/{pub['id']}/submit", json={"answer": "ещё раз"}, headers=H["cand"]).status_code == 409
    assert client.post(f"/api/tasks/{priv['id']}/submit", json={"answer": "a"}, headers=H["ml"]).status_code == 404
    assert client.post(f"/api/tasks/{priv['id']}/submit", json={"answer": "a", "invitation_id": IDS["inv_other"]}, headers=H["busy"]).status_code == 404
    assert client.post(f"/api/tasks/{pub['id']}/submit", json={"answer": "Скрытый ответ"}, headers=H["shy"]).status_code == 200
    assert client.post(f"/api/tasks/{priv['id']}/submit", json={"answer": "a", "invitation_id": IDS["inv_other"]}, headers=H["cand"]).status_code == 404
    assert client.post(f"/api/tasks/{pub['id']}/submit", json={"answer": "a", "invitation_id": IDS["inv"]}, headers=H["busy"]).status_code == 404
    r = client.post(f"/api/tasks/{priv['id']}/submit", json={"answer": "Через outbox", "invitation_id": IDS["inv"]}, headers=H["cand"])
    assert r.status_code == 200 and r.json()["invitation_id"] == IDS["inv"]

    assert client.get(f"/api/tasks/{pub['id']}/submissions", headers=H["emp2"]).status_code == 404
    subs = client.get(f"/api/tasks/{pub['id']}/submissions", headers=H["emp"])
    assert subs.status_code == 200
    assert "Орлов" not in subs.text and "d.orlov" not in subs.text and "@dorlov" not in subs.text  # контакты не раскрываются
    items = {i["hidden"]: i for i in subs.json()["items"]}
    assert items[True]["candidate"] is None and items[True]["answer"] is None and "S-0004" not in subs.text  # без согласия на публикацию
    assert client.post(f"/api/tasks/submissions/{items[True]['id']}/review", json={"review": "ok"}, headers=H["emp"]).status_code == 404
    sid = items[False]["id"]
    assert items[False]["candidate"]["id"] == "A-1042"

    with SessionLocal() as db:
        assert tasks.task_signal(db, IDS["cand"]) is None
    assert client.post(f"/api/tasks/submissions/{sid}/review", json={"review": "strong"}, headers=H["emp2"]).status_code == 404
    assert client.post(f"/api/tasks/submissions/{sid}/review", json={"review": "great"}, headers=H["emp"]).status_code == 422
    r = client.post(f"/api/tasks/submissions/{sid}/review", json={"review": "strong", "comment": "Учёл ретраи"}, headers=H["emp"])
    assert r.json()["review"] == "strong"

    mine = client.get("/api/tasks/mine", headers=H["emp"]).json()
    t = next(x for x in mine if x["id"] == pub["id"])
    assert t["submissions"] == 2 and t["reviewed"] == 1 and t["avg_review"] == 3
    cs = client.get("/api/tasks/submissions/mine", headers=H["cand"]).json()
    assert {s["review"] for s in cs} == {"strong", None}
    assert client.get("/api/tasks/showcase", headers=H["cand"]).json()[0]["review"] == "strong"
    with SessionLocal() as db:
        assert tasks.task_signal(db, IDS["cand"]) == {"days_ago": 0, "source": "employer", "review": "strong", "review_text": "сильное решение", "auto_ok": None,
                                                      "company_verified": False, "domain_confirmed": False, "inn_checksum_valid": True}


SECRET = "секретный-эталон-42"
REF_TASKS = {
    "text": {"answer_type": "text", "reference": {"answers": ["Read Committed", SECRET]}},
    "number": {"answer_type": "number", "reference": {"value": 1234.5, "tolerance": 0.5}},
    "choice": {"answer_type": "choice", "options": ["Read Uncommitted", "Serializable", "Read Committed"], "reference": {"correct": [1]}},
    "multi": {"answer_type": "multi", "options": ["B-tree", "Hash", "GIN", "Heap"], "reference": {"correct": [0, 2]}},
    "regex": {"answer_type": "regex", "reference": {"pattern": r"(a|aa)+|секрет-\d+"}},
}


def _no_reference(r):
    """Ответ API кандидату: ни ключа reference, ни значений эталона."""
    body = r.json()
    for it in body if isinstance(body, list) else [body]:
        assert "reference" not in it.get("task", it), it
    assert SECRET not in r.text and "1234.5" not in r.text and "(a|aa)" not in r.text and "correct" not in r.text


def test_reference_task_validation(client):
    bad = [{"answer_type": "essay"},
           {"answer_type": "text", "reference": {"answers": []}},
           {"answer_type": "text", "reference": {"answers": ["  "]}},
           {"answer_type": "text", "options": ["a", "b"], "reference": {"answers": ["x"]}},
           {"answer_type": "number", "reference": {"value": None}},
           {"answer_type": "number", "reference": {"value": 1, "tolerance": -1}},
           {"answer_type": "choice", "options": ["a"], "reference": {"correct": [0]}},
           {"answer_type": "choice", "options": ["a", "b"], "reference": {"correct": [0, 1]}},
           {"answer_type": "choice", "options": ["a", "b"], "reference": {"correct": [5]}},
           {"answer_type": "multi", "options": ["a", " A "], "reference": {"correct": [0]}},
           {"answer_type": "multi", "options": ["a", "b"], "reference": {}},
           {"answer_type": "regex", "reference": {"pattern": "(["}},
           {"answer_type": "regex", "reference": {"pattern": "x" * 301}},
           {"answer_type": "regex", "reference": {"pattern": "((((a{20}){20}){20}){20})"}},  # раздувается при компиляции
           {"answer_type": "regex", "reference": {"pattern": r"(((a\\{100}){100}){100}){100}"}}]  # «\\{» — не экранированная скобка
    for b in bad:
        assert client.post("/api/tasks", json={**TASK, **b}, headers=H["emp"]).status_code == 422, b
    # открытое задание: варианты и эталон не сохраняются
    r = client.post("/api/tasks", json={**TASK, "title": "Открытое", "options": ["a", "b"], "reference": {"answers": ["x"]}}, headers=H["emp"]).json()
    assert r["answer_type"] == "open" and r["options"] is None and r["reference"] is None


def test_reference_tasks_autocheck(client):
    made = {k: client.post("/api/tasks", json={**TASK, "title": f"Эталон {k}", "kind": "solve", **v}, headers=H["emp"]).json() for k, v in REF_TASKS.items()}
    assert made["text"]["reference"] == {"answers": ["Read Committed", SECRET], "exact": False}  # автору эталон виден
    assert made["choice"]["options"] == REF_TASKS["choice"]["options"]
    ids = {k: t["id"] for k, t in made.items()}

    # кандидату эталон не уходит — ни в витрине, ни в задании, ни в ответе на отправку
    _no_reference(client.get("/api/tasks/showcase", headers=H["cand"]))
    for k, tid in ids.items():
        r = client.get(f"/api/tasks/{tid}", headers=H["cand"])
        _no_reference(r)
        assert r.json()["answer_type"] == k and r.json()["auto_ok"] is None
    assert client.get(f"/api/tasks/{ids['multi']}", headers=H["cand"]).json()["options"] == ["B-tree", "Hash", "GIN", "Heap"]
    # и другой компании тоже: её списки и чужие решения закрыты
    assert all(t["id"] not in ids.values() for t in client.get("/api/tasks/mine", headers=H["emp2"]).json())
    assert client.get(f"/api/tasks/{ids['text']}/submissions", headers=H["emp2"]).status_code == 404

    def sub(k, who="cand", **b):
        return client.post(f"/api/tasks/{ids[k]}/submit", json=b, headers=H[who])

    assert sub("number", answer="двенадцать").status_code == 422  # не число — попытка не сгорает
    assert sub("number", answer="   ").status_code == 422
    assert sub("choice", answer="Serializable").status_code == 422  # выбор — только через choices
    assert sub("choice", choices=[0, 1]).status_code == 422
    assert sub("multi", choices=[7]).status_code == 422

    r = sub("text", answer="  read committed. ")
    assert r.status_code == 200 and r.json()["auto_ok"] is True and r.json()["auto_feedback"] == "Ответ совпал с эталоном"
    _no_reference(r)
    assert sub("number", answer="1 234,9").json()["auto_ok"] is True
    r = sub("choice", choices=[2])
    assert r.json()["auto_ok"] is False and r.json()["answer"] == "Read Committed" and r.json()["auto_feedback"] == "Ответ не совпал с эталоном"
    _no_reference(r)
    assert sub("multi", choices=[2, 0]).json()["auto_ok"] is True
    assert sub("multi", choices=[0]).status_code == 409  # попытка одна
    r = sub("regex", answer="a" * 3000 + "!")  # катастрофический возврат обрывается таймаутом — оценит работодатель
    assert r.status_code == 200 and r.json()["auto_ok"] is None and "работодатель" in r.json()["auto_feedback"]
    assert sub("regex", who="busy", answer="СЕКРЕТ-7").json()["auto_ok"] is True
    assert sub("number", who="busy", answer="1236").json()["auto_ok"] is False
    assert sub("text", who="shy", answer="Read Committed").json()["auto_ok"] is True  # карточку не публикует

    mine = client.get("/api/tasks/submissions/mine", headers=H["cand"])
    _no_reference(mine)
    by = {s["task"]["id"]: s for s in mine.json()}
    assert by[ids["multi"]]["auto_ok"] is True and by[ids["multi"]]["answer"] == "B-tree; GIN"
    show = {t["id"]: t for t in client.get("/api/tasks/showcase", headers=H["cand"]).json()}
    assert show[ids["choice"]]["submitted"] and show[ids["choice"]]["auto_ok"] is False

    # работодатель: результат в списке решений и в сводке; эталон — в своём задании
    subs = client.get(f"/api/tasks/{ids['number']}/submissions", headers=H["emp"]).json()
    assert subs["task"]["reference"] == {"value": 1234.5, "tolerance": 0.5}
    assert sorted(i["auto_ok"] for i in subs["items"]) == [False, True]
    hidden = [i for i in client.get(f"/api/tasks/{ids['text']}/submissions", headers=H["emp"]).json()["items"] if i["hidden"]]
    assert len(hidden) == 1 and hidden[0]["auto_ok"] is None and hidden[0]["auto_feedback"] is None  # скрытый — без результата
    st = {t["id"]: t for t in client.get("/api/tasks/mine", headers=H["emp"]).json()}
    assert (st[ids["number"]]["auto_checked"], st[ids["number"]]["auto_passed"], st[ids["number"]]["reviewed"]) == (2, 1, 0)
    assert (st[ids["regex"]]["auto_checked"], st[ids["regex"]]["auto_passed"]) == (1, 1)  # таймаут — не проверено
    timed_out = next(i for i in client.get(f"/api/tasks/{ids['regex']}/submissions", headers=H["emp"]).json()["items"] if i["auto_ok"] is None)
    r = client.post(f"/api/tasks/submissions/{timed_out['id']}/review", json={"review": "strong"}, headers=H["emp"])
    assert r.json()["review"] == "strong" and r.json()["auto_ok"] is None  # не сработавшую автопроверку оценивает работодатель

    # сигнал: последняя автопроверка; ручная оценка работодателя главнее
    with SessionLocal() as db:
        busy_sig = tasks.task_signal(db, db.scalar(select(Candidate.id).where(Candidate.public_id == "B-0001")))
    assert busy_sig["source"] == "auto" and busy_sig["auto_ok"] is True  # неверный ответ позже верного в сигнал не идёт
    # выгрузка своих данных (152-ФЗ): своё решение и результат — да, эталон — нет
    ex = client.get("/api/candidate/me/export", headers=H["cand"])
    assert ex.status_code == 200 and any(s.get("auto_ok") is True for s in ex.json()["task_submissions"])
    assert SECRET not in ex.text and "reference" not in ex.text and "1234.5" not in ex.text
    wrong = next(i for i in client.get(f"/api/tasks/{ids['choice']}/submissions", headers=H["emp"]).json()["items"] if i["candidate"])
    r = client.post(f"/api/tasks/submissions/{wrong['id']}/review", json={"review": "ok", "comment": "Тоже допустимо"}, headers=H["emp"]).json()
    assert r["review"] == "ok" and r["auto_ok"] is False  # переоценка не стирает автопроверку
    with SessionLocal() as db:
        sig = tasks.task_signal(db, IDS["cand"])
    assert sig["source"] == "employer" and sig["review"] == "ok" and sig["auto_ok"] is False
