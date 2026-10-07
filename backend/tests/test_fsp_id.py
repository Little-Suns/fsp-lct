"""ФСП ID по OpenID Connect против встроенного мок-провайдера: полный поток браузера (start → authorize → callback →
exchange), привязка и отвязка, импорт достижений по согласию, и отказы — чужой/повторный state, кука другого браузера,
повтор кода и билета, просроченный код, неверный PKCE, подпись чужим ключом, чужие aud/iss, nonce, alg. Своя БД (fsp_fspid)."""

import os

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fsp:fsp@localhost:5432/fsp_fspid")
os.environ["LLM_BASE_URL"] = ""
os.environ.setdefault("DEMO", "1")
os.environ["PUBLIC_URL"] = "http://testserver"  # адрес TestClient: issuer мока и redirect_uri собираются из него

import time
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, parse_qsl, urlsplit

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from sqlalchemy import select

from app import config
from app.catalog import CONSENT_VERSION
from app.db import SessionLocal, engine, reset_schema
from app.deps import issue_token
from app.integrations import fsp_id
from app.integrations.fsp_id import FspIdError
from app.main import app
from app.models import Achievement, AuditLog, Candidate, Company, Event, FspLogin, User
from app.routers import mock_fsp_id as mock

config.LLM_BASE_URL = ""


@pytest.fixture(scope="module")
def client():
    if "fsp_fspid" not in str(engine.url):
        pytest.skip("тест пересоздаёт схему — нужен отдельный DATABASE_URL (fsp_fspid)")
    reset_schema()
    with TestClient(app) as cl:
        yield cl


@pytest.fixture(autouse=True)
def backchannel(client, monkeypatch):
    """Запросы клиента к провайдеру (discovery, token, jwks, userinfo) — в то же приложение, отдельным TestClient."""
    monkeypatch.setattr(fsp_id, "HTTP", TestClient(app))
    fsp_id._cache.clear()
    client.cookies.clear()
    yield
    fsp_id._cache.clear()


def account(sub: str, email: str, verified: bool = True, achievements=None) -> str:
    mock.ACCOUNTS[sub] = {"name": "Тест Тестов", "email": email, "email_verified": verified, "achievements": achievements or []}
    return sub


def make_candidate(email: str, fsp: str | None = None, external: bool = True, role: str = "candidate",
                   profile: bool = True) -> tuple[int, dict]:
    with SessionLocal() as db:
        user = User(email=email, role=role, fsp_id=fsp)
        db.add(user)
        db.flush()
        if role == "candidate" and profile:
            db.add(Candidate(public_id=f"A-{uuid.uuid4().hex[:6]}", user_id=user.id, name="Тест", email=email, spec="Backend",
                             grade_claimed="Middle", min_salary=200000, city="Москва", consent_152=True,
                             consent_version=CONSENT_VERSION, consent_external=external,
                             consent_external_version=CONSENT_VERSION if external else None))
        db.commit()
        return user.id, {"Authorization": f"Bearer {issue_token(db, user)}"}


def authorize(client, mode: str = "login", headers=None) -> tuple[str, dict]:
    r = client.post("/api/auth/fsp/start", json={"mode": mode}, headers=headers or {})
    assert r.status_code == 200, r.text
    url = r.json()["url"]
    assert url.startswith(config.MOCK_FSP_ID_ISSUER + "/authorize?") and "fsp_flow" in client.cookies
    q = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    assert q["code_challenge_method"] == "S256" and q["redirect_uri"] == config.FSP_ID_REDIRECT_URI and "openid" in q["scope"]
    page = client.get(url)
    assert page.status_code == 200 and "ФСП ID (демо)" in page.text and page.headers["x-frame-options"] == "DENY"
    return url, q


def to_callback(client, q: dict, sub: str) -> str:
    """Пользователь выбрал аккаунт на странице мока → адрес callback с code и state."""
    form = {k: q[k] for k in ("client_id", "redirect_uri", "state", "nonce", "code_challenge")} | {"account": sub}
    r = client.post("/mock-fsp-id/authorize", data=form, follow_redirects=False)
    assert r.status_code == 303
    return r.headers["location"]


