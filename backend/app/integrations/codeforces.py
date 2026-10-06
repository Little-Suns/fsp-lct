"""Codeforces: официальное API (user.info, user.rating), лимит ~1 запрос / 2 с.

Владение: кандидат вписывает код вида FSP-7Q2K в поле «Организация» профиля CF
(допускаем и «Имя»/«Фамилию» — поле организации на CF иногда не принимает произвольный текст),
проверяем через user.info. Место в контесте берём из user.rating (поле rank) — отдельный
contest.standings не нужен.
"""

import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.deps import hash_secret
from app.integrations import common
from app.integrations.scoring import place_weight, rating_weight
from app.models import Achievement, ExternalAccount

API = "https://codeforces.com/api/"
SOURCE = "codeforces"
HANDLE_RE = re.compile(r"^[A-Za-z0-9_.\-]{3,24}$")
NOTABLE_PLACE = 100  # место в общем зачёте раунда, начиная с которого результат считается достижением
NOTABLE_MAX = 5  # сколько лучших контестов показываем
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # без 0/O, 1/I


CODE_RE = re.compile(r"FSP-[A-Z0-9]{4}", re.IGNORECASE)
CODE_TTL = timedelta(hours=24)


def new_code() -> str:
    """Код подтверждения владения вида FSP-7Q2K.

    По смыслу код публичный (кандидат сам публикует его в открытом профиле CF), но по правилу репозитория
    любые коды/токены в БД хранятся только как sha256 (deps.hash_secret): открытый код отдаётся один раз
    в ответе link, живёт CODE_TTL, после успешной проверки стирается (verify_code="", verify_expires_at=None).
    """
    return "FSP-" + "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))


def _call(method: str, **params) -> list:
    """Вызов API: ошибки CF (HTTP 400 + {status: FAILED, comment}) → ExternalError с понятным текстом."""
    try:
        data = common.get_json(API + method, params)
    except common.ExternalError as e:
        data = e.payload if isinstance(e.payload, dict) and e.payload.get("comment") else None
        if data is None:
            raise common.ExternalError(f"Codeforces: {e}", e.status) from e
    if not isinstance(data, dict):
        raise common.ExternalError("Codeforces: неожиданный формат ответа")
    if data.get("status") != "OK":
        comment = data.get("comment") or "неизвестная ошибка"
        if "not found" in comment:
            raise common.ExternalError(f"Codeforces: пользователь {params.get('handles') or params.get('handle')} не найден")
        raise common.ExternalError(f"Codeforces: {comment}")
    if not isinstance(data.get("result"), list):
        raise common.ExternalError(f"Codeforces: неожиданный формат ответа {method}")
    return data["result"]


def user_info(handle: str) -> dict:
    res = _call("user.info", handles=handle)
    if not res or not isinstance(res[0], dict) or not isinstance(res[0].get("handle"), str):
        raise common.ExternalError("Codeforces: неожиданный формат ответа user.info")
    return res[0]


def user_rating(handle: str) -> list[dict]:
    res = _call("user.rating", handle=handle)
    if not all(isinstance(h, dict) and isinstance(h.get("contestId"), int) and isinstance(h.get("contestName"), str)
               and isinstance(h.get("rank"), int) for h in res):
        raise common.ExternalError("Codeforces: неожиданный формат ответа user.rating")
    return res


def code_found(info: dict, code_hash: str) -> bool:
    """Есть ли в полях профиля (Организация / Имя / Фамилия) код, чей sha256 совпадает с сохранённым."""
    if not code_hash:
        return False
    text = " ".join(str(info.get(k) or "") for k in ("organization", "firstName", "lastName"))
    return any(hmac.compare_digest(hash_secret(tok.upper()), code_hash) for tok in CODE_RE.findall(text))


def contest_level(name: str) -> str:
    """Уровень раунда для place_weight: Div. 1 / Global — сильнейшее поле, Div. 3/4 — слабейшее."""
    # ponytail: эвристика по названию; точнее — число участников из contest.standings (дорого по лимиту API)
    if re.search(r"Div\.\s*[34]|Educational", name):
        return "regional"
    if re.search(r"Div\.\s*2", name):
        return "national"
    return "international"


def fetch(handle: str, info: dict | None = None) -> tuple[dict, list[dict]]:
    """Только HTTP, без записи в БД: (user.info, user.rating)."""
    return info or user_info(handle), user_rating(handle)


def apply(db: Session, acc: ExternalAccount, info: dict, history: list[dict]) -> None:
    """Записать рейтинг и пересобрать достижения source='codeforces'. Без HTTP и без commit."""
    cand = acc.candidate
    acc.handle = info.get("handle", acc.handle)  # каноническое написание
    acc.rating = info.get("rating")
    acc.rank = info.get("rank")
    acc.data = {"max_rating": info.get("maxRating"), "max_rank": info.get("maxRank"), "contests": len(history)}
    acc.fetched_at = datetime.now(UTC)

    keep: list[int] = []
    if acc.rating is not None:
        ach, _ = common.upsert_achievement(
            db, cand, SOURCE, None,
            title=f"Codeforces: рейтинг {acc.rating} ({acc.rank})",
            place=None, team=None, role=None, verified=True,
            weight=round(rating_weight(acc.rating), 3),
            data={"kind": "rating", "handle": acc.handle, "rating": acc.rating, "max_rating": info.get("maxRating")},
        )
        keep.append(ach.id)

    notable = sorted((h for h in history if h.get("rank") and h["rank"] <= NOTABLE_PLACE), key=lambda h: h["rank"])
    for h in notable[:NOTABLE_MAX]:
        level = contest_level(h["contestName"])
        ev = common.upsert_event(
            db, SOURCE, str(h["contestId"]), title=h["contestName"][:255], level=level,
            date=common.ts(h.get("ratingUpdateTimeSeconds")), url=f"https://codeforces.com/contest/{h['contestId']}",
            tags=["Алгоритмы"],
        )
        ach, _ = common.upsert_achievement(
            db, cand, SOURCE, ev,
            title=f"{h['contestName']}: {h['rank']} место",
            place=h["rank"], team=None, role=None, verified=True,
            weight=place_weight(h["rank"], None, level),
            data={"kind": "contest", "old_rating": h.get("oldRating"), "new_rating": h.get("newRating")},
        )
        keep.append(ach.id)

    # контесты, выпавшие из топа, и старый рейтинг удаляем
    db.execute(delete(Achievement).where(
        Achievement.candidate_id == cand.id, Achievement.source == SOURCE, Achievement.id.not_in(keep or [0])
    ))
