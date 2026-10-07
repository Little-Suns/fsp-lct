"""Data Eng / Analytics, сюжет «Квартальный отчёт»: сценарные семейства с SQL, логами Airflow/dbt/Spark и графиками витрин."""

from app.services.items import _choice, _log, family

SPEC = "Data Eng / Analytics"

# --- SQL ---


@family("dea_sql_fanout", SPEC, "SQL", "mark", 2.2, 0.1)
def _(rng):
    col = rng.choice(["region", "channel", "segment"])
    child = rng.choice(["order_items", "order_lines", "shipments"])
    k = rng.choice([2, 3, 4])
    lines = []
    if rng.random() < 0.5:
        lines.append(f"-- выручка по {col} за Q{rng.randint(1, 4)}")
    lines += [f"SELECT c.{col},", "       SUM(o.amount) AS revenue", "FROM orders o"]
    joins = ["JOIN customers c ON c.id = o.customer_id", f"JOIN {child} i ON i.order_id = o.id"]
    rng.shuffle(joins)
    lines += joins
    key = len(lines) - 1 if joins[0].startswith(f"JOIN {child}") else len(lines)
    lines += [f"WHERE o.created_at >= '2026-{rng.choice([1, 4, 7]):02d}-01'", "  AND i.status <> 'cancelled'", f"GROUP BY c.{col};"]
    return {"scene_title": "Выручка не сходится", "story": f"Выручка по {col} в квартальном отчёте примерно в {k} раза выше, чем в финансовой системе. Фильтр по отменённым позициям добавили на прошлой неделе.",
            "prompt": "Нажмите на строку, из-за которой выручка завышена.", "panel": {"type": "code", "lang": "sql", "lines": lines}, "key": key}


@family("dea_sql_not_in", SPEC, "SQL", "choice", 2.2, 1.1)
def _(rng):
    tbl, col, what = rng.choice([("orders", "customer_id", "заказов"), ("payments", "card_id", "платежей"), ("sessions", "user_id", "сессий")])
    black = rng.choice(["stop_list", "blocked_accounts", "fraud_marks"])
    n = rng.randint(120, 900)
    lines = ["SELECT count(*)", f"FROM {tbl} t", f"WHERE t.created_at >= '2026-0{rng.choice([1, 4, 7])}-01'",
             f"  AND t.{col} NOT IN (SELECT {col} FROM {black});"]
    opts, key = _choice(rng, f"В {black} есть NULL в {col}: с NULL условие NOT IN не бывает истинным; нужен NOT EXISTS", [
        "NOT IN с подзапросом больше 1000 строк планировщик заменяет пустым списком: стоп-лист нужно разбить на части и объединить через UNION",
        "count(*) пропускает строки, где есть NULL; нужно считать count(t.id)",
        "Подзапрос выполняется на каждую строку и обрывается по таймауту, поэтому вернулся 0",
    ])
    return {"scene_title": "Ноль вместо тысяч", "story": f"Нужно число {what} за квартал без клиентов из стоп-листа {black}, который собирают из CRM и ручных выгрузок. Запрос вернул 0, хотя {what} за квартал — около {n} тыс.",
            "prompt": "Почему так?", "panel": {"type": "code", "lang": "sql", "lines": lines}, "options": opts, "key": key}


@family("dea_sql_ch_replacing", SPEC, "SQL", "choice", 2.3, 2.0)
def _(rng):
    tbl, idc, thing = rng.choice([("orders_cdc", "order_id", "заказа"), ("payments_cdc", "payment_id", "платежа"), ("contracts_cdc", "contract_id", "договора")])
    p, h = rng.randint(4, 18), rng.choice([2, 3, 5])
    lines = [f"CREATE TABLE {tbl} (", f"    {idc} UInt64,", "    status String,", "    amount Decimal(18, 2),", "    updated_at DateTime",
             ") ENGINE = ReplacingMergeTree(updated_at)", f"ORDER BY {idc};", "", f"SELECT count(), sum(amount) FROM {tbl};"]
    opts, key = _choice(rng, "Версии схлопываются только при фоновых слияниях частей: читать с FINAL или брать argMax(amount, updated_at) по ключу", [
        "ReplacingMergeTree схлопывает дубли уже при вставке, значит CDC присылает каждую версию записи с новым id — проверять ключи в источнике",
        "Decimal(18, 2) округляет суммы при вставке, и ошибка копится: перейти на Float64",
        "Без PARTITION BY по дате движок вообще не дедуплицирует строки: добавить партиционирование",
    ])
    return {"scene_title": "Сумма гуляет", "story": f"CDC пишет в ClickHouse каждое изменение {thing}. Сразу после загрузки сумма в отчёте на {p} % выше, чем в источнике, а через {h} ч расхождение почти исчезает само.",
            "prompt": "В чём причина и как читать правильно?", "panel": {"type": "code", "lang": "sql", "lines": lines}, "options": opts, "key": key}


