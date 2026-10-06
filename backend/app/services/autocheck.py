"""Автопроверка заданий работодателя по эталону.

Постановщики: «есть эталон ответа — проверяет система, открытые задания (скрипт, бизнес-решение) оценивает работодатель».
Тип ответа задания (answer_type):
  open   — открытый ответ, оценивает работодатель (как раньше);
  text   — строка: совпадение с одним из эталонов, по умолчанию после нормализации (регистр, ё/е, пробелы,
           пунктуация по краям), с exact — посимвольно (без пробелов по краям);
  number — число с допуском |x − value| ≤ tolerance (запятая или точка, пробелы между разрядами);
  choice — один вариант из options, multi — набор вариантов: совпадение множества с correct (индексы);
  regex  — полное совпадение с шаблоном без учёта регистра.
Эталон (reference) хранится на сервере и не уходит кандидату — ни в задании, ни в обратной связи: кандидат видит
только «совпало / не совпало». Варианты (options) — публичная часть задания. Попытка одна (уникальный индекс
решения): одним аккаунтом эталон не перебрать (обход новыми аккаунтами — в table.md).
"""

import math
import re
import unicodedata

import regex

ANSWER_TYPES = ("open", "text", "number", "choice", "multi", "regex")
OPTIONS_MAX, OPTION_LEN, ANSWERS_MAX, ANSWER_LEN, PATTERN_LEN = 10, 200, 10, 500, 300
# ponytail: шаблон работодателя проверяется движком regex с таймаутом (concurrent — GIL отпускается) — катастрофический
# возврат (ReDoS) обрывается, решение уходит на ручную оценку. Компиляция таймаута не знает, а вложенные счётчики
# ((a{20}){20}){20}… раздуваются при компиляции — поэтому счётчиков не больше REPEATS_MAX и каждый ≤ REPEAT_MAX.
# Отдельный процесс-песочница с лимитом памяти, если понадобится жёстче.
REGEX_TIMEOUT = 0.05
REPEATS_MAX, REPEAT_MAX = 3, 100
_EDGE = " .,;:!?\"'«»`“”„()[]"
_NUMBER = re.compile(r"[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?", re.ASCII)
_COUNTED = re.compile(r"(?<!\\)\{([^}]*)\}")
_BOUNDS = re.compile(r"(\d{1,3})?(,(\d{1,3})?)?", re.ASCII)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s).casefold().replace("ё", "е")
    return " ".join(s.split()).strip(_EDGE)


def parse_number(s: str) -> float | None:
    """Число из ответа: ASCII-цифры, точка или запятая, пробелы между разрядами; без «1_000» и нецифровых систем."""
    s = "".join(s.split()).replace(",", ".")
    if not _NUMBER.fullmatch(s):
        return None
    x = float(s)
    return x if math.isfinite(x) else None


def _safe_pattern(pattern: str) -> bool:
    """Счётчики {m,n}: не больше REPEATS_MAX, границы ≤ REPEAT_MAX; другие конструкции в фигурных скобках (нечёткий поиск) — нет."""
    counted = _COUNTED.findall(pattern)
    if len(counted) > REPEATS_MAX:
        return False
    for body in counted:
        m = _BOUNDS.fullmatch(body)
        if not m or not (m.group(1) or m.group(3)) or any(int(x) > REPEAT_MAX for x in (m.group(1), m.group(3)) if x):
            return False
    return True


def build(answer_type: str, options: list[str] | None, ref: dict | None) -> tuple[list[str] | None, dict | None]:
    """Проверяет и нормализует варианты и эталон задания. Возвращает (options, reference); ошибка — ValueError с текстом для 422."""
    if answer_type not in ANSWER_TYPES:
        raise ValueError(f"Тип ответа: один из {', '.join(ANSWER_TYPES)}")
    if answer_type == "open":
        return None, None
    ref = ref or {}
    if answer_type in ("choice", "multi"):
        opts = [o.strip() for o in options or []]
        if not 2 <= len(opts) <= OPTIONS_MAX or not all(opts) or any(len(o) > OPTION_LEN for o in opts):
            raise ValueError(f"Варианты: от 2 до {OPTIONS_MAX} непустых строк до {OPTION_LEN} символов")
        if len({norm(o) for o in opts}) != len(opts):
            raise ValueError("Варианты не должны повторяться")
        correct = sorted(set(ref.get("correct") or []))
        if not correct or any(not isinstance(i, int) or not 0 <= i < len(opts) for i in correct):
            raise ValueError("Эталон: номера верных вариантов из списка")
        if answer_type == "choice" and len(correct) != 1:
            raise ValueError("Для одного варианта верный ответ ровно один")
        return opts, {"correct": correct}
    if options:
        raise ValueError("Варианты ответа — только для выбора из списка")
    if answer_type == "text":
        answers = [a.strip() for a in ref.get("answers") or []]
        if not 1 <= len(answers) <= ANSWERS_MAX or not all(norm(a) for a in answers) or any(len(a) > ANSWER_LEN for a in answers):
            raise ValueError(f"Эталон: от 1 до {ANSWERS_MAX} непустых ответов до {ANSWER_LEN} символов")
        return None, {"answers": answers, "exact": bool(ref.get("exact"))}
    if answer_type == "number":
        value, tol = ref.get("value"), ref.get("tolerance") or 0
        if not all(isinstance(x, int | float) and not isinstance(x, bool) and math.isfinite(x) for x in (value, tol)) or tol < 0:
            raise ValueError("Эталон: число value и допуск tolerance ≥ 0")
        return None, {"value": float(value), "tolerance": float(tol)}
    pattern = ref.get("pattern")
    if not isinstance(pattern, str) or not pattern.strip() or len(pattern) > PATTERN_LEN:
        raise ValueError(f"Эталон: шаблон до {PATTERN_LEN} символов")
    if not _safe_pattern(pattern):
        raise ValueError(f"Шаблон: не больше {REPEATS_MAX} счётчиков {{m,n}}, границы до {REPEAT_MAX}")
    try:
        regex.compile(pattern)
    except regex.error as e:
        raise ValueError(f"Шаблон не разбирается: {e}") from None
    return None, {"pattern": pattern}


