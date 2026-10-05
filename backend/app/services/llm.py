"""Клиент локальной LLM через OpenAI-совместимый API (Ollama / vLLM).

Все функции возвращают None, если модель недоступна или ответ не разобрался, — вызывающий код
обязан иметь фолбэк на правила. Так демо работает и без поднятой модели.
"""

import json
import logging
import time

import httpx

from app import config

log = logging.getLogger(__name__)
_down_until = 0.0  # после сбоя не дёргаем модель минуту, чтобы не копить таймауты


def _post(path: str, body: dict) -> dict | None:
    global _down_until
    if not config.LLM_BASE_URL or time.monotonic() < _down_until:
        return None
    try:
        r = httpx.post(config.LLM_BASE_URL.rstrip("/") + path, json=body, timeout=config.LLM_TIMEOUT)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("LLM недоступна (%s), переключаюсь на правила", e)
        _down_until = time.monotonic() + 60
        return None


def chat_json(system: str, user: str) -> dict | None:
    """Ответ модели как JSON-объект или None."""
    resp = _post(
        "/chat/completions",
        {
            "model": config.LLM_MODEL,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        },
    )
    if not resp:
        return None
    try:
        out = json.loads(resp["choices"][0]["message"]["content"])
        return out if isinstance(out, dict) else None
    except (KeyError, IndexError, json.JSONDecodeError):
        return None


def embed(texts: list[str]) -> list[list[float]] | None:
    resp = _post("/embeddings", {"model": config.EMBED_MODEL, "input": texts})
    if not resp:
        return None
    try:
        return [d["embedding"] for d in sorted(resp["data"], key=lambda d: d["index"])]
    except (KeyError, TypeError):
        return None
