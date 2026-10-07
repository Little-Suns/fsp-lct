"""Нормировка достижений в вес ∈ [0, 1] и сводный сигнал кандидата.

Сигнал входит в ранжирование внутри категории, на грейд не влияет. Нет достижений → 0 без штрафа.

Иерархии соревнований нет (QA с постановщиками: «все соревнования равно важны», чемпионат России
не выше хакатона). Вес соревнования определяет только результативность кандидата в нём, а сводный
сигнал растёт с числом соревнований с убывающей отдачей. Поэтому десяток онлайн-явок без результата
не сравняется ни с одним призовым местом.
"""

# Результативность → вес. Шкала по смыслу «насколько результат отделяет кандидата от остальных
# участников того же соревнования», а не по «важности» соревнования:
#   winner      — 1-е место: лучший результат в поле. 0,8, а не 1,0: остаётся запас под повторяемость
#                 (второй результат) и рейтинг, сигнал не насыщается от одной строки протокола;
#   prize       — 2–3-е место (призёр): тот же класс, что победа, на ступень ниже;
#   finalist    — прошёл отбор: финал / топ-10 % таблицы. Умеренный вклад — отбор отсеивает большинство;
#   participant — участник отбора без результата (типично — онлайн-явка). Почти ноль: явку легко набить.
RESULT_WEIGHT = {"winner": 0.8, "prize": 0.6, "finalist": 0.35, "participant": 0.05}
RESULT_LABEL = {"winner": "победитель", "prize": "призёр", "finalist": "финалист", "participant": "участник отбора"}
FINALIST_SHARE = 10  # финалист — место не ниже participants // FINALIST_SHARE (топ-10 %)
DECAY = 0.5  # k-е по силе соревнование (k = 0, 1, …) входит с множителем DECAY**k


def rating_weight(rating: float | None, lo: float = 1200, hi: float = 3000) -> float:
    """Рейтинг (Codeforces и т.п.) → [0,1]: 1200 и ниже — 0, 3000 и выше — 1.

    Рейтинг — отдельный сигнал, а не «соревнование»: он уже агрегирует сотни раундов, поэтому в combine
    не дисконтируется по числу соревнований. 1200 — стартовый рейтинг новичка CF (ниже — нет сигнала),
    3000 — уровень legendary grandmaster.
    """
    if rating is None:
        return 0.0
    return max(0.0, min(1.0, (rating - lo) / (hi - lo)))


def result_of(place: int | None, participants: int | None) -> str:
    """Место → результативность. Без места или при неизвестном размере поля ниже 3-го места — участник."""
    if place is None or place < 1:
        return "participant"
    if place == 1:
        return "winner"
    if place <= 3:
        return "prize"
    if participants and place <= max(3, participants // FINALIST_SHARE):
        return "finalist"
    return "participant"


def result_weight(result: str | None) -> float:
    return RESULT_WEIGHT.get(result or "participant", RESULT_WEIGHT["participant"])


def place_weight(place: int | None, participants: int | None, result: str | None = None) -> float:
    """Вес одного соревнования. result из протокола (организатор знает, кто финалист) важнее вывода по месту."""
    return result_weight(result or result_of(place, participants))


def combine(weights: list[float], ratings: list[float] = ()) -> float:
    """Сводный сигнал: соревнования с убывающей отдачей + рейтинг отдельным слагаемым (noisy-OR).

    Соревнования сортируются по весу, k-е входит как w·DECAY**k, затем noisy-OR. Итог ограничен сверху:
    сколько ни набивай явок по 0,05, их вклад не больше 0,05·(1 + ½ + ¼ + …) ≈ 0,1; одна победа (0,8)
    плюс два призовых места дают ≈ 0,88 — число результатов учитывается, но первая сильная строка главная.
    Рейтинг (лучший из ratings) — без дисконта: 1 − (1 − соревнования)·(1 − рейтинг).
    """
    rest = 1.0
    for k, w in enumerate(sorted((max(0.0, min(1.0, w)) for w in weights), reverse=True)):
        rest *= 1.0 - w * DECAY**k
    rest *= 1.0 - max((max(0.0, min(1.0, r)) for r in ratings), default=0.0)
    return round(1.0 - rest, 3)


def is_rating(a) -> bool:
    """Достижение-рейтинг (Codeforces user.rating), а не соревнование."""
    return (a.data or {}).get("kind") == "rating"


def signal(achievements) -> float:
    """Сигнал по списку Achievement (вызывающий сам отбирает подтверждённые)."""
    achs = list(achievements)
    return combine([a.weight for a in achs if not is_rating(a)], [a.weight for a in achs if is_rating(a)])


if __name__ == "__main__":
    assert rating_weight(1912) > rating_weight(1650) > 0 == rating_weight(None)
    assert place_weight(1, 300) > place_weight(2, 300) > place_weight(10, 300) > place_weight(200, 300) == place_weight(None, None)
    assert place_weight(12, None) == RESULT_WEIGHT["participant"] and place_weight(12, None, "finalist") == RESULT_WEIGHT["finalist"]
    # иерархии нет: победа на любом соревновании весит одинаково
    assert place_weight(1, 50) == place_weight(1, 5000)
    assert combine([]) == 0 and combine([1.0, 0.2]) == 1.0 and combine([0.5, 0.5]) == 0.625
    assert combine([0.05] * 50) < 0.11 < combine([0.35])  # набивка явками не догоняет один выход в финал
    assert combine([0.8], [0.4]) == round(1 - 0.2 * 0.6, 3) and combine([], [0.4]) == 0.4
    print("ok")
