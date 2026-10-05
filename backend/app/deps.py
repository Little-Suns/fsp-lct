"""Авторизация: Bearer-токен из users.token. Вход — код на почту (в демо код возвращается в ответе) или ФСП ID."""

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.db import get_db
from app.models import Candidate, Company, User

router = APIRouter(prefix="/api/auth", tags=["auth"])
OTP_TTL = timedelta(minutes=10)
OTP_MAX_ATTEMPTS = 5
# ponytail: токены бессрочные и без отзыва; TTL + хранение хеша токена — перед выходом за пределы демо


def current_user(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> User:
    token = authorization.removeprefix("Bearer ").strip()
    user = db.scalar(select(User).where(User.token == token)) if token else None
    if not user:
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
    """Подборка, карточки, приглашения и лотерея — только проверенным компаниям (защита от фиктивных работодателей)."""
    if not comp.verified:
        raise HTTPException(403, "Компания не подтверждена: проверьте ИНН и рабочую почту на домене компании")
    return comp


class EmailIn(BaseModel):
    email: str
    role: str = "candidate"


class VerifyIn(BaseModel):
    email: str
    otp: str


class FspIn(BaseModel):
    fsp_id: str


def _issue(user: User, db: Session) -> dict:
    user.token = secrets.token_urlsafe(32)
    user.otp = None
    user.otp_expires_at = None
    db.commit()
    return {"token": user.token, "role": user.role}


@router.post("/email")
def send_code(body: EmailIn, db: Session = Depends(get_db)):
    if body.role not in ("candidate", "employer"):
        raise HTTPException(422, "role: candidate | employer")
    email = body.email.strip().lower()
    if "@" not in email:
        raise HTTPException(422, "Некорректная почта")
    user = db.scalar(select(User).where(User.email == email))
    if not user:
        user = User(email=email, role=body.role)
        db.add(user)
    user.otp = f"{secrets.randbelow(10**6):06d}"
    user.otp_expires_at = datetime.now(UTC) + OTP_TTL
    user.otp_attempts = 0
    db.commit()
    # ponytail: письма нет — в демо код отдаётся в ответе; SMTP, когда появится домен
    return {"sent": True, "otp": user.otp if config.DEMO else None}


@router.post("/verify")
def verify(body: VerifyIn, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == body.email.strip().lower()))
    if not user or not user.otp or not user.otp_expires_at or user.otp_expires_at < datetime.now(UTC):
        raise HTTPException(401, "Код истёк — запросите новый")
    if user.otp_attempts >= OTP_MAX_ATTEMPTS:
        user.otp = None  # перебор: код сгорает, нужен новый
        db.commit()
        raise HTTPException(429, "Слишком много попыток — запросите новый код")
    if not secrets.compare_digest(user.otp, body.otp):
        user.otp_attempts += 1
        db.commit()
        raise HTTPException(401, "Неверный код")
    return _issue(user, db)


@router.post("/fsp")
def fsp_login(body: FspIn, db: Session = Depends(get_db)):
    # ponytail: заглушка OAuth ФСП ID — пускает любого с известным fsp_id, поэтому только в DEMO; реальный OAuth, когда дадут доступ
    if not config.DEMO:
        raise HTTPException(501, "Вход через ФСП ID ещё не подключён")
    user =db.scalar(select(User).where(User.fsp_id == body.fsp_id))
    if not user:
        raise HTTPException(404, "ФСП ID не найден")
    return _issue(user, db)


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


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email, "role": user.role}
