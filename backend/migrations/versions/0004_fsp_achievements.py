"""достижения: дисциплина, результат, разряд; вес без иерархии уровней

Событию — дисциплина ФСП, достижению — результативность (winner | prize | finalist | participant) и
спортивный разряд из протокола. Все колонки nullable: на существующих строках они пустые.

Данные: вес достижений пересчитывается по новой шкале scoring.py (результативность без уровня
соревнования), результат выводится из места и числа участников — так же, как при импорте. Константы
продублированы здесь намеренно: ревизия не должна менять поведение, если scoring.py поменяют потом.
Рейтинги (data.kind = rating) не трогаются — их шкала прежняя.

Revision ID: 0004_fsp_achievements
Revises: 0003_merge_chat_profile
Create Date: 2026-10-07 12:00:00.000000

"""
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# идентификаторы ревизии: NNNN_slug, down_revision — ревизия, поверх которой эта
revision: str = '0004_fsp_achievements'
down_revision: Union[str, Sequence[str], None] = '0003_merge_chat_profile'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

WEIGHT = {"winner": 0.8, "prize": 0.6, "finalist": 0.35, "participant": 0.05}
UNVERIFIED_CTF = 0.5  # ctftime.UNVERIFIED_FACTOR


def _result(place, participants, source, kind) -> str:
    if place is None or place < 1:
        return "participant"
    if place == 1:
        return "winner"
    if place <= 3:
        return "prize"
    if source == "codeforces" and kind == "contest":  # в достижения попадает только топ-100 раунда
        return "finalist"
    if participants and place <= max(3, participants // 10):
        return "finalist"
    return "participant"


def upgrade() -> None:
    """Применить изменение схемы."""
    op.add_column('events', sa.Column('discipline', sa.String(length=64), nullable=True))
    op.add_column('achievements', sa.Column('result', sa.String(length=16), nullable=True))
    op.add_column('achievements', sa.Column('sport_rank', sa.String(length=32), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT a.id, a.source, a.place, a.verified, a.data, e.participants "
        "FROM achievements a LEFT JOIN events e ON e.id = a.event_id"
    )).all()
    for aid, source, place, verified, data, participants in rows:
        data = json.loads(data) if isinstance(data, str) else (data or {})
        if data.get("kind") == "rating":
            continue
        result = _result(place, participants, source, data.get("kind"))
        weight = WEIGHT[result] * (UNVERIFIED_CTF if source == "ctftime" and not verified else 1.0)
        bind.execute(sa.text("UPDATE achievements SET result = :r, weight = :w WHERE id = :id"),
                     {"r": result, "w": round(weight, 3), "id": aid})


def downgrade() -> None:
    """Откатить изменение схемы (веса по старой шкале не восстанавливаются — их пересчитает следующая синхронизация)."""
    op.drop_column('achievements', 'sport_rank')
    op.drop_column('achievements', 'result')
    op.drop_column('events', 'discipline')
