"""Дашборд валидации для жюри: последний прогон из backend/var/validation.json; пересчёт — организатору."""

import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.routers.achievements import organizer
from app.services import validation as svc

router = APIRouter(prefix="/api/validation", tags=["validation"])


@router.get("")
def latest():
    if not svc.OUT.exists():
        raise HTTPException(404, "Прогона ещё не было: POST /api/validation/run или uv run python -m app.services.validation")
    return json.loads(svc.OUT.read_text())


@router.post("/run", dependencies=[Depends(organizer)])
def rerun(k: int = Query(10, ge=1, le=50), seed: int = 42, today: date = Query(svc.DEMO_TODAY), db: Session = Depends(get_db)):
    """Пересчёт (~40 с на 1500 кандидатах): синхронно, в пуле потоков FastAPI. today — дата засева (seed.generate --today)."""
    res = svc.run(db, k=k, seed=seed, today=today)
    svc.save(res)
    return res
