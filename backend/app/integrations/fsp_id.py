"""Клиент ФСП ID (Keycloak, OpenID Connect): Authorization Code + PKCE S256 против настраиваемого issuer.

Здесь только протокол: discovery, адрес авторизации, обмен кода, проверка id_token по JWKS, userinfo и импорт
подтверждённых достижений. Пользователи, куки и наш токен — в routers/fsp_id.py. Боевой Keycloak подключается
конфигурацией (config.FSP_ID_*): всё остальное берётся из {issuer}/.well-known/openid-configuration.

PKCE-верификатор и nonce не хранятся: выводятся HMAC(SECRET_KEY, state) — по дампу БД их не восстановить.
Достижения — custom claim fsp_achievements в userinfo (в Keycloak — protocol mapper) в формате протокола
hackathons.import_protocol: [{event: {external_id, title, level, date, participants, url, tags}, place, team, role}].
"""

import base64
import hashlib
import hmac
import logging
import time
from urllib.parse import urlencode

import httpx
import jwt
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import config
from app.integrations import hackathons
from app.models import Candidate
from app.services.matching import consent_ok

HTTP = httpx.Client(timeout=10.0, follow_redirects=False)  # тесты подменяют на TestClient приложения с моком
CACHE_TTL = 3600.0  # discovery и JWKS; неизвестный kid → JWKS перечитывается сразу (ротация ключей)
LEEWAY = 30  # секунд расхождения часов при проверке exp/iat
ACH_CLAIM = "fsp_achievements"
MAX_ACH = 200
log = logging.getLogger(__name__)
_cache: dict[str, tuple[float, object]] = {}


class FspIdError(Exception):
    """Провайдер недоступен, ответил ошибкой или прислал невалидный ответ. code уходит фронту (fsp-error=…), текст — в лог."""

    def __init__(self, reason: str, code: str = "provider"):
        super().__init__(reason)
        self.code = code


def enabled() -> bool:
    return bool(config.FSP_ID_ISSUER and config.FSP_ID_CLIENT_ID and config.FSP_ID_CLIENT_SECRET)


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _derive(purpose: str, state: str) -> str:
    return _b64(hmac.new(config.SECRET_KEY.encode(), f"fsp-id:{purpose}:{state}".encode(), hashlib.sha256).digest())


def verifier(state: str) -> str:
    """PKCE code_verifier: 43 символа base64url — минимум RFC 7636."""
    return _derive("pkce", state)


def nonce(state: str) -> str:
    return _derive("nonce", state)


def challenge(code_verifier: str) -> str:
    return _b64(hashlib.sha256(code_verifier.encode()).digest())


def _secure(url: str) -> bool:
    """Боевой провайдер — только https; http допустим лишь для встроенного мока."""
    return url.startswith("https://") or (config.FSP_ID_MOCK and url.startswith(config.MOCK_FSP_ID_ISSUER + "/"))


def _json(r: httpx.Response) -> dict:
    if r.status_code >= 400:
        raise FspIdError(f"ФСП ID ответил HTTP {r.status_code}")
    try:
        data = r.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise FspIdError("ФСП ID вернул не JSON-объект")
    return data


def _get(url: str, **kw) -> dict:
    try:
        return _json(HTTP.get(url, **kw))
    except httpx.HTTPError as e:
        raise FspIdError(f"ФСП ID недоступен: {type(e).__name__}") from e


def _cached(key: str, load, force: bool = False):
    hit = _cache.get(key)
    if hit and not force and hit[0] > time.monotonic():
        return hit[1]
    value = load()
    _cache[key] = (time.monotonic() + CACHE_TTL, value)
    return value


def discovery() -> dict:
    issuer = config.FSP_ID_ISSUER

    def load() -> dict:
        if not _secure(issuer + "/"):
            raise FspIdError("FSP_ID_ISSUER должен быть https://")
        doc = _get(issuer + "/.well-known/openid-configuration")
        if doc.get("issuer") != issuer:  # OIDC Discovery §4.3: иначе подменённый документ выдал бы чужие ключи
            raise FspIdError("discovery: issuer не совпадает с FSP_ID_ISSUER")
        for k in ("authorization_endpoint", "token_endpoint", "jwks_uri", "userinfo_endpoint"):
            if not isinstance(doc.get(k), str) or not _secure(doc[k]):
                raise FspIdError(f"discovery: нет {k} по https")
        if "S256" not in (doc.get("code_challenge_methods_supported") or []):
            raise FspIdError("discovery: провайдер не поддерживает PKCE S256")
        return doc

    return _cached("discovery:" + issuer, load)


def authorize_url(state: str) -> str:
    ep = discovery()["authorization_endpoint"]
    q = urlencode({
        "response_type": "code", "client_id": config.FSP_ID_CLIENT_ID, "redirect_uri": config.FSP_ID_REDIRECT_URI,
        "scope": config.FSP_ID_SCOPE, "state": state, "nonce": nonce(state),
        "code_challenge": challenge(verifier(state)), "code_challenge_method": "S256",
    })
    return ep + ("&" if "?" in ep else "?") + q


