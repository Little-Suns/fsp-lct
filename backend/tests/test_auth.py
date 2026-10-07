"""Вход и сессии: код почты и токен хранятся только как sha256, TTL кода и токена, лимит попыток, выход,
демо-входы закрыты без DEMO=1. Плюс сборка приложения целиком (main.py: роутеры, /api/health, /api/meta, статика).
Своя БД (fsp_auth)."""

import os
from datetime import UTC, datetime, timedelta

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fsp:fsp@localhost:5432/fsp_auth")
os.environ["LLM_BASE_URL"] = ""
os.environ.setdefault("DEMO", "1")

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app import catalog, config, deps
from app.db import Base, SessionLocal, engine, reset_schema
from app.deps import hash_secret, issue_token, otp_hash
from app.main import app
from app.models import Candidate, Company, LoginChallenge, User

config.LLM_BASE_URL = ""


@pytest.fixture(scope="module")
def client():
    if "fsp_auth" not in str(engine.url):
        pytest.skip("тест пересоздаёт схему — нужен отдельный DATABASE_URL (fsp_auth)")
    reset_schema()
    resend, deps.OTP_RESEND = deps.OTP_RESEND, timedelta(0)  # паузу между отправками проверяет отдельный тест
    with TestClient(app) as cl:  # lifespan → init_db → миграции (уже применены — no-op) и сверка схемы
        yield cl
    deps.OTP_RESEND = resend


def _user(email: str) -> User:
    with SessionLocal() as db:
        return db.scalar(select(User).where(User.email == email))


def _ch(email: str) -> LoginChallenge | None:
    with SessionLocal() as db:
        return db.get(LoginChallenge, email)


def _code(client, email: str, role: str = "candidate") -> str:
    r = client.post("/api/auth/email", json={"email": email, "role": role})
    assert r.status_code == 200 and r.json()["sent"] is True
    return r.json()["otp"]


def test_app_wiring(client):
    assert client.get("/api/health").json() == {"ok": True}
    meta = client.get("/api/meta").json()
    assert meta["cap"] == catalog.CANDIDATE_CAP and meta["invite_ttl_days"] == catalog.INVITE_TTL_DAYS and "Backend" in meta["specs"]
    assert meta["demo"] is config.DEMO
    paths = set(app.openapi()["paths"])
    for p in ("/api/auth/verify", "/api/candidate/me", "/api/employer/search", "/api/quest/start", "/api/achievements",
              "/api/lottery/{lottery_id}/public", "/api/validation", "/api/vacancies", "/api/tasks/mine"):
        assert p in paths, p
    if os.path.isdir(config.FRONTEND_DIR):  # фронт раздаётся тем же сервером
        assert client.get("/").status_code == 200


def test_index_without_frontend_is_503(client, tmp_path, monkeypatch):
    # каталог фронта пропал уже после старта (пересоздан на хосте): 503 с понятным текстом, а не 500 из FileResponse
    monkeypatch.setattr("app.main._front", tmp_path)
    r = client.get("/")
    assert r.status_code == 503 and r.json()["detail"].startswith("Фронт недоступен")
    (tmp_path / "index.html").write_text("<html>ok</html>", encoding="utf8")  # файл вернулся — страница отдаётся без рестарта
    assert client.get("/").status_code == 200


def test_otp_hashed_and_login(client):
    email = "Otp.User@Example.ru "
    otp = _code(client, email)
    assert len(otp) == 6 and otp.isdigit()
    assert _user("otp.user@example.ru") is None  # пользователь появляется только после проверки кода
    ch = _ch("otp.user@example.ru")  # почта нормализуется
    assert ch.role == "candidate" and ch.code_hash == otp_hash("otp.user@example.ru", otp) and ch.attempts == 0
    assert ch.code_hash != hash_secret(otp)  # HMAC с перцем, не голый sha256 — по дампу не перебрать
    assert ch.expires_at - datetime.now(UTC) <= deps.OTP_TTL
    r = client.post("/api/auth/verify", json={"email": email, "otp": f" {otp} "})
    assert r.status_code == 200 and r.json()["role"] == "candidate"
    token = r.json()["token"]
    u = _user("otp.user@example.ru")
    assert u.token == hash_secret(token) and token not in u.token and _ch("otp.user@example.ru") is None  # код одноразовый
    assert u.token_expires_at - datetime.now(UTC) > deps.TOKEN_TTL - timedelta(minutes=1)
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"}).json()["email"] == "otp.user@example.ru"
    # повтор того же кода не пускает
    assert client.post("/api/auth/verify", json={"email": email, "otp": otp}).status_code == 401
    # профиль ещё не создан → 403, компания — 403
    assert client.get("/api/candidate/me", headers={"Authorization": f"Bearer {token}"}).status_code == 403
    assert client.get("/api/employer/company", headers={"Authorization": f"Bearer {token}"}).status_code == 403
    # роль выбирает владелец почты при подтверждении; пока нет профиля, её можно сменить
    otp2 = _code(client, email, role="employer")
    assert _user("otp.user@example.ru").role == "candidate"  # запрос кода сам по себе роль не трогает
    assert client.post("/api/auth/verify", json={"email": email, "otp": otp2}).json()["role"] == "employer"


