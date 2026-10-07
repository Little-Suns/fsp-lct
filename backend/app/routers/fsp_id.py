"""Вход и привязка через ФСП ID (OIDC Authorization Code + PKCE): POST /start → провайдер → GET /callback → POST /exchange.

* Браузер привязан к потоку кукой fsp_flow (HttpOnly, SameSite=Lax, только /api/auth/fsp): чужая ссылка с code и state
  не войдёт и не привяжет чужой ФСП ID (login CSRF). state одноразовый — повтор callback не пройдёт.
* Наш Bearer-токен не попадает в URL: callback кладёт во фрагмент одноразовый билет на минуту, фронт меняет его
  на токен POST /exchange с той же кукой.
* Пользователь создаётся только по подтверждённой в ФСП ID почте, ролью из /start (кандидат или компания; компания после
  входа всё равно проходит ИНН и рабочую почту, причём почта входа считается подтверждённой только нашим кодом
  (users.email_confirmed), а не Keycloak или сторонним IdP). Сторонние входы (Яндекс ID, корпоративный SSO) — брокер Keycloak по kc_idp_hint. Существующий аккаунт с той же
  почтой связывается автоматически, только пока у него нет ни профиля кандидата, ни компании (роль — как во входе
  по коду, deps.verify); аккаунт с данными привязывается только из настроек после входа по коду — доверять одному
  email_verified провайдера, когда есть что угнать, не будем.
* Достижения из ФСП ID пишутся, только если у кандидата действует согласие на внешние данные (152-ФЗ).
"""

import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, Response
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app import config
from app.db import get_db
from app.deps import EMAIL_RE, _has_profile, current_user, hash_secret, login_token
from app.integrations import fsp_id
from app.integrations.fsp_id import FspIdError
from app.models import AuditLog, Candidate, FspLogin, User

router = APIRouter(prefix="/api/auth/fsp", tags=["auth"])
COOKIE = "fsp_flow"
COOKIE_PATH = "/api/auth/fsp"
FLOW_TTL = timedelta(minutes=10)
TICKET_TTL = timedelta(seconds=60)
MAX_PARAM = 2048  # state, code, error и кука длиннее — отказ «state» редиректом во фронт, а не 422 в браузере
log = logging.getLogger(__name__)


class StartIn(BaseModel):
    mode: Literal["login", "link"] = "login"
    role: Literal["candidate", "employer"] = "candidate"  # при mode=link игнорируется: привязка — только у кандидата
    idp: str | None = Field(default=None, max_length=32)  # alias Identity Provider из FSP_ID_IDPS (kc_idp_hint)


class TicketIn(BaseModel):
    ticket: str = Field(max_length=128)


