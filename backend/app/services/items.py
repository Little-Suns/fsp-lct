"""Банк заданий тест-квеста: параметрические шаблоны-семейства (защита от утечки).

Семейство — шаблон сцены: render(rng) подставляет другие сервисы, версии, числа, место бага, порядок
вариантов. Сложность b калибруется по семейству, клоны получают небольшой разброс (±0.1).

payload задания: {scene_title, time, story, prompt, panel, options?, comment?, time_limit_s, key}.
panel — данные для отрисовки на фронте (не картинки):
  {"type": "logs",  "lines": [{"t", "src", "lvl", "msg"}]}
  {"type": "chart", "x": [...], "series": [{"name", "axis": "left"|"right", "max", "data"}], "marker": {"i", "label"}}
  {"type": "code",  "lang", "lines": [str], "caption"?}
key: индекс варианта (choice) или номер строки кода с 1 (mark/review; может быть списком допустимых строк).
Задача на код (kind = code, семейства — services/code_items.py): payload["code"] — сигнатуры, шаблоны, открытые примеры;
key = {"seed"} — из него пересоздаются скрытые тесты, сами тесты и эталон в базе не лежат.
Ключ наружу не отдаётся — см. routers/quest.py.
"""

import random

from sqlalchemy import select
from sqlalchemy.orm import Session

from app import catalog
from app.models import Item
from app.services import code_items, irt, sandbox

TIME_LIMIT = {"choice": 240, "mark": 300, "review": 360, "code": 900}
CLONES = {"Backend": 8}  # остальным специализациям — CLONES_DEFAULT
CLONES_DEFAULT = 5
CLONES_PILOT = 4

# сюжет квеста по специализации: название и «часы» смены (время сцены зависит от её номера в сессии)
STORY = {
    "Backend": ("Смена дежурного", ["02:14", "02:19", "02:31", "03:05", "09:40", "10:25", "11:10", "12:40", "13:30", "14:15", "15:05", "16:20", "17:30"]),
    "Frontend": ("Неделя до релиза", ["Пн 10:00", "Пн 14:30", "Вт 11:00", "Вт 16:00", "Ср 10:30", "Ср 15:00", "Чт 11:00", "Чт 17:00", "Пт 10:00", "Пт 13:00", "Пт 16:00", "Пт 18:00", "Пт 19:00"]),
    "Mobile": ("Релиз в сторах", ["09:30", "10:15", "11:00", "12:20", "13:40", "14:30", "15:10", "16:00", "16:45", "17:20", "18:00", "18:40", "19:10"]),
    "ML / DS": ("Модель деградирует", ["09:00", "09:45", "10:30", "11:20", "12:40", "13:30", "14:20", "15:10", "16:00", "16:50", "17:30", "18:10", "18:40"]),
    "Data Eng / Analytics": ("Квартальный отчёт", ["08:30", "09:20", "10:10", "11:00", "12:00", "13:20", "14:10", "15:00", "15:50", "16:40", "17:20", "18:00", "18:30"]),
    "DevOps / SRE": ("Миграция в облако", ["22:00", "22:20", "22:45", "23:10", "23:40", "00:15", "00:50", "01:30", "02:10", "02:50", "03:30", "04:10", "04:40"]),
    "QA": ("Приёмка релиза", ["10:00", "10:40", "11:20", "12:00", "13:30", "14:10", "14:50", "15:30", "16:10", "16:50", "17:30", "18:00", "18:30"]),
    "Security": ("Ночной инцидент", ["01:05", "01:20", "01:40", "02:05", "02:30", "03:00", "03:30", "04:00", "04:30", "05:00", "05:30", "06:00", "06:30"]),
}

FAMILIES: list[dict] = []


def family(name: str, spec: str, competency: str, kind: str, a: float, b: float, pilot: bool = False):
    def reg(render):
        FAMILIES.append({"family": name, "spec": spec, "competency": competency, "kind": kind, "a": a, "b": b, "pilot": pilot, "render": render})
        return render

    return reg


def _choice(rng: random.Random, right: str, wrong: list[str]) -> tuple[list[str], int]:
    opts = [right, *wrong]
    rng.shuffle(opts)
    return opts, opts.index(right)


def _log(t: str, src: str, lvl: str, msg: str) -> dict:
    return {"t": t, "src": src, "lvl": lvl, "msg": msg}


def _ver(rng: random.Random) -> tuple[str, str]:
    major, minor = rng.randint(2, 4), rng.randint(20, 58)
    return f"v{major}.{minor}.0", f"v{major}.{minor - 1}.{rng.randint(1, 6)}"


SVC = {"payments-api": "POST /payments", "orders-api": "POST /orders", "billing-api": "POST /invoices", "checkout-api": "POST /checkout", "wallet-api": "POST /transfers"}
UPSTREAM = ["fraud-check", "risk-scoring", "antifraud", "limits-api"]


def _svc(rng):
    s = rng.choice(list(SVC))
    return s, SVC[s]


# ============================== Backend: «Смена дежурного» ==============================
# a — экспертная оценка до калибровки (сценарные задания с контекстом различают лучше «голых» вопросов);
# ponytail: a и b заданы вручную, пересчитывать по ответам пилотных заданий (MML/EM), когда наберётся ~300 ответов на семейство

# --- Диагностика инцидентов ---


