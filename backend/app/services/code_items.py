"""Задачи на код для тест-квеста: параметрические семейства простых алгоритмов (исполняются в песочнице sandbox/).

Клон семейства = make(Random(seed)): своё имя функции, своя деталь условия (включительно/полуинтервал, < или ≤,
набор скобок…) и свои данные. Кандидату уходят условие, сигнатуры на Python и TypeScript и 1–2 открытых примера.
Скрытые тесты не хранятся в базе: hidden_tests(family, seed) пересоздаёт их из сида клона (payload["key"]["seed"]),
ожидаемые ответы считает эталон на Python (solve) — он же в обоих языках лежит в ref (проверяется в песочнице,
sandbox/tests/test_references.py). Наружу не уходят ни скрытые тесты, ни эталон.

Модуль без зависимостей от приложения: его импортируют и бэкенд (items.py), и тесты песочницы.
"""

import random
from bisect import bisect_left, bisect_right
from collections import Counter

SPECS = ["Backend", "Frontend", "Mobile", "ML / DS", "Data Eng / Analytics"]  # у кого есть компетенция «Алгоритмы»
COMPETENCY = "Алгоритмы"
TIME_MS, MEMORY_MB = 3000, 256  # лимиты на один тест (стенка, со стартом рантайма): эталон на большом тесте — до ~0,5 с, запас от ложного tle под нагрузкой
BIG = 100_000  # размер большого теста: O(n·q) на нём не укладывается в лимит ни на Python, ни на Node
TS_NOTE = "TypeScript запускается без компиляции (Node 22, --experimental-strip-types): типы стираются, enum и namespace не поддерживаются."

FAMILIES: dict[str, dict] = {}


def code_family(name: str, a: float, b: float, pilot: bool = False):
    """a, b — экспертная оценка до калибровки (как у остальных семейств), уточнять по пилотным ответам (MML/EM).
    ponytail: a ниже сценарных заданий (2,0–2,5): исход бинарный, а LLM решает такие задачи почти всегда — вес умеренный."""
    def reg(make):
        FAMILIES[name] = {"name": name, "a": a, "b": b, "pilot": pilot, "make": make}
        return make
    return reg


def camel(s: str) -> str:
    head, *rest = s.split("_")
    return head + "".join(w.title() for w in rest)


