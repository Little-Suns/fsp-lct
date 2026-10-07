"""Backend: сложные семейства уровня Senior/Lead (b 2,4–2,9) — чтобы тест различал Senior и Lead, а θ не упиралась в потолок банка."""

from app.services.items import _choice, _log, family

# --- Проектирование API ---


@family("be_api_saga_unknown", "Backend", "Проектирование API", "choice", 2.3, 2.4)
def _(rng):
    order, psp = f"ord-{rng.randint(10000, 99999)}", rng.choice(["psp-gateway", "acquirer-api", "pay-provider"])
    key, m, wait = f"idem-{rng.randint(1000, 9999)}", rng.randint(10, 50), rng.choice([10, 15, 30])
    lines = [
        _log(f"11:{m:02d}:01", "order-saga", "INFO", f"{order}: step reserve_stock ok"),
        _log(f"11:{m:02d}:02", "order-saga", "INFO", f"{order}: step charge → {psp} (Idempotency-Key {key})"),
        _log(f"11:{m:02d}:{2 + wait:02d}", "order-saga", "ERROR", f"{order}: charge failed: ReadTimeout after {wait} s"),
        _log(f"11:{m:02d}:{2 + wait:02d}", "order-saga", "INFO", f"{order}: compensation scheduled: release_stock, mark_failed"),
    ]
    opts, key_i = _choice(rng, f"Исход неизвестен: шаг в pending, сверить статус у {psp} по тому же ключу и лишь потом продолжать или компенсировать", [
        f"Сразу компенсировать: снять резерв, пометить заказ failed и отправить refund в {psp} — возврат несуществующего списания безопасен, а клиент не ждёт",
        f"Повторить charge с новым Idempotency-Key, чтобы {psp} не вернул закешированный ответ, и компенсировать сагу целиком только после трёх неудачных попыток",
        f"Объединить reserve_stock и charge в одну распределённую транзакцию (2PC через XA) с {psp}, чтобы шаги фиксировались атомарно",
    ])
    return {"scene_title": "Сага и таймаут", "story": f"Шаг charge в саге заказа {order} упал по таймауту {wait} с. Оркестратор по умолчанию сразу запускает компенсацию.",
            "prompt": "Как правильно спроектировать обработку этого шага?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key_i}


# --- Ревью кода ---


@family("be_rv_cache_race", "Backend", "Ревью кода", "mark", 2.3, 2.55)
def _(rng):
    ent, tbl = rng.choice([("tariff", "tariffs"), ("merchant", "merchants"), ("limit", "limits"), ("product", "products")])
    ttl = rng.choice([600, 1800, 3600])
    lines = []
    if rng.random() < 0.5:
        lines.append("@trace")
    lines += [f"async def get_{ent}(id: int):", f'    row = await cache.get(f"{ent}:{{id}}")', "    if row is None:"]
    if rng.random() < 0.5:
        lines.append(f'        metrics.inc("{ent}_cache_miss")')
    lines.append(f'        row = await db.fetchrow("SELECT * FROM {tbl} WHERE id = $1", id)')
    lines.append(f'        await cache.set(f"{ent}:{{id}}", row, ttl={ttl})')
    key = len(lines)
    lines += ["    return row", "", "", f"async def update_{ent}(id: int, fields: dict):",
              f"    await db.execute(update_sql({tbl!r}, fields), id)", f'    await cache.delete(f"{ent}:{{id}}")']
    return {"scene_title": "Кэш помнит старое", "story": f"После обновления {ent} карточка иногда до {ttl // 60} минут показывает старое значение, хотя update удаляет ключ сразу после записи в БД. Чтений — тысячи в секунду.",
            "prompt": "Нажмите на строку, из-за которой в кэш возвращается устаревшее значение.",
            "panel": {"type": "code", "lang": "python", "lines": lines, "caption": f"PR #{rng.randint(700, 999)} · «кэш для {tbl}»"}, "key": key}


# --- Базы данных и транзакции ---


@family("be_db_outbox_gap", "Backend", "Базы данных и транзакции", "mark", 2.4, 2.7)
def _(rng):
    topic, n = rng.choice(["payments.events", "orders.events", "ledger.events", "refunds.events"]), rng.randint(3, 12) * 100
    batch = rng.choice([100, 500, 1000])
    lines = ["async def relay():"]
    if rng.random() < 0.5:
        lines.append(f"    log.info(\"outbox relay start\", topic=\"{topic}\")")
    lines += ['    last_id = await state.get("outbox_last_id") or 0', "    while True:", "        rows = await db.fetch("]
    lines.append(f'            "SELECT id, topic, payload FROM outbox WHERE id > $1 ORDER BY id LIMIT {batch}", last_id)')
    key = len(lines)
    lines += ["        for r in rows:", '            await kafka.send(r["topic"], r["payload"])', '            last_id = r["id"]',
              '        await state.set("outbox_last_id", last_id)', "        await asyncio.sleep(0.2)"]
    return {"scene_title": "Пропавшие события", "story": f"Outbox-релей {topic} изредка теряет события: строка в outbox есть, в Kafka её нет. Писатели вставляют в outbox в своих транзакциях, id — из sequence, около {n} вставок в секунду.",
            "prompt": "Нажмите на строку, из-за которой релей пропускает события.",
            "panel": {"type": "code", "lang": "python", "lines": lines}, "key": [key - 1, key]}


# --- Конкурентность ---


@family("be_cc_fencing", "Backend", "Конкурентность", "choice", 2.3, 2.8)
def _(rng):
    job, what = rng.choice([("settlement", "строк сверки"), ("payouts", "выплат"), ("billing-close", "счетов закрытия периода")])
    ttl = rng.choice([10, 15, 20, 30])
    pause = ttl + rng.randint(2, 9)
    w1, w2 = rng.sample(["worker-1", "worker-2", "worker-3"], 2)
    m = rng.randint(10, 50)
    lines = [
        _log(f"03:{m:02d}:00", w1, "INFO", f"lock {job}: acquired (SET NX PX {ttl * 1000})"),
        _log(f"03:{m:02d}:02", w1, "WARN", f"process paused {pause}.{rng.randint(1, 9)} s (stop-the-world GC)"),
        _log(f"03:{m:02d}:{ttl + 1:02d}", w2, "INFO", f"lock {job}: acquired (SET NX PX {ttl * 1000})"),
        _log(f"03:{m:02d}:{ttl + 2:02d}", w2, "INFO", f"{job}: batch written"),
        _log(f"03:{m:02d}:{pause + 3:02d}", w1, "INFO", f"{job}: batch written"),
        _log(f"03:{m:02d}:{pause + 4:02d}", "ledger-db", "ERROR", f"reconciliation: duplicate {what} for period {rng.randint(1, 12):02d}.2026"),
    ]
    opts, key = _choice(rng, "TTL-блокировка не спасает от паузы владельца: при захвате выдавать монотонный fencing-токен, а хранилище — отклонять запись со старым токеном", [
        "Перейти на Redlock: брать блокировку на большинстве из пяти независимых Redis — тогда второй воркер её не получит, пока первый жив и держит кворум узлов",
        f"Поднять TTL до {ttl * 6} с и продлевать блокировку фоновым потоком каждые {ttl // 3} с, пока задача работает",
        "Синхронизировать часы воркеров по NTP: истечение TTL считалось по разъехавшимся часам",
    ])
    return {"scene_title": "Два владельца", "story": f"Ночная задача {job} защищена распределённой блокировкой в Redis. Сегодня {what} записались дважды.",
            "prompt": "Что устранит причину?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Алгоритмы ---


@family("be_alg_quantile_merge", "Backend", "Алгоритмы", "choice", 2.2, 2.9)
def _(rng):
    svc, pods = rng.choice(["checkout-api", "payments-api", "orders-api", "search-api"]), rng.randint(6, 24)
    q, ql = rng.choice([(0.99, "p99"), (0.95, "p95"), (0.999, "p99.9")])
    shown, real = rng.randint(120, 220), rng.randint(700, 1400)
    lines = [f"# панель «{ql} {svc}», {pods} подов",
             "avg(",
             f"  histogram_quantile({q}, sum by (pod, le) (rate(http_request_duration_seconds_bucket{{svc=\"{svc}\"}}[5m])))",
             ")"]
    opts, key = _choice(rng, f"Квантили не усредняются: сложить бакеты всех подов (sum by (le)) и уже из суммы считать histogram_quantile({q})", [
        f"Взвесить {ql} подов по их RPS: средневзвешенный квантиль учитывает неравномерную нагрузку и даёт точный {ql} по сервису в целом",
        f"Брать максимум из {ql} подов: худший под и определяет хвост, это и есть {ql} сервиса",
        "Сузить окно rate с 5m до 1m: за 5 минут пики сглаживаются, отсюда заниженный квантиль",
    ])
    return {"scene_title": "Хвост не сходится", "story": f"Дашборд показывает {ql} = {shown} мс, а по трассам такой же доли самых медленных запросов — дольше {real} мс. Нагрузка между подами неравномерная.",
            "prompt": "Как считать квантиль по сервису?", "panel": {"type": "code", "lang": "promql", "lines": lines}, "options": opts, "key": key}
