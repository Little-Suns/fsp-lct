"""Мок-провайдер «ФСП ID (демо)»: OpenID Connect в том же приложении вместо Keycloak, которого на хакатоне не дают.

Протокол — как у realm Keycloak: discovery, /authorize (страница выбора демо-аккаунта вместо пароля), /token
(authorization_code + PKCE S256, код одноразовый, живёт CODE_TTL, привязан к client_id и redirect_uri), /userinfo
(+ claim fsp_achievements — подтверждённые участия и места из реестра ФСП), /jwks с RS256-ключом, созданным при старте.
Зарегистрирован один клиент — наш (config.FSP_ID_CLIENT_ID / SECRET / REDIRECT_URI). Включается FSP_ID_MOCK=1
(по умолчанию — при DEMO=1), иначе все пути — 404.
# ponytail: коды и access-токены — в памяти процесса (мок на одном воркере); боевой Keycloak хранит их сам
"""

import base64
import hashlib
import hmac
import html
import secrets
import threading
import time
from urllib.parse import unquote, urlencode

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import APIRouter, Depends, Form, Header, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from app import config


def _enabled() -> None:
    if not config.FSP_ID_MOCK:
        raise HTTPException(404)


router = APIRouter(prefix="/mock-fsp-id", include_in_schema=False, dependencies=[Depends(_enabled)])
CODE_TTL = 60.0  # секунд
TOKEN_TTL = 300.0
KID = secrets.token_hex(8)
_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)  # подписывает id_token; тесты подменяют на чужой
PUBLIC_JWK = {**jwt.algorithms.RSAAlgorithm.to_jwk(_key.public_key(), as_dict=True), "kid": KID, "use": "sig", "alg": "RS256"}
_lock = threading.Lock()
_codes: dict[str, dict] = {}  # sha256(code) → заявка; код одноразовый
_tokens: dict[str, tuple[str, float]] = {}  # sha256(access_token) → (sub, истекает)

# демо-аккаунты ФСП ID — синтетика: Орлов есть в сиде (FSP-1042), Соколовой на платформе ещё нет; сотрудники компаний —
# без достижений: Ковалёва — демо-работодатель из сида («Ладога Пэй»), Белова на платформе нет (новая компания)
ACCOUNTS = {
    "FSP-1042": {
        "name": "Дмитрий Орлов", "email": "d.orlov@example.ru", "email_verified": True,
        "achievements": [
            {"event": {"external_id": "cup-2025-prod", "level": "national", "participants": 600, "tags": ["product"],
                       "discipline": "продуктовое программирование",
                       "title": "Финал Кубка России по спортивному программированию 2025, продуктовое направление"},
             "place": 12, "team": "Команда «Сапсан»", "role": "backend", "rank": "1 разряд"},
            {"event": {"external_id": "reg-2024-moskva", "title": "Региональный этап ФСП 2024, Москва", "level": "regional",
                       "participants": 120, "tags": ["product"], "discipline": "продуктовое"},
             "place": 2, "team": "Команда «Сапсан»", "role": "backend"},
        ],
    },
    "KC-ladoga-0001": {"name": "Мария Ковалёва", "email": "m.kovaleva@ladoga-pay.example", "email_verified": True,
                       "company": True, "achievements": []},
    "KC-seversoft-0001": {"name": "Игорь Белов", "email": "i.belov@sever-soft.example", "email_verified": True,
                          "company": True, "achievements": []},
    "FSP-2077": {
        "name": "Анна Соколова", "email": "a.sokolova@example.ru", "email_verified": True,
        "achievements": [
            {"event": {"external_id": "champ-2025-sec", "level": "national", "participants": 300, "tags": ["security"],
                       "title": "Чемпионат России ФСП 2025, информационная безопасность", "date": "2025-07-10",
                       "discipline": "кибербезопасность"},
             "place": 3, "team": "Команда «Полюс»", "role": "pentest", "result": "призёр", "rank": "КМС"},
        ],
    },
}


def _h(v: str) -> str:
    return hashlib.sha256(v.encode()).hexdigest()


def _eq(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())  # str с не-ASCII compare_digest не принимает


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _issuer() -> str:
    return config.MOCK_FSP_ID_ISSUER


def sign(claims: dict) -> str:
    return jwt.encode(claims, _key, algorithm="RS256", headers={"kid": KID})


def _known_client(client_id: str, redirect_uri: str) -> bool:
    # redirect_uri — точное совпадение с зарегистрированным: иначе код утёк бы на чужой адрес
    return _eq(client_id, config.FSP_ID_CLIENT_ID) and _eq(redirect_uri, config.FSP_ID_REDIRECT_URI)


