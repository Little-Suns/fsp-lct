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
    opts, key = _choice(rng, f"В {black} есть строки с NULL в {col}: NOT IN тогда ни для одной строки не даёт TRUE; нужен NOT EXISTS", [
        "NOT IN не работает с подзапросом больше 1000 строк: стоп-лист нужно разбить на части",
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
        "ReplacingMergeTree убирает дубли при вставке, значит CDC присылает разные id: проверять источник",
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
        "В отдельную таблицу фактов, связанную с продажами по дате",
        f"В JSON-поле {fact}, чтобы не менять схему {dim}",
    ])
    return {"scene_title": "Новый атрибут", "story": f"Строите звезду для квартального отчёта: факт {fact} и измерения. Аналитик просит добавить {attr} — атрибут {ent}, который меняется редко.",
            "prompt": "Куда положить атрибут?", "panel": None, "options": opts, "key": key}


@family("dea_mod_semi_additive", SPEC, "Моделирование данных", "choice", 2.1, 1.2)
def _(rng):
    what, tbl, col, unit = rng.choice([("остатков на складах", "fact_stock_daily", "qty_on_hand", "млн шт."),
                                       ("остатков на счетах клиентов", "fact_balance_daily", "balance", "млрд ₽"),
                                       ("активных подписок", "fact_subscriptions_daily", "active_cnt", "тыс. подписок")])
    real = rng.randint(3, 9)
    month, days = rng.choice([("июль", 31), ("сентябрь", 30), ("ноябрь", 30)])
    shown = real * days + rng.randint(-3, 3)
    lines = ["SELECT date_trunc('month', snapshot_date) AS month,", f"       SUM({col}) AS total", f"FROM {tbl}", "GROUP BY 1", "ORDER BY 1;"]
    opts, key = _choice(rng, "Это полуаддитивная мера: по объектам её складывают, по дням — нет; брать значение на конец месяца или среднее", [
        "date_trunc считает в UTC, и часть дней попадает в соседний месяц: перевести в местное время",
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
        "Файл приходит битым: добавить проверку схемы перед загрузкой",
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
    opts, key = _choice(rng, "Включён catchup: Airflow создал запуск на каждый день с start_date; выключить catchup, ограничить max_active_runs, историю — отдельным backfill", [
        "Расписание @daily из-за часового пояса читается как «каждую минуту»",
        "Завис scheduler: его перезапуск очистит очередь запусков",
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
    opts, key = _choice(rng, "Перекос по ключу соединения: горячий ключ целиком попал в одну задачу; солить ключ или включить AQE skew join", [
        "Поднять spark.sql.shuffle.partitions до 2000: задачи станут мельче и закончатся быстрее",
        f"Добавить executors: задача {slow} ждёт свободных ядер в очереди",
        "Закэшировать обе таблицы через .cache() перед соединением",
    ])
    return {"scene_title": "Одна задача из 200", "story": f"Сборка витрины {mart} на Spark шла 20 минут, после подключения крупного маркетплейса — больше двух часов.",
            "prompt": "Что происходит и как исправить?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


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
    opts, key = _choice(rng, f"После релиза источник перестал заполнять {field}: нужна проверка доли пустых значений и разбор с командой источника", [
        "Загрузка теряет строки: объём витрины после релиза упал",
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
    opts, key = _choice(rng, "Источник не обновлялся двое суток, а тесты проверяют только корректность строк: проверка свежести должна блокировать публикацию", [
        "BI отдал закэшированный дашборд: сбросить кэш и обновить ещё раз",
        "Инкрементальная модель потеряла строки из-за unique_key: пересобрать с --full-refresh",
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


# --- Визуализация ---


@family("dea_viz_axis", SPEC, "Визуализация", "choice", 2.0, -0.3)
def _(rng):
    a = rng.choice([4.1, 3.2, 2.6])
    b = round(a + rng.choice([0.2, 0.3]), 1)
    lo = round(a - 0.1, 1)
    fmt = lambda v: f"{v:.1f}".replace(".", ",")
    opts, key = _choice(rng, "Для столбцов начинать ось с нуля; если важны десятые доли — линия или подпись разницы в п. п.", [
        "Добавить вторую ось Y справа с тем же масштабом, тогда разница будет видна честно",
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
        "Нужно поменять оси местами — тогда видно, что выручка опережает трафик",
    ])
    return {"scene_title": "Две оси", "story": f"Руководитель на разборе Q{q}: «Выручка повторяет трафик, значит, рост дал трафик — удваиваем закупку рекламы».",
            "prompt": "Что не так с выводом по этому графику?", "panel": panel, "options": opts, "key": key}


@family("dea_viz_simpson", SPEC, "Визуализация", "choice", 2.3, 2.3)
def _(rng):
    a, b = rng.choice([("контекст", "соцсети"), ("email", "push"), ("партнёры", "SEO")])
    va = {"desktop": rng.randint(76, 84) * 100, "mobile": rng.randint(18, 24) * 100}
    vb = {"desktop": rng.randint(18, 24) * 100, "mobile": rng.randint(76, 84) * 100}
    cra = {"desktop": rng.uniform(5.5, 6.2), "mobile": rng.uniform(1.6, 2.0)}
    crb = {"desktop": cra["desktop"] + rng.uniform(0.5, 0.9), "mobile": cra["mobile"] + rng.uniform(0.3, 0.5)}
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
        f"«{b}» хуже: общая конверсия учитывает все визиты и надёжнее, чем разрезы по устройствам",
        "Выводы делать рано: при десяти тысячах визитов разница внутри разрезов случайна",
        "Каналы равны: если усреднить конверсию по строкам, разница исчезает",
    ])
    return {"scene_title": "Урезать канал?", "story": f"Маркетинг хочет урезать бюджет канала «{b}»: на дашборде его общая конверсия почти вдвое ниже, чем у «{a}».",
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
        "Для каждой строки бинарным поиском найти место в итоговом файле и вставить",
    ])
    return {"scene_title": "Склейка выгрузок", "story": f"Есть {k} файлов событий по {gb} ГБ, каждый отсортирован по ts. Нужен один общий файл, отсортированный по ts; памяти — {mem} ГБ.",
            "prompt": "Как это сделать?", "panel": None, "options": opts, "key": key}


@family("dea_alg_reservoir", SPEC, "Алгоритмы", "choice", 2.0, 1.3)
def _(rng):
    k = rng.choice([1000, 5000, 10000])
    what = rng.choice(["кликов", "логов приложения", "транзакций"])
    opts, key = _choice(rng, f"Reservoir sampling: первые {k} событий в резерв, i-е заменяет случайное с вероятностью {k}/i", [
        f"Брать каждое сотое событие, пока не наберётся {k}",
        f"Взять первые {k} событий потока: порядок прихода случаен",
        "Сохранять события с вероятностью 1 %, а лишние в конце отбросить",
    ])
    return {"scene_title": "Выборка из потока", "story": f"Из потока {what} неизвестной длины нужна равномерная случайная выборка ровно {k} событий за один проход, весь поток в память не влезает.",
            "prompt": "Какой алгоритм выбрать?", "panel": None, "options": opts, "key": key}