# --- Моделирование данных ---


@family("dea_mod_star", SPEC, "Моделирование данных", "choice", 2.0, -1.3)
def _(rng):
    attr, ent, dim, k = rng.choice([("категорию товара", "товара", "dim_product", "product_key"), ("город магазина", "магазина", "dim_store", "store_key"),
                                    ("отрасль клиента", "клиента", "dim_customer", "customer_key")])
    fact = rng.choice(["fact_sales", "fact_orders", "fact_receipts"])
    opts, key = _choice(rng, f"В измерение {dim}, а в {fact} оставить ключ {k} и меры", [
        f"Текстом в каждую строку {fact}: отчёт обойдётся без JOIN",
        f"В отдельную таблицу фактов для каждого {ent}, связанную с {fact} по дате: тогда атрибут не раздует строки измерения {dim}",
        f"В JSON-поле {fact}, чтобы не менять схему {dim}",
    ])
    return {"scene_title": "Новый атрибут", "story": f"Строите звезду для квартального отчёта: факт {fact} и измерения. Аналитик просит добавить {attr} — атрибут {ent}, который меняется редко.",
            "prompt": "Куда положить атрибут?", "panel": None, "options": opts, "key": key}


@family("dea_mod_semi_additive", SPEC, "Моделирование данных", "choice", 2.1, 1.2)
def _(rng):
    what, tbl, col, unit = rng.choice([("остатков на складах", "fact_stock_daily", "qty_on_hand", "млн штук"),
                                       ("остатков на счетах клиентов", "fact_balance_daily", "balance", "млрд ₽"),
                                       ("активных подписок", "fact_subscriptions_daily", "active_cnt", "тыс. подписок")])
    real = rng.randint(3, 9)
    month, days = rng.choice([("июль", 31), ("сентябрь", 30), ("ноябрь", 30)])
    shown = real * days + rng.randint(-3, 3)
    lines = ["SELECT date_trunc('month', snapshot_date) AS month,", f"       SUM({col}) AS total", f"FROM {tbl}", "GROUP BY 1", "ORDER BY 1;"]
    opts, key = _choice(rng, "Это полуаддитивная мера: по объектам её складывают, по дням — нет; брать значение на конец месяца или среднее", [
        "date_trunc считает месяц в UTC, поэтому дни на стыке месяцев попадают в соседний и сумма раздувается: перевести даты в местное время",
        f"В снимке {tbl} дубли строк по объектам: нужен DISTINCT перед SUM",
        "Измерение объектов должно быть SCD Type 2, иначе история снимков теряется",
    ])
    return {"scene_title": "Остаток ×30", "story": f"{tbl} — ежедневный снимок {what}. За {month} отчёт показывает {shown} {unit}, хотя на конец месяца реально около {real} {unit}.",
            "prompt": "В чём ошибка?", "panel": {"type": "code", "lang": "sql", "lines": lines}, "options": opts, "key": key}


@family("dea_mod_scd_between", SPEC, "Моделирование данных", "mark", 2.3, 2.1)
def _(rng):
    ent, attr = rng.choice([("customer", "manager"), ("dealer", "region_manager"), ("partner", "account_manager")])
    lines = []
    if rng.random() < 0.5:
        lines.append("-- продажи по менеджерам, квартальный отчёт")
    lines.append("SELECT f.order_id,")
    if rng.random() < 0.5:
        lines.append("       f.sale_date,")
    lines += ["       f.amount,", f"       d.{attr}", "FROM fact_sales f", f"JOIN dim_{ent}_scd d", f"  ON d.{ent}_id = f.{ent}_id",
              " AND f.sale_date BETWEEN d.valid_from AND d.valid_to"]
    key = len(lines)
    lines.append(f"WHERE f.sale_date >= '2026-0{rng.choice([1, 4, 7])}-01';")
    return {"scene_title": "Двойные продажи", "story": f"dim_{ent}_scd — измерение SCD Type 2; загрузка пишет valid_to старой версии равным valid_from новой. Продажи в отчёте задваиваются, но только в отдельные дни.",
            "prompt": "Нажмите на строку, из-за которой продажи задваиваются.", "panel": {"type": "code", "lang": "sql", "lines": lines}, "key": key}