def _signing_key(kid: str | None):
    url = discovery()["jwks_uri"]

    def load(force: bool = False) -> jwt.PyJWKSet:
        try:
            return _cached("jwks:" + url, lambda: jwt.PyJWKSet.from_dict(_get(url)), force)
        except jwt.PyJWTError as e:
            raise FspIdError(f"JWKS: {type(e).__name__}") from e

    for force in (False, True):
        keys = [k for k in load(force).keys if k.key_type == "RSA" and (k.public_key_use in (None, "sig"))]
        match = [k for k in keys if k.key_id == kid] if kid else keys[:1] if len(keys) == 1 else []
        if match:
            return match[0].key
    raise FspIdError("id_token подписан неизвестным ключом", "token")


def verify_id_token(token: str, expected_nonce: str) -> dict:
    """Подпись RS256 по JWKS провайдера, iss, aud (наш client_id), azp, exp/iat, nonce. Иначе FspIdError(code='token')."""
    try:
        header = jwt.get_unverified_header(token)
    except jwt.PyJWTError as e:
        raise FspIdError("id_token: не JWT", "token") from e
    if header.get("alg") != "RS256":  # никаких none/HS256: алгоритм фиксирован, а не берётся из токена
        raise FspIdError("id_token: алгоритм не RS256", "token")
    key = _signing_key(header.get("kid"))
    try:
        claims = jwt.decode(
            token, key, algorithms=["RS256"], audience=config.FSP_ID_CLIENT_ID, issuer=config.FSP_ID_ISSUER,
            leeway=LEEWAY, options={"require": ["exp", "iat", "iss", "aud", "sub", "nonce"]},
        )
    except jwt.PyJWTError as e:
        raise FspIdError(f"id_token: {type(e).__name__}", "token") from e
    aud = claims["aud"] if isinstance(claims["aud"], list) else [claims["aud"]]
    if (len(aud) > 1 or "azp" in claims) and claims.get("azp") != config.FSP_ID_CLIENT_ID:
        raise FspIdError("id_token: azp — не наш клиент", "token")
    if not hmac.compare_digest(str(claims["nonce"]).encode(), expected_nonce.encode()):
        raise FspIdError("id_token: nonce не совпадает", "token")
    if not isinstance(claims["sub"], str) or not 0 < len(claims["sub"]) <= 64:
        raise FspIdError("id_token: некорректный sub", "token")
    return claims


def exchange(code: str, state: str) -> tuple[dict, str]:
    """Код → токены провайдера (client_secret_post + code_verifier). Возвращает (claims id_token, access_token)."""
    d = discovery()
    try:
        r = HTTP.post(d["token_endpoint"], data={
            "grant_type": "authorization_code", "code": code, "redirect_uri": config.FSP_ID_REDIRECT_URI,
            "code_verifier": verifier(state), "client_id": config.FSP_ID_CLIENT_ID, "client_secret": config.FSP_ID_CLIENT_SECRET,
        }, headers={"Accept": "application/json"})
    except httpx.HTTPError as e:
        raise FspIdError(f"ФСП ID недоступен: {type(e).__name__}") from e
    tok = _json(r)
    if str(tok.get("token_type", "")).lower() != "bearer" or not isinstance(tok.get("id_token"), str) \
            or not isinstance(tok.get("access_token"), str):
        raise FspIdError("token: в ответе нет id_token/access_token")
    return verify_id_token(tok["id_token"], nonce(state)), tok["access_token"]


def userinfo(access_token: str, sub: str) -> dict:
    info = _get(discovery()["userinfo_endpoint"], headers={"Authorization": f"Bearer {access_token}"})
    if info.get("sub") != sub:  # OIDC Core §5.3.2: иначе ответ подменён
        raise FspIdError("userinfo: sub не совпадает с id_token", "token")
    return info


def identity(claims: dict, info: dict) -> dict:
    """sub и почта — почта только подтверждённая провайдером (email_verified) и из того же источника, что и флаг."""
    src = claims if "email" in claims else info
    email = src.get("email") if src.get("email_verified") is True else None
    email = email.strip().lower() if isinstance(email, str) and 3 <= len(email.strip()) <= 254 and "@" in email else None
    return {"sub": claims["sub"], "email": email}


def _text(v, limit: int) -> str | None:
    return (str(v).strip()[:limit] if v is not None else "") or None


def import_achievements(db: Session, cand: Candidate | None, sub: str, info: dict) -> int | None:
    """Участия и места из claim fsp_achievements → Achievement (source='fsp') через hackathons.import_protocol.

    Без профиля кандидата или без действующего согласия на внешние данные ничего не пишется (152-ФЗ) → None.
    Иначе — число привязанных достижений. Битые записи провайдера пропускаются (в лог — только причина).
    """
    items = info.get(ACH_CLAIM)
    if cand is None or not consent_ok(cand, "external"):
        return None
    if not isinstance(items, list):
        return 0
    n = 0
    for it in items[:MAX_ACH]:
        if not isinstance(it, dict) or not isinstance(it.get("event"), dict):
            continue
        row = {"fsp_id": sub, "place": it.get("place"), "team": _text(it.get("team"), 128), "role": _text(it.get("role"), 64)}
        try:
            n += hackathons.import_protocol(db, {**it["event"], "source": "fsp"}, [row])["matched"]
        except (ValueError, TypeError, SQLAlchemyError) as e:  # формат записи или значение не влезло в схему
            db.rollback()
            log.warning("ФСП ID: запись достижения пропущена: %s", type(e).__name__)
    return n
