"""Авторизация: Bearer-токен, в БД — только его sha256. Вход — код на почту (в демо код возвращается в ответе)
или ФСП ID по OpenID Connect (routers/fsp_id.py)."""

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app import config, mail
from app.db import get_db
from app.models import Candidate, Company, LoginChallenge, User

router = APIRouter(prefix="/api/auth", tags=["auth"])
OTP_TTL = timedelta(minutes=10)
OTP_MAX_ATTEMPTS = 5
OTP_RESEND = timedelta(seconds=60)
TOKEN_TTL = timedelta(days=30)


def hash_secret(value: str) -> str:
    """Токены и коды хранятся только как sha256: утечка БД не даёт войти. Высокая энтропия токена → соль не нужна."""
    return hashlib.sha256(value.encode()).hexdigest()


EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def otp_hash(email: str, code: str) -> str:
    """Код из 6 цифр по голому sha256 перебирается за секунды — поэтому HMAC с серверным перцем и адресом."""
    return hmac.new(config.SECRET_KEY.encode(), f"login:{email}:{code}".encode(), hashlib.sha256).hexdigest()


def issue_token(db: Session, user: User) -> str:
    """Новый токен (старый отзывается). Возвращает открытое значение — единственный раз, клиенту."""
    token = secrets.token_urlsafe(32)
    user.token = hash_secret(token)
    user.token_expires_at = datetime.now(UTC) + TOKEN_TTL
    db.commit()
    return token


def current_user(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> User:
    token = authorization.removeprefix("Bearer ").strip()
    user = db.scalar(select(User).where(User.token == hash_secret(token))) if token else None
    if not user or not user.token_expires_at or user.token_expires_at < datetime.now(UTC):
        raise HTTPException(401, "Нужен вход")
    return user


def current_candidate(user: User = Depends(current_user), db: Session = Depends(get_db)) -> Candidate:
    cand = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
    if not cand:
        raise HTTPException(403, "Профиль кандидата не создан")
    return cand


def current_company(user: User = Depends(current_user), db: Session = Depends(get_db)) -> Company:
    comp = db.scalar(select(Company).where(Company.user_id == user.id))
    if not comp:
        raise HTTPException(403, "Компания не зарегистрирована")
    return comp


def current_verified_company(comp: Company = Depends(current_company)) -> Company:
    """Для действий, которые нельзя доверить неподтверждённой компании."""
    if not comp.verified:
        raise HTTPException(403, "Компания не подтверждена: проверьте ИНН и рабочую почту на домене компании")
    return comp


class EmailIn(BaseModel):
    email: str = Field(max_length=254)
    role: str = "candidate"


class VerifyIn(BaseModel):
    email: str = Field(max_length=254)
    otp: str = Field(max_length=16)


def _issue(user: User, db: Session) -> dict:
    return {"token": issue_token(db, user), "role": user.role}


@router.post("/email")
def send_code(body: EmailIn, db: Session = Depends(get_db)):
    if body.role not in ("candidate", "employer"):
        raise HTTPException(422, "role: candidate | employer")
    email = body.email.strip().lower()
    if not EMAIL_RE.fullmatch(email):
        raise HTTPException(422, "Некорректная почта")
    if not config.DEMO and not config.SMTP_HOST:
        raise HTTPException(503, "Отправка писем не настроена (SMTP_HOST)")
    otp = f"{secrets.randbelow(10**6):06d}"
    now = datetime.now(UTC)
    values = {"role": body.role, "code_hash": otp_hash(email, otp), "expires_at": now + OTP_TTL, "attempts": 0, "sent_at": now}
    # пауза между отправками — атомарно в одном upsert: строка обновится, только если прошлый код старше OTP_RESEND
    # ponytail: лимит только по адресу; по IP/устройству — rate limiter на прокси перед публичным стендом
    stmt = insert(LoginChallenge).values(email=email, **values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[LoginChallenge.email], set_=values, where=LoginChallenge.sent_at <= now - OTP_RESEND
    ).returning(LoginChallenge.email)
    issued = db.scalar(stmt)
    db.commit()
    if issued is None:
        raise HTTPException(429, f"Код уже отправлен — новый можно запросить через {int(OTP_RESEND.total_seconds())} с")
    if config.SMTP_HOST:
        try:
            mail.send(email, "Код входа в ФСП Карьеру", f"Ваш код: {otp}\nДействует {int(OTP_TTL.total_seconds() // 60)} минут.")
        except OSError as e:
            raise HTTPException(502, "Не удалось отправить письмо — попробуйте позже") from e
    return {"sent": True, "otp": otp if config.DEMO else None}


@router.post("/verify")
def verify(body: VerifyIn, db: Session = Depends(get_db)):
    email = body.email.strip().lower()
    now = datetime.now(UTC)
    # попытка списывается атомарно до сравнения: параллельные запросы не обойдут лимит
    tried = db.scalar(
        update(LoginChallenge)
        .where(LoginChallenge.email == email, LoginChallenge.expires_at > now, LoginChallenge.attempts < OTP_MAX_ATTEMPTS)
        .values(attempts=LoginChallenge.attempts + 1)
        .returning(LoginChallenge.email)
    )
    db.commit()
    if tried is None:
        raise HTTPException(401, "Код истёк или исчерпаны попытки — запросите новый")
    # верный код потребляется атомарно: из параллельных запросов с одним кодом строку удалит только один
    role = db.scalar(
        delete(LoginChallenge)
        .where(LoginChallenge.email == email, LoginChallenge.code_hash == otp_hash(email, body.otp.strip()))
        .returning(LoginChallenge.role)
    )
    if role is None:
        db.rollback()
        raise HTTPException(401, "Неверный код")
    # пользователь появляется только после подтверждения почты — роль выбирает владелец адреса
    user = db.scalar(select(User).where(User.email == email).with_for_update())
    if not user:
        user = User(email=email, role=role)
        db.add(user)
        db.flush()
    elif user.role != role and not _has_profile(db, user):
        user.role = role  # роль меняется, пока нет ни профиля кандидата, ни компании
    return _issue(user, db)  # один commit: код удалён, пользователь создан, токен выдан — или ничего


def _has_profile(db: Session, user: User) -> bool:
    return bool(
        db.scalar(select(Candidate.id).where(Candidate.user_id == user.id))
        or db.scalar(select(Company.id).where(Company.user_id == user.id))
    )


@router.post("/demo/{role}")
def demo_login(role: str, db: Session = Depends(get_db)):
    """Вход за демо-персонажа из макета: candidate → Дмитрий Орлов (A-1042), employer → «Ладога Пэй»."""
    if not config.DEMO:
        raise HTTPException(404)
    email = {"candidate": "d.orlov@example.ru", "employer": "m.kovaleva@ladoga-pay.example"}.get(role)
    user = db.scalar(select(User).where(User.email == email)) if email else None
    if not user:
        raise HTTPException(404, "Демо-данные не засеяны: запустите seed")
    return _issue(user, db)


@router.post("/logout")
def logout(user: User = Depends(current_user), db: Session = Depends(get_db)):
    user.token = None
    user.token_expires_at = None
    db.commit()
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email, "role": user.role, "fsp_id": user.fsp_id}