def test_role_fixed_after_profile(client):
    with SessionLocal() as db:
        u = User(email="has.company@example.ru", role="employer")
        db.add(u)
        db.flush()
        db.add(Company(inn="7707083893", name="ООО Тест", recruiter_name="HR", recruiter_email="hr@example.ru", user_id=u.id))
        db.commit()
    otp = _code(client, "has.company@example.ru", role="candidate")
    assert client.post("/api/auth/verify", json={"email": "has.company@example.ru", "otp": otp}).json()["role"] == "employer"


def test_send_code_validation(client):
    assert client.post("/api/auth/email", json={"email": "a@b.ru", "role": "admin"}).status_code == 422
    for bad in ("no-at-sign", "a@b", "a b@c.ru", "x" * 300 + "@a.ru"):
        assert client.post("/api/auth/email", json={"email": bad, "role": "candidate"}).status_code == 422, bad


def test_body_limit(client):
    r = client.post("/api/auth/email", content=b"{}", headers={"Content-Type": "application/json", "Content-Length": str(7 * 1024 * 1024)})
    assert r.status_code == 413


def test_smtp_tls(monkeypatch):
    from app import mail

    calls = []

    class Fake:
        def __init__(self, *a, **kw):
            calls.append(("init", type(self).__name__, kw.get("context") is not None))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self, context=None):
            calls.append(("starttls", context is not None))

        def login(self, *a):
            calls.append(("login",))

        def send_message(self, m):
            calls.append(("send", m["To"]))

    class FakeSSL(Fake):
        pass

    monkeypatch.setattr(mail.smtplib, "SMTP", Fake)
    monkeypatch.setattr(mail.smtplib, "SMTP_SSL", FakeSSL)
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.ru")
    monkeypatch.setattr(config, "SMTP_USER", "u")
    monkeypatch.setattr(config, "SMTP_PORT", 587)
    mail.send("a@b.ru", "s", "t")
    assert ("starttls", True) in calls and ("send", "a@b.ru") in calls  # STARTTLS с проверкой сертификата
    calls.clear()
    monkeypatch.setattr(config, "SMTP_PORT", 465)
    mail.send("a@b.ru", "s", "t")
    assert calls[0] == ("init", "FakeSSL", True) and not any(c[0] == "starttls" for c in calls)


def test_otp_attempts_lock(client):
    email = "brute@example.ru"
    otp = _code(client, email)
    wrong = "000000" if otp != "000000" else "111111"
    for _ in range(deps.OTP_MAX_ATTEMPTS):
        r = client.post("/api/auth/verify", json={"email": email, "otp": wrong})
        assert r.status_code == 401 and r.json()["detail"] == "Неверный код"
    # попытки исчерпаны — даже верный код не принимается
    r = client.post("/api/auth/verify", json={"email": email, "otp": otp})
    assert r.status_code == 401 and "исчерпаны" in r.json()["detail"]
    assert _ch(email).attempts == deps.OTP_MAX_ATTEMPTS
    # новый код сбрасывает счётчик
    otp = _code(client, email)
    assert _ch(email).attempts == 0
    assert client.post("/api/auth/verify", json={"email": email, "otp": otp}).status_code == 200


def test_otp_ttl(client):
    email = "slow@example.ru"
    otp = _code(client, email)
    with SessionLocal() as db:
        db.query(LoginChallenge).filter(LoginChallenge.email == email).update({"expires_at": datetime.now(UTC) - timedelta(seconds=1)})
        db.commit()
    assert client.post("/api/auth/verify", json={"email": email, "otp": otp}).status_code == 401
    assert client.post("/api/auth/verify", json={"email": "nobody@example.ru", "otp": otp}).status_code == 401