@family("dea_mod_late_member", SPEC, "Моделирование данных", "choice", 2.3, 2.6)
def _(rng):
    fact, many, sale = rng.choice([("fact_orders", "заказы", "заказа"), ("fact_sales", "продажи", "продажи"), ("fact_policies", "полисы", "оформления полиса")])
    channel = rng.choice(["партнёрского канала", "маркетплейса", "B2B-портала"])
    rows, lag, share = rng.randint(2, 8), rng.randint(1, 3), rng.randint(3, 9)
    opts, key = _choice(rng, "Заводить в измерении предполагаемую запись по натуральному ключу, а когда клиент придёт из CRM, дописать её атрибуты", [
        f"Оставить -1, но каждую ночь перегружать {fact} целиком за всю историю, чтобы старые {many} подхватили клиентов, появившихся в CRM",
        f"Держать такие {many} в staging, пока клиент не появится в CRM, и только тогда загружать их в факт",
        "Хранить в факте натуральный id клиента и при запросе брать атрибуты из текущей версии измерения",
    ])
    return {"scene_title": "Неизвестный клиент", "story": f"{fact} ({rows} млрд строк) ссылается на dim_customer — SCD Type 2: отчёты показывают сегмент клиента на дату {sale}. "
            f"Клиенты {channel} приходят из CRM на {lag} дн. позже первых записей; такие {many} получают customer_key = -1 («неизвестный») и так и остаются — их уже {share} %. Выручку финансы смотрят в тот же день.",
            "prompt": "Как правильно загружать такие заказы?", "panel": None, "options": opts, "key": key}


# --- Пайплайны ---