def back(client, callback_url: str) -> dict:
    r = client.get(callback_url, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/#") and r.headers["cache-control"] == "no-store"
    return dict(parse_qsl(urlsplit(r.headers["location"]).fragment))


def flow(client, sub: str, mode: str = "login", headers=None) -> dict:
    _, q = authorize(client, mode, headers)
    return back(client, to_callback(client, q, sub))


def login(client, sub: str) -> dict:
    frag = flow(client, sub)
    assert frag["fsp"] == "login", frag
    r = client.post("/api/auth/fsp/exchange", json={"ticket": frag["t"]})
    assert r.status_code == 200, r.text
    return {**r.json(), "ach": frag["ach"]}


def _user(**kw) -> User | None:
    with SessionLocal() as db:
        return db.scalar(select(User).filter_by(**kw))


def _achs(user_id: int) -> list[Achievement]:
    with SessionLocal() as db:
        cid = db.scalar(select(Candidate.id).where(Candidate.user_id == user_id))
        return db.scalars(select(Achievement).where(Achievement.candidate_id == cid).order_by(Achievement.id)).all()


# ---------- провайдер ----------


def test_mock_discovery_jwks_and_switch(client, monkeypatch):
    d = client.get("/mock-fsp-id/.well-known/openid-configuration").json()
    assert d["issuer"] == config.MOCK_FSP_ID_ISSUER == config.FSP_ID_ISSUER and d["code_challenge_methods_supported"] == ["S256"]
    keys = client.get("/mock-fsp-id/jwks").json()["keys"]
    assert keys[0]["kid"] == mock.KID and keys[0]["kty"] == "RSA" and "d" not in keys[0]  # только открытая часть
    assert client.get("/api/meta").json()["fsp_id"] is True
    monkeypatch.setattr(config, "FSP_ID_MOCK", False)
    assert client.get("/mock-fsp-id/jwks").status_code == 404
    # старая заглушка «ФСП ID без OAuth» удалена
    assert client.post("/api/auth/fsp", json={"fsp_id": "FSP-1042"}).status_code in (404, 405)


def test_mock_authorize_rejects_unknown_client_and_bad_request(client):
    _, q = authorize(client)
    bad = client.get("/mock-fsp-id/authorize", params={**q, "redirect_uri": "https://evil.example/cb"}, follow_redirects=False)
    assert bad.status_code == 400 and "location" not in bad.headers  # на чужой адрес не редиректим
    assert client.get("/mock-fsp-id/authorize", params={**q, "client_id": "other"}).status_code == 400
    form = {k: q[k] for k in ("client_id", "state", "nonce", "code_challenge")} | {"redirect_uri": "https://evil.example/cb", "account": "FSP-1042"}
    assert client.post("/mock-fsp-id/authorize", data=form, follow_redirects=False).status_code == 400
    nopkce = client.get("/mock-fsp-id/authorize", params={**q, "code_challenge_method": "plain"}, follow_redirects=False)
    assert nopkce.status_code == 303 and "error=invalid_request" in nopkce.headers["location"]
    # параметры на странице экранированы
    page = client.get("/mock-fsp-id/authorize", params={**q, "nonce": '"><script>x</script>'})
    assert "<script>x" not in page.text and "&lt;script&gt;" in page.text


def test_mock_token_endpoint_pkce_replay_and_client_auth(client, monkeypatch):
    _, q = authorize(client)
    code = parse_qs(urlsplit(to_callback(client, q, "FSP-1042")).query)["code"][0]
    good = {"grant_type": "authorization_code", "code": code, "redirect_uri": config.FSP_ID_REDIRECT_URI,
            "code_verifier": fsp_id.verifier(q["state"]), "client_id": config.FSP_ID_CLIENT_ID}
    assert client.post("/mock-fsp-id/token", data={**good, "client_secret": "wrong"}).json() == {"error": "invalid_client"}
    # неверный верификатор PKCE «сжигает» код (одноразовый)
    r = client.post("/mock-fsp-id/token", data={**good, "client_secret": config.FSP_ID_CLIENT_SECRET, "code_verifier": "x" * 43})
    assert r.status_code == 400 and r.json() == {"error": "invalid_grant"}
    assert client.post("/mock-fsp-id/token", data={**good, "client_secret": config.FSP_ID_CLIENT_SECRET}).json()["error"] == "invalid_grant"
    # client_secret_basic, затем повтор того же кода
    _, q = authorize(client)
    code = parse_qs(urlsplit(to_callback(client, q, "FSP-1042")).query)["code"][0]
    good |= {"code": code, "code_verifier": fsp_id.verifier(q["state"])}
    r = client.post("/mock-fsp-id/token", data=good, auth=(config.FSP_ID_CLIENT_ID, config.FSP_ID_CLIENT_SECRET))
    assert r.status_code == 200 and r.json()["token_type"] == "Bearer" and r.headers["cache-control"] == "no-store"
    access = r.json()["access_token"]
    assert client.post("/mock-fsp-id/token", data=good, auth=(config.FSP_ID_CLIENT_ID, config.FSP_ID_CLIENT_SECRET)).json()["error"] == "invalid_grant"
    assert client.get("/mock-fsp-id/userinfo", headers={"Authorization": f"Bearer {access}"}).json()["sub"] == "FSP-1042"
    assert client.get("/mock-fsp-id/userinfo", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.post("/mock-fsp-id/token", data={**good, "grant_type": "password", "client_secret": config.FSP_ID_CLIENT_SECRET}).json()["error"] == "unsupported_grant_type"
    assert client.post("/mock-fsp-id/token", data=good, headers={"Authorization": "Basic !!!"}).status_code == 401


# ---------- вход ----------


def test_login_existing_user_by_fsp_id_imports_achievements(client):
    uid, _ = make_candidate("orlov.fsp@example.ru", fsp="FSP-1042")
    r = login(client, "FSP-1042")
    assert r["role"] == "candidate" and r["has_profile"] is True and r["ach"] == "2"
    me = client.get("/api/auth/me", headers={"Authorization": f"Bearer {r['token']}"}).json()
    assert me["id"] == uid and me["fsp_id"] == "FSP-1042"
    achs = _achs(uid)
    assert [(a.source, a.place, a.verified) for a in achs] == [("fsp", 12, True), ("fsp", 2, True)] and all(a.weight > 0 for a in achs)
    assert login(client, "FSP-1042")["ach"] == "2" and len(_achs(uid)) == 2  # повторный вход идемпотентен
    assert "fsp_flow" not in client.cookies  # обмен снял куку потока
    with SessionLocal() as db:
        assert db.scalar(select(FspLogin).where(FspLogin.user_id == uid)) is None  # билет потреблён


def test_login_creates_candidate_only_by_verified_email(client):
    sub = account("FSP-T-new", "New.Person@Example.ru")
    r = login(client, sub)
    assert r["role"] == "candidate" and r["has_profile"] is False and r["ach"] == "consent"  # профиля нет — достижения не пишем
    u = _user(fsp_id=sub)
    assert u.email == "new.person@example.ru" and u.role == "candidate"
    # почта не подтверждена в ФСП ID — аккаунт не создаётся (адрес не закрепить за чужим)
    sub = account("FSP-T-unverified", "unverified@example.ru", verified=False)
    assert flow(client, sub) == {"fsp": "error", "e": "email"}
    assert _user(email="unverified@example.ru") is None


def test_login_links_existing_email_account_and_role_rules(client):
    # аккаунт без профиля (вошёл по коду, анкету не заполнил) связывается по подтверждённой почте
    uid, _ = make_candidate("byemail@example.ru", profile=False)
    sub = account("FSP-T-email", "byemail@example.ru")
    assert login(client, sub)["has_profile"] is False and _user(id=uid).fsp_id == sub
    with SessionLocal() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.actor_user_id == uid, AuditLog.action == "fsp_id_linked")).detail is None
    # аккаунт с профилем по одной лишь почте из ФСП ID не отдаём — только привязка из настроек после входа по коду
    pid, _ = make_candidate("withprofile@example.ru")
    assert flow(client, account("FSP-T-prof", "withprofile@example.ru")) == {"fsp": "error", "e": "link"}
    assert _user(id=pid).fsp_id is None
    # почта занята аккаунтом с другим ФСП ID
    make_candidate("other@example.ru", fsp="FSP-T-old")
    assert flow(client, account("FSP-T-new2", "other@example.ru")) == {"fsp": "error", "e": "other"}
    # работодатель с компанией (ФСП ID уже связан) — не превращаем в кандидата
    eid, _ = make_candidate("hr@company.example", role="employer", fsp="FSP-T-hr")
    with SessionLocal() as db:
        db.add(Company(user_id=eid, name="Ко", inn="7700000001", recruiter_name="HR", recruiter_email="hr@company.example"))
        db.commit()
    assert flow(client, account("FSP-T-hr", "hr@company.example")) == {"fsp": "error", "e": "role"}
    assert _user(id=eid).role == "employer"
    # организатор — никогда; роль без профиля меняется, как во входе по коду
    aid, _ = make_candidate("admin@fsp.example", role="admin", fsp="FSP-T-admin")
    assert flow(client, account("FSP-T-admin", "admin@fsp.example")) == {"fsp": "error", "e": "role"}
    assert _user(id=aid).role == "admin"
    # роль без профиля меняется, как во входе по коду
    nid, _ = make_candidate("noprofile@company.example", role="employer")
    assert login(client, account("FSP-T-np", "noprofile@company.example"))["role"] == "candidate" and _user(id=nid).role == "candidate"


