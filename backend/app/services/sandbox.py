"""Клиент песочницы задач на код (сервис sandbox/, nsjail). Код кандидата и тесты не покидают нашу инфраструктуру:
песочница — свой контейнер во внутренней сети compose, без выхода наружу (152-ФЗ; внешние сервисы вроде e2b не подходят).

Любой сбой (не настроена, недоступна, перегружена, странный ответ) — Unavailable: вызывающий код не засчитывает
задание ни в плюс, ни в минус. В логи — только причина, без кода и тестов.
"""

import logging
import threading
import time

import httpx

from app import config

log = logging.getLogger(__name__)
STATUSES = {"ok", "wrong", "tle", "mle", "re", "ce", "skip"}
HEALTH_TTL_S = 30
_health = {"at": -HEALTH_TTL_S, "ok": False}
# одновременных обращений API к песочнице: каждое держит поток пула FastAPI до минуты — остальной API не должен встать
_slots = threading.BoundedSemaphore(config.SANDBOX_API_SLOTS)


class Unavailable(Exception):
    """Песочница не настроена, не отвечает или сломана."""


class Busy(Unavailable):
    """Песочница перегружена (или заняты все слоты API) — решение не проверено, повторить можно."""


class Faulty(Unavailable):
    """Песочница ответила, но не вердиктом (500, битый ответ). Не void: такой ответ мог спровоцировать сам код кандидата —
    задание остаётся текущим (время не замораживается), отправить можно ещё раз."""


class Rejected(Exception):
    """Песочница отказалась принять решение (4xx: размер, недопустимые символы) — это ответ на само решение, не сбой.
    Не void: иначе кандидат пропускал бы задачу, нарочно присылая неприемлемый код."""


def enabled() -> bool:
    return bool(config.SANDBOX_URL and config.SANDBOX_TOKEN)


def ready() -> bool:
    """Включена и отвечает на /health (кэш на 30 с): лежащей песочнице задачи на код не выдаём.
    ponytail: кэш в памяти процесса; упала между проверкой и ответом — задание станет void."""
    if not enabled():
        return False
    now = time.monotonic()
    if now - _health["at"] >= HEALTH_TTL_S:
        try:
            ok = httpx.get(f"{config.SANDBOX_URL}/health", timeout=5).status_code == 200  # самопроверка песочницы — два запуска nsjail
        except httpx.HTTPError:
            ok = False
        _health.update(at=now, ok=ok)
    return _health["ok"]


def run(lang: str, code: str, entry: str, tests: list[dict], *, time_ms: int, memory_mb: int,
        fail_fast: bool = False, echo: bool = False) -> dict:
    """Прогон решения на тестах [{args, expected}] → {status, passed, total, results: [{status, time_ms, got?}], stderr}."""
    if not enabled():
        raise Unavailable("песочница не настроена (SANDBOX_URL)")
    body = {"lang": lang, "code": code, "harness": {"entry": entry}, "tests": tests,
            "limits": {"time_ms": time_ms, "memory_mb": memory_mb}, "fail_fast": fail_fast, "echo": echo}
    if not _slots.acquire(blocking=False):
        raise Busy("заняты все слоты API")
    try:
        r = httpx.post(f"{config.SANDBOX_URL}/run", json=body, headers={"X-Sandbox-Token": config.SANDBOX_TOKEN},
                       timeout=config.SANDBOX_TIMEOUT)
    except httpx.HTTPError as e:
        log.warning("песочница недоступна: %s", type(e).__name__)
        raise Unavailable("нет связи с песочницей") from None
    finally:
        _slots.release()
    if r.status_code == 429:
        raise Busy("песочница перегружена")
    if r.status_code in (400, 413, 422):
        log.warning("песочница отклонила решение: %s", r.status_code)
        raise Rejected(f"песочница отклонила решение ({r.status_code})")
    if r.status_code != 200:
        log.warning("песочница ответила %s", r.status_code)
        # void — только когда песочница сама сообщила о неисправности стенда (503) или до неё не достучаться
        raise (Unavailable if r.status_code == 503 else Faulty)(f"песочница ответила {r.status_code}")
    try:
        data = r.json()
        res = data["results"]
        ok = (len(res) == len(tests) and all(x.get("status") in STATUSES for x in res) and data.get("status") in STATUSES
              and data.get("passed") == sum(x["status"] == "ok" for x in res))
    except (ValueError, KeyError, TypeError, AttributeError):
        ok = False
    if not ok:
        log.warning("песочница вернула некорректный ответ")
        raise Faulty("некорректный ответ песочницы")
    return data