def test_token_ttl_logout_and_revoke(client):
    with SessionLocal() as db:
        u = User(email="tok@example.ru", role="employer")
        db.add(u)
        db.commit()
        t1 = issue_token(db, u)
        t2 = issue_token(db, u)  # новый токен отзывает старый
        uid = u.id
    h1, h2 = {"Authorization": f"Bearer {t1}"}, {"Authorization": f"Bearer {t2}"}
    assert client.get("/api/auth/me", headers=h1).status_code == 401
    assert client.get("/api/auth/me", headers=h2).json()["role"] == "employer"
    for bad in ({}, {"Authorization": "Bearer "}, {"Authorization": "Bearer nope"}, {"Authorization": t2[:-1]}):
        assert client.get("/api/auth/me", headers=bad).status_code == 401
    # без «Bearer » токен тоже читается
    assert client.get("/api/auth/me", headers={"Authorization": t2}).status_code == 200
    # TTL токена
    with SessionLocal() as db:
        db.get(User, uid).token_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert client.get("/api/auth/me", headers=h2).status_code == 401
    with SessionLocal() as db:
        t3 = issue_token(db, db.get(User, uid))
    h3 = {"Authorization": f"Bearer {t3}"}
    assert client.post("/api/auth/logout", headers=h3).json() == {"ok": True}
    assert client.get("/api/auth/me", headers=h3).status_code == 401
    assert client.post("/api/auth/logout", headers=h3).status_code == 401
    with SessionLocal() as db:
        u = db.get(User, uid)
        assert u.token is None and u.token_expires_at is None
    # необязательная авторизация списка вакансий: битый токен — как аноним, не 401
    assert client.get("/api/vacancies", headers={"Authorization": "Bearer nope"}).status_code == 200


def test_demo_logins(client, monkeypatch):
    # засеянных персонажей нет — 404
    assert client.post("/api/auth/demo/candidate").status_code == 404
    assert client.post("/api/auth/demo/admin").status_code == 404
    with SessionLocal() as db:
        db.add_all([User(email="d.orlov@example.ru", role="candidate", fsp_id="FSP-1042"), User(email="m.kovaleva@ladoga-pay.example", role="employer")])
        db.commit()
    r = client.post("/api/auth/demo/candidate")
    assert r.status_code == 200 and r.json()["role"] == "candidate"
    assert client.post("/api/auth/demo/employer").json()["role"] == "employer"
    # заглушки «ФСП ID без OAuth» больше нет: вход только через OIDC (tests/test_fsp_id.py)
    assert client.post("/api/auth/fsp", json={"fsp_id": "FSP-1042"}).status_code in (404, 405)
    # за персонажа входят десятки зрителей сразу: токен общий, вход и выход одного не выбивают остальных
    t1 = client.post("/api/auth/demo/candidate").json()["token"]
    exp = _user("d.orlov@example.ru").token_expires_at
    t2 = client.post("/api/auth/demo/candidate").json()["token"]
    assert t1 == t2  # второй зритель — тот же токен; вход через ФСП ID за персонажа — тоже (tests/test_fsp_id.py)
    assert _user("d.orlov@example.ru").token == hash_secret(t1)  # в БД — только хеш
    assert _user("d.orlov@example.ru").token_expires_at == exp  # повторный вход в течение суток строку не пишет (нет очереди на блокировке)
    h = {"Authorization": f"Bearer {t1}"}
    assert client.post("/api/auth/logout", headers=h).json() == {"ok": True}
    assert client.get("/api/auth/me", headers=h).json()["email"] == "d.orlov@example.ru"
    # вход по почте персонажа в демо (код приходит в ответе) — тот же общий токен, остальных не выбивает; код потреблён
    otp = client.post("/api/auth/email", json={"email": "d.orlov@example.ru"}).json()["otp"]
    assert client.post("/api/auth/verify", json={"email": "d.orlov@example.ru", "otp": otp}).json()["token"] == t1
    assert _ch("d.orlov@example.ru") is None
    # срок продлевали больше суток назад — вход пишет строку заново
    with SessionLocal() as db:
        db.get(User, _user("d.orlov@example.ru").id).token_expires_at = exp - timedelta(days=2)
        db.commit()
    assert client.post("/api/auth/demo/candidate").json()["token"] == t1
    assert _user("d.orlov@example.ru").token_expires_at > exp - timedelta(days=1)
    # обычный пользователь по почте получает свой токен — его выход отзывает как раньше
    otp = client.post("/api/auth/email", json={"email": "own@example.ru"}).json()["otp"]
    own = {"Authorization": f"Bearer {client.post('/api/auth/verify', json={'email': 'own@example.ru', 'otp': otp}).json()['token']}"}
    assert client.post("/api/auth/logout", headers=own).status_code == 200
    assert client.get("/api/auth/me", headers=own).status_code == 401
    # DEMO=0: демо-вход закрыт, код в ответе не возвращается, выданный ранее общий демо-токен не действует
    monkeypatch.setattr(config, "DEMO", False)
    assert client.get("/api/auth/me", headers=h).status_code == 401
    assert client.post("/api/auth/demo/candidate").status_code == 404
    assert client.post("/api/auth/email", json={"email": "prod@example.ru"}).status_code == 503  # без SMTP входа нет
    sent = []
    monkeypatch.setattr(config, "SMTP_HOST", "smtp.example.ru")
    monkeypatch.setattr(deps.mail, "send", lambda to, subj, text: sent.append((to, text)))
    r = client.post("/api/auth/email", json={"email": "prod@example.ru"})
    assert r.json() == {"sent": True, "otp": None}
    assert sent[0][0] == "prod@example.ru" and _ch("prod@example.ru").code_hash not in sent[0][1]  # в письме код, в БД — HMAC
    monkeypatch.setattr(deps.mail, "send", lambda *a: (_ for _ in ()).throw(OSError("down")))
    assert client.post("/api/auth/email", json={"email": "prod2@example.ru"}).status_code == 502


