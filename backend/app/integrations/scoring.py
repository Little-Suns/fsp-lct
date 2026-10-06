"""Нормировка достижений в вес ∈ [0, 1] и сводный сигнал кандидата.

Сигнал входит в ранжирование наравне с ФСП, на грейд не влияет. Нет достижений → 0 без штрафа.
"""

LEVEL = {"international": 1.0, "national": 0.8, "regional": 0.5, "local": 0.3}


def rating_weight(rating: float | None, lo: float = 1200, hi: float = 3000) -> float:
    """Рейтинг (Codeforces и т.п.) → [0,1]: 1200 и ниже — 0, 3000 и выше — 1."""
    if rating is None:
        return 0.0
    return max(0.0, min(1.0, (rating - lo) / (hi - lo)))


def place_weight(place: int | None, participants: int | None, level: str | None) -> float:
    """Место в соревновании с учётом уровня: призы ценятся выше, «участник» — немного."""
    base = LEVEL.get(level or "local", 0.3)
    if place is None:
        return 0.15 * base
    if place <= 3:
        factor = (1.0, 0.85, 0.75)[place - 1]
    elif participants and place <= max(3, participants // 10):
        factor = 0.5
    else:
        factor = 0.25
    return round(base * factor, 3)


def combine(weights: list[float]) -> float:
    """Noisy-OR: много мелких участий не перевешивают одну крупную победу."""
    rest = 1.0
    for w in weights:
        rest *= 1.0 - max(0.0, min(1.0, w))
    return round(1.0 - rest, 3)


if __name__ == "__main__":
    assert rating_weight(1912) > rating_weight(1650) > 0 == rating_weight(None)
    assert place_weight(1, 300, "national") > place_weight(10, 300, "national") > place_weight(200, 300, "national")
    assert place_weight(1, 50, "regional") < place_weight(1, 50, "international")
    assert combine([]) == 0 and combine([1.0, 0.2]) == 1.0 and combine([0.5, 0.5]) == 0.75
    print("ok")