def _back(redirect_uri: str, **params) -> RedirectResponse:
    return RedirectResponse(redirect_uri + ("&" if "?" in redirect_uri else "?") + urlencode(params), status_code=303)


@router.get("/.well-known/openid-configuration")
def discovery():
    iss = _issuer()
    return {
        "issuer": iss,
        "authorization_endpoint": iss + "/authorize",
        "token_endpoint": iss + "/token",
        "userinfo_endpoint": iss + "/userinfo",
        "jwks_uri": iss + "/jwks",
        "response_types_supported": ["code"],
        "grant_types_supported": ["authorization_code"],
        "subject_types_supported": ["public"],
        "id_token_signing_alg_values_supported": ["RS256"],
        "code_challenge_methods_supported": ["S256"],
        "token_endpoint_auth_methods_supported": ["client_secret_post", "client_secret_basic"],
        "scopes_supported": ["openid", "email", "profile"],
        "claims_supported": ["sub", "identity_provider", "email", "email_verified", "name", "preferred_username", "fsp_achievements"],
    }


@router.get("/jwks")
def jwks():
    return {"keys": [PUBLIC_JWK]}


PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ФСП ID (демо)</title><style>body{{font:16px system-ui,sans-serif;background:#f4f4f7;color:#1b1c21;margin:0}}
main{{max-width:420px;margin:48px auto;padding:28px;background:#fff;border-radius:16px}}h1{{font-size:22px;margin:0 0 6px}}
p{{color:#555;font-size:14px}}h2{{font-size:13px;text-transform:uppercase;letter-spacing:.06em;color:#777;margin:18px 0 0}}button{{display:block;width:100%;padding:14px;margin:10px 0;border:1px solid #d0d0da;border-radius:10px;
background:#fff;font:inherit;text-align:left;cursor:pointer}}button.main{{background:#402fff;color:#fff;border-color:#402fff}}
small{{display:block;color:inherit;opacity:.75}}@media(max-width:460px){{main{{margin:16px;padding:20px}}}}</style></head><body><main>
<h1>ФСП ID (демо)</h1><p>Имитация единого входа ФСП на Keycloak (OpenID Connect). Пароль не нужен: выберите демо-аккаунт.
Сервис «ФСП Карьера» получит ФСП ID, подтверждённую почту, имя и подтверждённые участия и места.</p>
{via}<form method="post" action="{action}">{hidden}{buttons}<button name="account" value="">Отмена</button></form></main></body></html>"""


@router.get("/authorize", response_class=HTMLResponse)
def authorize(response_type: str = "", client_id: str = "", redirect_uri: str = "", scope: str = "", state: str = "",
              nonce: str = "", code_challenge: str = "", code_challenge_method: str = "", kc_idp_hint: str = ""):
    if not _known_client(client_id, redirect_uri):
        # неизвестный клиент или адрес — не редиректим (RFC 6749 §4.1.2.1), показываем ошибку
        return HTMLResponse("<h1>ФСП ID (демо): неизвестный клиент или redirect_uri</h1>", status_code=400)
    if response_type != "code" or "openid" not in scope.split() or code_challenge_method != "S256" \
            or not 43 <= len(code_challenge) <= 128 or not state:
        return _back(redirect_uri, error="invalid_request", state=state)
    fields = {"client_id": client_id, "redirect_uri": redirect_uri, "state": state, "nonce": nonce, "code_challenge": code_challenge,
              "kc_idp_hint": kc_idp_hint}
    hidden = "".join(f'<input type="hidden" name="{k}" value="{html.escape(v)}">' for k, v in fields.items())
    def group(title: str, company: bool) -> str:
        rows = "".join(
            f'<button class="main" name="account" value="{sub}">{html.escape(a["name"])}<small>{sub} · {html.escape(a["email"])}</small></button>'
            for sub, a in ((html.escape(k), v) for k, v in ACCOUNTS.items()) if bool(a.get("company")) == company
        )
        return f"<h2>{title}</h2>{rows}" if rows else ""

    buttons = group("Кандидаты", False) + group("Компании", True)
    # как у Keycloak: с kc_idp_hint он сразу ведёт на стороннего провайдера (здесь — имитация того же выбора аккаунта)
    via = f"<p><b>Вход через {html.escape(kc_idp_hint)}</b> (демо, брокер Keycloak)</p>" if kc_idp_hint else ""
    return HTMLResponse(PAGE.format(action=html.escape(_issuer() + "/authorize"), hidden=hidden, buttons=buttons, via=via),
                        headers={"X-Frame-Options": "DENY", "Content-Security-Policy": "frame-ancestors 'none'"})  # без кликджекинга


@router.post("/authorize")
def authorize_submit(client_id: str = Form(""), redirect_uri: str = Form(""), state: str = Form(""), nonce: str = Form(""),
                     code_challenge: str = Form(""), account: str = Form(""), kc_idp_hint: str = Form("")):
    # ponytail: без CSRF-токена на форме — паролей нет, а чужой код без state и куки нашего клиента бесполезен
    if not _known_client(client_id, redirect_uri):
        return HTMLResponse("<h1>ФСП ID (демо): неизвестный клиент или redirect_uri</h1>", status_code=400)
    if account not in ACCOUNTS:
        return _back(redirect_uri, error="access_denied", state=state)
    code = secrets.token_urlsafe(32)
    with _lock:
        now = time.time()
        for k in [k for k, v in _codes.items() if v["exp"] < now]:
            del _codes[k]
        _codes[_h(code)] = {"client_id": client_id, "redirect_uri": redirect_uri, "challenge": code_challenge,
                            "nonce": nonce, "sub": account, "idp": kc_idp_hint[:32], "exp": now + CODE_TTL}
    return _back(redirect_uri, code=code, state=state)


def _oauth_error(error: str, status: int = 400) -> JSONResponse:
    return JSONResponse({"error": error}, status_code=status, headers={"Cache-Control": "no-store"})


@router.post("/token")
def token(grant_type: str = Form(""), code: str = Form(""), redirect_uri: str = Form(""), code_verifier: str = Form(""),
          client_id: str = Form(""), client_secret: str = Form(""), authorization: str = Header(default="")):
    if authorization.startswith("Basic "):  # client_secret_basic: id и секрет url-кодированы (RFC 6749 §2.3.1)
        try:
            client_id, _, client_secret = base64.b64decode(authorization[6:]).decode().partition(":")
            client_id, client_secret = unquote(client_id), unquote(client_secret)
        except ValueError:
            return _oauth_error("invalid_client", 401)
    if not (_eq(client_id, config.FSP_ID_CLIENT_ID) and _eq(client_secret, config.FSP_ID_CLIENT_SECRET)):
        return _oauth_error("invalid_client", 401)
    if grant_type != "authorization_code":
        return _oauth_error("unsupported_grant_type")
    with _lock:
        rec = _codes.pop(_h(code), None)  # одноразовый: повтор того же кода — invalid_grant
    if not rec or rec["exp"] < time.time() or rec["client_id"] != client_id or rec["redirect_uri"] != redirect_uri:
        return _oauth_error("invalid_grant")
    if not 43 <= len(code_verifier) <= 128 or not _eq(_b64(hashlib.sha256(code_verifier.encode()).digest()), rec["challenge"]):
        return _oauth_error("invalid_grant")  # PKCE: перехваченный код без верификатора бесполезен
    acc, now = ACCOUNTS[rec["sub"]], int(time.time())
    access = secrets.token_urlsafe(32)
    with _lock:
        for k in [k for k, v in _tokens.items() if v[1] < now]:
            del _tokens[k]
        _tokens[_h(access)] = (rec["sub"], now + TOKEN_TTL)
    claims = {"iss": _issuer(), "sub": rec["sub"], "aud": client_id, "azp": client_id, "iat": now, "exp": now + int(TOKEN_TTL),
              "auth_time": now, "email": acc["email"], "email_verified": acc["email_verified"], "name": acc["name"],
              "preferred_username": rec["sub"]}
    if rec["idp"]:
        claims["identity_provider"] = rec["idp"]  # как protocol mapper Keycloak: через какой брокер вошли
    if rec["nonce"]:
        claims["nonce"] = rec["nonce"]
    return JSONResponse({"access_token": access, "token_type": "Bearer", "expires_in": int(TOKEN_TTL), "id_token": sign(claims),
                         "scope": "openid email profile"}, headers={"Cache-Control": "no-store"})


@router.get("/userinfo")
def userinfo(authorization: str = Header(default="")):
    with _lock:
        hit = _tokens.get(_h(authorization.removeprefix("Bearer ").strip()))
    if not hit or hit[1] < time.time():
        return JSONResponse({"error": "invalid_token"}, status_code=401, headers={"WWW-Authenticate": 'Bearer error="invalid_token"'})
    sub = hit[0]
    acc = ACCOUNTS[sub]
    return {"sub": sub, "email": acc["email"], "email_verified": acc["email_verified"], "name": acc["name"],
            "preferred_username": sub, "fsp_achievements": acc["achievements"]}