@family("dea_pipe_sensor", SPEC, "Пайплайны", "choice", 2.1, -1.4)
def _(rng):
    src = rng.choice(["sales", "returns", "payments"])
    day = rng.randint(10, 29)
    late = rng.randint(4, 25)
    lines = [
        _log("03:00:01", "scheduler", "INFO", f"DAG {src}_daily: run scheduled__2026-09-{day:02d} started"),
        _log("03:00:04", f"load_{src}", "ERROR", f"FileNotFoundError: s3://raw/{src}/2026-09-{day:02d}.csv"),
        _log("03:00:05", "scheduler", "INFO", f"task load_{src} failed, retries=0"),
        _log(f"03:{late:02d}:40", "s3-events", "INFO", f"object created raw/{src}/2026-09-{day:02d}.csv ({rng.randint(80, 400)} MB)"),
    ]
    opts, key = _choice(rng, "Выгрузка приходит позже запуска по расписанию: ждать появления файла сенсором или запускать по событию", [
        "У задачи нет прав на чтение бакета: выдать роль на s3://raw",
        "Файл иногда приходит битым или неполным: добавить проверку схемы и числа строк перед загрузкой, а упавшие запуски повторять",
        "Включить catchup, чтобы Airflow сам догнал упавший запуск",
    ])
    return {"scene_title": "Утренний перезапуск", "story": f"Ночная загрузка {src} падает примерно раз в неделю. Утром её перезапускают руками — и она проходит.",
            "prompt": "В чём причина?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("dea_pipe_catchup", SPEC, "Пайплайны", "choice", 2.2, 0.9)
def _(rng):
    dag = rng.choice(["crm_snapshot", "ads_costs", "erp_invoices"])
    year = rng.choice([2024, 2025])
    total = (2026 - year) * 365 + rng.randint(200, 270)
    lines = [
        _log("09:14:02", "scheduler", "INFO", f"DAG {dag} added, schedule=@daily, start_date={year}-01-01"),
        _log("09:14:03", "scheduler", "INFO", f"Created DagRun scheduled__{year}-01-01T00:00:00"),
        _log("09:14:03", "scheduler", "INFO", f"Created DagRun scheduled__{year}-01-02T00:00:00"),
        _log("09:14:04", "scheduler", "INFO", f"DagRuns queued for {dag}: {total}"),
        _log("09:14:30", "pg-replica", "WARN", f"{rng.randint(40, 90)} active queries from airflow_etl, connections near limit"),
    ]
    opts, key = _choice(rng, "Включён catchup: Airflow ставит запуск на каждый день с start_date; выключить catchup, историю — отдельным backfill", [
        "Расписание @daily из-за часового пояса читается как «каждую минуту»",
        "Завис scheduler и дублирует запуски: перезапустить его, очистить очередь DagRun и выставить max_active_runs=1 для всех DAG",
        "У DAG нет retries, и каждая ошибка порождает новый DagRun",
    ])
    return {"scene_title": "Сотни запусков", "story": f"Новый DAG {dag} выкатили утром. Через минуту воркеры забиты, а реплика базы-источника захлёбывается запросами.",
            "prompt": "Что произошло и как исправить?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("dea_pipe_skew", SPEC, "Пайплайны", "choice", 2.4, 1.9)
def _(rng):
    mart = rng.choice(["mart_orders", "mart_gmv", "mart_sellers"])
    stage, slow, gb = rng.randint(8, 30), rng.randint(5, 199), round(rng.uniform(22, 48), 1)
    mins = rng.randint(35, 80)
    lines = [
        _log("02:41:10", "spark", "INFO", f"stage {stage} (join at build_{mart}.py:{rng.randint(60, 140)}): 199/200 tasks finished, median 18 s"),
        _log("02:41:10", "spark", "INFO", f"task {slow} RUNNING {mins} min, shuffle read {gb} GB, records {rng.randint(300, 600)} 000 000"),
        _log("02:41:11", "spark", "INFO", f"task {(slow + 7) % 200} SUCCESS 17 s, shuffle read {rng.randint(120, 200)} MB"),
        _log("02:41:15", f"executor-{rng.randint(1, 12)}", "WARN", f"spilling {round(gb / 3, 1)} GB to disk"),
    ]
    opts, key = _choice(rng, "Перекос по ключу соединения: горячий ключ попал в одну задачу; солить ключ или включить AQE skew join", [
        "Поднять spark.sql.shuffle.partitions до 2000: задачи станут мельче, и долгая задача разобьётся на сотню быстрых параллельных",
        f"Добавить executors: задача {slow} ждёт свободных ядер в очереди",
        "Закэшировать обе таблицы через .cache() перед соединением",
    ])
    return {"scene_title": "Одна задача из 200", "story": f"Сборка витрины {mart} на Spark шла 20 минут, после подключения крупного маркетплейса — больше двух часов.",
            "prompt": "Что происходит и как исправить?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("dea_pipe_late_watermark", SPEC, "Пайплайны", "mark", 2.3, 2.75)
def _(rng):
    mart, src = rng.choice([("mart_app_events", "raw.app_events"), ("mart_checkout_events", "raw.checkout_events"), ("mart_game_events", "raw.game_events")])
    lag, gap = rng.randint(6, 30), f"{rng.uniform(1.2, 3.5):.1f}".replace(".", ",")
    lines = [f"INSERT INTO {mart} (event_id, user_id, event_ts, event_type, country)", "SELECT e.event_id, e.user_id, e.event_ts, e.event_type, u.country",
             f"FROM {src} e", "LEFT JOIN dim_users u ON u.user_id = e.user_id", f"WHERE e.event_ts > (SELECT coalesce(max(event_ts), '1970-01-01') FROM {mart})"]
    key = len(lines)
    if rng.random() < 0.5:
        lines.append("  AND e.event_type <> 'heartbeat'")
    lines.append("ON CONFLICT (event_id) DO NOTHING;")
    return {"scene_title": "Недостача за прошлые дни", "story": f"Загрузка {mart} идёт каждый час. Мобильные клиенты копят события офлайн и досылают их до {lag} ч позже; event_ts — время на устройстве. "
            f"За прошлые дни в витрине на {gap} % меньше событий, чем в {src}, и разница со временем не уходит; пересборка с нуля сходится с источником.",
            "prompt": "Нажмите на строку, из-за которой витрина теряет события.", "panel": {"type": "code", "lang": "sql", "lines": lines}, "key": key}


# --- Качество данных ---


@family("dea_dq_null_share", SPEC, "Качество данных", "choice", 2.1, -1.0)
def _(rng):
    field = rng.choice(["region", "city", "utm_source"])
    rel, d0 = rng.randint(3, 5), rng.randint(1, 20)
    x = [f"{d0 + i:02d}.09" for i in range(8)]
    rows = [rng.randint(410, 440) for _ in range(8)]
    nulls = [rng.randint(1, 3) if i < rel else rng.randint(31, 44) for i in range(8)]
    ver = f"v{rng.randint(3, 6)}.{rng.randint(10, 40)}"
    panel = {"type": "chart", "x": x, "marker": {"i": rel, "label": f"релиз приложения {ver}"}, "series": [
        {"name": "строк в витрине за день, тыс.", "axis": "left", "max": 500, "data": rows},
        {"name": f"доля пустых {field}, %", "axis": "right", "max": 50, "data": nulls},
    ]}
    opts, key = _choice(rng, f"Релиз источника перестал заполнять {field}: проверять долю пустых и чинить в источнике", [
        f"Загрузка теряет строки после релиза: пустые {field} — это заказы, для которых не нашлась пара при JOIN со справочником",
        "Витрина задвоилась после перезапуска загрузки",
        "Это сезонность конца квартала, через неделю всё вернётся",
    ])
    return {"scene_title": "«Не указано»", "story": f"В отчёте по {field} внезапно выросла доля «не указано». Есть графики витрины за восемь дней.",
            "prompt": "Что произошло?", "panel": panel, "options": opts, "key": key}


@family("dea_dq_freshness", SPEC, "Качество данных", "choice", 2.3, 1.3)
def _(rng):
    mart, dash = rng.choice([("fct_orders", "Продажи за день"), ("fct_payments", "Платежи"), ("fct_shipments", "Отгрузки")])
    day = rng.randint(5, 28)
    lines = [
        _log("06:00:05", "dbt", "WARN", f"source raw.{mart[4:]}: max(loaded_at) = 2026-09-{day - 2:02d} 23:58"),
        _log("06:00:30", "dbt", "INFO", f"OK created incremental model {mart} [INSERT 0 0 in {rng.uniform(1.5, 4.5):.1f}s]"),
        _log("06:01:40", "dbt", "INFO", f"1 of 3 PASS not_null_{mart}_id"),
        _log("06:01:41", "dbt", "INFO", f"2 of 3 PASS unique_{mart}_id"),
        _log("06:01:41", "dbt", "INFO", f"3 of 3 PASS accepted_values_{mart}_status"),
        _log("06:01:50", "bi", "INFO", f"dashboard «{dash}» refreshed"),
    ]
    opts, key = _choice(rng, "Источник не обновлялся двое суток, а тесты проверяют только строки: нужна проверка свежести перед публикацией", [
        "BI отдал закэшированный дашборд: сбросить кэш и обновить ещё раз",
        "Инкрементальная модель отбросила новые строки из-за неверного unique_key: пересобрать её с --full-refresh и добавить тест на число строк",
        "Отчёт строится в UTC, и вчерашние продажи попали в сегодняшний день",
    ])
    return {"scene_title": "Зелёные тесты", "story": f"Все проверки {mart} зелёные, дашборд «{dash}» обновился в 06:01. Финансы пишут: продаж за вчера в отчёте нет.",
            "prompt": "В чём причина?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("dea_dq_nondet", SPEC, "Качество данных", "mark", 2.3, 2.3)
def _(rng):
    mart, idc, measure = rng.choice([("mart_orders", "order_id", "выручки"), ("mart_loans", "loan_id", "выдач"), ("mart_tickets", "ticket_id", "возвратов")])
    lines = []
    if rng.random() < 0.5:
        lines.append("-- последняя версия записи из CDC")
    lines += ["WITH ranked AS (", "  SELECT *,", "         ROW_NUMBER() OVER (", f"           PARTITION BY {idc}", "           ORDER BY updated_at DESC"]
    key = len(lines)
    lines += ["         ) AS rn", f"  FROM raw_{mart[5:]}_cdc"]
    if rng.random() < 0.5:
        lines.append("  WHERE op <> 'd'")
    lines += [")", "SELECT * FROM ranked WHERE rn = 1;"]
    return {"scene_title": "Плавающая сумма", "story": f"{mart} собирается из CDC-потока, updated_at — с точностью до секунды. На одних и тех же данных сумма {measure} при каждом перезапуске немного другая.",
            "prompt": "Нажмите на строку, из-за которой результат недетерминирован.", "panel": {"type": "code", "lang": "sql", "lines": lines}, "key": key}


@family("dea_dq_session_split", SPEC, "Качество данных", "choice", 2.4, 2.9)
def _(rng):
    rel, d0, k = rng.randint(3, 4), rng.randint(1, 20), rng.choice([1.5, 1.7, 1.9])
    x = [f"{d0 + i:02d}.09" for i in range(8)]
    users = [rng.randint(380, 420) for _ in range(8)]
    sess = [round(u * (1.3 if i < rel else 1.3 * k)) + rng.randint(-8, 8) for i, u in enumerate(users)]
    orders = [rng.randint(18, 21) for _ in range(8)]
    cr = lambda part: f"{100 * sum(orders[i] for i in part) / sum(sess[i] for i in part):.1f}".replace(".", ",")
    sdk = f"SDK аналитики {rng.randint(5, 7)}.{rng.randint(0, 9)}"
    panel = {"type": "chart", "x": x, "marker": {"i": rel, "label": f"релиз: новый чекаут и {sdk}"}, "series": [
        {"name": "сессии, тыс.", "axis": "left", "max": 1200, "data": sess},
        {"name": "уникальные пользователи, тыс.", "axis": "left", "max": 1000, "data": users},
        {"name": "заказы, тыс.", "axis": "right", "max": 30, "data": orders},
    ]}
    opts, key = _choice(rng, "Бизнес не просел: при тех же пользователях и заказах выросли только сессии — новый SDK дробит их; чинить определение сессии", [
        "Пришёл бот-трафик: сессий стало больше, а заказов столько же; отфильтровать ботов по user-agent и ASN, пересчитать конверсию без них и только потом решать про чекаут",
        "Новый чекаут отпугивает покупателей: конверсия упала сразу после релиза, его нужно откатить и разобрать воронку",
        "После обновления SDK задвоились user_id: один человек считается дважды, отсюда и рост сессий — чинить склейку",
    ])
    return {"scene_title": "Конверсия рухнула", "story": f"Конверсия сессии в заказ упала с {cr(range(rel))} % до {cr(range(rel, 8))} % в день релиза, где вышли новый чекаут и {sdk}. Продакт требует откатить чекаут.",
            "prompt": "Что показывают графики и что делать?", "panel": panel, "options": opts, "key": key}


# --- Визуализация ---


@family("dea_viz_axis", SPEC, "Визуализация", "choice", 2.0, -0.3)
def _(rng):
    a = rng.choice([4.1, 3.2, 2.6])
    b = round(a + rng.choice([0.2, 0.3]), 1)
    lo = round(a - 0.1, 1)
    fmt = lambda v: f"{v:.1f}".replace(".", ",")
    opts, key = _choice(rng, "Для столбцов начинать ось с нуля; если важны десятые доли — линия или подпись разницы в п. п.", [
        "Оставить ось как есть, но подписать значения над столбцами: зритель прочитает точные цифры, а масштаб подчеркнёт рост",
        "Сделать столбцы объёмными, чтобы разница читалась точнее",
        "Заменить столбцы круговой диаграммой по месяцам",
    ])
    return {"scene_title": "Рост втрое", "story": f"На дашборде столбцы конверсии за два месяца: {fmt(a)} % и {fmt(b)} %. Второй выглядит втрое выше первого: ось Y начинается с {fmt(lo)} %.",
            "prompt": "Что исправить?", "panel": None, "options": opts, "key": key}


@family("dea_viz_dual", SPEC, "Визуализация", "choice", 2.2, 0.8)
def _(rng):
    q = rng.randint(1, 4)
    x = [f"нед. {i + 1}" for i in range(8)]
    visits = [rng.randint(180, 220) + 12 * i for i in range(8)]
    k = rng.choice([2, 3, 4])
    revenue = [round(v * k / 10 + rng.randint(-2, 2)) for v in visits]
    panel = {"type": "chart", "x": x, "series": [
        {"name": "визиты, тыс.", "axis": "left", "max": 320, "data": visits},
        {"name": "выручка, млн ₽", "axis": "right", "max": 32 * k, "data": revenue},
    ]}
    opts, key = _choice(rng, "Совпадение линий задано масштабами двух осей; сравнить в индексах к базе 100 и проверять связь отдельно", [
        "Ничего: линии совпадают, значит корреляция близка к единице и связь доказана",
        "Ошибка только в стиле: выручку нужно рисовать сплошной линией, как визиты",
        "Вывод верный, но график неполный: нужно поменять оси местами и добавить лаг на неделю — тогда видно, что выручка идёт следом за трафиком",
    ])
    return {"scene_title": "Две оси", "story": f"Руководитель на разборе Q{q}: «Выручка повторяет трафик, значит, рост дал трафик — удваиваем закупку рекламы».",
            "prompt": "Что не так с выводом по этому графику?", "panel": panel, "options": opts, "key": key}


@family("dea_viz_simpson", SPEC, "Визуализация", "choice", 2.3, 2.3)
def _(rng):
    a, b = rng.choice([("контекст", "соцсети"), ("email", "push"), ("партнёры", "SEO")])
    # объёмы ~100 тыс. визитов на канал: разница CR внутри разрезов — 3–5 стандартных ошибок, а не шум
    va = {"desktop": rng.randint(76, 84) * 1000, "mobile": rng.randint(18, 24) * 1000}
    vb = {"desktop": rng.randint(18, 24) * 1000, "mobile": rng.randint(76, 84) * 1000}
    cra = {"desktop": rng.uniform(5.5, 6.2), "mobile": rng.uniform(1.6, 2.0)}
    crb = {"desktop": cra["desktop"] + rng.uniform(0.7, 1.0), "mobile": cra["mobile"] + rng.uniform(0.4, 0.6)}
    oa = {d: round(va[d] * cra[d] / 100) for d in va}
    ob = {d: round(vb[d] * crb[d] / 100) for d in vb}
    pct = lambda o, v: f"{100 * o / v:.1f} %".replace(".", ",")
    num = lambda n: f"{n:,}".replace(",", " ")
    row = lambda ch, dev, v, o: f"{ch:<10}{dev:<10}{num(v):>8}{num(o):>8}{pct(o, v):>9}"
    lines = [f"{'канал':<10}{'девайс':<10}{'визиты':>8}{'заказы':>8}{'CR':>9}"]
    for ch, v, o in ((a, va, oa), (b, vb, ob)):
        lines += [row(ch, d, v[d], o[d]) for d in ("desktop", "mobile")]
    lines += [row(a, "всего", sum(va.values()), sum(oa.values())), row(b, "всего", sum(vb.values()), sum(ob.values()))]
    opts, key = _choice(rng, f"«{b}» конвертирует лучше на каждом устройстве; общий проигрыш — из-за доли мобильного трафика (парадокс Симпсона)", [
        f"«{b}» хуже: общая конверсия учитывает все визиты сразу, поэтому она надёжнее разрезов, где выборка делится на части",
        "Выводы делать рано: внутри разрезов разница меньше процентного пункта, это обычный шум конверсии",
        "Каналы равны: если усреднить конверсию по строкам, разница исчезает",
    ])
    total = lambda o, v: pct(sum(o.values()), sum(v.values()))
    return {"scene_title": "Урезать канал?", "story": f"Маркетинг хочет урезать бюджет канала «{b}»: на дашборде его общая конверсия {total(ob, vb)} против {total(oa, va)} у «{a}».",
            "prompt": "Какой вывод корректен?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


# --- Алгоритмы ---


@family("dea_alg_nested", SPEC, "Алгоритмы", "mark", 2.1, -1.1)
def _(rng):
    field = rng.choice(["region", "segment", "city"])
    n, m = rng.randint(200, 900), rng.randint(50, 300)
    lines = ["def enrich(orders: list[dict], customers: list[dict]) -> list[dict]:"]
    if rng.random() < 0.5:
        lines.append(f'    """Добавить {field} клиента к каждому заказу."""')
    lines += ["    result = []", "    for o in orders:", f"        {field} = None", "        for c in customers:"]
    key = len(lines)
    lines += ['            if c["id"] == o["customer_id"]:', f'                {field} = c["{field}"]', f'        result.append({{**o, "{field}": {field}}})', "    return result"]
    return {"scene_title": "Обогащение на всю ночь", "story": f"Скрипт обогащает {n} тыс. заказов справочником из {m} тыс. клиентов и работает несколько часов.",
            "prompt": "Нажмите на строку, из-за которой скрипт работает так долго.", "panel": {"type": "code", "lang": "python", "lines": lines}, "key": [key, key + 1]}


@family("dea_alg_kmerge", SPEC, "Алгоритмы", "choice", 2.0, 0.4)
def _(rng):
    k, gb, mem = rng.choice([24, 40, 64]), rng.choice([10, 20, 30]), rng.choice([4, 8, 16])
    opts, key = _choice(rng, f"Слияние {k} потоков через мин-кучу по ts: один проход, O(N log {k}), в памяти по строке на файл", [
        "Прочитать все файлы в память и отсортировать целиком: так проще всего",
        "Склеить файлы подряд: каждый уже отсортирован, значит, и результат тоже",
        f"Внешняя сортировка: разбить всё на куски по {mem} ГБ, отсортировать каждый в памяти и записать куски подряд — раз куски отсортированы, слияние не нужно",
    ])
    return {"scene_title": "Склейка выгрузок", "story": f"Файлов событий — {k}, по {gb} ГБ, каждый отсортирован по ts. Нужен один общий файл, отсортированный по ts; памяти — {mem} ГБ.",
            "prompt": "Как это сделать?", "panel": None, "options": opts, "key": key}


@family("dea_alg_reservoir", SPEC, "Алгоритмы", "choice", 2.0, 1.3)
def _(rng):
    k = rng.choice([1000, 5000, 10000])
    what = rng.choice(["кликов", "логов приложения", "транзакций"])
    opts, key = _choice(rng, f"Reservoir sampling: первые {k} событий в резерв, i-е заменяет случайное с вероятностью {k}/i", [
        f"Брать каждое сотое событие, пока не наберётся {k}",
        f"Взять первые {k} событий потока: порядок прихода случаен",
        f"Сохранять каждое событие с вероятностью p = 1 % и в конце случайно отбросить лишние до {k}: выборка останется равномерной при любой длине потока",
    ])
    return {"scene_title": "Выборка из потока", "story": f"Из потока {what} неизвестной длины нужна равномерная случайная выборка ровно {k} событий за один проход, весь поток в память не влезает.",
            "prompt": "Какой алгоритм выбрать?", "panel": None, "options": opts, "key": key}


@family("dea_alg_sketch", SPEC, "Алгоритмы", "choice", 2.2, 2.4)
def _(rng):
    n, m = rng.randint(20, 60), rng.randint(6, 15)
    country, platform = rng.choice(["RU", "KZ", "BY"]), rng.choice(["ios", "android", "web"])
    lines = ["-- предложение аналитика: MAU из дневной витрины", "SELECT sum(dau) AS mau",
             "FROM mart_dau_daily  -- day, country, platform, channel, dau = uniqExact(user_id)",
             "WHERE day BETWEEN '2026-09-01' AND '2026-09-30'", f"  AND country = '{country}' AND platform = '{platform}';"]
    right = rng.choice([("Хранить по дню и сегменту скетч uniqState(user_id) и для любого периода и фильтров сливать его через uniqMerge: погрешность около 1–2 %, "
                         "зато в отличие от готовых чисел состояния скетчей корректно складываются"),
                        "Хранить по дню и сегменту скетч uniqState(user_id) и сливать его через uniqMerge: погрешность около 1–2 %, зато состояния складываются"])
    opts, key = _choice(rng, right, [
        "Хранить по дню и сегменту готовую оценку HyperLogLog (число) и для периода брать среднее оценок, умноженное на число дней — погрешность та же, что у скетча",
        f"Оставить uniqExact, но по сырым событиям с проекцией ORDER BY (country, platform, channel, day): чтение сузится до нужных гранул, и {m} мин превратятся в секунды",
        "MAU = sum(dau) × коэффициент повторных визитов, один раз посчитанный по полному месяцу",
    ])
    return {"scene_title": "MAU на лету", "story": f"Продукт хочет MAU по любому периоду и сочетанию фильтров (страна × платформа × канал) за секунды. Сырых событий {n} млрд, uniqExact по ним за месяц считается {m} мин.",
            "prompt": "Как построить витрину?", "panel": {"type": "code", "lang": "sql", "lines": lines}, "options": opts, "key": key}
