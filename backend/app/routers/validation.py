"""Дашборд валидации для жюри: последний прогон из backend/var/validation.json; пересчёт — организатору, на демо-стенде — всем."""

import json
import threading

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import config
from app.db import get_db
from app.models import Need
from app.routers.achievements import organizer
from app.services import validation as svc

router = APIRouter(prefix="/api/validation", tags=["validation"])
# ponytail: блокировка в памяти — API строго один процесс (CLAUDE.md); при нескольких воркерах — advisory lock в Postgres
_running = threading.Lock()


def run_access(authorization: str = Header(default=""), db: Session = Depends(get_db)) -> None:
    """Пересчёт: на демо-стенде (DEMO=1) — кнопкой на /v без входа, иначе только организатору."""
    if not config.DEMO:
        organizer(authorization, db)


@router.get("")
def latest():
    if not svc.OUT.exists():
        raise HTTPException(404, "Прогона ещё не было: POST /api/validation/run или uv run python -m app.services.validation")
    return json.loads(svc.OUT.read_text())


@router.post("/run", dependencies=[Depends(run_access)])
def rerun(k: int = Query(10, ge=1, le=50), seed: int = 42, today: str = Query(svc.DEMO_TODAY.isoformat()), db: Session = Depends(get_db)):
    """Пересчёт (~40 с на 1500 кандидатах): синхронно, в пуле потоков FastAPI; второй одновременный — 409.
    today — дата засева, как у seed.generate --today: YYYY-MM-DD или now (засев от реального времени)."""
    try:
        day = svc.parse_today(today)
    except ValueError:
        raise HTTPException(422, "today: дата YYYY-MM-DD или now") from None
    if db.scalar(select(Need.id).where(Need.is_synthetic.is_(True)).limit(1)) is None:
        raise HTTPException(409, "В базе нет синтетики: сначала засейте её — python -m seed.generate --reset --today now")
    if not _running.acquire(blocking=False):
        raise HTTPException(409, "Прогон уже идёт, подождите минуту")
    try:
        res = svc.run(db, k=k, seed=seed, today=day)
    finally:
        _running.release()
    svc.save(res)
    return res
