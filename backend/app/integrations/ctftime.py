"""CTFtime: команда, её места в CTF за текущий и прошлый год, вес события (rating weight CTFtime).

Владение: у команды CTFtime нет поля свободного текста, которое можно надёжно проверить через API
(aliases — общие для всей команды и правятся капитаном). Поэтому достижения CTFtime создаются
с verified=False, роль — со слов кандидата, вес снижен в UNVERIFIED_FACTOR раз. Подтверждение —
импортом протокола от организатора с source='ctftime' и external_id = id события CTFtime
(hackathons.import_protocol найдёт то же событие и выставит verified=True и полный вес).
"""

import time
from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.integrations import common
from app.integrations.scoring import place_weight
from app.models import Achievement, ExternalAccount

API = "https://ctftime.org/api/v1/"
SOURCE = "ctftime"
TOP_MAX = 5  # сколько лучших результатов превращаем в достижения (по каждому — запрос events/{id})
SYNC_DEADLINE = 40.0  # секунд на одну синхронизацию CTFtime целиком (5–8 запросов)
UNVERIFIED_FACTOR = 0.5  # ponytail: заявленное членство в команде весит вполовину; полный вес — после протокола организатора


def _get(path: str, deadline: float | None):
    """GET к CTFtime с общим дедлайном синхронизации: таймаут запроса — не дольше оставшегося времени."""
    left = common.TIMEOUT if deadline is None else deadline - time.monotonic()
    if left <= 0:
        raise common.ExternalError(f"CTFtime: синхронизация не уложилась в {SYNC_DEADLINE:.0f} с, попробуйте позже")
    try:
        return common.get_json(API + path, timeout=min(common.TIMEOUT, left))
    except common.ExternalError as e:
        raise common.ExternalError(f"CTFtime: {e}", e.status) from e


def _iso(v) -> datetime | None:
    try:
        return datetime.fromisoformat(v) if isinstance(v, str) else None
    except ValueError:
        return None


def _bad(what: str):
    return common.ExternalError(f"CTFtime: неожиданный формат ответа {what}")


def team(team_id: int, deadline: float | None = None) -> dict:
    try:
        data = _get(f"teams/{team_id}/", deadline)
    except common.ExternalError as e:
        if e.status == 404:
            raise common.ExternalError(f"CTFtime: команда {team_id} не найдена", 404) from e
        raise
    if not isinstance(data, dict) or not isinstance(data.get("id"), int) or not isinstance(data.get("rating") or {}, dict):
        raise _bad("teams/")
    return data


def results(year: int, deadline: float | None = None) -> dict:
    data = _get(f"results/{year}/", deadline)
    if not isinstance(data, dict) or not all(
        isinstance(ev, dict) and isinstance(ev.get("scores", []), list) and isinstance(ev.get("time") or 0, int | float)
        and all(isinstance(s, dict) and isinstance(s.get("team_id"), int) and isinstance(s.get("place"), int) for s in ev.get("scores", []))
        for ev in data.values()
    ):
        raise _bad("results/")
    return data


def event(event_id: int | str, deadline: float | None = None) -> dict:
    data = _get(f"events/{event_id}/", deadline)
    if not isinstance(data, dict) or not isinstance(data.get("title"), str):
        raise _bad("events/")
    return data


def level_by_weight(weight: float | None) -> str:
    """Вес события CTFtime (0–100) → уровень для scoring.place_weight."""
    w = weight or 0
    return "international" if w >= 60 else "national" if w >= 30 else "regional" if w >= 15 else "local"


def team_places(team_id: int, by_year: dict[int, dict]) -> list[dict]:
    """Из results/{year} выбрать места команды: [{event_id, title, place, participants, time}]."""
    out = []
    for res in by_year.values():
        for eid, ev in res.items():
            scores = ev.get("scores") or []
            # таблица в results/ бывает неполной (место 382 при 37 строках) → берём максимум из обоих
            total = max([len(scores)] + [s.get("place") or 0 for s in scores])
            for s in scores:
                if s.get("team_id") == team_id:
                    out.append({"event_id": int(eid), "title": ev.get("title") or f"CTF #{eid}", "place": s.get("place"),
                                "participants": total, "time": ev.get("time")})
    return sorted(out, key=lambda r: (r["place"] or 10**6) / max(r["participants"], 1))


def sync(db: Session, acc: ExternalAccount) -> None:
    """Подтянуть команду и результаты, пересобрать достижения source='ctftime'. Без commit."""
    acc.data = acc.data or {}
    team_id = int(acc.handle)  # handle = id команды
    deadline = time.monotonic() + SYNC_DEADLINE
    info = team(team_id, deadline)
    now = datetime.now(UTC)
    # ponytail: results/{год} — общий для всех ~1–2 МБ; кеш в памяти по году, если кандидатов станет много
    places = team_places(team_id, {y: results(y, deadline) for y in (now.year, now.year - 1)})
    # рейтинг CTFtime за последний год: место в мире есть не всегда, место в стране — почти всегда
    year, last = max((info.get("rating") or {}).items(), default=(None, {}))
    acc.rating = last.get("rating_points")
    acc.rank = (f"#{last['rating_place']} в мире, {year}" if last.get("rating_place")
                else f"#{last['country_place']} в {info.get('country')}, {year}" if last.get("country_place") else None)
    acc.data = {**acc.data, "team_id": team_id, "team": info.get("name"), "country": info.get("country"), "events": len(places)}
    acc.fetched_at = now

    keep: list[int] = []
    for p in places[:TOP_MAX]:
        meta = event(p["event_id"], deadline)
        level = level_by_weight(meta.get("weight"))
        # events/{id}.participants — число заявок, может быть меньше реальной таблицы
        participants = max(meta.get("participants") or 0, p["participants"])
        ev = common.upsert_event(
            db, SOURCE, str(p["event_id"]), title=(meta.get("title") or p["title"])[:255], level=level,
            date=_iso(meta.get("start")) or common.ts(p["time"]),
            participants=participants, url=meta.get("ctftime_url"), tags=["Security", "CTF"],
        )
        prev = db.scalar(select(Achievement).where(Achievement.candidate_id == acc.candidate_id, Achievement.event_id == ev.id))
        verified = bool(prev and prev.verified)  # подтверждение организатором не теряем при обновлении
        w = place_weight(p["place"], participants, level)
        ach, _ = common.upsert_achievement(
            db, acc.candidate, SOURCE, ev,
            title=f"{ev.title}: {p['place']} место из {participants}",
            place=p["place"], team=info.get("name"), role=acc.data.get("role") if not verified else prev.role,
            verified=verified, weight=w if verified else round(w * UNVERIFIED_FACTOR, 3),
            data={"kind": "ctf", "team_id": team_id, "ctftime_weight": meta.get("weight")},
        )
        keep.append(ach.id)

    db.execute(delete(Achievement).where(
        Achievement.candidate_id == acc.candidate_id, Achievement.source == SOURCE,
        Achievement.verified.is_(False), Achievement.id.not_in(keep or [0]),
    ))
