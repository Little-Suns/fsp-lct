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
from app.models import AuditLog, Candidate, Company, LoginChallenge, User

router = APIRouter(prefix="/api/auth", tags=["auth"])
OTP_TTL = timedelta(minutes=10)
OTP_MAX_ATTEMPTS = 5
OTP_RESEND = timedelta(seconds=60)
TOKEN_TTL = timedelta(days=30)
DEMO_PERSONAS = {"candidate": "d.orlov@example.ru", "employer": "m.kovaleva@ladoga-pay.example"}


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
    if not config.DEMO and user.token == hash_secret(demo_token(user)):
        raise HTTPException(401, "Нужен вход")  # общий демо-токен вне демо-режима не действует: его мог получить кто угодно
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


def demo_token(user: User) -> str:
    """Общий токен демо-входа: HMAC от адреса на серверном перце — у всех, кто вошёл за персонажа, один и тот же.
    Обычный вход отзывает прежний токен, и десятки зрителей стенда выбивали бы друг друга (нагрузочный прогон: 80 % 401)."""
    return hmac.new(config.SECRET_KEY.encode(), f"demo:{user.email}".encode(), hashlib.sha256).hexdigest()


def _issue_demo(user: User, db: Session) -> dict:
    token, now = demo_token(user), datetime.now(UTC)
    # персонаж уже открыт и срок продлевали меньше суток назад — без записи: иначе одновременные входы зрителей
    # выстраиваются в очередь на блокировке одной строки users (нагрузочный прогон в Docker: вход до 11 с)
    fresh = user.token == hash_secret(token) and user.token_expires_at and user.token_expires_at > now + TOKEN_TTL - timedelta(days=1)
    if not fresh:
        user.token, user.token_expires_at = hash_secret(token), now + TOKEN_TTL
    db.commit()  # без изменений — пустая транзакция; у verify здесь же фиксируется удаление кода
    return {"token": token, "role": user.role}


def login_token(user: User, db: Session) -> dict:
    """Токен входа (по коду почты или ФСП ID). Демо-персонаж в DEMO получает общий токен: иначе вход одного зрителя
    отозвал бы токен у остальных, вошедших за того же персонажа."""
    return _issue_demo(user, db) if config.DEMO and user.email in DEMO_PERSONAS.values() else _issue(user, db)


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
    elif not _has_profile(db, user):
        if user.role != role:
            user.role = role  # роль меняется, пока нет ни профиля кандидата, ни компании
        if user.fsp_id:  # пустой аккаунт с привязкой из брокера: владелец почты её не подтверждал (предзахват) — сбрасываем
            user.fsp_id = None
            db.add(AuditLog(actor_user_id=user.id, action="fsp_id_unlinked", detail=None))
    user.email_confirmed = True
    from app.routers.employer import refresh_verified  # поздний импорт: employer сам зависит от deps

    refresh_verified(db, user)  # доменная почта могла подтвердиться этим входом
    # один commit: код удалён, пользователь создан, токен выдан — или ничего. В демо вход по почте персонажа даёт общий
    # токен: код там приходит в ответе, и любой зритель иначе выбил бы остальных
    return login_token(user, db)


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
    email = DEMO_PERSONAS.get(role)
    user = db.scalar(select(User).where(User.email == email)) if email else None
    if not user:
        raise HTTPException(404, "Демо-данные не засеяны: запустите seed")
    return _issue_demo(user, db)


@router.post("/logout")
def logout(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if config.DEMO and user.token == hash_secret(demo_token(user)):
        return {"ok": True}  # общий демо-токен не отзывается: его и так выдают любому, а остальных зрителей выбило бы
    user.token = None
    user.token_expires_at = None
    db.commit()
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return {"id": user.id, "email": user.email, "role": user.role, "fsp_id": user.fsp_id}
