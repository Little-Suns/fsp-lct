"""Инвариант ПДн на засеянном мире: обходим каждый эндпоинт, который видит работодатель, и ищем в JSON ФИО, почту
и Telegram кандидатов. Разрешены только те, кто принял приглашение этой компании или сам откликнулся на её вакансию
(и не отозвал отклик). Скрытые поля синтетики (`truth`, резюме, эмбеддинг) не уходят никому.
Плюс сценарий жизни кандидата: приглашение → принятие (запись contacts_revealed) → отзыв согласий → выгрузка → удаление.
Своя БД (fsp_priv)."""

import json
import os
import re

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fsp:fsp@localhost:5432/fsp_priv")
os.environ["LLM_BASE_URL"] = ""
os.environ.setdefault("DEMO", "1")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from app import catalog, config, deps
from app.db import Base, SessionLocal, engine
from app.deps import issue_token
from app.models import Application, AuditLog, Candidate, Company, Invitation, User, Vacancy
from app.routers import candidate, employer, lottery, quest, tasks, vacancies
from app.services import matching
from seed.generate import build

config.LLM_BASE_URL = ""
pytestmark = pytest.mark.slow
FORBIDDEN_KEYS = {"truth", "theta_true", "skills_true", "cv_text", "cv_filename", "embedding", "hidden_from", "verify_code", "decline_comment"}


@pytest.fixture(scope="module")
def world():
    if "fsp_priv" not in str(engine.url):
        pytest.skip("тест пересоздаёт схему — нужен отдельный DATABASE_URL (fsp_priv)")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    heads = {}
    with SessionLocal() as db:
        build(db, 60, 8, 11)
        db.commit()
        for co in db.scalars(select(Company).where(Company.user_id.is_not(None)).order_by(Company.id)):
            heads[co.id] = {"Authorization": "Bearer " + issue_token(db, db.get(User, co.user_id))}
    app = FastAPI()
    for r in (deps, candidate, employer, vacancies, tasks, lottery, quest):
        app.include_router(r.router)
    return TestClient(app), heads


def _get(client, url, h, out):
    r = client.get(url, headers=h)
    assert r.status_code == 200, (url, r.status_code, r.text[:200])
    out.append((url, r.text))
    return r.json()


def crawl(client, h) -> list[tuple[str, str]]:
    """Все ответы эндпоинтов работодателя для компании с заголовком h."""
    out: list[tuple[str, str]] = []
    for url in ("/api/employer/company", "/api/employer/pipeline", "/api/employer/quota", "/api/vacancies", "/api/tasks/mine"):
        _get(client, url, h, out)
    needs = _get(client, "/api/employer/needs", h, out)
    pids = set()
    for n in needs:
        for variant in ("full", "embed"):
            pids |= {c["id"] for c in _get(client, f"/api/employer/needs/{n['id']}/picks?limit=500&variant={variant}", h, out)["items"]}
    page = 1
    while items := _get(client, f"/api/employer/search?limit=100&page={page}", h, out)["items"]:
        pids |= {c["id"] for c in items}
        page += 1
    for pid in sorted(pids):
        _get(client, f"/api/employer/candidates/{pid}" + (f"?need_id={needs[0]['id']}" if needs else ""), h, out)
    for v in _get(client, "/api/vacancies/mine", h, out):
        _get(client, f"/api/vacancies/{v['id']}", h, out)
        _get(client, f"/api/vacancies/{v['id']}/applications", h, out)
    for t in client.get("/api/tasks/mine", headers=h).json():
        _get(client, f"/api/tasks/{t['id']}/submissions", h, out)
    if needs:  # лотерея по первой потребности: пул, жребий, проверка, публичная страница
        r = client.post("/api/lottery/", json={"need_id": needs[0]["id"], "threshold": {"require_free": False}, "draw_count": 3}, headers=h)
        if r.status_code == 200:
            lid = r.json()["id"]
            out.append(("lottery create", r.text))
            out.append(("lottery draw", client.post(f"/api/lottery/{lid}/draw", headers=h).text))
            for url in (f"/api/lottery/{lid}", f"/api/lottery/{lid}/verify", f"/api/lottery/{lid}/public"):
                _get(client, url, h, out)
    return out