def test_denied_and_provider_errors(client, monkeypatch):
    _, q = authorize(client)
    form = {k: q[k] for k in ("client_id", "redirect_uri", "state", "nonce", "code_challenge")} | {"account": ""}
    loc = client.post("/mock-fsp-id/authorize", data=form, follow_redirects=False).headers["location"]
    assert "error=access_denied" in loc and back(client, loc) == {"fsp": "error", "e": "denied"}
    # просроченный код: провайдер отвечает invalid_grant → ошибка провайдера, поток удалён
    monkeypatch.setattr(mock, "CODE_TTL", -1.0)
    assert flow(client, "FSP-1042") == {"fsp": "error", "e": "provider"}
    monkeypatch.setattr(mock, "CODE_TTL", 60.0)
    # провайдер недоступен на старте (discovery не в кэше)
    fsp_id._cache.clear()
    monkeypatch.setattr(fsp_id, "_get", lambda *a, **k: (_ for _ in ()).throw(FspIdError("down")))
    assert client.post("/api/auth/fsp/start", json={"mode": "login"}).status_code == 502
    monkeypatch.setattr(config, "FSP_ID_ISSUER", "")
    assert client.post("/api/auth/fsp/start", json={"mode": "login"}).status_code == 503
    assert client.get("/api/meta").json()["fsp_id"] is False
    # боевой issuer — только с https redirect_uri
    monkeypatch.setattr(config, "FSP_ID_ISSUER", "https://id.example/realms/fsp")
    assert fsp_id.enabled() is False
    monkeypatch.setattr(config, "FSP_ID_REDIRECT_URI", "https://career.example/api/auth/fsp/callback")
    assert fsp_id.enabled() is True