class Fail(Exception):
    """Отказ во входе/привязке; code — ключ сообщения на фронте (fsp-error=…)."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def _back(**params) -> RedirectResponse:
    """Назад во фронт: только фиксированный путь «/», параметры — во фрагменте (не уходят на сервер и в Referer)."""
    r = RedirectResponse("/#" + urlencode(params), status_code=303)
    r.headers["Cache-Control"] = "no-store"
    r.headers["Referrer-Policy"] = "no-referrer"
    return r


@router.post("/start")
def start(body: StartIn, response: Response, authorization: str = Header(default=""), db: Session = Depends(get_db)):
    """Адрес авторизации у провайдера; фронт уводит туда браузер. mode=link — привязать ФСП ID к вошедшему кандидату."""
    if not fsp_id.enabled():
        raise HTTPException(503, "Вход через ФСП ID не настроен (FSP_ID_ISSUER, FSP_ID_CLIENT_ID, FSP_ID_CLIENT_SECRET)")
    if body.idp is not None and body.idp not in config.FSP_ID_IDPS:
        raise HTTPException(422, "Неизвестный провайдер входа")
    user_id, role = None, body.role
    if body.mode == "link":
        role = "candidate"
        user = current_user(authorization, db)
        if user.role != "candidate":
            raise HTTPException(403, "ФСП ID привязывается только к аккаунту кандидата")
        user_id = user.id
    state, browser = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    try:
        url = fsp_id.authorize_url(state, body.idp)
    except FspIdError as e:
        log.warning("ФСП ID: %s", e)
        raise HTTPException(502, "ФСП ID недоступен — попробуйте позже") from None
    now = datetime.now(UTC)
    # ponytail: незавершённые входы чистятся здесь же; лимит на /start по IP — на прокси, как и для /api/auth/email
    db.execute(delete(FspLogin).where(FspLogin.expires_at < now))
    db.add(FspLogin(state_hash=hash_secret(state), browser_hash=hash_secret(browser), mode=body.mode, role=role, user_id=user_id,
                    expires_at=now + FLOW_TTL))
    db.commit()
    response.set_cookie(COOKIE, browser, max_age=int(FLOW_TTL.total_seconds()), path=COOKIE_PATH, httponly=True,
                        samesite="lax", secure=config.FSP_ID_REDIRECT_URI.startswith("https://"))
    return {"url": url}


def _login_user(db: Session, ident: dict, role: str) -> User:
    """Кто входит: по ФСП ID; иначе по подтверждённой почте (связываем); иначе новый пользователь с выбранной ролью."""
    user = db.scalar(select(User).where(User.fsp_id == ident["sub"]).with_for_update())
    if not user:
        if not ident["email"] or not EMAIL_RE.fullmatch(ident["email"]):
            raise Fail("email")  # без подтверждённой почты аккаунт не создаём: иначе адрес занял бы не его владелец
        user = db.scalar(select(User).where(func.lower(User.email) == ident["email"]).with_for_update())
        if user and user.fsp_id:
            raise Fail("other")  # к этой почте уже привязан другой ФСП ID
        if user and _has_profile(db, user):
            raise Fail("link")  # аккаунт с данными: войти по коду и привязать ФСП ID в настройках
        if not user:
            user = User(email=ident["email"], role=role)
            db.add(user)
            db.flush()
        user.fsp_id = ident["sub"]
        db.add(AuditLog(actor_user_id=user.id, action="fsp_id_linked", detail=None))
    if user.role != role:
        if user.role == "admin" or _has_profile(db, user):
            raise Fail("role")  # организатора не превращаем, аккаунт с данными другой роли не переключаем
        db.add(AuditLog(actor_user_id=user.id, action="role_changed", detail=None))  # без ПДн: только идентификатор
        user.role = role  # как во входе по коду: роль меняется, пока нет ни профиля, ни компании
    return user


def _link_user(db: Session, user_id: int | None, sub: str) -> User:
    user = db.scalar(select(User).where(User.id == user_id).with_for_update()) if user_id else None
    if not user:
        raise Fail("state")
    if user.role != "candidate":
        raise Fail("role")  # роль могла смениться за время потока
    if user.fsp_id != sub:
        if user.fsp_id:
            raise Fail("other")  # сначала отвязать прежний
        if db.scalar(select(User.id).where(User.fsp_id == sub)):
            raise Fail("taken")
        user.fsp_id = sub
        db.add(AuditLog(actor_user_id=user.id, action="fsp_id_linked", detail=None))
    return user


@router.get("/callback")
def callback(state: str = Query(""), code: str = Query(""), error: str = Query(""), fsp_flow: str = Cookie(default=""),
             db: Session = Depends(get_db)):
    now = datetime.now(UTC)
    if max(len(state), len(code), len(error), len(fsp_flow)) > MAX_PARAM:
        state = ""
    # state потребляется атомарно и только в том же браузере: повтор или чужая ссылка — отказ
    flow = db.execute(
        update(FspLogin)
        .where(FspLogin.state_hash == hash_secret(state), FspLogin.browser_hash == hash_secret(fsp_flow), FspLogin.expires_at > now)
        .values(state_hash=None)
        .returning(FspLogin.id, FspLogin.mode, FspLogin.role, FspLogin.user_id)
    ).first() if state and fsp_flow else None
    db.commit()
    if not flow:
        return _back(fsp="error", e="state")
    try:
        if error or not code:
            raise Fail("denied" if error == "access_denied" else "provider")
        claims, access = fsp_id.exchange(code, state)
        info = fsp_id.userinfo(access, claims["sub"])
        ident = fsp_id.identity(claims, info)
        user = _link_user(db, flow.user_id, ident["sub"]) if flow.mode == "link" else _login_user(db, ident, flow.role)
        db.flush()
        db.commit()  # связь с ФСП ID — до импорта: import_protocol ищет кандидата по User.fsp_id и коммитит сам
    except IntegrityError:  # параллельный вход занял тот же ФСП ID или почту
        db.rollback()
        return _abort(db, flow.id, "taken")
    except Fail as e:
        db.rollback()
        return _abort(db, flow.id, e.code)
    except FspIdError as e:
        db.rollback()
        log.warning("ФСП ID: %s", e)  # причина без ПДн: тип ошибки и поле протокола
        return _abort(db, flow.id, e.code)
    if user.role == "candidate":  # достижения — только кандидату
        cand = db.scalar(select(Candidate).where(Candidate.user_id == user.id))
        ach = fsp_id.import_achievements(db, cand, ident["sub"], info)
        ach = "consent" if ach is None else str(ach)
    else:
        ach = "0"
    if flow.mode == "link":
        db.execute(delete(FspLogin).where(FspLogin.id == flow.id))
        db.commit()
        return _back(fsp="linked", ach=ach)
    ticket = secrets.token_urlsafe(32)
    db.execute(update(FspLogin).where(FspLogin.id == flow.id)
               .values(ticket_hash=hash_secret(ticket), user_id=user.id, expires_at=datetime.now(UTC) + TICKET_TTL))
    db.commit()
    return _back(fsp="login", t=ticket, ach=ach)


def _abort(db: Session, flow_id: int, code: str) -> RedirectResponse:
    db.execute(delete(FspLogin).where(FspLogin.id == flow_id))
    db.commit()
    return _back(fsp="error", e=code)


@router.post("/exchange")
def exchange(body: TicketIn, response: Response, fsp_flow: str = Cookie(default=""), db: Session = Depends(get_db)):
    """Одноразовый билет из callback (и кука того же браузера) → наш токен."""
    uid = db.scalar(
        delete(FspLogin)
        .where(FspLogin.ticket_hash == hash_secret(body.ticket), FspLogin.browser_hash == hash_secret(fsp_flow),
               FspLogin.mode == "login", FspLogin.expires_at > datetime.now(UTC))
        .returning(FspLogin.user_id)
    ) if fsp_flow and body.ticket else None
    user = db.get(User, uid) if uid else None
    if not user:
        db.rollback()
        raise HTTPException(401, "Вход через ФСП ID устарел — начните заново")
    response.delete_cookie(COOKIE, path=COOKIE_PATH)
    has_profile = _has_profile(db, user)  # у кандидата — профиль, у компании — карточка компании
    return login_token(user, db) | {"has_profile": has_profile}  # login_token коммитит удаление билета


@router.post("/unlink")
def unlink(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Отвязать ФСП ID. Подтверждённые достижения остаются; удалить их — отзыв согласия на внешние данные."""
    if user.fsp_id:
        user.fsp_id = None
        db.add(AuditLog(actor_user_id=user.id, action="fsp_id_unlinked", detail=None))
        db.commit()
    return {"fsp_id": None}
