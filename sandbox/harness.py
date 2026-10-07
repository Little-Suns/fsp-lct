"""Обвязка решения на Python внутри nsjail: вызывает функцию кандидата на одном тесте.

Пишет ровно одну строку-маркер в исходный stdout: «\\x1eRESULT {json}». Сравнение с ожидаемым — снаружи
песочницы (server.py): ожидаемые ответы внутрь не попадают, подделать проверку изнутри нельзя.
"""

import json
import os
import sys
import traceback

MARK = "\x1eRESULT "


def main():
    out = os.fdopen(os.dup(1), "w", encoding="utf-8")

    def emit(obj):
        out.write(MARK + json.dumps(obj, ensure_ascii=False) + "\n")
        out.flush()

    with open("/task/input.json", encoding="utf-8") as f:
        data = json.load(f)
    entry = data["entry"]
    with open("/task/solution.py", encoding="utf-8") as f:
        src = f.read()
    try:
        code = compile(src, "solution.py", "exec")
    except (SyntaxError, ValueError) as e:
        line = getattr(e, "lineno", None)
        emit({"error": "ce", "msg": f"{type(e).__name__}: {getattr(e, 'msg', e)}" + (f" (строка {line})" if line else "")})
        return
    sys.setrecursionlimit(10_000)
    ns = {"__name__": "__solution__"}
    try:
        exec(code, ns)
        fn = ns.get(entry)
        if not callable(fn):
            emit({"error": "ce", "msg": f"Не найдена функция {entry}"})
            return
        res = fn(*data["args"])
    except MemoryError:
        emit({"error": "mle"})
        return
    except RecursionError:
        emit({"error": "re", "msg": "RecursionError: слишком глубокая рекурсия"})
        return
    except BaseException as e:  # noqa: BLE001 — любое исключение решения — ошибка выполнения
        frames = [fr for fr in traceback.extract_tb(e.__traceback__) if fr.filename == "solution.py"]
        where = f" (строка {frames[-1].lineno})" if frames else ""
        emit({"error": "re", "msg": f"{type(e).__name__}: {str(e)[:200]}{where}"})
        return
    try:
        emit({"ok": res})
    except (TypeError, ValueError):
        emit({"error": "re", "msg": f"Результат типа {type(res).__name__} не переводится в JSON"})


main()