def _keys(obj):
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield k
            yield from _keys(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keys(v)


def _pii(c: Candidate) -> list[str]:
    return [x for x in (c.name, c.email, c.tg) if x]


def _found(value: str, text: str) -> bool:
    return re.search(rf"(?<![\w.@-]){re.escape(value)}(?![\w.-])", text) is not None


def allowed_ids(db, company_id: int) -> set[int]:
    acc = db.scalars(select(Invitation.candidate_id).where(Invitation.company_id == company_id, Invitation.status == "accepted"))
    app = db.scalars(
        select(Application.candidate_id).join(Vacancy).where(Vacancy.company_id == company_id, Application.status != "withdrawn")
    )
    return set(acc) | set(app)


def assert_no_leaks(client, heads) -> int:
    """Возвращает число проверенных пар (компания × кандидат), чтобы тест не был пустым."""
    checked = 0
    with SessionLocal() as db:
        cands = db.scalars(select(Candidate)).all()
        companies = db.scalars(select(Company)).all()
        for co_id, h in heads.items():
            pages = crawl(client, h)
            text = "\n".join(t for _, t in pages)
            for url, t in pages:
                bad = FORBIDDEN_KEYS & set(_keys(json.loads(t)))
                assert not bad, (url, bad)
            ok = allowed_ids(db, co_id)
            # значения, которые законно в ответе: контакты разрешённых кандидатов и рекрутёров
            legit = {v for c in cands if c.id in ok for v in _pii(c)}
            legit |= {v for co in companies for v in (co.recruiter_name, co.recruiter_email, co.recruiter_tg, co.name) if v}
            for c in cands:
                if c.id in ok:
                    continue
                for v in _pii(c):
                    if any(v in lv for lv in legit):
                        continue  # тёзка разрешённого кандидата или рекрутёра — не отличить по тексту
                    hit = next((u for u, t in pages if _found(v, t)), None)
                    assert hit is None, f"ПДн кандидата {c.public_id} ({v!r}) у компании {co_id} в {hit}"
                    checked += 1
            # контакты разрешённых действительно видны (иначе проверка выше могла бы быть пустой)
            assert all(_found(c.email, text) for c in cands if c.id in ok), co_id
    return checked


def test_employer_endpoints_do_not_leak_pii(world):
    client, heads = world
    with SessionLocal() as db:
        lad = db.scalar(select(Company).where(Company.name == "Ладога Пэй"))
        assert allowed_ids(db, lad.id), "в засеве должны быть принятые приглашения/отклики"
    assert assert_no_leaks(client, heads) > 100


def _pick_free(client, h, db, co) -> Candidate:
    """Видимый кандидат без связей с компанией и со свободной ёмкостью."""
    linked = allowed_ids(db, co.id) | set(db.scalars(select(Invitation.candidate_id).where(Invitation.company_id == co.id)))
    items = client.get("/api/employer/search?limit=100", headers=h).json()["items"]
    for it in items:
        c = db.scalar(select(Candidate).where(Candidate.public_id == it["id"]))
        if c.id not in linked and not it["busy"] and c.user_id is None and c.min_salary:
            return c
    raise AssertionError("нет свободного кандидата")


def _invite(client, h, c: Candidate) -> int:
    p25 = catalog.market(c.spec, c.grade, c.city)["p25"]
    lo = max(p25, c.min_salary)
    body = {"candidate_id": c.public_id, "role": "Разработчик", "salary_from": lo, "salary_to": int(lo * 1.2), "format": (c.formats or ["Удалённо"])[0]}
    r = client.post("/api/employer/invites", json=body, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["invite"]["contact"] is None
    return r.json()["invite"]["id"]


def _login_as(db, c: Candidate) -> dict:
    u = User(email=f"user-{c.public_id.lower()}@example.ru", role="candidate")
    db.add(u)
    db.flush()
    c.user_id = u.id
    db.commit()
    return {"Authorization": "Bearer " + issue_token(db, u)}


def test_candidate_lifecycle_contacts_consents_delete(world):
    client, heads = world
    with SessionLocal() as db:
        lad = db.scalar(select(Company).where(Company.name == "Ладога Пэй"))
        h = heads[lad.id]
        x = _pick_free(client, h, db, lad)
        pid, email, name = x.public_id, x.email, x.name
        iid = _invite(client, h, x)
        y = _pick_free(client, h, db, lad)
        iid_y = _invite(client, h, y)
        hx, hy = _login_as(db, x), _login_as(db, y)
        y_email = y.email

    def pipe_text():
        return client.get("/api/employer/pipeline", headers=h).text

    # до ответа — анонимно; компания видна кандидату сразу
    assert not _found(email, pipe_text())
    d = client.get(f"/api/candidate/invites/{iid}", headers=hx).json()
    assert d["company_knows"] == "anonymous" and d["recruiter"]["email"] and "company_sees" not in d
    # отказ — контакты так и не раскрываются
    assert client.post(f"/api/candidate/invites/{iid_y}/decline", json={"reason": "salary", "comment": "мало"}, headers=hy).status_code == 200
    row = next(r for r in client.get("/api/employer/pipeline", headers=h).json()["items"] if r["id"] == iid_y)
    assert row["status"] == "no" and row["contact"] is None and "мало" not in pipe_text()  # комментарий отказа компании не показываем
    assert not _found(y_email, pipe_text())
    # принятие — контакты видны, раскрытие в журнале (без ПДн в detail)
    acc = client.post(f"/api/candidate/invites/{iid}/accept", headers=hx).json()
    assert acc["company_knows"] == "contacts" and acc["company_sees"]["email"] == email
    assert _found(email, pipe_text())
    with SessionLocal() as db:
        logs = db.scalars(select(AuditLog).where(AuditLog.action == "contacts_revealed", AuditLog.detail["invitation_id"].as_integer() == iid)).all()
        assert len(logs) == 1 and logs[0].detail == {"invitation_id": iid, "company_id": lad.id}
    assert assert_no_leaks(client, {lad.id: h}) > 0  # после принятия правило «разрешённых» всё ещё держится

    # отзыв согласия на публикацию → карточка пропадает из поиска и подборок, новые приглашения невозможны
    assert client.patch("/api/candidate/consents", json={"consent_publish": False}, headers=hx).json()["consent_publish"] is False
    assert client.get(f"/api/employer/candidates/{pid}", headers=h).status_code == 404
    search = client.get("/api/employer/search?limit=100", headers=h).json()
    assert pid not in [c["id"] for c in search["items"]]
    other = next(co_id for co_id in heads if co_id != lad.id)
    with SessionLocal() as db:
        cx = db.scalar(select(Candidate).where(Candidate.public_id == pid))
        assert not matching.visible(cx)
    r = client.post("/api/employer/invites", json={"candidate_id": pid, "role": "Разработчик", "salary_from": 300000, "salary_to": 330000, "format": "Удалённо"},
                    headers=heads[other])
    assert r.status_code == 404
    # отзыв согласия на обработку → «не ищу», публикацию вернуть нельзя
    off = client.patch("/api/candidate/consents", json={"consent_152": False}, headers=hx).json()
    assert (off["consent_152"], off["consent_publish"], off["status"]) == (False, False, "off")
    assert client.patch("/api/candidate/consents", json={"consent_publish": True}, headers=hx).status_code == 422
    on = client.patch("/api/candidate/consents", json={"consent_152": True, "consent_publish": True}, headers=hx).json()
    assert on["consent_152"] and on["consent_publish"] and on["consent_version"] == catalog.CONSENT_VERSION

    # выгрузка: свои данные с приглашениями, без служебных полей
    ex = client.get("/api/candidate/me/export", headers=hx)
    assert ex.status_code == 200 and ex.json()["profile"]["email"] == email
    assert {i["id"] for i in ex.json()["invitations"]} >= {iid}
    leaked = (FORBIDDEN_KEYS - {"cv_text", "cv_filename", "hidden_from", "decline_comment", "embedding", "truth", "theta_true", "skills_true"}) & set(_keys(ex.json()))
    assert not leaked, leaked  # выгрузка полная: свои данные, включая служебные (truth — у синтетики это её же скрытые поля)

    # удаление: каскадом уходят приглашения, контакты пропадают из воронки, в журнале — только идентификаторы
    assert client.delete("/api/candidate/me", headers=hx).json() == {"deleted": True}
    assert not _found(email, pipe_text())
    with SessionLocal() as db:
        assert db.scalar(select(Candidate).where(Candidate.public_id == pid)) is None
        assert db.get(Invitation, iid) is None
        for a in db.scalars(select(AuditLog)):
            s = json.dumps(a.detail, ensure_ascii=False) if a.detail else ""
            assert email not in s and name not in s, a.action
    assert client.get("/api/candidate/me", headers=hx).status_code == 401


def test_search_does_not_load_pii_columns(world):
    """Поиск грузит весь банк: ФИО, почта, резюме и «правда» синтетики даже не читаются из БД (employer.SEARCH_SKIP) —
    и быстрее (нагрузочный прогон), и ПДн не попадают в память обработчика, который выдаёт анонимные карточки."""
    client, heads = world
    h = next(iter(heads.values()))
    sqls: list[str] = []
    listen = lambda conn, cur, stmt, *a: sqls.append(stmt)  # noqa: E731
    event.listen(engine, "before_cursor_execute", listen)
    try:
        for q in ("", "?spec=Backend&q=python kafka&fsp=1", "?cf=1&hackathon=1&format=Удалённо"):
            assert client.get(f"/api/employer/search{q}", headers=h).status_code == 200
    finally:
        event.remove(engine, "before_cursor_execute", listen)
    # запрос банка — выборка открытых кандидатов (без теста тоже видны — фильтра по theta нет)
    bank = [s for s in sqls if "FROM candidates" in s and "candidates.status = " in s]
    assert len(bank) == 3, "запрос банка не найден"
    for col in ("name", "email", "tg", "cv_text", "embedding", "truth", "competencies", "notif"):
        assert not any(re.search(rf"candidates\.{col}\b", s) for s in bank), col
    assert all("candidates.public_id" in s for s in bank)  # сама выборка на месте