def answer_text(answer_type: str, options: list[str] | None, answer: str, choices: list[int] | None) -> str:
    """Ответ кандидата в виде текста для хранения и показа работодателю; неверный формат — ValueError."""
    if answer_type in ("choice", "multi"):
        picked = sorted(set(choices or []))
        if not picked or any(not 0 <= i < len(options or []) for i in picked) or (answer_type == "choice" and len(picked) != 1):
            raise ValueError("Выберите вариант ответа" if answer_type == "choice" else "Выберите один или несколько вариантов")
        return "; ".join(options[i] for i in picked)
    answer = answer.strip()
    if not answer:
        raise ValueError("Напишите решение")
    if answer_type == "number" and parse_number(answer) is None:
        raise ValueError("Ответ — число, например 42 или 3,14")
    return answer


def check(answer_type: str, options: list[str] | None, ref: dict | None, answer: str, choices: list[int] | None) -> bool | None:
    """Сверка с эталоном: True / False; None — проверять работодателю (открытый ответ, нет эталона, таймаут шаблона)."""
    if answer_type == "open" or not ref:
        return None
    if answer_type in ("choice", "multi"):
        return sorted(set(choices or [])) == ref["correct"]
    if answer_type == "text":
        if ref.get("exact"):
            return answer.strip() in ref["answers"]
        return norm(answer) in {norm(a) for a in ref["answers"]}
    if answer_type == "number":
        x = parse_number(answer)
        return x is not None and abs(x - ref["value"]) <= ref["tolerance"] + 1e-9 * max(1.0, abs(ref["value"]))
    try:
        return regex.fullmatch(ref["pattern"], answer.strip(), flags=regex.IGNORECASE, timeout=REGEX_TIMEOUT,
                              concurrent=True) is not None
    except TimeoutError:
        return None


def feedback(answer_type: str, auto_ok: bool | None) -> str | None:
    """Короткая обратная связь кандидату — без эталона и без подсказки, в какую сторону ошибка."""
    if answer_type == "open":
        return None
    if auto_ok is None:
        return "Автопроверка не сработала — решение оценит работодатель"
    return "Ответ совпал с эталоном" if auto_ok else "Ответ не совпал с эталоном"


if __name__ == "__main__":
    assert build("open", ["x"], {"answers": ["y"]}) == (None, None)
    o, r = build("text", None, {"answers": [" Read Committed "]})
    assert check("text", o, r, "read  committed.", None) and not check("text", o, r, "serializable", None)
    assert not check("text", None, build("text", None, {"answers": ["Ёж"], "exact": True})[1], "еж", None)
    assert check("text", None, build("text", None, {"answers": ["Ёж"]})[1], "ЕЖ!", None)
    r = build("number", None, {"value": 3.14, "tolerance": 0.01})[1]
    assert check("number", None, r, "3,145", None) and not check("number", None, r, "3.2", None) and not check("number", None, r, "пи", None)
    o, r = build("multi", ["a", "b", "c"], {"correct": [2, 0]})
    assert check("multi", o, r, "", [0, 2]) and not check("multi", o, r, "", [0]) and answer_text("multi", o, "", [2, 0]) == "a; c"
    r = build("regex", None, {"pattern": r"(a|aa)+"})[1]
    assert check("regex", None, r, "AAA", None) and check("regex", None, r, "a" * 5000 + "!", None) is None  # ReDoS — на ручную оценку
    assert parse_number("1 234,5") == 1234.5 and parse_number("-.5e1") == -5 and parse_number("1_000") is None and parse_number("١٢") is None
    assert build("regex", None, {"pattern": r"\d{3}-\d{2,}\{x\}"})
    for bad in [("regex", None, {"pattern": "((((a{20}){20}){20}){20})"}), ("regex", None, {"pattern": "a{101}"}),
                ("regex", None, {"pattern": "(?:ab){e<=1}"}), ("regex", None, {"pattern": "a{,}"}),
                ("choice", ["a", "b"], {"correct": [0, 1]}), ("choice", ["a", "A"], {"correct": [0]}), ("number", None, {"value": True}),
                ("regex", None, {"pattern": "("}), ("text", ["a"], {"answers": ["x"]}), ("magic", None, None)]:
        try:
            build(*bad)
            raise AssertionError(bad)
        except ValueError:
            pass
    print("autocheck: ok")