def test_bad_signature_is_rejected(client, monkeypatch):
    monkeypatch.setattr(mock, "_key", rsa.generate_private_key(public_exponent=65537, key_size=2048))  # тот же kid, чужой ключ
    assert flow(client, "FSP-1042") == {"fsp": "error", "e": "token"}


def test_state_cookie_and_replay(client):
    make_candidate("state@example.ru", fsp="FSP-T-state")
    account("FSP-T-state", "state@example.ru")
    _, q = authorize(client)
    cb = to_callback(client, q, "FSP-T-state")
    # подменённый state
    assert back(client, cb.replace("state=", "state=x")) == {"fsp": "error", "e": "state"}
    # чужой браузер: та же ссылка без нашей куки (login CSRF)
    cookie, other = client.cookies["fsp_flow"], TestClient(app)
    assert back(other, cb) == {"fsp": "error", "e": "state"}
    frag = back(client, cb)
    assert frag["fsp"] == "login"
    assert back(client, cb) == {"fsp": "error", "e": "state"}  # повтор callback
    # билет: с чужой кукой — нет, с нашей — один раз
    assert other.post("/api/auth/fsp/exchange", json={"ticket": frag["t"]}, headers={"Cookie": "fsp_flow=other"}).status_code == 401
    assert client.post("/api/auth/fsp/exchange", json={"ticket": "x" + frag["t"]}).status_code == 401
    assert client.post("/api/auth/fsp/exchange", json={"ticket": frag["t"]}).status_code == 200
    assert other.post("/api/auth/fsp/exchange", json={"ticket": frag["t"]}, headers={"Cookie": f"fsp_flow={cookie}"}).status_code == 401
    # просроченный поток
    _, q = authorize(client)
    cb = to_callback(client, q, "FSP-T-state")
    with SessionLocal() as db:
        db.query(FspLogin).filter(FspLogin.state_hash.is_not(None)).update({"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
        db.commit()
    assert back(client, cb) == {"fsp": "error", "e": "state"}
    assert back(client, "/api/auth/fsp/callback?code=x") == {"fsp": "error", "e": "state"}  # без state
    assert back(client, "/api/auth/fsp/callback?code=x&state=" + "s" * 3000) == {"fsp": "error", "e": "state"}  # не 422


# ---------- привязка из настроек ----------


def test_link_unlink_and_consent(client):
    uid, h = make_candidate("link@example.ru", external=False)
    sub = account("FSP-T-link", "fsp-mail@example.ru", achievements=mock.ACCOUNTS["FSP-2077"]["achievements"])
    assert client.post("/api/auth/fsp/start", json={"mode": "link"}).status_code == 401
    assert flow(client, sub, "link", h) == {"fsp": "linked", "ach": "consent"}  # без согласия на внешние данные — не пишем
    assert _user(id=uid).fsp_id == sub and _achs(uid) == []
    with SessionLocal() as db:
        assert db.scalar(select(Event.id).where(Event.source == "fsp", Event.external_id == "champ-2025-sec")) is None
    assert client.post("/api/achievements/consent", json={"value": True}, headers=h).status_code == 200
    assert flow(client, sub, "link", h) == {"fsp": "linked", "ach": "1"}  # повторная привязка того же ФСП ID — обновление
    assert [(a.source, a.place, a.team) for a in _achs(uid)] == [("fsp", 3, "Команда «Полюс»")]
    # этот ФСП ID уже у другого / к аккаунту привязан другой
    _, h2 = make_candidate("link2@example.ru")
    assert flow(client, sub, "link", h2) == {"fsp": "error", "e": "taken"}
    assert flow(client, account("FSP-T-link3", "x3@example.ru"), "link", h) == {"fsp": "error", "e": "other"}
    # отвязка: ФСП ID снят, подтверждённые достижения остаются, журнал без ПДн
    assert client.post("/api/auth/fsp/unlink", headers=h).json() == {"fsp_id": None}
    assert _user(id=uid).fsp_id is None and len(_achs(uid)) == 1
    assert client.post("/api/auth/fsp/unlink", headers=h).json() == {"fsp_id": None}
    with SessionLocal() as db:
        assert [a.action for a in db.scalars(select(AuditLog).where(AuditLog.actor_user_id == uid).order_by(AuditLog.id))
                if a.action.startswith("fsp_id")] == ["fsp_id_linked", "fsp_id_unlinked"]
    # работодатель привязать не может; роль сменилась за время потока — тоже отказ
    eid, he = make_candidate("emp@company.example", role="employer")
    assert client.post("/api/auth/fsp/start", json={"mode": "link"}, headers=he).status_code == 403
    _, q = authorize(client, "link", h2)
    with SessionLocal() as db:
        db.get(User, db.scalar(select(FspLogin.user_id).where(FspLogin.state_hash.is_not(None)))).role = "employer"
        db.commit()
    assert back(client, to_callback(client, q, account("FSP-T-link4", "x4@example.ru"))) == {"fsp": "error", "e": "role"}
    with SessionLocal() as db:
        db.query(User).filter(User.email == "link2@example.ru").update({"role": "candidate"})
        db.commit()
    # удалённый за время потока пользователь
    _, q = authorize(client, "link", h2)
    with SessionLocal() as db:
        db.query(FspLogin).filter(FspLogin.state_hash.is_not(None)).update({"user_id": None})
        db.commit()
    assert back(client, to_callback(client, q, sub)) == {"fsp": "error", "e": "state"}


def test_broken_achievement_records_are_skipped(client):
    good = mock.ACCOUNTS["FSP-1042"]["achievements"][1]
    bad = ["строка", {"event": "не объект"}, {"event": {"external_id": "x1", "title": "T", "level": "galactic"}},
           {"event": {"external_id": "x2", "title": "T", "participants": 10**12}}, {"event": {"external_id": "x3"}},
           {"event": {"external_id": "x4", "title": "T"}, "place": "первое"}, {"event": {"external_id": "x5", "title": "T", "level": ["national"]}}]
    uid, _ = make_candidate("broken@example.ru", fsp="FSP-T-broken")
    account("FSP-T-broken", "broken@example.ru", achievements=[*bad, {**good, "team": "К" * 500}])
    assert login(client, "FSP-T-broken")["ach"] == "1"
    assert [len(a.team) for a in _achs(uid)] == [128]
    with SessionLocal() as db:
        assert fsp_id.import_achievements(db, None, "FSP-T-broken", {"fsp_achievements": [good]}) is None
        cand = db.scalar(select(Candidate).where(Candidate.user_id == uid))
        assert fsp_id.import_achievements(db, cand, "FSP-T-broken", {}) == 0


# ---------- проверка id_token ----------


def _claims(**kw) -> dict:
    now = int(time.time())
    return {"iss": config.FSP_ID_ISSUER, "sub": "FSP-1042", "aud": config.FSP_ID_CLIENT_ID, "iat": now, "exp": now + 300,
            "nonce": fsp_id.nonce("st"), **kw}


def _verify(token: str) -> dict:
    return fsp_id.verify_id_token(token, fsp_id.nonce("st"))


def test_id_token_validation(client):
    assert _verify(mock.sign(_claims()))["sub"] == "FSP-1042"
    assert _verify(mock.sign(_claims(aud=[config.FSP_ID_CLIENT_ID, "x"], azp=config.FSP_ID_CLIENT_ID)))["sub"] == "FSP-1042"
    rogue = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    bad = {
        "подпись чужим ключом": jwt.encode(_claims(), rogue, algorithm="RS256", headers={"kid": mock.KID}),
        "неизвестный kid": jwt.encode(_claims(), rogue, algorithm="RS256", headers={"kid": "other"}),
        "чужой aud": mock.sign(_claims(aud="other-client")),
        "чужой iss": mock.sign(_claims(iss="https://evil.example/realms/fsp")),
        "истёк": mock.sign(_claims(exp=int(time.time()) - 120)),
        "из будущего": mock.sign(_claims(iat=int(time.time()) + 3600)),
        "чужой nonce": mock.sign(_claims(nonce="other")),
        "без nonce": mock.sign({k: v for k, v in _claims().items() if k != "nonce"}),
        "azp чужой": mock.sign(_claims(aud=[config.FSP_ID_CLIENT_ID, "x"], azp="x")),
        "длинный sub": mock.sign(_claims(sub="s" * 65)),
        "HS256 на открытом ключе": jwt.encode(_claims(), "secret-key-that-is-long-enough-32b", algorithm="HS256"),
        "alg none": jwt.encode(_claims(), None, algorithm="none"),
        "не JWT": "not.a.jwt",
    }
    for name, tok in bad.items():
        with pytest.raises(FspIdError) as e:
            _verify(tok)
        assert e.value.code == "token", name


def test_discovery_and_userinfo_checks(client, monkeypatch):
    real = fsp_id._get
    monkeypatch.setattr(fsp_id, "_get", lambda url, **k: {**real(url, **k), "issuer": "https://evil.example"})
    with pytest.raises(FspIdError, match="issuer"):
        fsp_id.discovery()
    monkeypatch.setattr(fsp_id, "_get", lambda url, **k: {**real(url, **k), "code_challenge_methods_supported": ["plain"]})
    with pytest.raises(FspIdError, match="S256"):
        fsp_id.discovery()
    monkeypatch.setattr(fsp_id, "_get", real)
    # боевой issuer — только https
    monkeypatch.setattr(config, "FSP_ID_ISSUER", "http://keycloak.example/realms/fsp")
    with pytest.raises(FspIdError, match="https"):
        fsp_id.discovery()
    monkeypatch.setattr(config, "FSP_ID_ISSUER", config.MOCK_FSP_ID_ISSUER)
    # userinfo с чужим sub
    monkeypatch.setattr(fsp_id, "_get", lambda url, **k: {"sub": "FSP-0000"} if url.endswith("/userinfo") else real(url, **k))
    with pytest.raises(FspIdError) as e:
        fsp_id.userinfo("tok", "FSP-1042")
    assert e.value.code == "token"
    # почта без email_verified не принимается
    assert fsp_id.identity({"sub": "s", "email": "a@b.ru"}, {})["email"] is None
    assert fsp_id.identity({"sub": "s"}, {"email": " A@B.ru ", "email_verified": True})["email"] == "a@b.ru"
    assert fsp_id.identity({"sub": "s", "email": "x", "email_verified": True}, {})["email"] is None


def test_http_failures(client, monkeypatch):
    import httpx

    def boom(*a, **k):
        raise httpx.ConnectError("нет сети")

    monkeypatch.setattr(fsp_id.HTTP, "get", boom)
    with pytest.raises(FspIdError, match="недоступен"):
        fsp_id.discovery()
    monkeypatch.undo()
    monkeypatch.setattr(fsp_id, "HTTP", TestClient(app))
    fsp_id._cache.clear()
    fsp_id.discovery()
    monkeypatch.setattr(fsp_id.HTTP, "post", boom)
    with pytest.raises(FspIdError, match="недоступен"):
        fsp_id.exchange("code", "st")
    resp = lambda status, body: type("R", (), {"status_code": status, "json": lambda self: body})()  # noqa: E731
    monkeypatch.setattr(fsp_id.HTTP, "post", lambda *a, **k: resp(200, {"token_type": "Bearer"}))
    with pytest.raises(FspIdError, match="id_token"):
        fsp_id.exchange("code", "st")
    monkeypatch.setattr(fsp_id.HTTP, "post", lambda *a, **k: resp(200, ["list"]))
    with pytest.raises(FspIdError, match="JSON"):
        fsp_id.exchange("code", "st")

    def not_json(self):
        raise ValueError

    monkeypatch.setattr(fsp_id.HTTP, "post", lambda *a, **k: type("R", (), {"status_code": 200, "json": not_json})())
    with pytest.raises(FspIdError, match="JSON"):
        fsp_id.exchange("code", "st")
    # битый JWKS (ключ — не объект) — отказ, а не 500
    monkeypatch.setattr(fsp_id, "_get", lambda url, **k: {"keys": ["x"]} if url.endswith("/jwks") else fsp_id.discovery())
    with pytest.raises(FspIdError, match="JWKS"):
        _verify(mock.sign(_claims()))
    # JWKS без пригодных ключей
    monkeypatch.setattr(fsp_id, "_get", lambda url, **k: {"keys": []} if url.endswith("/jwks") else fsp_id.discovery())
    with pytest.raises(FspIdError, match="JWKS"):
        _verify(mock.sign(_claims()))


def test_account_deletion_drops_pending_flows(client):
    uid, h = make_candidate("gone@example.ru")
    authorize(client, "link", h)
    assert client.delete("/api/candidate/me", headers=h).json() == {"deleted": True}
    with SessionLocal() as db:
        assert db.scalar(select(FspLogin).where(FspLogin.user_id == uid)) is None