@family("be_inc_env", "Backend", "Диагностика инцидентов", "choice", 2.2, -1.6)
def _(rng):
    svc, _ep = _svc(rng)
    ver, _prev = _ver(rng)
    var = rng.choice(["PSP_API_KEY", "REDIS_URL", "KAFKA_BROKERS", "JWT_SECRET", "LEDGER_DSN"])
    m = rng.randint(10, 50)
    lines = [
        _log(f"01:{m:02d}:02", "deployer", "INFO", f"rollout {svc} {ver} started"),
        _log(f"01:{m:02d}:09", svc, "ERROR", f"Traceback: settings.py line {rng.randint(18, 60)}, in <module>\n    {var.lower()} = os.environ[\"{var}\"]\nKeyError: '{var}'"),
        _log(f"01:{m:02d}:10", "kubelet", "WARN", f"Back-off restarting failed container {svc} (restart {rng.randint(3, 6)})"),
        _log(f"01:{m:02d}:31", "kubelet", "WARN", "Readiness probe failed: connection refused"),
        _log(f"01:{m:02d}:40", "deployer", "INFO", f"rollout {svc} {ver}: 0/3 pods ready, previous ReplicaSet still serving"),
    ]
    opts, key = _choice(rng, f"В окружении нового релиза не задана переменная {var}", [
        "Поду не хватает памяти, его убивает OOM-killer",
        f"Kubernetes не может скачать образ {ver}",
        "Readiness-проба настроена слишком строго",
    ])
    return {"scene_title": "Выкладка", "story": f"Ночная выкладка {ver}. Новые поды {svc} не поднимаются, старые пока держат трафик.",
            "prompt": "В чём причина?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("be_inc_pool", "Backend", "Диагностика инцидентов", "choice", 2.4, 0.0)
def _(rng):
    """Сцена 1 макета: «Пейджер»."""
    svc, ep = _svc(rng)
    up = rng.choice(UPSTREAM)
    ver, _prev = _ver(rng)
    pool, maxc = rng.choice([5, 10, 20]), rng.choice([100, 200])
    m, ms = rng.randint(5, 40), rng.randint(2050, 2400)
    t = lambda dm, s: f"02:{m + dm:02d}:{s:02d}"  # noqa: E731
    pool_err = f"TimeoutError: QueuePool limit of size {pool}\n  overflow 0 reached, timeout 2.00"
    lines = [
        _log(t(0, 58), svc, "INFO", f"deploy {ver} finished (3/3 pods)"),
        _log(t(1, 40), svc, "WARN", f"db pool: waiting for connection {rng.uniform(1.8, 2.4):.1f}s"),
        _log(t(1, 41), svc, "ERROR", pool_err),
        _log(t(1, 41), svc, "ERROR", f"{ep} 503 ({ms} ms)"),
        _log(t(2, 5), "pg-primary", "LOG", f"connections: {maxc - rng.randint(1, 3)} of max_connections {maxc}"),
        _log(t(2, 6), up, "WARN", f"upstream {svc} slow, p95 {ms / 1000 + 0.2:.1f}s"),
        _log(t(2, 30), svc, "ERROR", pool_err),
        _log(t(2, 31), svc, "INFO", f"GET /health 200 ({rng.randint(2, 6)} ms)"),
    ]
    opts, key = _choice(rng, f"Пул соединений исчерпан после релиза {ver}: запросы держат соединения дольше", [
        "Отказ pg-primary: база недоступна",
        f"{up} замедлил {svc}, отсюда таймауты",
        f"Сетевые потери между подами {svc}",
    ])
    return {"scene_title": "Пейджер", "story": f"Понедельник. Пейджер: доля 5xx на {ep} — {rng.randint(22, 45)} %. {up} жалуется на медленные ответы. Открываете логи.",
            "prompt": "Что вероятнее всего стало первопричиной?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("be_inc_rollback", "Backend", "Диагностика инцидентов", "choice", 2.4, 0.6)
def _(rng):
    """Сцена 2 макета: «Графики»."""
    _svc_name, ep = _svc(rng)
    ver, prev = _ver(rng)
    rel, m0 = rng.randint(2, 4), rng.randint(0, 30)
    x = [f"02:{m0 + 2 * i:02d}" for i in range(8)]
    base, peak = rng.randint(160, 200), rng.randint(1900, 2300)
    p95 = [base + rng.randint(-15, 15) if i < rel else int(base * 1.4) if i == rel else peak + rng.randint(-120, 120) for i in range(8)]
    conn = [rng.randint(38, 45) if i < rel else rng.randint(55, 65) if i == rel else rng.randint(96, 99) for i in range(8)]
    panel = {"type": "chart", "x": x, "marker": {"i": rel, "label": f"релиз {ver}"}, "series": [
        {"name": f"p95 {ep}, мс", "axis": "left", "max": 2500, "data": p95},
        {"name": "соединения с pg-primary из 100", "axis": "right", "max": 100, "data": conn},
    ]}
    opts, key = _choice(rng, f"Откатить на {prev}, затем разбирать, что держит соединения", [
        "Поднять max_connections на pg-primary до 300",
        "Увеличить пул до 50 соединений на под",
        "Перезапустить pg-primary, чтобы сбросить соединения",
    ])
    return {"scene_title": "Графики", "story": "Тимлид в чате: «Что делаем?». У вас есть графики за 15 минут. Каждая минута — это неуспешные платежи.",
            "prompt": "Какое действие сделать первым?", "panel": panel, "options": opts, "key": key}


@family("be_inc_retry_storm", "Backend", "Диагностика инцидентов", "choice", 2.3, 1.6)
def _(rng):
    svc, _ep = _svc(rng)
    dep = rng.choice(["ledger", "limits-db", "accounts-api", "psp-gateway"])
    m0, blip = rng.randint(0, 20), rng.randint(2, 3)
    x = [f"03:{m0 + 2 * i:02d}" for i in range(8)]
    inc = [rng.randint(1150, 1300) for _ in range(8)]
    calls = [rng.randint(1200, 1350) if i < blip else rng.randint(4200, 5200) for i in range(8)]
    errs = [rng.randint(0, 2) if i < blip else 90 if i == blip else rng.randint(35, 60) for i in range(8)]
    panel = {"type": "chart", "x": x, "marker": {"i": blip, "label": f"сбой {dep} 30 с"}, "series": [
        {"name": f"входящие запросы {svc}, RPS", "axis": "left", "max": 6000, "data": inc},
        {"name": f"запросы {svc} → {dep}, RPS", "axis": "left", "max": 6000, "data": calls},
        {"name": f"ошибки {dep}, %", "axis": "right", "max": 100, "data": errs},
    ]}
    opts, key = _choice(rng, f"Клиент {dep} повторяет запросы без экспоненциальной задержки и джиттера: шторм повторов держит {dep} под перегрузкой", [
        f"Автоскейлер не успел добавить поды {svc}",
        "Пользователи массово повторяют оплату вручную",
        f"В {dep} утекает память после сбоя",
    ])
    return {"scene_title": "Эхо сбоя", "story": f"{dep} лежал 30 секунд и поднялся. Прошло 10 минут, а ошибки не уходят.",
            "prompt": f"Почему нагрузка на {dep} не спадает?", "panel": panel, "options": opts, "key": key}


# --- Базы данных и транзакции ---


@family("be_db_index", "Backend", "Базы данных и транзакции", "choice", 2.0, -1.2)
def _(rng):
    tbl, col = rng.choice([("payments", "external_id"), ("orders", "tracking_code"), ("users", "phone"), ("invoices", "number")])
    n, ms = rng.randint(3, 40) * 1_000_000, rng.randint(900, 4800)
    lines = [
        f"EXPLAIN ANALYZE SELECT * FROM {tbl} WHERE {col} = $1;",
        f"Seq Scan on {tbl}  (cost=0.00..{n // 9:,}.00 rows=1 width=212)".replace(",", " "),
        f"  Filter: ({col} = $1)",
        f"  Rows Removed by Filter: {n - 1}",
        f"Execution Time: {ms}.{rng.randint(100, 999)} ms",
    ]
    opts, key = _choice(rng, f"Создать индекс по {tbl}({col})", [f"VACUUM FULL {tbl}", "Увеличить work_mem", "Добавить LIMIT 1000"])
    return {"scene_title": "Медленный запрос", "story": f"Поиск по {col} тормозит: {ms} мс на запрос, таблица — {n // 1_000_000} млн строк.",
            "prompt": "Что поможет?", "panel": {"type": "code", "lang": "sql", "lines": lines}, "options": opts, "key": key}


@family("be_db_lost_update", "Backend", "Базы данных и транзакции", "mark", 2.3, 0.4)
def _(rng):
    fn, tbl = rng.choice(["add_bonus", "top_up", "credit"]), rng.choice(["wallets", "accounts", "balances"])
    lines = [f"async def {fn}(user_id: int, amount: int):"]
    if rng.random() < 0.5:
        lines.append(f'    log.info("{fn}", user_id=user_id, amount=amount)')
    lines += ["    async with db.transaction():", "        row = await db.fetchrow("]
    key = len(lines) + 1
    lines += [
        f'            "SELECT balance FROM {tbl} WHERE id = $1", user_id)',
        '        new_balance = row["balance"] + amount',
        "        await db.execute(",
        f'            "UPDATE {tbl} SET balance = $1 WHERE id = $2",',
        "            new_balance, user_id)",
    ]
    return {"scene_title": "Потерянные бонусы", "story": f"Поддержка: при одновременных начислениях часть денег пропадает. Два воркера вызывают {fn} для одного пользователя.",
            "prompt": "Нажмите на строку, которую нужно исправить, чтобы начисление не терялось.",
            "panel": {"type": "code", "lang": "python", "lines": lines}, "key": [key - 1, key]}


@family("be_db_migration", "Backend", "Базы данных и транзакции", "choice", 2.2, 1.4)
def _(rng):
    tbl, col = rng.choice([("payments", "merchant_id"), ("orders", "customer_id"), ("events", "session_id"), ("transfers", "account_id")])
    rows, w = rng.randint(80, 400), rng.randint(5, 30)
    lines = [f"-- 0{rng.randint(100, 399)}_{tbl}_{col}_idx.sql", f"CREATE INDEX idx_{tbl}_{col} ON {tbl} ({col});"]
    opts, key = _choice(rng, "CREATE INDEX CONCURRENTLY вне транзакции миграции, затем проверить, что индекс валиден", [
        "Выполнить ночью: блокировка будет короткой",
        "Сначала VACUUM ANALYZE, потом тот же CREATE INDEX",
        "Поднять maintenance_work_mem — тогда блокировки не будет",
    ])
    return {"scene_title": "Миграция", "story": f"Таблица {tbl}: {rows} млн строк, около {w} тыс. вставок в минуту. Миграцию выкатывают днём.",
            "prompt": "Как выкатить её без остановки записи?", "panel": {"type": "code", "lang": "sql", "lines": lines}, "options": opts, "key": key}


@family("be_db_write_skew", "Backend", "Базы данных и транзакции", "choice", 2.2, 2.2)
def _(rng):
    tbl, who = rng.choice([("oncall", "дежурных"), ("courier_slots", "курьеров на слоте"), ("support_shift", "операторов смены")])
    lines = [
        "BEGIN ISOLATION LEVEL REPEATABLE READ;",
        f"SELECT count(*) FROM {tbl} WHERE shift_id = $1 AND active;",
        "-- если больше одного, можно уйти",
        f"UPDATE {tbl} SET active = false WHERE shift_id = $1 AND person_id = $2;",
        "COMMIT;",
    ]
    opts, key = _choice(rng, "SERIALIZABLE с повтором транзакции при ошибке сериализации (или блокировка строк смены через SELECT … FOR UPDATE)", [
        "Перейти на READ COMMITTED",
        "Ничего: REPEATABLE READ уже защищает от этого",
        "Добавить индекс по shift_id",
    ])
    return {"scene_title": "Пустая смена", "story": f"Правило: в смене должен остаться хотя бы один из {who}. Двое одновременно снялись — и не осталось никого.",
            "prompt": "Что исправит проблему?", "panel": {"type": "code", "lang": "sql", "lines": lines}, "options": opts, "key": key}


# --- Ревью кода ---


@family("be_rv_sqli", "Backend", "Ревью кода", "mark", 2.2, -1.0)
def _(rng):
    res, tbl = rng.choice([("products", "products"), ("articles", "articles"), ("merchants", "merchants")])
    lines = [f'@router.get("/{res}/search")', "async def search(q: str, limit: int = 20):", "    limit = min(limit, 100)"]
    if rng.random() < 0.5:
        lines.append("    q = q.strip()")
    lines.append(f"    sql = f\"SELECT id, title FROM {tbl} WHERE title ILIKE '%{{q}}%' LIMIT {{limit}}\"")
    key = len(lines)
    lines += ["    rows = await db.fetch(sql)", "    return [dict(r) for r in rows]"]
    return {"scene_title": "Поиск", "story": "Стажёр прислал PR с поиском. Ревью за вами.", "prompt": "Нажмите на строку с уязвимостью.",
            "panel": {"type": "code", "lang": "python", "lines": lines, "caption": f"PR #{rng.randint(600, 999)} · «поиск по {res}»"}, "key": key}


@family("be_rv_mutable_default", "Backend", "Ревью кода", "mark", 2.0, -0.2)
def _(rng):
    fn, field = rng.choice([("collect_tags", "tags"), ("merge_labels", "labels"), ("gather_ids", "ids")])
    lines = []
    if rng.random() < 0.5:
        lines.append("@trace")
    lines.append(f"def {fn}(event: dict, acc: list = []) -> list:")
    key = len(lines)
    lines += [f'    for x in event.get("{field}", []):', "        if x not in acc:", "            acc.append(x)", "    return acc", "", "", "def handle(event: dict) -> dict:", f'    return {{"{field}": {fn}(event)}}']
    return {"scene_title": "Странные данные", "story": f"В ответах API {field} из разных запросов «перетекают» друг в друга, и список растёт с каждым вызовом.",
            "prompt": "Нажмите на строку с причиной.", "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("be_rv_double_charge", "Backend", "Ревью кода", "review", 2.5, 1.2)
def _(rng):
    """Сцена 3 макета: «Ревью фикса» от ИИ-ассистента."""
    psp, fn, k = rng.choice(["psp", "acquirer", "gateway"]), rng.choice(["charge", "pay_order", "capture"]), rng.choice([3, 4, 5])
    lines = [
        f"async def {fn}(order_id: str, amount: int):",
        "    async with db.transaction():",
        "        order = await orders.get(order_id, for_update=True)",
        '        if order.status == "paid":',
        "            return order",
    ]
    if rng.random() < 0.5:
        lines.append(f'    log.info("{fn} start", order_id=order_id)')
    lines += [f"    for attempt in range({k}):", "        try:", f"            resp = await {psp}.charge(order.card_token, amount)"]
    key = len(lines)
    lines += ["            break", "        except TimeoutError:", "            await asyncio.sleep(2 ** attempt)  # backoff",
              "    async with db.transaction():", "        await orders.mark_paid(order_id, resp.id)", "    return order"]
    return {"scene_title": "Ревью фикса", "story": "Утро после инцидента. ИИ-ассистент предложил фикс для повторных попыток списания. Ревью за вами.",
            "prompt": "Нажмите на строку, из-за которой клиент может получить двойное списание. Коротко объясните, что не так.",
            "panel": {"type": "code", "lang": "python", "lines": lines, "caption": f"PR #{rng.randint(700, 999)} · «retry для {psp}.charge при таймауте» · автор: ИИ-ассистент"},
            "comment": True, "key": key}


@family("be_rv_outbox", "Backend", "Ревью кода", "review", 2.3, 2.0)
def _(rng):
    ent, topic, step = rng.choice([("order", "orders.created", "await stock.reserve(order.items)"),
                                   ("booking", "bookings.created", "await slots.hold(booking.slot_id)"),
                                   ("shipment", "shipments.created", "await limits.check(shipment.merchant_id)")])
    lines = [f"async def create_{ent}(cmd) -> {ent.capitalize()}:", "    async with db.transaction():", f"        {ent} = await {ent}s.insert(cmd)"]
    if rng.random() < 0.5:
        lines.append(f"        metrics.inc(\"{ent}_created\")")
    lines.append(f'        await kafka.send("{topic}", {ent}.to_event())')
    key = len(lines)
    lines += [f"        {step}", f"    return {ent}"]
    return {"scene_title": "Призрачные события", "story": f"Соседняя команда жалуется: им приходят события {topic} о записях, которых нет в базе.",
            "prompt": "Нажмите на строку с проблемой и предложите исправление.",
            "panel": {"type": "code", "lang": "python", "lines": lines, "caption": f"PR #{rng.randint(700, 999)} · «публикация {topic}»"}, "comment": True, "key": key}


# --- Проектирование API ---


@family("be_api_status", "Backend", "Проектирование API", "choice", 1.9, -1.8)
def _(rng):
    sit, right = rng.choice([
        ("запрос без токена авторизации", "401 Unauthorized"),
        ("токен есть, но заказ принадлежит другому пользователю", "403 Forbidden"),
        ("регистрация с почтой, которая уже занята", "409 Conflict"),
        ("заказ с таким id не существует", "404 Not Found"),
    ])
    opts, key = _choice(rng, right, [c for c in ["401 Unauthorized", "403 Forbidden", "409 Conflict", "404 Not Found"] if c != right])
    return {"scene_title": "Вопрос из чата", "story": "Фронтенд-разработчик спрашивает, какой код ответа ждать от API.",
            "prompt": f"Какой код вернуть, если {sit}?", "panel": None, "options": opts, "key": key}


@family("be_api_pagination", "Backend", "Проектирование API", "choice", 2.2, 0.2)
def _(rng):
    feed, lim = rng.choice(["операций", "уведомлений", "заказов", "отзывов"]), rng.choice([20, 50, 100])
    opts, key = _choice(rng, "Курсорная пагинация: отдавать курсор по (created_at, id) и запрашивать записи «после курсора»", [
        f"Увеличить limit до {lim * 5}", "Кэшировать каждую страницу на 5 минут", "Сортировать по случайному ключу с сидом",
    ])
    return {"scene_title": "Дубли в ленте", "story": f"Лента {feed} отдаётся через ?offset=&limit={lim}. Пока пользователь листает, появляются новые записи, и он видит дубли.",
            "prompt": "Как исправить?", "panel": None, "options": opts, "key": key}


@family("be_api_idem", "Backend", "Проектирование API", "choice", 2.3, 0.8)
def _(rng):
    res, thing = rng.choice([("payments", "платежа"), ("transfers", "перевода"), ("orders", "заказа")])
    opts, key = _choice(rng, "Клиент шлёт Idempotency-Key, сервер хранит ключ с результатом и на повтор отдаёт сохранённый ответ", [
        "Запретить клиенту повторы: пусть показывает ошибку",
        "Заменить POST на PUT без изменений на сервере",
        "Дедуплицировать по сумме и времени запроса в окне 10 секунд",
    ])
    return {"scene_title": "Двойные записи", "story": f"Мобильное приложение повторяет POST /{res} при обрыве сети. Иногда создаются два {thing}.",
            "prompt": "Как спроектировать API?", "panel": None, "options": opts, "key": key}


@family("be_api_breaking", "Backend", "Проектирование API", "choice", 2.2, 1.8)
def _(rng):
    res, old, new = rng.choice([("profile", "phone", "phone_e164"), ("orders", "sum", "amount"), ("cards", "num", "masked_pan")])
    opts, key = _choice(rng, f"Добавить {new}, оставить {old} помеченным как устаревшее и убрать, когда метрики покажут, что старых клиентов не осталось", [
        "Переименовать и выпустить вместе с новой версией приложения",
        "Перенести весь API в /v2 и сразу выключить /v1",
        f"Отдавать {old} только по заголовку Accept-Version, по умолчанию — {new}",
    ])
    return {"scene_title": "Переименование", "story": f"Поле {old} в GET /{res} нужно переименовать в {new}. Старые версии мобильного приложения живут ещё полгода.",
            "prompt": "Что делать?", "panel": None, "options": opts, "key": key}


# --- Конкурентность ---


@family("be_cc_blocking", "Backend", "Конкурентность", "mark", 2.0, -0.6)
def _(rng):
    fn, call = rng.choice([("fetch_rates", 'requests.get(f"{RATES_URL}/{cur}", timeout=5)'), ("load_limits", 'requests.post(LIMITS_URL, json={"cur": cur}, timeout=5)')])
    lines = [f"async def {fn}(currencies: list[str]) -> dict:", "    result = {}", "    for cur in currencies:", f"        resp = {call}"]
    key = len(lines)
    lines += ['        result[cur] = resp.json()["rate"]', "    return result"]
    return {"scene_title": "Замирание", "story": f"Пока выполняется {fn}, весь сервис перестаёт отвечать, даже /health.",
            "prompt": "Нажмите на строку с причиной.", "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("be_cc_race", "Backend", "Конкурентность", "mark", 2.3, 0.6)
def _(rng):
    new, old, revoked, fn = rng.choice([("новый токен", "старый", "отозванный токен", "get_token"),
                                        ("новую сессию", "старую", "отозванную сессию", "get_session"),
                                        ("новый ключ", "старый", "отозванный ключ", "get_key")])
    lines = ["_cache: dict[str, str] = {}", ""]
    if rng.random() < 0.5:
        lines += ["", "# выдача отзывает предыдущее значение"]
    lines += [f"async def {fn}(client_id: str) -> str:", "    if client_id not in _cache:", "        _cache[client_id] = await auth.issue(client_id)"]
    key = len(lines)
    lines.append("    return _cache[client_id]")
    return {"scene_title": "Гонка", "story": f"Сервис авторизации, выдавая {new}, отзывает {old}. Под нагрузкой часть запросов получает {revoked}.",
            "prompt": "Нажмите на строку, где возникает гонка.", "panel": {"type": "code", "lang": "python", "lines": lines}, "key": [key - 1, key]}


@family("be_cc_gather", "Backend", "Конкурентность", "choice", 2.2, 1.4)
def _(rng):
    n = rng.randint(20, 90) * 1000
    lines = ["async def notify_all(users):", "    async with httpx.AsyncClient() as client:", "        await asyncio.gather(*(notify(client, u) for u in users))"]
    opts, key = _choice(rng, "Ограничить параллелизм asyncio.Semaphore (например, на 100) вокруг вызова notify", [
        "Увеличить timeout у HTTP-клиента", "Запустить notify в ThreadPoolExecutor", "Добавить return_exceptions=True в gather",
    ])
    return {"scene_title": "Рассылка", "story": f"Рассылка {n} уведомлений падает с OSError: [Errno 24] Too many open files, а сервис уведомлений отвечает 429.",
            "prompt": "Как исправить с минимальными изменениями?", "panel": {"type": "code", "lang": "python", "lines": lines}, "options": opts, "key": key}


@family("be_cc_deadlock", "Backend", "Конкурентность", "choice", 2.2, 2.4)
def _(rng):
    p1, p2, t1, t2 = rng.randint(3000, 4999), rng.randint(5000, 6999), rng.randint(9000, 9999), rng.randint(10000, 10999)
    tbl = rng.choice(["accounts", "wallets", "balances"])
    lines = [
        _log("14:02:11", "pg-primary", "ERROR", "deadlock detected"),
        _log("14:02:11", "pg-primary", "DETAIL", f"Process {p1} waits for ShareLock on transaction {t2}; blocked by process {p2}.\n"
                                                  f"Process {p2} waits for ShareLock on transaction {t1}; blocked by process {p1}."),
        _log("14:02:11", "pg-primary", "CONTEXT", f'while updating tuple (12,7) in relation "{tbl}"'),
    ]
    opts, key = _choice(rng, "Блокировать счета в одном порядке: сначала меньший id, потом больший", [
        "Увеличить deadlock_timeout", "Перейти на SERIALIZABLE", "Вынести каждое UPDATE в отдельную транзакцию",
    ])
    return {"scene_title": "Взаимная блокировка", "story": f"Перевод делает два UPDATE в {tbl}: сначала счёт отправителя, потом получателя. Изредка переводы падают.",
            "prompt": "Что устранит причину?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Алгоритмы ---


@family("be_alg_set", "Backend", "Алгоритмы", "choice", 1.9, -1.4)
def _(rng):
    n, m = rng.randint(200, 900), rng.randint(50, 300)
    lines = ["def find_blocked(payments: list, blocked: list[str]) -> list:", "    return [p for p in payments if p.card_hash in blocked]"]
    opts, key = _choice(rng, "Сделать blocked множеством (set): проверка станет O(1), всего O(n + m)", [
        "Отсортировать payments перед проверкой", "Переписать list comprehension на цикл for", "Распараллелить на 4 потока",
    ])
    return {"scene_title": "Медленная сверка", "story": f"Платежей ~{n} тыс., заблокированных карт ~{m} тыс. Сверка идёт десятки минут.",
            "prompt": "Как ускорить?", "panel": {"type": "code", "lang": "python", "lines": lines}, "options": opts, "key": key}


@family("be_alg_topk", "Backend", "Алгоритмы", "choice", 2.2, 0.2)
def _(rng):
    n, k = rng.randint(50, 500), rng.choice([10, 50, 100])
    opts, key = _choice(rng, f"Мин-куча размера {k}: O(n log k) по времени, O(k) по памяти", [
        "Сортировать все платежи: O(n log n), память O(n)", f"{k} раз пройти поток и выбрать максимум", "Бинарный поиск по потоку",
    ])
    return {"scene_title": "Топ платежей", "story": f"Из потока ~{n} млн платежей за сутки нужен топ-{k} крупнейших. Память сервиса ограничена, поток читается один раз.",
            "prompt": "Какой подход выбрать?", "panel": None, "options": opts, "key": key}


@family("be_alg_intervals", "Backend", "Алгоритмы", "choice", 2.2, 1.2)
def _(rng):
    ent, n = rng.choice(["задач", "звонков", "сессий"]), rng.randint(1, 9) * 100_000
    opts, key = _choice(rng, "Отсортировать 2n событий (начало +1, конец −1; при равенстве конец раньше) и пройти, считая сумму: O(n log n)", [
        "Для каждого интервала посчитать пересечения с остальными: O(n log n)",
        "Отсортировать по началу и посчитать пересечения соседних пар",
        "Жадно выбирать интервал с самым ранним концом",
    ])
    return {"scene_title": "Пиковая нагрузка", "story": f"Есть {n:,} интервалов {ent} [start, end).".replace(",", " ") + " Нужно найти, сколько их шло одновременно в пике.",
            "prompt": "Какой алгоритм корректен и эффективен?", "panel": None, "options": opts, "key": key}


@family("be_alg_rehash", "Backend", "Алгоритмы", "choice", 2.3, 2.2)
def _(rng):
    n = rng.randint(3, 12)
    right, w1 = f"≈ {round(100 * n / (n + 1))} %", f"≈ {round(100 / (n + 1))} %"
    opts, key = _choice(rng, right, [w1, "≈ 50 %", "0 %, если хеш-функция стабильная"])
    return {"scene_title": "Ещё один шард", "story": f"Ключи кэша распределены по {n} шардам как hash(key) mod {n}. Добавляем ещё один шард.",
            "prompt": "Какая доля ключей сменит шард?", "panel": None, "options": opts, "key": key}


# --- пилотные (калибровка, на грейд не влияют) ---


@family("be_pilot_stampede", "Backend", "Конкурентность", "choice", 1.5, 1.0, pilot=True)
def _(rng):
    thing = rng.choice(["курса валют", "каталога", "тарифов"])
    opts, key = _choice(rng, "Пересчитывать значение одним запросом под блокировкой (single-flight), остальным отдавать старое значение", [
        "Уменьшить TTL", "Увеличить пул соединений к базе", "Удалять ключ при каждом изменении",
    ])
    return {"scene_title": "Лавина в кэше", "story": f"Ключ кэша {thing} истекает, и сотни запросов одновременно идут в базу.",
            "prompt": "Как защититься?", "panel": None, "options": opts, "key": key}


@family("be_pilot_percentiles", "Backend", "Диагностика инцидентов", "choice", 1.5, -0.5, pilot=True)
def _(rng):
    avg = rng.randint(90, 160)
    opts, key = _choice(rng, "Перцентили p95/p99 по эндпоинтам", ["Медиану", "Среднее за сутки вместо часа", "Число запросов в секунду"])
    return {"scene_title": "Жалобы на скорость", "story": f"Среднее время ответа {avg} мс, а пользователи жалуются на тормоза.",
            "prompt": "Что смотреть в первую очередь?", "panel": None, "options": opts, "key": key}


# ============================== остальные специализации ==============================
# ponytail: по одному простому семейству на компетенцию (≈6 заданий за сессию); расширять банк по образцу Backend


def _fill(s, v: dict):
    if isinstance(s, list):
        return [_fill(x, v) for x in s]
    for k, val in v.items():
        s = s.replace(f"⟨{k}⟩", str(val))
    return s


def simple(spec: str, comp: str, b: float, title: str, story: str, prompt: str, right: str, wrong: list[str], vars=None, code: list[str] | None = None):
    """Простое семейство: выбор из 4 вариантов, подстановка ⟨переменных⟩ и перемешивание вариантов."""

    def render(rng):
        v = vars(rng) if callable(vars) else {k: rng.choice(opts) for k, opts in (vars or {}).items()}
        opts, key = _choice(rng, _fill(right, v), _fill(wrong, v))
        panel = {"type": "code", "lang": "text", "lines": _fill(code, v)} if code else None
        return {"scene_title": title, "story": _fill(story, v), "prompt": _fill(prompt, v), "panel": panel, "options": opts, "key": key}

    FAMILIES.append({"family": "", "spec": spec, "competency": comp, "kind": "choice", "a": 1.7, "b": b, "pilot": False, "render": render})


simple("Frontend", "Отладка UI", -1.2, "Кнопка не жмётся", "После релиза кнопка «⟨btn⟩» перестала нажиматься. В DevTools поверх неё лежит прозрачный ⟨el⟩.",
       "Что проверить первым?", "z-index и pointer-events перекрывающего элемента",
       ["Обработчик onClick у кнопки", "Кэш браузера", "Версию фреймворка"], {"btn": ["Оплатить", "Оформить", "Сохранить"], "el": ["баннер cookies", "оверлей модалки", "блок промо"]})
simple("Frontend", "Производительность", 0.6, "Лагающий список", "Список из ⟨n⟩ строк тормозит при прокрутке: каждая строка — тяжёлый компонент.",
       "Что даст основной выигрыш?", "Виртуализация: рендерить только видимые строки",
       ["Заменить CSS-классы на inline-стили", "Перенести список в iframe", "Добавить debounce на onScroll"], {"n": [5000, 12000, 30000]})
simple("Frontend", "Ревью кода", 0.0, "PR с эффектом", "Компонент карточки ⟨res⟩ получает id из пропсов. При переходе на другую карточку данные не меняются.",
       "Что не так в коде?", "В массиве зависимостей нет id: при смене id эффект не перезапускается",
       ["fetch нельзя вызывать внутри useEffect", "setData нужно обернуть в useCallback", "Нужно использовать XMLHttpRequest"],
       {"res": ["товара", "заказа", "пользователя"]}, code=["useEffect(() => {", "  fetch(`/api/⟨res⟩/${id}`)", "    .then(r => r.json())", "    .then(setData);", "}, []);"])
simple("Frontend", "Архитектура клиента", 1.2, "Три корзины", "Состояние ⟨what⟩ хранится в store, в localStorage и в URL. После перезагрузки они расходятся.",
       "Как исправить архитектурно?", "Один источник правды в store; localStorage и URL синхронизируются из него в одну сторону",
       ["Синхронизировать все три копии по setInterval", "Хранить всё только в localStorage и читать на каждый рендер", "Добавить ещё один контекст поверх"], {"what": ["корзины", "фильтров", "черновика"]})
simple("Frontend", "Доступность", -0.4, "Немая кнопка", "Кнопка-иконка «⟨icon⟩» без текста. Скринридер читает просто «кнопка».",
       "Как исправить?", "Добавить aria-label с названием действия", ["Добавить role=\"img\" к иконке", "Заменить button на div с onClick", "Увеличить иконку"],
       {"icon": ["корзина", "закрыть", "поиск"]})
simple("Frontend", "Алгоритмы", 1.8, "Подсказки поиска", "Поиск по ⟨n⟩ тыс. названий на клиенте: подсказки по префиксу на каждое нажатие клавиши.",
       "Какую структуру выбрать?", "Отсортированный массив с бинарным поиском границ префикса или префиксное дерево",
       ["filter + includes на каждый ввод — это быстро при любом объёме", "Регулярное выражение по склеенной строке", "Хеш-таблица по полному названию"], {"n": [50, 200, 500]})

simple("Mobile", "Отладка", -1.2, "Краш при повороте", "Приложение падает при повороте экрана на экране «⟨scr⟩». Колбэк загрузки обращается к уже уничтоженному view.",
       "Что исправить?", "Отменять загрузку и отписываться от колбэков при уничтожении экрана",
       ["Запретить поворот экрана во всём приложении", "Обернуть колбэк в try/catch", "Увеличить таймаут загрузки"], {"scr": ["Профиль", "Корзина", "Заказ"]})
simple("Mobile", "Жизненный цикл приложения", 0.0, "Пустой экран", "Пользователь свернул приложение во время ⟨what⟩, вернулся через 20 минут — экран пустой: система убила процесс.",
       "Что сделать?", "Сохранять состояние экрана и восстанавливать его после пересоздания процесса",
       ["Запустить foreground-сервис, чтобы процесс не убивали", "Перезапускать приложение с главного экрана", "Хранить состояние в статической переменной"],
       {"what": ["оформления заказа", "заполнения анкеты", "загрузки документа"]})
simple("Mobile", "Ревью кода", 0.6, "Подвисание", "В PR запрос ⟨req⟩ выполняется синхронно в обработчике нажатия кнопки.",
       "Что не так?", "Сеть на главном потоке: интерфейс зависнет; запрос — в фон, UI обновлять на главном потоке",
       ["Ничего, если запрос быстрый", "Нужно добавить индикатор загрузки, этого достаточно", "Кнопку нужно отключать после нажатия, остальное в порядке"],
       {"req": ["профиля", "баланса", "истории заказов"]})
simple("Mobile", "Сеть и офлайн", 1.2, "Метро", "Заказ ⟨what⟩, оформленный без сети, должен уйти, когда связь появится, и не задвоиться.",
       "Как реализовать?", "Локальная очередь исходящих запросов с идемпотентным ключом и повтором при появлении сети",
       ["Показать ошибку и попросить повторить позже", "Повторять запрос каждую секунду до успеха", "Отправить по SMS"], {"what": ["такси", "еды", "билета"]})
simple("Mobile", "Производительность", -0.4, "Дёрганая лента", "Лента фотографий ⟨res⟩ дёргается при прокрутке: картинки декодируются целиком на главном потоке.",
       "Что поможет больше всего?", "Уменьшать картинки до размера ячейки и декодировать вне главного потока",
       ["Отключить анимации", "Перейти на PNG", "Загружать все картинки при старте"], {"res": ["4000×3000", "12 Мп", "в полном размере"]})
simple("Mobile", "Алгоритмы", 1.8, "Ближайшие точки", "Нужно показывать ⟨k⟩ ближайших точек самовывоза из 50 тыс. и обновлять при сдвиге карты.",
       "Как искать?", "Пространственный индекс (геохеш или k-d дерево) и запрос по окрестности",
       ["Сортировать все точки по широте и брать первые", "Хеш-таблица по названию города", "Кэшировать ответ на сутки"], {"k": [10, 20, 50]})

simple("ML / DS", "Постановка задачи", -1.2, "Запрос бизнеса", "Бизнес просит «предсказать отток ⟨who⟩».",
       "Что уточнить первым?", "Что считается оттоком, горизонт прогноза и какое действие примут по прогнозу",
       ["Какую нейросеть использовать", "Сколько GPU выделят", "Какой будет accuracy"], {"who": ["клиентов", "мерчантов", "подписчиков"]})
simple("ML / DS", "Валидация моделей", 0.0, "Слишком хорошо", "Доля мошеннических транзакций ⟨p⟩ %. Модель показывает accuracy ⟨acc⟩ %.",
       "Что это значит?", "Почти ничего: константа «не мошенник» даёт ⟨base⟩ %; нужны precision/recall или PR-AUC",
       ["Модель отличная, можно выкатывать", "Модель переобучилась", "Нужно поднять порог до 0,9"],
       lambda rng: (lambda p: {"p": p, "acc": f"{100 - p * 0.8:.1f}".replace(".", ","), "base": f"{100 - p:.1f}".replace(".", ",")})(rng.choice([0.5, 1.0, 2.0])))
simple("ML / DS", "Дрейф данных", 0.6, "Деградация", "Через ⟨w⟩ недель после запуска метрика скоринга упала. Распределение признака «⟨f⟩» сдвинулось, PSI = ⟨psi⟩.",
       "Что делать?", "Это дрейф: проверить источник данных, затем переобучить на свежем окне и настроить мониторинг PSI",
       ["Увеличить глубину деревьев", "Поднять порог классификации", "Игнорировать: такой PSI — это шум"],
       {"w": [3, 6, 8], "f": ["доход", "регион", "устройство"], "psi": ["0,31", "0,38", "0,45"]})
simple("ML / DS", "Feature engineering", 1.2, "Подозрительный AUC", "Признак «⟨feat⟩» считается по всем заказам клиента, включая заказы после даты прогноза. ROC-AUC на валидации ⟨auc⟩.",
       "В чём проблема?", "Утечка из будущего: считать признак только по данным до точки прогноза и валидировать по времени",
       ["Признак слишком шумный, его надо логарифмировать", "Не хватает регуляризации", "Нужно больше деревьев"],
       {"feat": ["средний чек", "число заказов", "доля возвратов"], "auc": ["0,97", "0,98", "0,99"]})
simple("ML / DS", "MLOps", 1.8, "Ноутбук vs прод", "Модель ⟨m⟩ в проде отвечает иначе, чем в ноутбуке, на тех же сырых данных.",
       "Что вероятнее всего?", "Препроцессинг в обучении и в сервинге разный: вынести его в общий пайплайн и версионировать с моделью",
       ["В проде другая версия CPU", "Модель недообучена", "Нужно включить float64 в проде"], {"m": ["скоринга", "рекомендаций", "антифрода"]})
simple("ML / DS", "Алгоритмы", -0.4, "Поиск соседей", "Нужно найти ⟨k⟩ ближайших эмбеддингов среди ⟨n⟩ млн за 20 мс.",
       "Что использовать?", "Приближённый поиск ближайших соседей (HNSW или IVF)", ["Полный перебор косинусов на CPU", "k-means с k = ⟨k⟩", "Сортировку по норме вектора"],
       {"k": [10, 50, 100], "n": [10, 50, 200]})

simple("Data Eng / Analytics", "SQL", -1.2, "Пустые регионы", "Нужна выручка по ⟨dim⟩, включая те, где продаж не было.",
       "Как написать запрос?", "LEFT JOIN продаж к справочнику ⟨dim⟩ и COALESCE(sum, 0)", ["INNER JOIN и GROUP BY", "UNION ALL справочника и продаж", "SELECT DISTINCT по продажам"],
       {"dim": ["регионам", "категориям", "магазинам"]})
simple("Data Eng / Analytics", "Моделирование данных", 0.6, "История менеджеров", "Менеджер у ⟨who⟩ меняется, а отчёты за прошлые кварталы должны показывать прежнего.",
       "Как хранить измерение?", "SCD Type 2: версии строк измерения с датами действия", ["Перезаписывать поле (SCD Type 1)", "Хранить менеджера в JSON заказа", "Пересчитывать старые отчёты вручную"],
       {"who": ["клиента", "дилера", "партнёра"]})
simple("Data Eng / Analytics", "Пайплайны", 0.0, "Задвоение", "Ежедневная загрузка ⟨src⟩ упала посередине, её перезапустили — данные за день задвоились.",
       "Как исправить загрузку?", "Сделать её идемпотентной: перезаписывать партицию дня целиком (delete + insert или MERGE)",
       ["Запускать DISTINCT после каждой загрузки по всей таблице", "Не перезапускать упавшие загрузки", "Увеличить ретраи"], {"src": ["заказов", "событий", "платежей"]})
simple("Data Eng / Analytics", "Качество данных", -0.4, "Пропавшие строки", "В витрине ⟨tbl⟩ вчера оказалось на 40 % меньше строк, заметили только в отчёте.",
       "Как ловить такое раньше?", "Автоматические проверки объёма и свежести с алертом до публикации витрины",
       ["Раз в неделю смотреть дашборд", "Добавить индексы", "Перейти на другой формат хранения"], {"tbl": ["sales", "orders", "visits"]})
simple("Data Eng / Analytics", "Визуализация", -1.6, "Доли каналов", "Нужно сравнить доли ⟨n⟩ каналов привлечения по кварталам.",
       "Какой график выбрать?", "Столбцы с накоплением до 100 % по кварталам", ["Круговую диаграмму на каждый квартал", "3D-столбцы", "Одну линию с двумя осями"], {"n": [4, 5, 6]})
simple("Data Eng / Analytics", "Алгоритмы", 1.8, "Уникальные пользователи", "Нужно число уникальных пользователей за ⟨d⟩ дней по ⟨n⟩ млрд событий, погрешность до 2 % допустима.",
       "Что использовать?", "HyperLogLog: скетчи по дням, которые можно объединять", ["COUNT(DISTINCT) по сырым событиям каждый раз", "Сумму дневных уникальных", "Выборку 1 % событий и умножение на 100"],
       {"d": [7, 30, 90], "n": [2, 5, 20]})

simple("DevOps / SRE", "Диагностика инцидентов", -1.2, "Перезапуски", "Под ⟨svc⟩ в CrashLoopBackOff, в describe: Last State: Terminated, Reason: OOMKilled.",
       "Что происходит?", "Контейнер превышает лимит памяти: проверить потребление, поднять limits или найти утечку",
       ["Не скачивается образ", "Не прошла readiness-проба", "Закончилось место на диске узла"], {"svc": ["billing", "search", "gateway"]})
simple("DevOps / SRE", "Сети", 0.6, "Имя не резолвится", "Из пода ⟨svc⟩ не резолвится db.internal, а по IP подключение проходит.",
       "Куда смотреть?", "DNS: CoreDNS и resolv.conf пода (search, ndots)", ["NetworkPolicy блокирует порт базы", "MTU на узле", "Сертификат базы истёк"], {"svc": ["orders", "auth", "reports"]})
simple("DevOps / SRE", "Kubernetes", 0.0, "502 при выкладке", "Во время каждой выкладки ⟨svc⟩ около 30 секунд отдаёт 502.",
       "Что настроить?", "Readiness-пробу и корректное завершение (preStop, обработка SIGTERM), чтобы под уходил из балансировки до остановки",
       ["Увеличить число реплик вдвое", "Перейти на стратегию Recreate", "Убрать liveness-пробу"], {"svc": ["api", "frontend", "payments"]})
simple("DevOps / SRE", "CI/CD", -0.4, "Долгая сборка", "Сборка образа ⟨svc⟩ каждый раз ставит зависимости с нуля, ⟨m⟩ минут.",
       "Как ускорить?", "Копировать lock-файл и ставить зависимости до копирования кода, чтобы слой кэшировался",
       ["Собирать на более мощном раннере", "Отключить тесты", "Собирать образ раз в сутки"], {"svc": ["api", "worker", "admin"], "m": [8, 12, 15]})
simple("DevOps / SRE", "Наблюдаемость", 1.2, "Ложные алерты", "Алерт «CPU > 80 %» на ⟨svc⟩ срабатывает по ночам, но пользователи ничего не замечают.",
       "Что изменить?", "Алертить по симптомам: SLO по ошибкам и задержке, скорость сжигания бюджета ошибок",
       ["Поднять порог до 95 %", "Отключить ночные алерты", "Добавить алерт на память"], {"svc": ["api", "search", "billing"]})
simple("DevOps / SRE", "План отката", 1.8, "Переименование колонки", "Новая версия ⟨svc⟩ переименовывает колонку ⟨col⟩ в БД.",
       "Как выкатить, чтобы откат оставался возможен?", "Expand/contract: добавить новую колонку, писать в обе, переключить чтение, старую удалить в следующем релизе",
       ["Переименовать в миграции и выкатить, при проблеме восстановить из бэкапа", "Выкатить ночью", "Сделать снапшот диска перед выкладкой"],
       {"svc": ["orders", "billing", "crm"], "col": ["user_name", "amount", "status"]})

simple("QA", "Тест-дизайн", -1.2, "Границы", "Поле «⟨field⟩» принимает целые числа от ⟨lo⟩ до ⟨hi⟩.",
       "Какой набор минимален и покрывает границы?", "⟨lo1⟩, ⟨lo⟩, ⟨hi⟩, ⟨hi1⟩", ["⟨lo⟩, ⟨mid⟩, ⟨hi⟩", "Все значения от ⟨lo⟩ до ⟨hi⟩", "0, −1, 999999"],
       lambda rng: (lambda f, lo, hi: {"field": f, "lo": lo, "hi": hi, "lo1": lo - 1, "hi1": hi + 1, "mid": (lo + hi) // 2})(
           *rng.choice([("Возраст", 18, 65), ("Количество", 1, 99), ("Срок, мес.", 3, 36)])))
simple("QA", "Приёмка релиза", 0.6, "Баг за час до релиза", "За час до релиза найден баг: ⟨bug⟩. Фикс есть, но регресс по нему не пройден.",
       "Что делать?", "Оценить риск с владельцем продукта: выключить фичу флагом или перенести релиз, решение зафиксировать",
       ["Выкатить фикс без регресса", "Выпустить как есть и чинить потом", "Отложить релиз на неделю без обсуждения"],
       {"bug": ["промокод применяется дважды", "в корзине не пересчитывается доставка", "кнопка оплаты пропадает на iPhone SE"]})
simple("QA", "Автотесты", 0.0, "Мигающий тест", "UI-тест «⟨t⟩» падает примерно в одном прогоне из десяти: элемент не найден.",
       "Как стабилизировать?", "Явное ожидание нужного состояния элемента и стабильные локаторы (data-testid)",
       ["Добавить sleep(5)", "Перезапускать упавшие тесты трижды", "Отключить тест"], {"t": ["оформление заказа", "вход", "поиск"]})
simple("QA", "API-тестирование", -0.4, "Повторный запрос", "POST /⟨res⟩ повторяется с тем же Idempotency-Key.",
       "Какой результат ожидаем?", "Тот же ответ, что и в первый раз, без создания второй записи",
       ["409 Conflict", "Новая запись с новым id", "500 Internal Server Error"], {"res": ["payments", "orders", "transfers"]})
simple("QA", "Баг-репорты", -1.6, "Баг-репорт", "Приложение падает на экране «⟨scr⟩».",
       "Что обязательно в баг-репорте?", "Шаги воспроизведения, ожидаемый и фактический результат, окружение и версия",
       ["Скриншот и слово «срочно»", "Имя разработчика, который виноват", "Предложение по исправлению кода"], {"scr": ["Корзина", "Профиль", "Оплата"]})
simple("QA", "Регресс", 1.4, "Не успеваем", "Изменили расчёт ⟨what⟩. Полный регресс из 2000 кейсов до релиза не успеть.",
       "Что прогнать?", "Кейсы по анализу влияния изменения (связанные модули и сценарии оплаты) плюс смоук",
       ["Случайные 10 % кейсов", "Только новые кейсы", "Только автотесты, ручные пропустить"], {"what": ["скидки в корзине", "стоимости доставки", "налога"]})

simple("Security", "Веб-уязвимости", -1.2, "Чужие данные", "GET /⟨res⟩?id=⟨n⟩ возвращает чужие данные, если поменять id.",
       "Что это и как исправить?", "IDOR: проверять на сервере, что объект принадлежит пользователю",
       ["XSS: экранировать вывод", "CSRF: добавить токен", "SQL-инъекция: параметризовать запрос"], {"res": ["invoices", "orders", "profile"], "n": [1042, 7731, 318]})
simple("Security", "Ревью кода", 0.6, "Пинг", "В админке есть проверка доступности хоста по имени, которое вводит пользователь.",
       "Какая уязвимость в коде?", "Внедрение команд: shell=True и пользовательский ввод в строке команды",
       ["Утечка памяти", "SSRF через ICMP", "Ничего, есть таймаут"], {}, code=['host = request.args["host"]', 'subprocess.run(f"ping -c 1 {host}", shell=True, timeout=5)'])
simple("Security", "Сети", 0.0, "Недоступность", "С ⟨n⟩ тыс. адресов идут SYN без завершения рукопожатия, сервис перестал принимать соединения.",
       "Что это и что включить?", "SYN flood: SYN cookies и фильтрация на периметре", ["Брутфорс: fail2ban", "DNS amplification: закрыть резолвер", "ARP-спуфинг: статические записи"],
       {"n": [12, 40, 90]})
simple("Security", "Криптография", 1.2, "Пароли", "Пароли пользователей хранятся как ⟨h⟩(password).",
       "Как правильно?", "Медленная функция с солью: argon2id или bcrypt", ["sha512 вместо ⟨h⟩", "AES-шифрование с ключом в конфиге", "⟨h⟩ дважды"], {"h": ["sha256", "md5", "sha1"]})
simple("Security", "Реагирование", -0.4, "Утёкший ключ", "Ключ ⟨key⟩ попал в публичный репозиторий два часа назад.",
       "Первое действие?", "Отозвать и перевыпустить ключ, затем проверить журналы его использования",
       ["Удалить коммит из истории", "Сделать репозиторий приватным", "Написать в чат команды"], {"key": ["облачного хранилища", "платёжного шлюза", "почтового сервиса"]})
simple("Security", "Реверс", 1.8, "Проверка лицензии", "В бинарнике ⟨app⟩ проверка лицензии сравнивает введённый ключ через strcmp с константой.",
       "Что это значит?", "Ключ достаётся статическим анализом строк; проверку надо переносить на сервер",
       ["Защита надёжна, если бинарник обфусцирован", "Нужно заменить strcmp на memcmp", "Достаточно упаковать UPX"], {"app": ["агента", "десктоп-клиента", "плагина"]})

# задачи на код — одни и те же семейства у всех специализаций с «Алгоритмами»; выдаются отдельным слотом (irt.choose)
for _spec in code_items.SPECS:
    for _f in code_items.FAMILIES.values():
        FAMILIES.append({"family": _f["name"], "spec": _spec, "competency": code_items.COMPETENCY, "kind": "code", "a": _f["a"], "b": _f["b"],
                         "pilot": _f["pilot"], "render": lambda rng, name=_f["name"]: code_items.render(name, rng)})

# уникальные имена семейств для простых шаблонов
for i, f in enumerate(FAMILIES):
    if not f["family"]:
        f["family"] = f"{f['spec'].split()[0].lower()}_{i:03d}"


def generate_bank() -> list[dict]:
    """Все клоны всех семейств как словари полей Item. Детерминировано: сид = семейство + номер клона."""
    out = []
    for f in FAMILIES:
        n = CLONES_PILOT if f["pilot"] else CLONES.get(f["spec"], CLONES_DEFAULT)
        for i in range(n):
            rng = random.Random(f"{f['family']}:{i}")
            payload = f["render"](rng)
            payload["time_limit_s"] = TIME_LIMIT[f["kind"]]
            out.append({"family": f["family"], "spec": f["spec"], "competency": f["competency"], "kind": f["kind"],
                        "a": round(f["a"] * rng.uniform(0.95, 1.05), 3), "b": round(f["b"] + rng.uniform(-0.1, 0.1), 3),
                        "payload": payload, "pilot": f["pilot"]})
    return out


def seed_items(db: Session) -> int:
    """Засеять банк: добавить семейства, которых в нём ещё нет (пустой банк — целиком; на старом стенде — новые семейства,
    например задачи на код). Уже засеянные задания не трогаются: на них ссылаются ответы в сессиях. Возвращает число добавленных."""
    have = {tuple(r) for r in db.execute(select(Item.family, Item.spec).distinct())}
    bank = [row for row in generate_bank() if (row["family"], row["spec"]) not in have]
    db.add_all(Item(**row) for row in bank)
    db.commit()
    return len(bank)


# ============================== план теста под вакансию ==============================
# навык → компетенции, которые его проверяют (берутся те, что есть у специализации)
SKILL_COMP = {
    "PostgreSQL": ["Базы данных и транзакции", "SQL"], "MySQL": ["Базы данных и транзакции", "SQL"], "SQL": ["Базы данных и транзакции", "SQL"],
    "MongoDB": ["Базы данных и транзакции", "Моделирование данных"], "ClickHouse": ["Базы данных и транзакции", "SQL", "Моделирование данных"],
    "Redis": ["Базы данных и транзакции", "Проектирование API"],
    "Kafka": ["Конкурентность", "Пайплайны"], "RabbitMQ": ["Конкурентность"], "asyncio": ["Конкурентность"],
    "FastAPI": ["Проектирование API"], "Django": ["Проектирование API"], "gRPC": ["Проектирование API", "Сеть и офлайн"],
    "Kubernetes": ["Kubernetes", "Диагностика инцидентов", "MLOps", "План отката"], "Docker": ["CI/CD", "Kubernetes", "MLOps", "Диагностика инцидентов"],
    "Terraform": ["CI/CD", "План отката"], "Prometheus": ["Наблюдаемость", "Диагностика инцидентов"], "Linux": ["Сети", "Диагностика инцидентов"],
    "Python": ["Ревью кода", "Feature engineering", "Автотесты"], "Go": ["Ревью кода", "Конкурентность"], "Java": ["Ревью кода"], "Kotlin": ["Ревью кода", "Жизненный цикл приложения"],
    "C#": ["Ревью кода"], "Node.js": ["Ревью кода", "Проектирование API"], "TypeScript": ["Ревью кода", "Архитектура клиента"], "JavaScript": ["Ревью кода", "Отладка UI"],
    "React": ["Архитектура клиента", "Производительность"], "Vue": ["Архитектура клиента"], "Angular": ["Архитектура клиента"],
    "Swift": ["Ревью кода", "Жизненный цикл приложения"], "Flutter": ["Жизненный цикл приложения", "Производительность"],
    "Spark": ["Пайплайны", "Алгоритмы"], "Airflow": ["Пайплайны", "Качество данных"],
    "PyTorch": ["Валидация моделей", "MLOps"], "scikit-learn": ["Валидация моделей", "Feature engineering"], "LLM": ["Постановка задачи", "Валидация моделей"],
    "Computer Vision": ["Валидация моделей", "Feature engineering"], "Selenium": ["Автотесты", "Регресс"], "Pentest": ["Веб-уязвимости", "Реагирование"],
}
MUST_W, NICE_W, MAX_W = 0.25, 0.1, 1.5
SHARE_OF_LIMIT = 0.75  # ponytail: время ≈ 75 % лимита на сцену; заменить медианой реальных прохождений


def plan_for_need(spec: str, must: list[str], nice: list[str], grade: str) -> dict:
    """Как система собирает тест под вакансию: веса компетенций из навыков, сложность вокруг порога грейда, семейства банка.
    Веса уходят в QuestSession.focus и только сдвигают выбор заданий; грейд считается по всем компетенциям одинаково."""
    if spec not in catalog.COMPETENCIES:
        raise ValueError(f"Неизвестная специализация: {spec}")
    grade = grade if grade in catalog.GRADES else "Middle"
    names = catalog.COMPETENCIES[spec]
    w, why = {n: 1.0 for n in names}, {n: [] for n in names}
    for skills, add in ((must or [], MUST_W), (nice or [], NICE_W)):
        for sk in skills:
            for c in SKILL_COMP.get(sk, []):
                if c in w and sk not in why[c]:
                    w[c] = min(MAX_W, w[c] + add)
                    why[c].append(sk)
    c0 = irt.grade_anchor(grade)
    lo, hi = round(c0 - 1.0, 2), round(c0 + 1.0, 2)
    # задачи на код — только при включённой песочнице и одна на сессию (слот irt.CODE_AT)
    fams = [f for f in FAMILIES if f["spec"] == spec and not f["pilot"] and (f["kind"] != "code" or sandbox.enabled())]
    has_code = any(f["kind"] == "code" for f in fams)
    chosen = [f for f in fams if lo <= f["b"] <= hi] or sorted(fams, key=lambda f: abs(f["b"] - c0))[:6]
    chosen.sort(key=lambda f: (-w[f["competency"]], abs(f["b"] - c0)))
    families = []
    for f in chosen:
        sample = f["render"](random.Random(f"{f['family']}:preview"))  # отдельный сид: в банке такого клона нет
        families.append({"family": f["family"], "competency": f["competency"], "kind": f["kind"], "b": f["b"],
                         "scene_title": sample["scene_title"], "sample_prompt": f"{sample['story']} {sample['prompt']}"})
    plain = [f for f in chosen if f["kind"] != "code"]
    items_total = min(irt.MAX_ITEMS, sum(f["kind"] != "code" for f in fams) + has_code)
    avg_limit = (sum(TIME_LIMIT[f["kind"]] for f in plain) / max(len(plain), 1)) * (items_total - has_code) / max(items_total, 1) \
        + TIME_LIMIT["code"] * has_code / max(items_total, 1)
    return {
        "spec": spec, "grade": grade,
        "competencies": sorted(({"n": n, "weight": round(w[n], 2), "why": why[n]} for n in names), key=lambda c: -c["weight"]),
        "difficulty": {"b_from": lo, "b_to": hi},
        "families": families,
        "items_total": items_total,
        "minutes": round(items_total * avg_limit * SHARE_OF_LIMIT / 60),
        "focus": {n: round(w[n], 2) for n in names},
    }