def _sorted(rng, n, lo=-10**9, hi=10**9, dup=True):
    if dup:
        pool = [rng.randint(lo, hi) for _ in range(max(1, n // 3))]
        return sorted(rng.choice(pool) for _ in range(n))
    return sorted(rng.sample(range(lo, hi), n))


def _task(name, sig_py, sig_ts, statement, story, constraints, solve, examples, gen, ref_py, ref_ts, complexity):
    return {"name": name, "sig_py": sig_py, "sig_ts": sig_ts, "statement": statement, "story": story, "constraints": constraints,
            "solve": solve, "examples": examples, "gen": gen, "ref": {"python": ref_py, "typescript": ref_ts}, "complexity": complexity}


# ============================== семейства ==============================

@code_family("code_prefix_sums", 1.6, -1.0)
def _prefix(rng):
    mode = rng.choice(["incl0", "half0", "incl1"])
    name = rng.choice(["range_sums", "segment_totals", "window_sums", "interval_sums"])
    what = rng.choice(["выручка по часам", "число заказов по дням", "ошибки по минутам", "трафик по секундам"])
    rule = {"incl0": "отрезок [l, r] включительно, индексы с 0",
            "half0": "полуинтервал [l, r): l включительно, r — нет, индексы с 0; при l = r сумма равна 0",
            "incl1": "отрезок [l, r] включительно, индексы с 1"}[mode]
    expr = {"incl0": "pre[r + 1] - pre[l]", "half0": "pre[r] - pre[l]", "incl1": "pre[r] - pre[l - 1]"}[mode]
    dr, dl = {"incl0": (1, 0), "half0": (0, 0), "incl1": (0, 1)}[mode]  # то же выражение: pre[r + dr] - pre[l - dl]

    def solve(a, qs):
        pre = [0]
        for x in a:
            pre.append(pre[-1] + x)
        return [pre[r + dr] - pre[l - dl] for l, r in qs]

    def q(rng, n):
        if mode == "incl0":
            l = rng.randrange(n)
            return [l, rng.randrange(l, n)]
        if mode == "half0":
            l = rng.randint(0, n)
            return [l, rng.randint(l, n)]
        l = rng.randint(1, n)
        return [l, rng.randint(l, n)]

    def case(rng, n, nq, lo=-1000, hi=1000):
        return [[rng.randint(lo, hi) for _ in range(n)], [q(rng, n) for _ in range(nq)]]

    def gen(rng):
        return [case(rng, 1, 2), case(rng, 2, 3, -5, -1), *(case(rng, rng.randint(3, 12), rng.randint(1, 8)) for _ in range(5)),
                case(rng, 300, 300, -10**4, 10**4), case(rng, BIG, BIG, -10**4, 10**4)]

    ex = case(rng, rng.randint(5, 7), 3, -9, 9)
    return _task(
        name, f"def {name}(a: list[int], queries: list[list[int]]) -> list[int]:", f"function {camel(name)}(a: number[], queries: number[][]): number[] {{",
        f"Дан массив целых чисел a и список запросов [l, r]. Для каждого запроса верните сумму элементов a на отрезке: {rule}. Ответы — в порядке запросов.",
        f"Дашборд показывает {what}. Аналитики просят суммы за произвольные интервалы, запросов много.",
        "1 ≤ n ≤ 10⁵, до 10⁵ запросов, |a[i]| ≤ 10⁴", solve, [ex, case(rng, 4, 2, 0, 9)], gen,
        f"def {name}(a, queries):\n    pre = [0]\n    for x in a:\n        pre.append(pre[-1] + x)\n    return [{expr} for l, r in queries]\n",
        f"function {camel(name)}(a: number[], queries: number[][]): number[] {{\n  const pre: number[] = [0];\n  for (const x of a) pre.push(pre[pre.length - 1] + x);\n"
        f"  return queries.map(([l, r]) => {expr});\n}}\n",
        "O(n + q)")


@code_family("code_hash_count", 1.5, -1.4)
def _hash(rng):
    mode = rng.choice(["most", "unique", "atleast"])
    k = rng.randint(2, 3)
    if mode == "most":
        name = rng.choice(["most_frequent", "top_value", "mode_value"])
        rule = "Верните значение, которое встречается чаще всех; если таких несколько — наименьшее из них."
        sig_py, sig_ts = f"def {name}(a: list[int]) -> int:", f"function {camel(name)}(a: number[]): number {{"
        solve = lambda a: min(Counter(a).items(), key=lambda kv: (-kv[1], kv[0]))[0]  # noqa: E731
        ref_py = f"from collections import Counter\n\ndef {name}(a):\n    c = Counter(a)\n    return min(c, key=lambda x: (-c[x], x))\n"
        ref_ts = (f"function {camel(name)}(a: number[]): number {{\n  const c = new Map<number, number>();\n  for (const x of a) c.set(x, (c.get(x) ?? 0) + 1);\n"
                  "  let best = 0, cnt = -1;\n  for (const [x, n] of c) if (n > cnt || (n === cnt && x < best)) { best = x; cnt = n; }\n  return best;\n}\n")
    elif mode == "unique":
        name = rng.choice(["first_unique", "first_single", "first_lonely"])
        rule = "Верните первый по порядку элемент, который встречается в массиве ровно один раз; если такого нет — верните −1."
        sig_py, sig_ts = f"def {name}(a: list[int]) -> int:", f"function {camel(name)}(a: number[]): number {{"
        solve = _first_unique
        ref_py = f"from collections import Counter\n\ndef {name}(a):\n    c = Counter(a)\n    return next((x for x in a if c[x] == 1), -1)\n"
        ref_ts = (f"function {camel(name)}(a: number[]): number {{\n  const c = new Map<number, number>();\n  for (const x of a) c.set(x, (c.get(x) ?? 0) + 1);\n"
                  "  for (const x of a) if (c.get(x) === 1) return x;\n  return -1;\n}\n")
    else:
        name = rng.choice(["count_frequent", "frequent_kinds", "popular_count"])
        rule = f"Верните, сколько различных значений встречается в массиве не меньше {k} раз."
        sig_py, sig_ts = f"def {name}(a: list[int]) -> int:", f"function {camel(name)}(a: number[]): number {{"
        solve = lambda a: sum(1 for v in Counter(a).values() if v >= k)  # noqa: E731
        ref_py = f"from collections import Counter\n\ndef {name}(a):\n    return sum(1 for v in Counter(a).values() if v >= {k})\n"
        ref_ts = (f"function {camel(name)}(a: number[]): number {{\n  const c = new Map<number, number>();\n  for (const x of a) c.set(x, (c.get(x) ?? 0) + 1);\n"
                  f"  let n = 0;\n  for (const v of c.values()) if (v >= {k}) n++;\n  return n;\n}}\n")
    what = rng.choice(["коды ошибок из логов", "идентификаторы товаров в заказах", "номера карт в платежах", "id пользователей в событиях"])

    def case(rng, n, span):
        return [[rng.randint(-span, span) for _ in range(n)]]

    def gen(rng):
        return [[[7]], [[5, 5, 5]], [[3, 1, 3, 1]], *(case(rng, rng.randint(2, 15), rng.randint(1, 6)) for _ in range(5)),
                case(rng, 2000, 500), case(rng, BIG, BIG // 3), [list(range(BIG))]]

    return _task(name, sig_py, sig_ts, f"Дан массив целых чисел a (непустой). {rule}", f"В выгрузке — {what}. Нужна быстрая сводка по частотам.",
                 "1 ≤ n ≤ 10⁵, |a[i]| ≤ 10⁹", solve, [case(rng, rng.randint(6, 8), 3), case(rng, 5, 2)], gen, ref_py, ref_ts, "O(n)")


def _first_unique(a):
    c = Counter(a)
    return next((x for x in a if c[x] == 1), -1)


BRACKETS = ["()[]{}", "()[]<>", "(){}"]


@code_family("code_brackets", 1.6, -0.6)
def _brackets(rng):
    pairs = rng.choice(BRACKETS)
    other = rng.random() < 0.5
    mode = rng.choice(["ok", "depth"])
    opens, closes = pairs[0::2], pairs[1::2]
    shown = ", ".join(f"{o}{c}" for o, c in zip(opens, closes))
    if mode == "ok":
        name = rng.choice(["is_balanced", "brackets_ok", "valid_brackets"])
        rule = "Верните true, если скобки расставлены правильно (каждая закрывающая закрывает последнюю открытую того же вида, все открытые закрыты), иначе false."
        ret_py, ret_ts = "bool", "boolean"
    else:
        name = rng.choice(["max_depth", "nesting_depth", "deepest_level"])
        rule = "Если скобки расставлены правильно, верните максимальную глубину вложенности (для пустой строки — 0), иначе −1."
        ret_py, ret_ts = "int", "number"
    skip = " Остальные символы (буквы, цифры, пробелы) не скобки — их пропускайте." if other else " Строка состоит только из этих скобок."

    def solve(s):
        st, depth = [], 0
        match = dict(zip(closes, opens))
        for ch in s:
            if ch in opens:
                st.append(ch)
                depth = max(depth, len(st))
            elif ch in match:
                if not st or st.pop() != match[ch]:
                    return False if mode == "ok" else -1
        if st:
            return False if mode == "ok" else -1
        return True if mode == "ok" else depth

    def word(rng, n, valid=True):
        out, st = [], []
        while len(out) < n:
            if other and rng.random() < 0.2:
                out.append(rng.choice("ab1 x"))
            elif st and (rng.random() < 0.45 or len(out) + len(st) >= n):
                out.append(closes[opens.index(st.pop())])
            else:
                o = rng.choice(opens)
                st.append(o)
                out.append(o)
        out += [closes[opens.index(o)] for o in reversed(st)]
        if not valid:
            i = rng.randrange(len(out))
            out[i] = rng.choice(pairs)
        return "".join(out)

    def gen(rng):
        deep = "".join(opens[i % len(opens)] for i in range(BIG // 2))
        deep += "".join(closes[opens.index(deep[i])] for i in range(len(deep) - 1, -1, -1))
        return [[""], [opens[0]], [closes[0]], [opens[0] + closes[-1]], [opens[0] + opens[-1] + closes[0] + closes[-1]],
                *([word(rng, rng.randint(2, 16), rng.random() < 0.5)] for _ in range(6)), [deep], [deep[:-1] + opens[0]]]

    ref_py = (f"def {name}(s):\n    pairs = {dict(zip(closes, opens))!r}\n    st, depth = [], 0\n    for ch in s:\n"
              f"        if ch in {opens!r}:\n            st.append(ch)\n            depth = max(depth, len(st))\n"
              f"        elif ch in pairs:\n            if not st or st.pop() != pairs[ch]:\n                return {'False' if mode == 'ok' else '-1'}\n"
              f"    if st:\n        return {'False' if mode == 'ok' else '-1'}\n    return {'True' if mode == 'ok' else 'depth'}\n")
    pairs_ts = ", ".join(f'"{c}": "{o}"' for o, c in zip(opens, closes))
    bad_ts = "false" if mode == "ok" else "-1"
    ref_ts = (f"function {camel(name)}(s: string): {ret_ts} {{\n  const pairs: Record<string, string> = {{ {pairs_ts} }};\n  const st: string[] = [];\n  let depth = 0;\n"
              f"  for (const ch of s) {{\n    if ({opens!r}.includes(ch)) {{ st.push(ch); depth = Math.max(depth, st.length); }}\n"
              f"    else if (ch in pairs) {{ if (!st.length || st.pop() !== pairs[ch]) return {bad_ts}; }}\n  }}\n"
              f"  if (st.length) return {bad_ts};\n  return {'true' if mode == 'ok' else 'depth'};\n}}\n")
    return _task(name, f"def {name}(s: str) -> {ret_py}:", f"function {camel(name)}(s: string): {ret_ts} {{",
                 f"Дана строка s. Скобки: {shown}.{skip} {rule}",
                 rng.choice(["Конфиг шаблонизатора не парсится — нужна быстрая проверка скобок перед выкладкой.",
                             "Линтер формул в отчётах: проверить вложенность скобок до отправки в расчёт."]),
                 "0 ≤ |s| ≤ 10⁵", solve, [[word(rng, 8, True)], [word(rng, 6, False)]], gen, ref_py, ref_ts, "O(n)")


@code_family("code_binary_search", 1.7, 0.0)
def _bsearch(rng):
    mode = rng.choice(["less", "atmost", "first", "between"])
    name = {"less": ["count_less", "below_count"], "atmost": ["count_at_most", "not_above"],
            "first": ["first_at_least", "lower_index"], "between": ["count_between", "in_range"]}[mode]
    name = rng.choice(name)
    rule = {"less": "сколько элементов a строго меньше x",
            "atmost": "сколько элементов a не больше x (≤ x)",
            "first": "индекс первого элемента a, который не меньше x (≥ x), с нуля; если такого нет — len(a)",
            "between": "сколько элементов a лежит в отрезке [lo, hi] включительно (запрос — пара [lo, hi], lo ≤ hi)"}[mode]
    q_py = {"less": "bisect_left(a, x)", "atmost": "bisect_right(a, x)", "first": "bisect_left(a, x)",
            "between": "bisect_right(a, hi) - bisect_left(a, lo)"}[mode]
    pair = mode == "between"

    def solve(a, qs):
        if pair:
            return [bisect_right(a, hi) - bisect_left(a, lo) for lo, hi in qs]
        return [bisect_left(a, x) if mode in ("less", "first") else bisect_right(a, x) for x in qs]

    def qv(rng, a):
        x = rng.choice(a) + rng.choice([-1, 0, 0, 1]) if a and rng.random() < 0.7 else rng.randint(-10**9, 10**9)
        if not pair:
            return x
        y = x + rng.randint(0, 10**8)
        return [x, y]

    def case(rng, n, nq):
        a = _sorted(rng, n)
        return [a, [qv(rng, a) for _ in range(nq)]]

    def gen(rng):
        return [[[], [qv(rng, [5])] * 2], [[5], [qv(rng, [5]) for _ in range(3)] + ([[4, 6], [6, 9]] if pair else [4, 5, 6])],
                [[2, 2, 2, 2], [[2, 2], [1, 1], [1, 3]] if pair else [1, 2, 3]],
                *(case(rng, rng.randint(1, 20), rng.randint(1, 10)) for _ in range(5)), case(rng, BIG, BIG)]

    exa = _sorted(rng, 7, 0, 12)
    examples = [[exa, [[exa[1], exa[4]], [100, 200]] if pair else [exa[2], exa[0] - 1, exa[-1] + 1]], [[1, 3, 3, 5], [[3, 3]] if pair else [3]]]
    q_ts = {"less": "lb(x)", "atmost": "ub(x)", "first": "lb(x)", "between": "ub(hi) - lb(lo)"}[mode]
    sig_q_py, sig_q_ts = ("list[list[int]]", "number[][]") if pair else ("list[int]", "number[]")
    loop_py = "lo, hi in queries" if pair else "x in queries"
    ref_ts = (f"function {camel(name)}(a: number[], queries: {sig_q_ts}): number[] {{\n"
              "  const bound = (x: number, strict: boolean): number => {\n    let lo = 0, hi = a.length;\n"
              "    while (lo < hi) { const m = (lo + hi) >> 1; if (a[m] < x || (!strict && a[m] === x)) lo = m + 1; else hi = m; }\n    return lo;\n  };\n"
              "  const lb = (x: number) => bound(x, true), ub = (x: number) => bound(x, false);\n"
              f"  return queries.map(({'[lo, hi]' if pair else 'x'}) => {q_ts});\n}}\n")
    return _task(name, f"def {name}(a: list[int], queries: {sig_q_py}) -> list[int]:", f"function {camel(name)}(a: number[], queries: {sig_q_ts}): number[] {{",
                 f"Дан отсортированный по неубыванию массив целых a (повторы возможны) и список запросов. Для каждого запроса верните {rule}. Ответы — в порядке запросов.",
                 rng.choice(["Тарифная сетка отсортирована по цене; поддержка спрашивает, сколько тарифов дешевле порога клиента.",
                             "Отсортированные времена событий из логов: на каждый запрос нужно быстро ответить без полного прохода."]),
                 "0 ≤ n ≤ 10⁵, до 10⁵ запросов, |a[i]|, |x| ≤ 10⁹ (+10⁸ для hi)", solve, examples, gen,
                 f"from bisect import bisect_left, bisect_right\n\ndef {name}(a, queries):\n    return [{q_py} for {loop_py}]\n", ref_ts, "O((n + q) · log n)")


@code_family("code_two_pointers", 1.7, 0.6)
def _pairs(rng):
    op = rng.choice(["<=", "<", ">="])
    name = rng.choice(["count_pairs", "pairs_within", "budget_pairs", "pair_count"])
    word = {"<=": "не больше t", "<": "строго меньше t", ">=": "не меньше t"}[op]

    def solve(a, t):
        n, i, j, cnt = len(a), 0, len(a) - 1, 0
        if op in ("<=", "<"):
            while i < j:
                if (a[i] + a[j] <= t) if op == "<=" else (a[i] + a[j] < t):
                    cnt += j - i
                    i += 1
                else:
                    j -= 1
            return cnt
        while i < j:
            if a[i] + a[j] >= t:
                cnt += j - i
                j -= 1
            else:
                i += 1
        return cnt

    def case(rng, n, lo=-1000, hi=1000):
        a = sorted(rng.randint(lo, hi) for _ in range(n))
        t = (rng.choice(a) + rng.choice(a)) if a else 0
        return [a, t + rng.choice([-1, 0, 0, 1])]

    def gen(rng):
        return [[[], 0], [[3], 10], [[1, 1], 2], [[1, 1, 1, 1], 2], [[-5, 0, 5], 0],
                *(case(rng, rng.randint(2, 20)) for _ in range(5)), case(rng, 3000), case(rng, BIG, -10**9, 10**9)]

    cmp_py = {"<=": "a[i] + a[j] <= t", "<": "a[i] + a[j] < t", ">=": "a[i] + a[j] >= t"}[op]
    if op == ">=":
        body_py = (f"    i, j, cnt = 0, len(a) - 1, 0\n    while i < j:\n        if {cmp_py}:\n            cnt += j - i\n            j -= 1\n"
                   "        else:\n            i += 1\n    return cnt\n")
        body_ts = (f"  let i = 0, j = a.length - 1, cnt = 0;\n  while (i < j) {{\n    if ({cmp_py}) {{ cnt += j - i; j--; }} else i++;\n  }}\n  return cnt;\n")
    else:
        body_py = (f"    i, j, cnt = 0, len(a) - 1, 0\n    while i < j:\n        if {cmp_py}:\n            cnt += j - i\n            i += 1\n"
                   "        else:\n            j -= 1\n    return cnt\n")
        body_ts = (f"  let i = 0, j = a.length - 1, cnt = 0;\n  while (i < j) {{\n    if ({cmp_py}) {{ cnt += j - i; i++; }} else j--;\n  }}\n  return cnt;\n")
    ex = case(rng, 6, 0, 20)
    return _task(name, f"def {name}(a: list[int], t: int) -> int:", f"function {camel(name)}(a: number[], t: number): number {{",
                 f"Дан отсортированный по неубыванию массив целых a и число t. Верните количество пар индексов i < j, для которых a[i] + a[j] {word}.",
                 rng.choice(["Цены товаров отсортированы. Маркетинг спрашивает, сколько пар товаров укладывается в бюджет акции.",
                             "Отсортированные задержки двух реплик: сколько пар запросов в сумме выходит за SLA."]),
                 "0 ≤ n ≤ 10⁵, |a[i]| ≤ 10⁹, |t| ≤ 2·10⁹", solve, [ex, [[1, 2, 3, 4], 5]], gen,
                 f"def {name}(a, t):\n{body_py}", f"function {camel(name)}(a: number[], t: number): number {{\n{body_ts}}}\n", "O(n)")


@code_family("code_rotated_search", 1.5, 1.2, pilot=True)
def _rotated(rng):
    mode = rng.choice(["index", "contains"])
    name = rng.choice(["search_rotated", "find_in_rotated", "rotated_index"] if mode == "index" else ["rotated_contains", "has_in_rotated"])
    rule = "индекс x в a (с нуля) или −1, если x нет" if mode == "index" else "true, если x есть в a, иначе false"

    def rot(rng, n, lo=-10**9, hi=10**9):
        a = _sorted(rng, n, lo, hi, dup=False)
        k = rng.randrange(n) if n else 0
        return a[k:] + a[:k]

    def solve(a, qs):
        pos = {x: i for i, x in enumerate(a)}
        return [pos.get(x, -1) for x in qs] if mode == "index" else [x in pos for x in qs]

    def case(rng, n, nq):
        a = rot(rng, n)
        return [a, [rng.choice(a) if a and rng.random() < 0.6 else rng.randint(-10**9, 10**9) for _ in range(nq)]]

    def gen(rng):
        return [[[], [1]], [[4], [4, 5]], [[3, 1], [1, 3, 2]], [[5, 6, 1, 2, 3], [1, 6, 4]],
                *(case(rng, rng.randint(2, 20), rng.randint(1, 8)) for _ in range(5)), case(rng, BIG, BIG)]

    ret = ("list[int]", "number[]") if mode == "index" else ("list[bool]", "boolean[]")
    miss_py, hit_py = ("-1", "m") if mode == "index" else ("False", "True")
    miss_ts, hit_ts = ("-1", "m") if mode == "index" else ("false", "true")
    ref_py = (f"def {name}(a, queries):\n    def find(x):\n        lo, hi = 0, len(a) - 1\n        while lo <= hi:\n            m = (lo + hi) // 2\n"
              f"            if a[m] == x:\n                return {hit_py}\n            if a[lo] <= a[m]:\n"
              "                if a[lo] <= x < a[m]:\n                    hi = m - 1\n                else:\n                    lo = m + 1\n"
              "            elif a[m] < x <= a[hi]:\n                lo = m + 1\n            else:\n                hi = m - 1\n"
              f"        return {miss_py}\n    return [find(x) for x in queries]\n")
    ref_ts = (f"function {camel(name)}(a: number[], queries: number[]): {ret[1]} {{\n  const find = (x: number) => {{\n    let lo = 0, hi = a.length - 1;\n"
              f"    while (lo <= hi) {{\n      const m = (lo + hi) >> 1;\n      if (a[m] === x) return {hit_ts};\n"
              "      if (a[lo] <= a[m]) { if (a[lo] <= x && x < a[m]) hi = m - 1; else lo = m + 1; }\n"
              "      else if (a[m] < x && x <= a[hi]) lo = m + 1; else hi = m - 1;\n    }\n"
              f"    return {miss_ts};\n  }};\n  return queries.map(find);\n}}\n")
    ex = rot(rng, 7, 0, 50)
    return _task(name, f"def {name}(a: list[int], queries: list[int]) -> {ret[0]}:", f"function {camel(name)}(a: number[], queries: number[]): {ret[1]} {{",
                 f"Массив различных целых чисел отсортировали по возрастанию и циклически сдвинули (например, [4, 5, 1, 2, 3]). Для каждого запроса x верните {rule}. Ответы — в порядке запросов.",
                 "Кольцевой буфер отсортированных меток времени после переполнения начинается с середины. Поиск должен остаться быстрым.",
                 "0 ≤ n ≤ 10⁵, до 10⁵ запросов, значения различны, |a[i]| ≤ 10⁹", solve, [[ex, [ex[2], 51]], [[4, 5, 1, 2, 3], [1, 3]]],
                 gen, ref_py, ref_ts, "O((n + q) · log n) или O(n + q)")


# ============================== банк ==============================

def task(family: str, seed: int) -> dict:
    return FAMILIES[family]["make"](random.Random(seed))


def render(family: str, rng: random.Random) -> dict:
    """payload клона (как у остальных семейств items.py). Скрытого здесь только сид — в payload["key"]."""
    seed = rng.getrandbits(48)
    t = task(family, seed)
    py, ts = t["name"], camel(t["name"])
    return {
        "scene_title": "Задача на код", "story": t["story"], "prompt": t["statement"], "panel": None,
        "code": {
            "entry": {"python": py, "typescript": ts},
            "templates": {"python": f"{t['sig_py']}\n    # ваше решение\n    ...\n", "typescript": f"{t['sig_ts']}\n  // ваше решение\n}}\n"},
            "examples": [{"args": args, "expected": t["solve"](*args)} for args in t["examples"]],
            "constraints": t["constraints"], "complexity": t["complexity"], "ts_note": TS_NOTE,
        },
        "key": {"seed": seed},
    }


def hidden_tests(family: str, seed: int) -> list[dict]:
    """Скрытые тесты клона: открытые примеры + крайние случаи + случайные + большой тест. Пересоздаются по сиду."""
    t = task(family, seed)
    cases = [*t["examples"], *t["gen"](random.Random(f"{seed}:tests"))]
    return [{"args": args, "expected": t["solve"](*args)} for args in cases]


def reference(family: str, seed: int, lang: str) -> str:
    return task(family, seed)["ref"][lang]
