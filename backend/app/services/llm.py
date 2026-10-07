"""Клиент LLM через OpenAI-совместимый API: локальная Ollama, свой шлюз, YandexGPT или GigaChat (`config.LLM_PROVIDER`).

Все функции возвращают None, если модель выключена, недоступна или ответ не разобрался, — вызывающий код
обязан иметь фолбэк на правила. Так демо работает и без модели. Свободный текст (резюме, потребность) сюда
приходит уже без ПДн — его маскирует `parsing.mask_pii`; подбор шлёт только структурные поля без ФИО.
"""

import functools
import json
import logging
import re
import ssl
import threading
import time
import uuid

import httpx

from app import config

log = logging.getLogger(__name__)
_down_until = 0.0  # после сбоя не дёргаем модель минуту, чтобы не копить таймауты
_token = ("", 0.0)  # GigaChat: access token и момент истечения (time.time())
_token_lock = threading.Lock()  # один запрос токена на всех: остальные потоки ждут его, а не шлют свои
_PROVIDERS = ("none", "ollama", "openai_compatible", "yandexgpt", "gigachat")
if config.LLM_PROVIDER not in _PROVIDERS:
    log.warning("LLM_PROVIDER=%r не поддерживается (%s) — работаю на правилах", config.LLM_PROVIDER, ", ".join(_PROVIDERS))


def _enabled() -> bool:
    p = config.LLM_PROVIDER
    if p not in _PROVIDERS or p == "none" or not config.LLM_BASE_URL:
        return False
    if p == "yandexgpt":
        return bool(config.LLM_API_KEY and config.YANDEX_FOLDER_ID)
    if p == "gigachat":
        return bool(config.GIGACHAT_AUTH_KEY)
    return True


@functools.lru_cache(maxsize=4)
def _ssl_context(cafile: str) -> ssl.SSLContext:
    ctx = ssl.create_default_context()  # системные корни + проверка имени хоста
    ctx.load_verify_locations(cafile=cafile)  # и дополнительные (Russian Trusted Root CA для GigaChat)
    return ctx


def _verify() -> ssl.SSLContext | bool:
    return _ssl_context(config.LLM_CA_BUNDLE) if config.LLM_CA_BUNDLE else True


def _gigachat_token(stale: str = "") -> str:
    """OAuth-токен GigaChat по ключу авторизации; живёт 30 минут, обновляем за минуту до истечения.
    stale — токен, на который API ответил 401: обновляем, только если его ещё не заменил соседний поток."""
    global _token
    with _token_lock:
        tok, exp = _token
        if tok and tok != stale and time.time() < exp - 60:
            return tok
        r = httpx.post(
            config.GIGACHAT_OAUTH_URL,
            headers={"Authorization": f"Basic {config.GIGACHAT_AUTH_KEY}", "RqUID": str(uuid.uuid4()), "Accept": "application/json"},
            data={"scope": config.GIGACHAT_SCOPE},
            timeout=config.LLM_TIMEOUT,
            verify=_verify(),
        )
        r.raise_for_status()
        j = r.json()
        _token = (str(j["access_token"]), float(j.get("expires_at") or 0) / 1000 or time.time() + 25 * 60)  # expires_at — мс
        return _token[0]


def _headers(stale: str = "") -> dict:
    p = config.LLM_PROVIDER
    if p == "gigachat":
        return {"Authorization": f"Bearer {_gigachat_token(stale)}"}
    if p == "yandexgpt":
        # логирование запросов на стороне Yandex для дообучения выключаем явно
        return {"Authorization": f"Api-Key {config.LLM_API_KEY}", "x-folder-id": config.YANDEX_FOLDER_ID, "x-data-logging-enabled": "false"}
    return {"Authorization": f"Bearer {config.LLM_API_KEY}"} if config.LLM_API_KEY else {}


def _send(path: str, body: dict, headers: dict) -> httpx.Response:
    return httpx.post(config.LLM_BASE_URL.rstrip("/") + path, json=body, headers=headers, timeout=config.LLM_TIMEOUT, verify=_verify())


def _post(path: str, body: dict) -> dict | None:
    global _down_until
    if not _enabled() or time.monotonic() < _down_until:
        return None
    try:
        h = _headers()
        r = _send(path, body, h)
        if r.status_code == 401 and config.LLM_PROVIDER == "gigachat":  # токен отозван раньше срока — один повтор с новым
            r = _send(path, body, _headers(stale=h["Authorization"].removeprefix("Bearer ")))
        r.raise_for_status()
        return r.json()
    # ValueError — не JSON; KeyError/TypeError — ответ OAuth; OSError — не читается LLM_CA_BUNDLE
    except (httpx.HTTPError, ValueError, KeyError, TypeError, OSError) as e:
        status = getattr(getattr(e, "response", None), "status_code", "")  # только тип и код: в тексте ошибки бывает адрес
        log.warning("LLM недоступна (%s %s), переключаюсь на правила", type(e).__name__, status)
        _down_until = time.monotonic() + 60
        return None


def _model(name: str, scheme: str) -> str:
    """YandexGPT адресует модели URI каталога: «yandexgpt-lite/latest» → «gpt://<каталог>/yandexgpt-lite/latest»."""
    if config.LLM_PROVIDER == "yandexgpt" and "://" not in name:
        return f"{scheme}://{config.YANDEX_FOLDER_ID}/{name}"
    return name


def _json_object(content: str) -> dict | None:
    """JSON из ответа; модели без response_format (GigaChat) любят обрамлять его в ```json … ```."""
    try:
        out = json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.DOTALL)
        try:
            out = json.loads(m[0]) if m else None
        except json.JSONDecodeError:
            return None
    return out if isinstance(out, dict) else None


def chat_json(system: str, user: str) -> dict | None:
    """Ответ модели как JSON-объект или None."""
    body = {
        "model": _model(config.LLM_MODEL, "gpt"),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "temperature": 0,
        "response_format": {"type": "json_object"},
    }
    if config.LLM_PROVIDER == "gigachat":  # response_format GigaChat не поддерживает (JSON просим в промпте), температура — строго > 0
        del body["response_format"]
        body["temperature"] = 0.01
    resp = _post("/chat/completions", body)
    if not resp:
        return None
    try:
        content = resp["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return None
    return _json_object(content) if isinstance(content, str) else None


def embed(texts: list[str]) -> list[list[float]] | None:
    if not config.EMBED_MODEL:  # эмбеддинги выключены — подбор по навыкам
        return None
    resp = _post("/embeddings", {"model": _model(config.EMBED_MODEL, "emb"), "input": texts})
    if not resp:
        return None
    try:
        return [d["embedding"] for d in sorted(resp["data"], key=lambda d: d["index"])]
    except (KeyError, TypeError):
        return None
