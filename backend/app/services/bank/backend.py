"""Backend: сложные семейства уровня Senior/Lead (b 2,4–2,9) — чтобы тест различал Senior и Lead, а θ не упиралась в потолок банка.
У каждого семейства три варианта механики (items._variant), правильные ответы других вариантов — среди дистракторов."""

from app.services.items import _log, _options, _variant, family

# --- Проектирование API ---


@family("be_api_saga_unknown", "Backend", "Проектирование API", "choice", 2.3, 2.4)
def _(rng):
    order, psp = f"ord-{rng.randint(10000, 99999)}", rng.choice(["psp-gateway", "acquirer-api", "pay-provider"])
    key, m, wait = f"idem-{rng.randint(1000, 9999)}", rng.randint(10, 50), rng.choice([10, 15, 30])
    t = lambda s: f"11:{m:02d}:{s:02d}"  # noqa: E731
    v = _variant(rng, 3)
    if v == 0:
        story = f"Шаг charge в саге заказа {order} упал по таймауту {wait} с. Оркестратор по умолчанию сразу запускает компенсацию."
        lines = [_log(t(1), "order-saga", "INFO", f"{order}: step reserve_stock ok"),
                 _log(t(2), "order-saga", "INFO", f"{order}: step charge → {psp} (Idempotency-Key {key})"),
                 _log(t(2 + wait), "order-saga", "ERROR", f"{order}: charge failed: ReadTimeout after {wait} s"),
                 _log(t(2 + wait), "order-saga", "INFO", f"{order}: compensation scheduled: release_stock, mark_failed")]
    elif v == 1:
        story = f"Банк отклонил charge в саге заказа {order}, оркестратор запустил компенсацию, но склад ответил 503. Сага помечена failed, товар так и висит в резерве."
        lines = [_log(t(1), "order-saga", "INFO", f"{order}: step reserve_stock ok"),
                 _log(t(2), "order-saga", "ERROR", f"{order}: charge declined by {psp}: insufficient_funds"),
                 _log(t(3), "order-saga", "INFO", f"{order}: compensation: release_stock"),
                 _log(t(4), "order-saga", "ERROR", f"{order}: release_stock failed: warehouse-api 503"),
                 _log(t(4), "order-saga", "INFO", f"{order}: saga state = failed")]
    else:
        story = f"Клиент получил письмо «Заказ {order} передан в доставку», а оплата после этого не прошла. Отменить отгрузку уже нельзя."
        lines = [_log(t(1), "order-saga", "INFO", f"{order}: step reserve_stock ok"),
                 _log(t(2), "order-saga", "INFO", f"{order}: step ship ok (courier assigned)"),
                 _log(t(3), "order-saga", "INFO", f"{order}: step notify_customer ok"),
                 _log(t(5), "order-saga", "ERROR", f"{order}: charge declined by {psp}: card_expired"),
                 _log(t(5), "order-saga", "WARN", f"{order}: compensation for ship: not compensable")]
    opts, key_i = _options(rng, [f"Исход неизвестен: шаг в pending, сверить статус у {psp} по тому же ключу и лишь потом продолжать или компенсировать",
                                 "Компенсацию повторять с бэкоффом до успеха: она идемпотентна, а сага остаётся «компенсируется», а не failed",
                                 "Переставить шаги: необратимые (отгрузка, письмо клиенту) — только после шагов, которые могут не пройти, включая charge"], v,
                           [f"Сразу компенсировать: снять резерв, пометить заказ failed и отправить refund в {psp} — возврат несуществующего списания безопасен, а клиент не ждёт",
                            f"Объединить reserve_stock и charge в одну распределённую транзакцию (2PC через XA) с {psp}, чтобы шаги фиксировались атомарно"])
    return {"scene_title": "Сага заказа", "story": story, "prompt": "Как правильно спроектировать сагу?",
            "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key_i}


# --- Ревью кода ---


@family("be_rv_cache_race", "Backend", "Ревью кода", "mark", 2.3, 2.55)
def _(rng):
    ent, tbl = rng.choice([("tariff", "tariffs"), ("merchant", "merchants"), ("limit", "limits"), ("product", "products")])
    ttl = rng.choice([600, 1800, 3600])
    v = _variant(rng, 3)
    lines = []
    if v == 1:
        lines += [f"_local = TTLCache(maxsize=10_000, ttl={ttl})", "", ""]
    if rng.random() < 0.5:
        lines.append("@trace")
    lines.append(f"async def get_{ent}(id: int):")
    if v == 1:
        lines += ["    if id in _local:", "        return _local[id]"]
        key = [len(lines) - 1, len(lines)]
    lines += [f'    row = await cache.get(f"{ent}:{{id}}")', "    if row is None:"]
    if rng.random() < 0.5:
        lines.append(f'        metrics.inc("{ent}_cache_miss")')
    src = "replica" if v == 2 else "db"
    lines.append(f'        row = await {src}.fetchrow("SELECT * FROM {tbl} WHERE id = $1", id)')
    if v == 2:
        key = len(lines)
    lines.append(f'        await cache.set(f"{ent}:{{id}}", row, ttl={ttl if v != 1 else 60})')
    if v == 0:
        key = len(lines)
    if v == 1:
        lines.append("    _local[id] = row")
    lines += ["    return row", "", "", f"async def update_{ent}(id: int, fields: dict):",
              f"    await db.execute(update_sql({tbl!r}, fields), id)", f'    await cache.delete(f"{ent}:{{id}}")']
    story = [f"После обновления {ent} карточка иногда до {ttl // 60} минут показывает старое значение, хотя update удаляет ключ сразу после записи в БД. Чтений — тысячи в секунду.",
             f"После обновления {ent} часть подов до {ttl // 60} минут показывает старое значение, другие — новое. Redis-ключ update удаляет сразу после записи в БД.",
             f"После обновления {ent} карточка почти каждый раз до {ttl // 60} минут показывает старое значение. Чтения при промахе идут с асинхронной реплики, её лаг — до секунды."][v]
    return {"scene_title": "Кэш помнит старое", "story": story, "prompt": "Нажмите на строку, из-за которой пользователи видят устаревшее значение.",
            "panel": {"type": "code", "lang": "python", "lines": lines, "caption": f"PR #{rng.randint(700, 999)} · «кэш для {tbl}»"}, "key": key}


# --- Базы данных и транзакции ---


@family("be_db_outbox_gap", "Backend", "Базы данных и транзакции", "mark", 2.4, 2.7)
def _(rng):
    topic, n = rng.choice(["payments.events", "orders.events", "ledger.events", "refunds.events"]), rng.randint(3, 12) * 100
    batch = rng.choice([100, 500, 1000])
    v = _variant(rng, 3)
    lines = []
    if v == 2:
        lines += ["producer = AIOKafkaProducer(bootstrap_servers=BROKERS, acks=0)"]
        key = len(lines)
        lines += ["", ""]
    lines.append("async def relay():")
    if rng.random() < 0.5:
        lines.append(f"    log.info(\"outbox relay start\", topic=\"{topic}\")")
    if v == 0:
        lines += ['    last_id = await state.get("outbox_last_id") or 0', "    while True:", "        rows = await db.fetch("]
        lines.append(f'            "SELECT id, topic, payload FROM outbox WHERE id > $1 ORDER BY id LIMIT {batch}", last_id)')
        key = [len(lines) - 1, len(lines)]
        lines += ["        for r in rows:", '            await kafka.send(r["topic"], r["payload"])', '            last_id = r["id"]',
                  '        await state.set("outbox_last_id", last_id)', "        await asyncio.sleep(0.2)"]
        story = f"Outbox-релей {topic} изредка теряет события: строка в outbox есть, в Kafka её нет. Писатели вставляют в outbox в своих транзакциях, id — из sequence, около {n} вставок в секунду."
        prompt = "Нажмите на строку, из-за которой релей пропускает события."
    else:
        send = '            await kafka.send(r["topic"], r["payload"])' if v == 1 else '            await producer.send_and_wait(r["topic"], r["payload"], key=r["aggregate_id"])'
        lines += ["    while True:", "        rows = await db.fetch(", f'            "SELECT id, topic, payload, aggregate_id FROM outbox ORDER BY id LIMIT {batch}")',
                  "        for r in rows:", send]
        if v == 1:
            key = len(lines)
        lines += ['        await db.execute("DELETE FROM outbox WHERE id = ANY($1)", [r["id"] for r in rows])', "        await asyncio.sleep(0.2)"]
        if v == 1:
            story = f"Консьюмеры {topic} (по одному на партицию) иногда получают события одного заказа не по порядку: «оплачен» раньше «создан». Релей один, в outbox порядок верный."
            prompt = "Нажмите на строку, из-за которой нарушается порядок событий."
        else:
            story = f"После перезапуска брокера Kafka часть событий {topic} пропала: релей их отправил и удалил из outbox, а в топике их нет."
            prompt = "Нажмите на строку, из-за которой релей теряет события."
    return {"scene_title": "Outbox-релей", "story": story, "prompt": prompt, "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


# --- Конкурентность ---


@family("be_cc_fencing", "Backend", "Конкурентность", "choice", 2.3, 2.8)
def _(rng):
    job, what = rng.choice([("settlement", "строк сверки"), ("payouts", "выплат"), ("billing-close", "счетов закрытия периода")])
    ttl = rng.choice([10, 15, 20, 30])
    pause = ttl + rng.randint(2, 9)
    w1, w2, w3 = rng.sample(["worker-1", "worker-2", "worker-3"], 3)
    m = rng.randint(10, 50)
    t = lambda s: f"03:{m:02d}:{s:02d}"  # noqa: E731
    dup = _log(t(pause + 4), "ledger-db", "ERROR", f"reconciliation: duplicate {what} for period {rng.randint(1, 12):02d}.2026")
    v = _variant(rng, 3)
    if v == 0:
        lines = [_log(t(0), w1, "INFO", f"lock {job}: acquired (SET NX PX {ttl * 1000})"),
                 _log(t(2), w1, "WARN", f"process paused {pause}.{rng.randint(1, 9)} s (stop-the-world GC)"),
                 _log(t(ttl + 1), w2, "INFO", f"lock {job}: acquired (SET NX PX {ttl * 1000})"),
                 _log(t(ttl + 2), w2, "INFO", f"{job}: batch written"),
                 _log(t(pause + 3), w1, "INFO", f"{job}: batch written"), dup]
    elif v == 1:
        lines = [_log(t(0), w1, "INFO", f"lock {job}: acquired (SET NX PX {ttl * 1000})"),
                 _log(t(ttl - 3), w1, "INFO", f"{job}: batch written, waiting for audit-log"),
                 _log(t(ttl + 1), w2, "INFO", f"lock {job}: acquired (SET NX PX {ttl * 1000})"),
                 _log(t(ttl + 2), w1, "INFO", f"{job}: done, lock released (DEL lock:{job})"),
                 _log(t(ttl + 3), w3, "INFO", f"lock {job}: acquired (SET NX PX {ttl * 1000})"),
                 _log(t(pause + 2), w2, "INFO", f"{job}: batch written"),
                 _log(t(pause + 3), w3, "INFO", f"{job}: batch written"), dup]
    else:
        lines = [_log(t(0), w1, "INFO", f"TZ=Europe/Moscow, period 2026-10-05; lock {job}:2026-10-05: acquired (SET NX PX {ttl * 1000})"),
                 _log(t(0), w2, "INFO", f"TZ=UTC, period 2026-10-04; lock {job}:2026-10-04: acquired (SET NX PX {ttl * 1000})"),
                 _log(t(ttl - 4), w1, "INFO", f"{job}: batch written"),
                 _log(t(ttl - 3), w2, "INFO", f"{job}: batch written"), dup]
    opts, key = _options(rng, ["TTL-блокировка не спасает от паузы владельца: при захвате выдавать монотонный fencing-токен, а хранилище — отклонять запись со старым токеном",
                               "Снимать блокировку только своим значением: сравнить и удалить атомарно (Lua-скрипт), а не голым DEL по имени ключа",
                               "Ключ блокировки зависит от локальной даты воркера: период считать в одной зоне (UTC), иначе воркеры берут разные блокировки"], v,
                         ["Перейти на Redlock: брать блокировку на большинстве из пяти независимых Redis — тогда второй воркер её не получит, пока первый жив и держит кворум узлов",
                          f"Поднять TTL до {ttl * 6} с и продлевать блокировку фоновым потоком каждые {ttl // 3} с, пока задача работает",
                          "Синхронизировать часы воркеров по NTP: истечение TTL считалось по разъехавшимся часам"])
    return {"scene_title": "Два владельца", "story": f"Ночная задача {job} защищена распределённой блокировкой в Redis. Сегодня {what} записались дважды.",
            "prompt": "Что устранит причину?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Алгоритмы ---


@family("be_alg_quantile_merge", "Backend", "Алгоритмы", "choice", 2.2, 2.9)
def _(rng):
    svc, pods = rng.choice(["checkout-api", "payments-api", "orders-api", "search-api"]), rng.randint(6, 24)
    q, ql = rng.choice([(0.99, "p99"), (0.95, "p95"), (0.999, "p99.9")])
    shown, real = rng.randint(120, 220), rng.randint(700, 1400)
    metric = f'http_request_duration_seconds_bucket{{svc="{svc}"}}'
    v = _variant(rng, 3)
    if v == 0:
        lines = [f"# панель «{ql} {svc}», {pods} подов", "avg(", f"  histogram_quantile({q}, sum by (pod, le) (rate({metric}[5m])))", ")"]
        story = f"Дашборд показывает {ql} = {shown} мс, а по трассам такой же доли самых медленных запросов — дольше {real} мс. Нагрузка между подами неравномерная."
    elif v == 1:
        lines = [f"# панель «{ql} {svc}», {pods} подов; бакеты le: 0.05, 0.1, 0.5, 5, +Inf", f"histogram_quantile({q}, sum by (le) (rate({metric}[5m])))"]
        sec = f"{rng.randint(38, 46) / 10:.1f}".replace(".", ",")
        story = f"Дашборд показывает {ql} = {sec} с, а по трассам такая же доля самых медленных запросов укладывается в {real} мс."
    else:
        lines = [f"# панель «запросов за час, {svc}», {pods} подов", f'sum(http_requests_total{{svc="{svc}"}})', f'  - sum(http_requests_total{{svc="{svc}"}} offset 1h)']
        story = "Панель «запросов за час» после каждой выкладки на какое-то время показывает провал, иногда уходит в минус."
    opts, key = _options(rng, [f"Квантили не усредняются: сложить бакеты всех подов (sum by (le)) и уже из суммы считать histogram_quantile({q})",
                               "Добавить границы бакетов между 0,5 и 5 с: внутри широкого бакета квантиль — линейная интерполяция, отсюда завышение",
                               "Считать sum(increase(http_requests_total[1h])): increase по каждому ряду учитывает сброс счётчика при рестарте пода"], v,
                         [f"Взвесить {ql} подов по их RPS: средневзвешенный квантиль учитывает неравномерную нагрузку и даёт точный {ql} по сервису в целом",
                          f"Брать максимум из {ql} подов: худший под и определяет хвост, это и есть {ql} сервиса",
                          "Сузить окно rate с 5m до 1m: за 5 минут пики сглаживаются, отсюда искажённая картина"])
    return {"scene_title": "Метрики не сходятся", "story": story, "prompt": "Как исправить расчёт?", "panel": {"type": "code", "lang": "promql", "lines": lines}, "options": opts, "key": key}
