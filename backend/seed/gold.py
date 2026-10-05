"""«Правильные ответы» для валидации подбора: релевантность пары кандидат × потребность по полям, без LLM.

Шкала (сессия, §8): 3 — идеальный; 2 — не хватает одного желательного навыка (или одна мелкая нестыковка);
1 — стек совпал, грейд ниже; 0 — мимо.

Правило:
- стек = специализация + трек (если указан в потребности) + все обязательные навыки ⊂ skills_true; нет стека → 0;
- грейд: ниже на один → 1; ниже на два и больше или выше на два и больше → 0; ровно или +1 — совпадение;
- «дефекты»: каждый недостающий желательный навык, min_salary > вилки «до», несовместимый формат/город;
  0 дефектов → 3, 1 → 2, ≥ 2 → 1.

Для синтетики берётся скрытая правда (Candidate.truth: spec, track, grade_true, skills_true),
а не то, что кандидат заявил в резюме, — иначе «завышенные резюме» считались бы релевантными.
"""

from app.catalog import GRADES


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _cand_fields(c) -> dict:
    """Кандидат (ORM-объект или dict) → поля правды. truth приоритетнее наблюдаемых полей."""
    truth = _get(c, "truth") or {}
    if isinstance(c, dict) and not truth:
        truth = c
    return {
        "spec": truth.get("spec") or _get(c, "spec"),
        "track": truth.get("track") or _get(c, "track"),
        "grade": truth.get("grade_true") or truth.get("grade") or _get(c, "grade") or _get(c, "grade_claimed"),
        "skills": set(truth.get("skills_true") or truth.get("skills") or _get(c, "skills_confirmed") or []),
        "min_salary": _get(c, "min_salary"),
        "formats": _get(c, "formats") or [],
        "city": _get(c, "city"),
    }


def format_ok(formats: list[str], city: str | None, need_format: str | None, need_city: str | None) -> bool:
    if not need_format:
        return True
    if need_format not in formats:
        return False
    # офис и гибрид требуют того же города; удалёнка — нет
    return need_format == "Удалённо" or not need_city or city == need_city


def relevance(cand, need) -> int:
    c = _cand_fields(cand)
    if c["spec"] != _get(need, "spec"):
        return 0
    if _get(need, "track") and c["track"] != _get(need, "track"):
        return 0
    if not set(_get(need, "must") or []) <= c["skills"]:
        return 0
    diff = GRADES.index(c["grade"]) - GRADES.index(_get(need, "grade"))
    if diff <= -2 or diff >= 2:
        return 0
    if diff == -1:
        return 1
    defects = len(set(_get(need, "nice") or []) - c["skills"])
    to = _get(need, "salary_to")
    defects += bool(to and c["min_salary"] and c["min_salary"] > to)
    defects += not format_ok(c["formats"], c["city"], _get(need, "format"), _get(need, "city"))
    return 3 if defects == 0 else 2 if defects == 1 else 1


if __name__ == "__main__":
    need = {"spec": "Backend", "track": "Python", "grade": "Middle", "must": ["Python", "PostgreSQL", "Kafka"],
            "nice": ["Kubernetes"], "salary_to": 300000, "format": "Гибрид", "city": "Москва"}
    base = {"min_salary": 230000, "formats": ["Гибрид", "Удалённо"], "city": "Москва"}
    t = {"spec": "Backend", "track": "Python", "grade_true": "Middle", "skills_true": ["Python", "PostgreSQL", "Kafka", "Kubernetes"]}
    assert relevance({**base, "truth": t}, need) == 3
    assert relevance({**base, "truth": {**t, "skills_true": ["Python", "PostgreSQL", "Kafka"]}}, need) == 2  # нет nice
    assert relevance({**base, "truth": {**t, "grade_true": "Junior"}}, need) == 1  # грейд ниже
    assert relevance({**base, "truth": {**t, "grade_true": "Senior"}}, need) == 3  # +1 — совпадение
    assert relevance({**base, "truth": {**t, "grade_true": "Lead"}}, need) == 0
    assert relevance({**base, "truth": {**t, "spec": "Data Eng / Analytics"}}, need) == 0  # соседняя специализация
    assert relevance({**base, "truth": {**t, "skills_true": ["Python", "PostgreSQL"]}}, need) == 0  # нет must
    assert relevance({**base, "min_salary": 350000, "truth": t}, need) == 2  # вилка ниже ожиданий
    assert relevance({**base, "min_salary": 350000, "formats": ["Удалённо"], "truth": t}, need) == 1
    assert relevance({**base, "city": "Казань", "truth": t}, need) == 2  # гибрид в другом городе
    assert relevance({**base, "city": "Казань", "truth": t}, {**need, "format": "Удалённо"}) == 3  # удалёнке город не важен
    print("ok")