def test_resend_cooldown(client, monkeypatch):
    monkeypatch.setattr(deps, "OTP_RESEND", timedelta(seconds=60))
    assert client.post("/api/auth/email", json={"email": "cool@example.ru"}).status_code == 200
    r = client.post("/api/auth/email", json={"email": "cool@example.ru"})
    assert r.status_code == 429 and "60" in r.json()["detail"]
    with SessionLocal() as db:  # минута прошла
        db.query(LoginChallenge).filter(LoginChallenge.email == "cool@example.ru").update({"sent_at": datetime.now(UTC) - timedelta(seconds=61)})
        db.commit()
    assert client.post("/api/auth/email", json={"email": "cool@example.ru"}).status_code == 200


def test_schema_check(monkeypatch):
    from app import db as dbmod

    class Insp:
        def get_table_names(self):
            return [t for t in Base.metadata.tables if t != "audit_log"]

        def get_columns(self, name):
            return [] if name == "users" else [{"name": c.name} for c in Base.metadata.tables[name].columns]

    monkeypatch.setattr("sqlalchemy.inspect", lambda e: Insp())
    with pytest.raises(RuntimeError) as e:
        dbmod.check_schema()
    msg = str(e.value)  # нет таблицы целиком и нет колонок; подсказка — ревизия Alembic
    assert "audit_log" in msg and "users.email" in msg and "ревизии Alembic" in msg


def test_verified_company_guard():
    co = Company(inn="7707083893", name="Фейк", recruiter_name="HR", verified=False)
    with pytest.raises(HTTPException) as e:
        deps.current_verified_company(co)
    assert e.value.status_code == 403
    co.verified = True
    assert deps.current_verified_company(co) is co


def test_no_plaintext_secrets_in_db(client):
    """Ни один токен или код в users не похож на открытое значение: только sha256-хеши."""
    with SessionLocal() as db:
        for u in db.scalars(select(User)):
            v = u.token
            assert v is None or (len(v) == 64 and all(ch in "0123456789abcdef" for ch in v)), (u.email, v)
        for ch in db.scalars(select(LoginChallenge)):
            assert len(ch.code_hash) == 64 and not ch.code_hash.isdigit()
        assert db.scalar(select(Candidate).limit(1)) is None  # набор не трогает кандидатов


def test_code_consumed_once_in_parallel(client):
    """Один верный код из параллельных запросов пускает ровно один раз."""
    from concurrent.futures import ThreadPoolExecutor

    otp = _code(client, "race@example.ru")
    with ThreadPoolExecutor(4) as ex:
        codes = list(ex.map(lambda _: client.post("/api/auth/verify", json={"email": "race@example.ru", "otp": otp}).status_code, range(4)))
    assert sorted(codes) == [200, 401, 401, 401]
    with SessionLocal() as db:
        assert db.scalar(select(func.count()).select_from(User).where(User.email == "race@example.ru")) == 1
