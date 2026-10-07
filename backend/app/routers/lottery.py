"""Квалифицированная лотерея для работодателя: порог → замороженный пул + sha256(seed) → жребий → проверка.

Выбранных приглашают обычным потоком приглашений (роутер работодателя) с Invitation.lottery_id = id;
квота списывается только там. Логика и обоснование — app/services/lottery.py.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.catalog import FORMATS
from app.db import get_db
from app.deps import active_company, current_company
from app.models import Company, Lottery, Need
from app.services import lottery as svc

router = APIRouter(prefix="/api/lottery", tags=["lottery"])


class Threshold(BaseModel):
    """База — потребность (services.lottery.effective_threshold); поля здесь могут только ужесточить её."""

    spec: str | None = None  # = need.spec
    track: str | None = None  # = need.track
    grade_min: str | None = None  # ≥ грейд потребности − 1
    theta_min: float | None = None  # θ − SE ≥ theta_min
    must_skills: list[str] = []  # ⊂ skills_confirmed; need.must добавляются всегда
    fork_to: int | None = Field(default=None, gt=0)  # min_salary ≤ fork_to ≤ need.salary_to
    formats: list[str] | None = None
    require_free: bool = True  # нагрузка < CANDIDATE_CAP


class LotteryIn(BaseModel):
    need_id: int  # обязателен: одна жеребьёвка на потребность
    threshold: Threshold
    draw_count: int = Field(ge=1, le=50)


def _own(db: Session, company: Company, lottery_id: int) -> Lottery:
    lot = db.get(Lottery, lottery_id)
    if not lot or lot.company_id != company.id:
        raise HTTPException(404, "Лотерея не найдена")
    return lot


@router.post("/")
def create(body: LotteryIn, company: Company = Depends(active_company), db: Session = Depends(get_db)):
    """Доступно и неподтверждённой компании: лотерея квоту не тратит, приглашения выбранным — по обычным правилам квоты."""
    th = body.threshold
    if th.formats and not set(th.formats) <= set(FORMATS):
        raise HTTPException(422, f"formats ⊂ {FORMATS}")
    need = db.get(Need, body.need_id)
    if not need or need.company_id != company.id:
        raise HTTPException(404, "Потребность не найдена")
    try:
        lot = svc.create(db, company, svc.effective_threshold(th.model_dump(), need), body.draw_count, body.need_id)
    except svc.LotteryExists as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    return {"id": lot.id, "pool_size": len(lot.pool_ids), "seed_hash": lot.seed_hash, "commitment": lot.commitment,
            "threshold": lot.threshold}


@router.post("/{lottery_id}/draw")
def draw(lottery_id: int, company: Company = Depends(active_company), db: Session = Depends(get_db)):
    lot = _own(db, company, lottery_id)
    try:
        return svc.draw(db, lot)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e


@router.get("/{lottery_id}")
def state(lottery_id: int, company: Company = Depends(current_company), db: Session = Depends(get_db)):
    return svc.public_state(db, _own(db, company, lottery_id))


@router.get("/{lottery_id}/verify")
def verify(lottery_id: int, company: Company = Depends(current_company), db: Session = Depends(get_db)):
    lot = _own(db, company, lottery_id)
    if lot.drawn_ids is None:
        raise HTTPException(409, "Жребий ещё не брошен")
    return {**svc.verify(lot), "drawn_ids": lot.drawn_ids}


@router.get("/{lottery_id}/public")
def public(lottery_id: int, db: Session = Depends(get_db)):
    """Без авторизации: обезличенные данные жеребьёвки, чтобы проверить её мог кто угодно."""
    lot = db.get(Lottery, lottery_id)
    if not lot:
        raise HTTPException(404, "Лотерея не найдена")
    return svc.public_view(lot)
