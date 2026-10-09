"""Data Eng / Analytics, сюжет «Квартальный отчёт»: сценарные семейства с SQL, логами Airflow/dbt/Spark и графиками витрин.
У каждого семейства три варианта механики (items._variant), правильные ответы других вариантов — среди дистракторов."""

from app.services.items import _log, _options, _variant, family

SPEC = "Data Eng / Analytics"


def _pct(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


# --- SQL ---


@family("dea_sql_fanout", SPEC, "SQL", "mark", 2.2, 0.1)
def _(rng):
    col = rng.choice(["region", "channel", "segment"])
    child = rng.choice(["order_items", "order_lines", "shipments"])
    k = rng.choice([2, 3, 4])
    q = rng.choice([1, 4, 7])
    v = _variant(rng, 3)
    lines = []
    if rng.random() < 0.5:
        lines.append(f"-- выручка по {col} за квартал")
    if v == 0:
        lines += [f"SELECT c.{col},", "       SUM(o.amount) AS revenue", "FROM orders o"]
        joins = ["JOIN customers c ON c.id = o.customer_id", f"JOIN {child} i ON i.order_id = o.id"]
        rng.shuffle(joins)
        lines += joins
        key = len(lines) - 1 if joins[0].startswith(f"JOIN {child}") else len(lines)
        lines += [f"WHERE o.created_at >= '2026-{q:02d}-01'", "  AND i.status <> 'cancelled'", f"GROUP BY c.{col};"]
        story, prompt = (f"Выручка по {col} в квартальном отчёте примерно в {k} раза выше, чем в финансовой системе. Фильтр по отменённым позициям добавили на прошлой неделе.",
                         "Нажмите на строку, из-за которой выручка завышена.")
    elif v == 1:
        lines += [f"SELECT c.{col},", "       SUM(o.amount) AS revenue,", "       SUM(p.discount) AS app_promo_discount", "FROM orders o",
                  "JOIN customers c ON c.id = o.customer_id", "LEFT JOIN promo_usage p ON p.order_id = o.id", f"WHERE o.created_at >= '2026-{q:02d}-01'",
                  "  AND p.channel = 'app'"]
        key = len(lines)
        lines += [f"GROUP BY c.{col};"]
        story, prompt = (f"В отчёт по {col} добавили сумму скидок по промокодам из приложения. После этого выручка упала в разы: остались только заказы с промокодом.",
                         "Нажмите на строку, из-за которой выручка занижена.")
    else:
        lines += [f"SELECT c.{col},", "       SUM(o.amount) AS revenue", "FROM orders o", "JOIN customers c ON c.id = o.customer_id",
                  f"WHERE o.created_at BETWEEN '2026-{q:02d}-01' AND '2026-{q + 2:02d}-{ {1: 31, 4: 30, 7: 30}[q]}'"]
        key = len(lines)
        lines += [f"GROUP BY c.{col};"]
        story, prompt = (f"Выручка по {col} за квартал чуть ниже, чем в финансовой системе: не хватает продаж последнего дня квартала. created_at — timestamp.",
                         "Нажмите на строку, из-за которой выручка занижена.")
    return {"scene_title": "Выручка не сходится", "story": story, "prompt": prompt, "panel": {"type": "code", "lang": "sql", "lines": lines}, "key": key}


@family("dea_sql_not_in", SPEC, "SQL", "choice", 2.2, 1.1)
def _(rng):
    tbl, col, what = rng.choice([("orders", "customer_id", "заказов"), ("payments", "card_id", "платежей"), ("sessions", "user_id", "сессий")])
    black = rng.choice(["stop_list", "blocked_accounts", "fraud_marks"])
    n = rng.randint(120, 900)
    q = rng.choice([1, 4, 7])
    v = _variant(rng, 3)
    if v == 0:
        lines = ["SELECT count(*)", f"FROM {tbl} t", f"WHERE t.created_at >= '2026-0{q}-01'", f"  AND t.{col} NOT IN (SELECT {col} FROM {black});"]
        story = f"Нужно число {what} за квартал без клиентов из стоп-листа {black}, который собирают из CRM и ручных выгрузок. Запрос вернул 0, хотя {what} за квартал — около {n} тыс."
    elif v == 1:
        lines = ["SELECT count(*)", f"FROM {tbl} t", f"WHERE t.created_at >= '2026-0{q}-01'", "  AND t.status <> 'test';"]
        story = f"Нужно число {what} за квартал без тестовых. Запрос вернул на {rng.randint(15, 40)} % меньше ожидаемого: у старых записей статус не заполнен."
    else:
        lines = [f"SELECT count(t.promo_code) AS {tbl}_cnt", f"FROM {tbl} t", f"WHERE t.created_at >= '2026-0{q}-01';"]
        story = f"Нужно число {what} за квартал. Запрос вернул втрое меньше, чем в финансовом отчёте; промокод указан примерно у трети записей."
    opts, key = _options(rng, [f"В {black} есть NULL в {col}: с NULL условие NOT IN не бывает истинным; нужен NOT EXISTS",
                               "Сравнение с NULL даёт не «истину», а NULL: строки с пустым статусом выпадают, нужен OR status IS NULL",
                               "count(колонка) не считает строки, где в ней NULL: для числа строк нужен count(*)"], v,
                         ["NOT IN и <> с подзапросами больше 1000 строк планировщик обрезает: условие нужно разбить на части",
                          "Запрос обрывается по таймауту и возвращает частичный результат"])
    return {"scene_title": "Меньше, чем должно", "story": story, "prompt": "Почему так?", "panel": {"type": "code", "lang": "sql", "lines": lines}, "options": opts, "key": key}


@family("dea_sql_ch_replacing", SPEC, "SQL", "choice", 2.3, 2.0)
def _(rng):
    tbl, idc, thing, things = rng.choice([("orders_cdc", "order_id", "заказа", "заказам"), ("payments_cdc", "payment_id", "платежа", "платежам"),
                                          ("contracts_cdc", "contract_id", "договора", "договорам")])
    p, h = rng.randint(4, 18), rng.choice([2, 3, 5])
    v = _variant(rng, 3)
    if v == 0:
        lines = [f"CREATE TABLE {tbl} (", f"    {idc} UInt64,", "    status String,", "    amount Decimal(18, 2),", "    updated_at DateTime",
                 ") ENGINE = ReplacingMergeTree(updated_at)", f"ORDER BY {idc};", "", f"SELECT count(), sum(amount) FROM {tbl};"]
        story = f"CDC пишет в ClickHouse каждое изменение {thing}. Сразу после загрузки сумма в отчёте на {p} % выше, чем в источнике, а через {h} ч расхождение почти исчезает само."
    elif v == 1:
        lines = [f"CREATE MATERIALIZED VIEW {tbl}_daily_mv TO {tbl}_daily AS", "SELECT toDate(updated_at) AS day, sum(amount) AS amount",
                 f"FROM {tbl}", "GROUP BY day;", "", f"SELECT day, sum(amount) FROM {tbl}_daily GROUP BY day ORDER BY day;"]
        story = f"Для быстрого отчёта по {things} сделали materialized view с агрегатами по дням. За сегодня данные есть, а за все прошлые месяцы — пусто."
    else:
        lines = [f"-- {tbl}: ReplicatedMergeTree на каждом из {h + 1} шардов, {tbl}_all — Distributed поверх них",
                 f"SELECT count(), sum(amount) FROM {tbl} FINAL;"]
        story = f"Отчёт по {things} в ClickHouse показывает примерно 1/{h + 1} от суммы в источнике, и с каждым запросом цифры чуть разные — в зависимости от узла, куда попал запрос."
    opts, key = _options(rng, ["Версии схлопываются только при фоновых слияниях частей: читать с FINAL или брать argMax(amount, updated_at) по ключу",
                               "MV обрабатывает только новые вставки: историю нужно залить в целевую таблицу отдельно, INSERT … SELECT",
                               f"Запрос читает локальную таблицу одного шарда: читать через Distributed-таблицу {tbl}_all"], v,
                         ["ReplacingMergeTree схлопывает дубли уже при вставке, значит, источник присылает каждую версию записи с новым id",
                          "Decimal(18, 2) округляет суммы при вставке, и ошибка копится: перейти на Float64"])
    return {"scene_title": "ClickHouse считает не то", "story": story, "prompt": "В чём причина и как читать правильно?",
            "panel": {"type": "code", "lang": "sql", "lines": lines}, "options": opts, "key": key}


# --- Моделирование данных ---


@family("dea_mod_star", SPEC, "Моделирование данных", "choice", 2.0, -1.3)
def _(rng):
    attr, ent, dim, k = rng.choice([("категорию товара", "товара", "dim_product", "product_key"), ("город магазина", "магазина", "dim_store", "store_key"),
                                    ("отрасль клиента", "клиента", "dim_customer", "customer_key")])
    fact = rng.choice(["fact_sales", "fact_orders", "fact_receipts"])
    v = _variant(rng, 3)
    story = [f"Аналитик просит добавить {attr} — атрибут {ent}, который меняется редко.",
             "Аналитик просит добавить сумму скидки по каждой позиции чека.",
             "Аналитик просит добавить план продаж: он задаётся на месяц по каждому магазину."][v]
    opts, key = _options(rng, [f"В измерение {dim}, а в {fact} оставить ключ {k} и меры", f"Мерой в {fact} на уровне позиции чека",
                               "Отдельной таблицей фактов на своём зерне «месяц × магазин» с общими измерениями"], v,
                         [f"Текстом в каждую строку {fact}: отчёт обойдётся без JOIN", f"В JSON-поле {fact}, чтобы не менять схему"])
    return {"scene_title": "Куда положить", "story": f"Строите звезду для квартального отчёта: факт {fact} (строка — позиция чека) и измерения. {story}",
            "prompt": "Куда положить новые данные?", "panel": None, "options": opts, "key": key}


@family("dea_mod_semi_additive", SPEC, "Моделирование данных", "choice", 2.1, 1.2)
def _(rng):
    what, tbl, col, unit = rng.choice([("остатков на складах", "fact_stock_daily", "qty_on_hand", "млн штук"),
                                       ("остатков на счетах клиентов", "fact_balance_daily", "balance", "млрд ₽"),
                                       ("активных подписок", "fact_subscriptions_daily", "active_cnt", "тыс. подписок")])
    real = rng.randint(3, 9)
    month, days = rng.choice([("июль", 31), ("сентябрь", 30), ("ноябрь", 30)])
    v = _variant(rng, 3)
    if v == 0:
        lines = ["SELECT date_trunc('month', snapshot_date) AS month,", f"       SUM({col}) AS total", f"FROM {tbl}", "GROUP BY 1", "ORDER BY 1;"]
        story = f"{tbl} — ежедневный снимок {what}. За {month} отчёт показывает {real * days + rng.randint(-3, 3)} {unit}, хотя на конец месяца реально около {real} {unit}."
    elif v == 1:
        lines = ["SELECT region,", "       SUM(avg_check) AS avg_check", "FROM mart_avg_check_by_store", "GROUP BY region;"]
        story = f"Средний чек по региону в отчёте получается в {rng.randint(8, 30)} раз больше, чем средний чек любого магазина региона."
    else:
        lines = ["SELECT date_trunc('month', paid_at) AS month,", "       SUM(amount) AS revenue", "FROM payments  -- amount в валюте платежа: RUB, KZT, USD",
                 "GROUP BY 1;"]
        story = "Выручка за месяц скачет на десятки процентов, хотя число платежей стабильно; меняется только доля казахстанских платежей."
    opts, key = _options(rng, ["Это полуаддитивная мера: по объектам её складывают, по дням — нет; брать значение на конец месяца или среднее",
                               "Средние не складываются: считать как сумма выручки / число чеков на нужном уровне",
                               "Суммируются разные валюты: переводить в рубли по курсу на дату платежа, затем складывать"], v,
                         ["date_trunc считает месяц в UTC, поэтому дни на стыке месяцев попадают в соседний и сумма раздувается",
                          "В таблице дубли строк: нужен DISTINCT перед SUM"])
    return {"scene_title": "Сумма не та", "story": story, "prompt": "В чём ошибка?", "panel": {"type": "code", "lang": "sql", "lines": lines}, "options": opts, "key": key}


@family("dea_mod_scd_between", SPEC, "Моделирование данных", "mark", 2.3, 2.1)
def _(rng):
    ent, attr = rng.choice([("customer", "manager"), ("dealer", "region_manager"), ("partner", "account_manager")])
    v = _variant(rng, 3)
    lines = []
    if rng.random() < 0.5:
        lines.append("-- продажи по менеджерам, квартальный отчёт")
    lines.append("SELECT f.order_id,")
    if rng.random() < 0.5:
        lines.append("       f.sale_date,")
    lines += ["       f.amount,", f"       d.{attr}", "FROM fact_sales f", f"JOIN dim_{ent}_scd d", f"  ON d.{ent}_id = f.{ent}_id"]
    if v == 1:  # условия по датам версии нет: дефектны и JOIN, и его ON
        key = [len(lines) - 1, len(lines)]
    if v == 0:
        lines.append(" AND f.sale_date BETWEEN d.valid_from AND d.valid_to")
        key = len(lines)
    if v == 2:
        lines.append(" AND d.is_current")
        key = len(lines)
    lines.append(f"WHERE f.sale_date >= '2026-0{rng.choice([1, 4, 7])}-01';")
    story = [f"dim_{ent}_scd — измерение SCD Type 2; загрузка пишет valid_to старой версии равным valid_from новой. Продажи в отчёте задваиваются, но только в отдельные дни.",
             f"dim_{ent}_scd — измерение SCD Type 2. Продажи клиентов, у которых менялся менеджер, в отчёте умножаются на число версий.",
             f"dim_{ent}_scd — измерение SCD Type 2. После смены менеджера все его прошлые продажи в квартальном отчёте переехали к новому менеджеру."][v]
    prompt = "Нажмите на строку, из-за которой продажи приписаны не тому менеджеру." if v == 2 else "Нажмите на строку, из-за которой продажи задваиваются."
    return {"scene_title": "Продажи по менеджерам", "story": story, "prompt": prompt, "panel": {"type": "code", "lang": "sql", "lines": lines}, "key": key}


@family("dea_mod_late_member", SPEC, "Моделирование данных", "choice", 2.3, 2.6)
def _(rng):
    fact, many, sale = rng.choice([("fact_orders", "заказы", "заказа"), ("fact_sales", "продажи", "продажи"), ("fact_policies", "полисы", "оформления полиса")])
    channel = rng.choice(["партнёрского канала", "маркетплейса", "B2B-портала"])
    rows, lag, share = rng.randint(2, 8), rng.randint(1, 3), rng.randint(3, 9)
    v = _variant(rng, 3)
    story = [f"Клиенты {channel} приходят из CRM на {lag} дн. позже первых записей; такие {many} получают customer_key = -1 («неизвестный») и так и остаются — их уже {share} %. "
             "Выручку финансы смотрят в тот же день.",
             f"Записи {channel} приходят с опозданием до {lag + 3} дн.; загрузка берёт текущую версию клиента, и {many} клиентов, у которых за это время сменился сегмент, "
             "попадают в новый сегмент.",
             f"В dim_customer добавили «диапазон баланса» клиента, он меняется почти каждый день: таблица выросла в {rng.randint(40, 90)} раз, а JOIN с фактом стал тормозить."][v]
    opts, key = _options(rng, ["Заводить в измерении предполагаемую запись по натуральному ключу, а когда клиент придёт из CRM, дописать её атрибуты",
                               f"Искать версию клиента, действовавшую на дату {sale}, а не текущую на момент загрузки",
                               "Вынести быстро меняющийся атрибут в мини-измерение (или в факт), а не плодить версии клиента"], v,
                         [f"Оставить -1, но каждую ночь перегружать {fact} целиком за всю историю, чтобы старые {many} подхватили изменения из CRM",
                          f"Держать такие {many} в staging, пока данные клиента не устоятся, и только тогда загружать их в факт",
                          "Хранить в факте натуральный id клиента и при запросе брать атрибуты из текущей версии измерения"])
    return {"scene_title": "Измерение клиентов", "story": f"{fact} ({rows} млрд строк) ссылается на dim_customer — SCD Type 2: отчёты показывают сегмент клиента на дату {sale}. {story}",
            "prompt": "Как правильно загружать такие данные?", "panel": None, "options": opts, "key": key}


# --- Пайплайны ---


@family("dea_pipe_sensor", SPEC, "Пайплайны", "choice", 2.1, -1.4)
def _(rng):
    src = rng.choice(["sales", "returns", "payments"])
    day = rng.randint(10, 29)
    late = rng.randint(4, 25)
    v = _variant(rng, 3)
    head = _log("03:00:01", "scheduler", "INFO", f"DAG {src}_daily: run scheduled__2026-09-{day:02d} started")
    if v == 0:
        lines = [head, _log("03:00:04", f"load_{src}", "ERROR", f"FileNotFoundError: s3://raw/{src}/2026-09-{day:02d}.csv"),
                 _log("03:00:05", "scheduler", "INFO", f"task load_{src} failed, retries=0"),
                 _log(f"03:{late:02d}:40", "s3-events", "INFO", f"object created raw/{src}/2026-09-{day:02d}.csv ({rng.randint(80, 400)} MB)")]
        story = f"Ночная загрузка {src} падает примерно раз в неделю. Утром её перезапускают руками — и она проходит."
    elif v == 1:
        lines = [_log("02:10:00", "iam", "INFO", f"role etl-{src} rotated: new policy attached (s3:GetObject on raw/{src}/* — missing)"), head,
                 _log("03:00:04", f"load_{src}", "ERROR", f"AccessDenied: s3:GetObject on s3://raw/{src}/2026-09-{day:02d}.csv"),
                 _log("03:00:05", "scheduler", "INFO", f"task load_{src} failed, retries=3, all failed")]
        story = f"Этой ночью загрузка {src} упала, и все повторы — тоже, хотя файл в бакете на месте."
    else:
        # выгрузка пишется частями в каталог дня: загрузка видит каталог непустым и забирает то, что уже успело лечь
        lines = [head, _log("03:00:04", f"load_{src}", "INFO", f"loaded s3://raw/{src}/2026-09-{day:02d}/*.csv: {rng.randint(40, 300)} 000 rows"),
                 _log(f"03:{late:02d}:40", "s3-events", "INFO", f"object created raw/{src}/2026-09-{day:02d}/part-00002.csv; marker raw/{src}/2026-09-{day:02d}/_SUCCESS created"),
                 _log("09:30:00", "finance", "WARN", f"{src} за {day}.09: в отчёте на треть меньше, чем в источнике")]
        story = f"Загрузка {src} проходит успешно, но примерно раз в неделю в отчёте не хватает части строк за день."
    opts, key = _options(rng, ["Выгрузка приходит позже запуска по расписанию: ждать появления файла сенсором или запускать по событию",
                               "У задачи нет прав на чтение бакета: вернуть роли нужное разрешение",
                               "Выгрузка читается до конца записи: запускать загрузку по маркеру готовности _SUCCESS, а не по файлам"], v,
                         ["Включить catchup, чтобы Airflow сам догнал упавший запуск", "Увеличить retries до пяти с паузой в минуту"])
    return {"scene_title": "Загрузка в 03:00", "story": story, "prompt": "В чём причина?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("dea_pipe_catchup", SPEC, "Пайплайны", "choice", 2.2, 0.9)
def _(rng):
    dag = rng.choice(["crm_snapshot", "ads_costs", "erp_invoices"])
    year = rng.choice([2024, 2025])
    total = (2026 - year) * 365 + rng.randint(200, 270)
    v = _variant(rng, 3)
    if v == 0:
        lines = [_log("09:14:02", "scheduler", "INFO", f"DAG {dag} added, schedule=@daily, start_date={year}-01-01"),
                 _log("09:14:03", "scheduler", "INFO", f"Created DagRun scheduled__{year}-01-01T00:00:00"),
                 _log("09:14:03", "scheduler", "INFO", f"Created DagRun scheduled__{year}-01-02T00:00:00"),
                 _log("09:14:04", "scheduler", "INFO", f"DagRuns queued for {dag}: {total}"),
                 _log("09:14:30", "pg-replica", "WARN", f"{rng.randint(40, 90)} active queries from airflow_etl, connections near limit")]
        story = f"Выкатили новый DAG {dag} — и через минуту воркеры забиты, а реплика базы-источника захлёбывается запросами."
    elif v == 1:
        d = rng.randint(3, 12)
        lines = [_log("09:14:02", "scheduler", "INFO", f"clear & rerun {dag}: scheduled__2026-09-{d:02d}"),
                 _log("09:14:10", f"load_{dag}", "INFO", "SELECT … WHERE dt = CURRENT_DATE - 1  -- в SQL задачи"),
                 _log("09:15:40", f"load_{dag}", "INFO", f"inserted rows for dt=2026-10-0{rng.randint(4, 6)}")]
        story = f"Пересчитали DAG {dag} за прошлую дату после исправления бага, но витрина за ту дату не изменилась, а за вчера данные задвоились."
    else:
        lines = [_log("09:14:02", "scheduler", "INFO", f"DAG {dag} added, schedule=@daily, start_date=datetime.now()"),
                 _log("09:14:03", "scheduler", "INFO", f"{dag}: next_dagrun_create_after moves with every parse"),
                 _log("09:14:04", "scheduler", "INFO", f"{dag}: 0 runs in the last 3 days")]
        story = f"DAG {dag} выкатили три дня назад, он включён и без ошибок — но так ни разу и не запустился."
    opts, key = _options(rng, ["Включён catchup: Airflow ставит запуск на каждый день с start_date; выключить catchup, историю — отдельным backfill",
                               "Задача берёт текущую дату вместо логической: в SQL подставлять {{ ds }} запуска",
                               "start_date вычисляется заново при каждом разборе DAG: задать фиксированную дату в прошлом"], v,
                         ["Расписание @daily из-за часового пояса читается как «каждую минуту»",
                          "Завис scheduler и путает запуски: перезапустить его и очистить очередь DagRun"])
    return {"scene_title": "Расписание Airflow", "story": story, "prompt": "Что произошло и как исправить?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("dea_pipe_skew", SPEC, "Пайплайны", "choice", 2.4, 1.9)
def _(rng):
    mart = rng.choice(["mart_orders", "mart_gmv", "mart_sellers"])
    stage, slow, gb = rng.randint(8, 30), rng.randint(5, 199), round(rng.uniform(22, 48), 1)
    mins = rng.randint(35, 80)
    v = _variant(rng, 3)
    if v == 0:
        lines = [_log("02:41:10", "spark", "INFO", f"stage {stage} (join at build_{mart}.py:{rng.randint(60, 140)}): 199/200 tasks finished, median 18 s"),
                 _log("02:41:10", "spark", "INFO", f"task {slow} RUNNING {mins} min, shuffle read {gb} GB, records {rng.randint(300, 600)} 000 000"),
                 _log("02:41:11", "spark", "INFO", f"task {(slow + 7) % 200} SUCCESS 17 s, shuffle read {rng.randint(120, 200)} MB"),
                 _log("02:41:15", f"executor-{rng.randint(1, 12)}", "WARN", f"spilling {round(gb / 3, 1)} GB to disk")]
        story = f"Сборка витрины {mart} на Spark шла 20 минут, после подключения крупного маркетплейса — больше двух часов."
    elif v == 1:
        n = rng.randint(180, 420)
        lines = [_log("02:10:00", "spark", "INFO", f"listing s3://lake/events/: {n} 000 files, avg size {rng.randint(40, 120)} KB, listing took {rng.randint(8, 20)} min"),
                 _log("02:31:00", "spark", "INFO", f"stage 0: {n} 000 tasks, median 0.4 s, scheduler delay 2.1 s per task"),
                 _log("02:31:02", "ingest", "INFO", "стриминг пишет файл каждые 10 секунд в каждую партицию")]
        story = f"Сборка витрины {mart} становится медленнее с каждой неделей, хотя объём данных почти не растёт."
    else:
        lines = [_log("02:41:10", "spark", "INFO", f"stage {stage}: BroadcastHashJoin, broadcasting dim_sellers ({rng.randint(5, 9)}.{rng.randint(1, 9)} GB after filter)"),
                 _log("02:41:40", "driver", "ERROR", "java.lang.OutOfMemoryError: Java heap space (building broadcast relation)"),
                 _log("02:41:41", "spark", "INFO", "spark.sql.autoBroadcastJoinThreshold = 10g (задан в прошлом месяце для ускорения)")]
        story = f"Сборка витрины {mart} падает с OOM на драйвере после того, как справочник продавцов вырос."
    opts, key = _options(rng, ["Перекос по ключу соединения: горячий ключ попал в одну задачу; солить ключ или включить AQE skew join",
                               "Слишком много мелких файлов: уплотнять их (compaction) до сотен мегабайт",
                               "Большую таблицу нельзя рассылать на все узлы: вернуть порог broadcast к разумному, пусть идёт sort-merge join"], v,
                         ["Поднять spark.sql.shuffle.partitions до 2000: задачи станут мельче и всё ускорится", "Закэшировать обе таблицы через .cache() перед соединением"])
    return {"scene_title": "Spark тормозит", "story": story, "prompt": "Что происходит и как исправить?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("dea_pipe_late_watermark", SPEC, "Пайплайны", "mark", 2.3, 2.75)
def _(rng):
    mart, src = rng.choice([("mart_app_events", "raw.app_events"), ("mart_checkout_events", "raw.checkout_events"), ("mart_game_events", "raw.game_events")])
    lag, gap = rng.randint(6, 30), f"{rng.uniform(1.2, 3.5):.1f}".replace(".", ",")
    v = _variant(rng, 3)
    lines = [f"INSERT INTO {mart} (event_id, user_id, event_ts, event_type, country)", "SELECT e.event_id, e.user_id, e.event_ts, e.event_type, u.country",
             f"FROM {src} e", "JOIN dim_users u ON u.user_id = e.user_id" if v == 2 else "LEFT JOIN dim_users u ON u.user_id = e.user_id"]
    if v == 2:
        key = len(lines)
    lines.append(f"WHERE e.event_ts > (SELECT coalesce(max(event_ts), '1970-01-01') FROM {mart})" if v == 0 else
                 f"WHERE e.ingested_at > (SELECT last_ingested_at FROM etl_state WHERE target = '{mart}')")
    if v == 0:
        key = len(lines)
    if rng.random() < 0.5:
        lines.append("  AND e.event_type <> 'heartbeat'")
    lines.append("ON CONFLICT (user_id, event_ts) DO NOTHING;" if v == 1 else "ON CONFLICT (event_id) DO NOTHING;")
    if v == 1:
        key = len(lines)
    story = [f"Загрузка {mart} идёт каждый час. Мобильные клиенты копят события офлайн и досылают их до {lag} ч позже; event_ts — время на устройстве. "
             f"За прошлые дни в витрине на {gap} % меньше событий, чем в {src}, и разница со временем не уходит; пересборка с нуля сходится с источником.",
             f"В витрине {mart} на {gap} % меньше событий, чем в {src}, и пересборка с нуля не помогает. Больше всего не хватает у активных пользователей: event_ts — с точностью до секунды.",
             f"В витрине {mart} на {gap} % меньше событий, чем в {src}. Не хватает в основном событий новых пользователей: dim_users обновляется раз в сутки."][v]
    return {"scene_title": "Недостача событий", "story": story, "prompt": "Нажмите на строку, из-за которой витрина теряет события.",
            "panel": {"type": "code", "lang": "sql", "lines": lines}, "key": key}


# --- Качество данных ---


@family("dea_dq_null_share", SPEC, "Качество данных", "choice", 2.1, -1.0)
def _(rng):
    field = rng.choice(["region", "city", "utm_source"])
    rel, d0 = rng.randint(3, 5), rng.randint(1, 20)
    x = [f"{d0 + i:02d}.09" for i in range(8)]
    v = _variant(rng, 3)
    base = [rng.randint(410, 440) for _ in range(8)]
    rows = [r if v == 0 or i < rel else (r * 2 + rng.randint(-5, 5) if v == 2 else round(r * rng.uniform(0.55, 0.65))) for i, r in enumerate(base)]
    nulls = [rng.randint(1, 3) if i < rel or v != 0 else rng.randint(31, 44) for i in range(8)]
    mark = [f"релиз приложения v{rng.randint(3, 6)}.{rng.randint(10, 40)}", f"релиз приложения v{rng.randint(3, 6)}.{rng.randint(10, 40)} (iOS)", "ручной перезапуск загрузки"][v]
    panel = {"type": "chart", "x": x, "marker": {"i": rel, "label": mark}, "series": [
        {"name": "строк в витрине за день, тыс.", "axis": "left", "max": 1000, "data": rows},
        {"name": f"доля пустых {field}, %", "axis": "right", "max": 50, "data": nulls}]}
    story = [f"В отчёте по {field} внезапно выросла доля «не указано».", "В отчёте внезапно просели все показатели — примерно на 40 %.",
             "В отчёте внезапно удвоились все показатели."][v]
    opts, key = _options(rng, [f"Релиз источника перестал заполнять {field}: проверять долю пустых и чинить в источнике",
                               "Источник перестал присылать часть событий (одну платформу): чинить выгрузку, а не отчёт",
                               "Витрина задвоилась после перезапуска загрузки: загрузку сделать идемпотентной"], v,
                         ["Это сезонность конца квартала, через неделю всё вернётся", f"Загрузка теряет строки: пустые {field} — это заказы без пары при JOIN со справочником"])
    return {"scene_title": "Странный отчёт", "story": f"{story} Есть графики витрины за восемь дней.", "prompt": "Что произошло?", "panel": panel, "options": opts, "key": key}


@family("dea_dq_freshness", SPEC, "Качество данных", "choice", 2.3, 1.3)
def _(rng):
    mart, dash = rng.choice([("fct_orders", "Продажи за день"), ("fct_payments", "Платежи"), ("fct_shipments", "Отгрузки")])
    day = rng.randint(5, 28)
    v = _variant(rng, 3)
    fresh = f"source raw.{mart[4:]}: max(loaded_at) = 2026-09-{day - (2 if v == 0 else 0):02d} {'23:58' if v == 0 else '05:41'}"
    ins = f"INSERT 0 {rng.randint(30, 90)}412" if v == 2 else "INSERT 0 0"
    lines = [_log("06:00:05", "dbt", "WARN" if v == 0 else "INFO", fresh),
             _log("06:00:30", "dbt", "INFO", f"OK created incremental model {mart} [{ins} in {rng.uniform(1.5, 4.5):.1f}s]")]
    if v == 1:
        lines.append(_log("06:00:31", "dbt", "INFO", f"{mart}: materialized=incremental, unique_key='order_date' — rows merged: {rng.randint(30, 90)} 000 → 1 per day"))
    lines += [_log("06:01:40", "dbt", "INFO", f"1 of 2 PASS not_null_{mart}_id"), _log("06:01:41", "dbt", "INFO", f"2 of 2 PASS accepted_values_{mart}_status")]
    lines.append(_log("06:01:50", "bi", "INFO", f"dashboard «{dash}» refreshed" if v != 2 else f"dashboard «{dash}»: served from cache (built 2026-09-{day - 1:02d} 06:02, ttl 24h)"))
    opts, key = _options(rng, ["Источник не обновлялся больше суток, а тесты проверяют только строки: нужна проверка свежести перед публикацией",
                               "Неверный unique_key: инкрементальная модель сливает все строки дня в одну — ключ должен быть id записи",
                               "Дашборд отдал вчерашний кэш: обновлять его после публикации данных, а не по таймеру кэша"], v,
                         ["Отчёт строится в UTC, и вчерашние продажи попали в сегодняшний день", "Тесты слишком слабые: добавить accepted_values ещё на два поля"])
    return {"scene_title": "Зелёные тесты", "story": f"Все проверки {mart} зелёные, дашборд «{dash}» обновился {day:02d}.09 в 06:01. Финансы пишут: данных за вчера в отчёте нет.",
            "prompt": "В чём причина?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("dea_dq_nondet", SPEC, "Качество данных", "mark", 2.3, 2.3)
def _(rng):
    mart, idc, measure = rng.choice([("mart_orders", "order_id", "выручки"), ("mart_loans", "loan_id", "выдач"), ("mart_tickets", "ticket_id", "возвратов")])
    v = _variant(rng, 3)
    lines = []
    if v == 0:
        if rng.random() < 0.5:
            lines.append("-- последняя версия записи из CDC")
        lines += ["WITH ranked AS (", "  SELECT *,", "         ROW_NUMBER() OVER (", f"           PARTITION BY {idc}", "           ORDER BY updated_at DESC"]
        key = len(lines)
        lines += ["         ) AS rn", f"  FROM raw_{mart[5:]}_cdc"]
        if rng.random() < 0.5:
            lines.append("  WHERE op <> 'd'")
        lines += [")", "SELECT * FROM ranked WHERE rn = 1;"]
        story = f"{mart} собирается из CDC-потока, updated_at — с точностью до секунды. На одних и тех же данных сумма {measure} при каждом перезапуске немного другая."
    elif v == 1:
        lines += [f"-- контрольная выборка {mart} для ручной сверки с источником", f"CREATE TABLE {mart}_sample AS", f"SELECT * FROM {mart}",
                  "WHERE created_at >= '2026-07-01'", "LIMIT 10000;"]
        key = len(lines)
        story = f"Аудиторы сверяют {mart} с источником по контрольной выборке. Каждый перезапуск даёт другие строки, и сверку не удаётся повторить."
    else:
        lines += ["SELECT sum(amount::double precision) AS total", f"FROM {mart}", "WHERE created_at >= '2026-07-01';"]
        key = 1
        story = f"Сумма {measure} в {mart} при каждом запуске отличается в копейках; запрос выполняется параллельно на нескольких воркерах."
    return {"scene_title": "Каждый раз по-разному", "story": story, "prompt": "Нажмите на строку, из-за которой результат недетерминирован.",
            "panel": {"type": "code", "lang": "sql", "lines": lines}, "key": key}


@family("dea_dq_session_split", SPEC, "Качество данных", "choice", 2.4, 2.9)
def _(rng):
    rel, d0, k = rng.randint(3, 4), rng.randint(1, 20), rng.choice([1.5, 1.7, 1.9])
    x = [f"{d0 + i:02d}.09" for i in range(8)]
    v = _variant(rng, 3)
    users0 = [rng.randint(380, 420) for _ in range(8)]
    users = [round(u * (k if v == 2 and i >= rel else 1)) for i, u in enumerate(users0)]
    sess = [round(u * (1.3 if i < rel or v == 1 else 1.3 * k)) + rng.randint(-8, 8) for i, u in enumerate(users0)]
    orders = [rng.randint(18, 21) if i < rel or v != 1 else rng.randint(11, 13) for i in range(8)]
    cr = lambda part: _pct(100 * sum(orders[i] for i in part) / sum(sess[i] for i in part))  # noqa: E731
    sdk = f"SDK аналитики {rng.randint(5, 7)}.{rng.randint(0, 9)}"
    panel = {"type": "chart", "x": x, "marker": {"i": rel, "label": f"релиз: новый чекаут и {sdk}"}, "series": [
        {"name": "сессии, тыс.", "axis": "left", "max": 1200, "data": sess},
        {"name": "уникальные пользователи, тыс.", "axis": "left", "max": 1200, "data": users},
        {"name": "заказы, тыс.", "axis": "right", "max": 30, "data": orders}]}
    opts, key = _options(rng, ["Бизнес не просел: при тех же пользователях и заказах выросли только сессии — новый SDK дробит их; чинить определение сессии",
                               "Заказы упали при тех же сессиях и пользователях: проблема в новом чекауте — откатить его и разобрать воронку",
                               "Пришли «пользователи», которые ничего не заказывают, — похоже на ботов: отфильтровать их и пересчитать конверсию"], v,
                         ["После обновления SDK задвоились user_id: один человек считается дважды — чинить склейку",
                          "Это сезонное падение спроса: подождать неделю и сравнить"])
    return {"scene_title": "Конверсия рухнула", "story": f"Конверсия сессии в заказ упала с {cr(range(rel))} % до {cr(range(rel, 8))} % в день релиза, где вышли новый чекаут и {sdk}. Продакт требует откатить чекаут.",
            "prompt": "Что показывают графики и что делать?", "panel": panel, "options": opts, "key": key}


# --- Визуализация ---


@family("dea_viz_axis", SPEC, "Визуализация", "choice", 2.0, -0.3)
def _(rng):
    a = rng.choice([4.1, 3.2, 2.6])
    b = round(a + rng.choice([0.2, 0.3]), 1)
    v = _variant(rng, 3)
    times = round((b - a + 0.1) / 0.1)  # видимые высоты столбцов от начала оси: 0,1 и b − a + 0,1
    story = [f"На дашборде столбцы конверсии за два месяца: {_pct(a)} % и {_pct(b)} %. Второй выглядит в {times} раза выше первого: ось Y начинается с {_pct(a - 0.1)} %.",
             f"На дашборде доли выручки {rng.randint(11, 14)} категорий показаны круговой диаграммой; руководитель не может понять, какая категория больше.",
             f"На дашборде выручка по {rng.randint(8, 12)} регионам нарисована линией, регионы по алфавиту; руководитель видит «падение к концу списка»."][v]
    opts, key = _options(rng, ["Для столбцов начинать ось с нуля; если важны десятые доли — линия или подпись разницы в п. п.",
                               "Горизонтальные столбцы, отсортированные по убыванию: десяток долей в круге не сравнить",
                               "Для несвязанных категорий — столбцы: линия между регионами рисует тренд, которого нет"], v,
                         ["Сделать диаграмму объёмной, чтобы разница читалась точнее", "Оставить как есть, но подписать значения: зритель прочитает точные цифры"])
    return {"scene_title": "Неудачный график", "story": story, "prompt": "Что исправить?", "panel": None, "options": opts, "key": key}


@family("dea_viz_dual", SPEC, "Визуализация", "choice", 2.2, 0.8)
def _(rng):
    q = rng.randint(1, 4)
    x = [f"нед. {i + 1}" for i in range(8)]
    v = _variant(rng, 3)
    if v == 0:
        visits = [rng.randint(180, 220) + 12 * i for i in range(8)]
        k = rng.choice([2, 3, 4])
        series = [{"name": "визиты, тыс.", "axis": "left", "max": 320, "data": visits},
                  {"name": "выручка, млн ₽", "axis": "right", "max": 32 * k, "data": [round(n * k / 10 + rng.randint(-2, 2)) for n in visits]}]
        quote = "Выручка повторяет трафик, значит, рост дал трафик — удваиваем закупку рекламы."
    elif v == 1:
        weekly = [48 - 2 * i + rng.randint(-1, 1) for i in range(8)]  # спад заметен сквозь шум
        cum = [sum(weekly[:i + 1]) for i in range(8)]
        series = [{"name": "выручка с начала квартала, млн ₽", "axis": "left", "max": 400, "data": cum}]
        quote = "Выручка растёт каждую неделю — бизнес на подъёме, увеличиваем план."
    else:
        mean = [rng.randint(2200, 2400) + (600 if i >= 5 else 0) for i in range(8)]
        series = [{"name": "средний чек, ₽", "axis": "left", "max": 4000, "data": mean},
                  {"name": "медианный чек, ₽", "axis": "left", "max": 4000, "data": [rng.randint(1500, 1580) for _ in range(8)]}]
        quote = "Средний чек вырос на четверть — все клиенты стали покупать больше."
    # выручка на графике действительно пропорциональна визитам: ошибка вывода — причинность, а не масштаб осей
    opts, key = _options(rng, ["Корреляция — не причина: обе линии мог поднять общий фактор (сезон, промо); эффект рекламы проверять экспериментом",
                               "Накопительный итог растёт всегда: смотреть понедельные значения — они снижаются",
                               "Средний вырос из-за немногих крупных заказов, медиана стоит: смотреть распределение, а не среднее"], v,
                         ["Ничего: вывод прямо следует из графика", "Ошибка только в стиле: линии нужно сделать сплошными и одного цвета"])
    return {"scene_title": "Вывод по графику", "story": f"Руководитель на разборе Q{q}: «{quote}»",
            "prompt": "Что не так с выводом по этому графику?", "panel": {"type": "chart", "x": x, "series": series}, "options": opts, "key": key}


@family("dea_viz_simpson", SPEC, "Визуализация", "choice", 2.3, 2.3)
def _(rng):
    a, b = rng.choice([("контекст", "соцсети"), ("email", "push"), ("партнёры", "SEO")])
    num = lambda n: f"{n:,}".replace(",", " ")  # noqa: E731
    pct = lambda o, n: f"{100 * o / n:.1f} %".replace(".", ",")  # noqa: E731
    v = _variant(rng, 3)
    if v == 0:
        # объёмы ~100 тыс. визитов на канал: разница CR внутри разрезов — 3–5 стандартных ошибок, а не шум
        va = {"desktop": rng.randint(76, 84) * 1000, "mobile": rng.randint(18, 24) * 1000}
        vb = {"desktop": rng.randint(18, 24) * 1000, "mobile": rng.randint(76, 84) * 1000}
        cra = {"desktop": rng.uniform(5.5, 6.2), "mobile": rng.uniform(1.6, 2.0)}
        crb = {"desktop": cra["desktop"] + rng.uniform(0.7, 1.0), "mobile": cra["mobile"] + rng.uniform(0.4, 0.6)}
        oa = {d: round(va[d] * cra[d] / 100) for d in va}
        ob = {d: round(vb[d] * crb[d] / 100) for d in vb}
        row = lambda ch, dev, n, o: f"{ch:<10}{dev:<10}{num(n):>8}{num(o):>8}{pct(o, n):>9}"  # noqa: E731
        lines = [f"{'канал':<10}{'девайс':<10}{'визиты':>8}{'заказы':>8}{'CR':>9}"]
        for ch, n, o in ((a, va, oa), (b, vb, ob)):
            lines += [row(ch, d, n[d], o[d]) for d in ("desktop", "mobile")]
        lines += [row(a, "всего", sum(va.values()), sum(oa.values())), row(b, "всего", sum(vb.values()), sum(ob.values()))]
        story = (f"Маркетинг хочет урезать бюджет канала «{b}»: на дашборде его общая конверсия {pct(sum(ob.values()), sum(vb.values()))} "
                 f"против {pct(sum(oa.values()), sum(va.values()))} у «{a}».")
    elif v == 1:
        w1, b1 = rng.randint(40, 50), rng.randint(130, 150)
        w2, b2 = round(w1 * (1 + rng.randint(15, 20) / 100)), round(b1 * (1 - rng.randint(4, 8) / 100))
        lines = ["магазин   выручка Q1   выручка Q2   прирост", f"худшие 20 (тренинг)   {w1} млн   {w2} млн   +{round(100 * (w2 / w1 - 1))} %",
                 f"лучшие 20 (без)       {b1} млн  {b2} млн  −{round(100 * (1 - b2 / b1))} %",
                 "остальные (без)       ровно            ровно            +1 %"]
        story = "После Q1 двадцати худшим магазинам провели тренинг продавцов. Директор: «тренинг работает — худшие выросли, а лучшие без него просели»."
    else:
        n1, o1 = rng.randint(20, 30), rng.randint(3, 4)
        n0, o0 = rng.randint(90, 120) * 1000, rng.randint(3800, 4400)
        lines = ["канал       визиты   заказы   CR", f"{a:<10}  {num(n0)}  {num(o0)}   {pct(o0, n0)}",
                 f"{b:<10}  {n1}       {o1}        {pct(o1, n1)}"]
        story = f"Маркетинг хочет перенести весь бюджет в канал «{b}»: его конверсия в разы выше, чем у «{a}»."
    opts, key = _options(rng, [f"«{b}» конвертирует лучше на каждом устройстве; общий проигрыш — из-за доли мобильного трафика (парадокс Симпсона)",
                               "Регрессия к среднему: худшие и лучшие сами сдвигаются к середине — эффект тренинга мерить по контрольной группе",
                               f"Визитов у «{b}» пара десятков: интервал огромный, вывод делать рано — набрать данные"], v,
                         [f"«{b}» хуже: общая конверсия учитывает все визиты сразу, поэтому она надёжнее разрезов",
                          "Выводы верные: цифры в таблице говорят сами за себя"])
    return {"scene_title": "Цифры обманывают", "story": story, "prompt": "Какой вывод корректен?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


# --- Алгоритмы ---


@family("dea_alg_nested", SPEC, "Алгоритмы", "mark", 2.1, -1.1)
def _(rng):
    field = rng.choice(["region", "segment", "city"])
    n, m = rng.randint(200, 900), rng.randint(50, 300)
    v = _variant(rng, 3)
    lines = ["def enrich(orders: list[dict], customers: list[dict]) -> list[dict]:"]
    if rng.random() < 0.5:
        lines.append(f'    """Добавить {field} клиента и сумму в рублях к каждому заказу."""')
    if v == 0:
        lines += ["    rates = load_rates()", "    result = []", "    for o in orders:", f"        {field} = None", "        for c in customers:"]
        key = [len(lines), len(lines) + 1]
        lines += ['            if c["id"] == o["customer_id"]:', f'                {field} = c["{field}"]']
    else:
        lines.append('    by_id = {c["id"]: c for c in customers}')
        if v == 2:
            lines.append("    rates = load_rates()")
        lines += ["    result = []", "    for o in orders:"]
        if v == 1:
            lines.append("        rates = load_rates()  # курсы из файла и внешнего API")
            key = len(lines)
        lines.append(f'        {field} = by_id[o["customer_id"]]["{field}"]')
        if v == 2:
            lines.append('        last = sorted(result, key=lambda r: r["ts"])[-1] if result else None')
            key = len(lines)
            lines.append('        o["gap"] = o["ts"] - last["ts"] if last else 0')
    lines += [f'        result.append({{**o, "{field}": {field}, "rub": o["amount"] * rates[o["cur"]]}})', "    return result"]
    story = [f"Скрипт обогащает {n} тыс. заказов справочником из {m} тыс. клиентов и работает несколько часов.",
             f"Скрипт обогащает {n} тыс. заказов: справочник клиентов уже в словаре, но работа всё равно занимает часы, и всё это время активна сеть.",
             f"Скрипт обогащает {n} тыс. заказов и считает разрыв с предыдущим заказом; справочник — в словаре, а работа всё равно занимает часы."][v]
    return {"scene_title": "Обогащение на всю ночь", "story": story, "prompt": "Нажмите на строку, из-за которой скрипт работает так долго.",
            "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("dea_alg_kmerge", SPEC, "Алгоритмы", "choice", 2.0, 0.4)
def _(rng):
    k, gb, mem = rng.choice([24, 40, 64]), rng.choice([10, 20, 30]), rng.choice([4, 8, 16])
    v = _variant(rng, 3)
    story = [f"Файлов событий — {k}, по {gb} ГБ, каждый отсортирован по ts. Нужен один общий файл, отсортированный по ts; памяти — {mem} ГБ.",
             f"Выгрузка событий — один файл на {gb * k} ГБ в случайном порядке; нужно убрать дубли по event_id. Памяти — {mem} ГБ.",
             f"Два файла по {gb * k // 2} ГБ — заказы и платежи, оба отсортированы по order_id. Нужно соединить их по order_id; памяти — {mem} ГБ."][v]
    opts, key = _options(rng, [f"Слияние {k} потоков через мин-кучу по ts: один проход, в памяти по строке на файл",
                               f"Внешняя сортировка по event_id кусками по {mem} ГБ и слияние, затем один проход с отбросом соседних дублей",
                               "Слияние двух отсортированных файлов (merge join) за один проход с двумя указателями"], v,
                         ["Прочитать всё в память и обработать целиком: так проще всего", "Склеить файлы подряд и обработать построчно без сортировки"])
    return {"scene_title": "Большие файлы", "story": story, "prompt": "Как это сделать?", "panel": None, "options": opts, "key": key}


@family("dea_alg_reservoir", SPEC, "Алгоритмы", "choice", 2.0, 1.3)
def _(rng):
    k = rng.choice([1000, 5000, 10000])
    what = rng.choice(["кликов", "логов приложения", "транзакций"])
    v = _variant(rng, 3)
    story = [f"Из потока {what} неизвестной длины нужна равномерная случайная выборка ровно {k} событий за один проход; весь поток в память не влезает.",
             f"Из потока {what} неизвестной длины нужна выборка ровно {k} событий, где шанс попасть пропорционален сумме события; один проход, поток в память не влезает.",
             f"Из потока {what} нужна выборка ровно по {k} событий на каждую из {rng.randint(5, 12)} стран, равномерная внутри страны; один проход."][v]
    opts, key = _options(rng, [f"Reservoir sampling: первые {k} событий в резерв, i-е заменяет случайное с вероятностью {k}/i",
                               f"Взвешенный резервуар: ключ u^(1/вес) для каждого события, держать {k} наибольших в мин-куче",
                               "Отдельный резервуар на каждую страну, событие идёт в резервуар своей страны"], v,
                         [f"Брать каждое сотое событие, пока не наберётся {k}", f"Взять первые {k} событий потока: порядок прихода случаен"])
    return {"scene_title": "Выборка из потока", "story": story, "prompt": "Какой алгоритм выбрать?", "panel": None, "options": opts, "key": key}


@family("dea_alg_sketch", SPEC, "Алгоритмы", "choice", 2.2, 2.4)
def _(rng):
    n, m = rng.randint(20, 60), rng.randint(6, 15)
    country, platform = rng.choice(["RU", "KZ", "BY"]), rng.choice(["ios", "android", "web"])
    v = _variant(rng, 3)
    if v == 0:
        lines = ["-- предложение аналитика: MAU из дневной витрины", "SELECT sum(dau) AS mau",
                 "FROM mart_dau_daily  -- day, country, platform, channel, dau = uniqExact(user_id)",
                 "WHERE day BETWEEN '2026-09-01' AND '2026-09-30'", f"  AND country = '{country}' AND platform = '{platform}';"]
        story = (f"Продукту нужен MAU за любой период и по любому сочетанию фильтров (страна × платформа × канал) за секунды, погрешность 1–2 % допустима. "
                 f"Сочетаний тысячи — хранить на каждое по дню полный список пользователей дорого, а uniqExact по {n} млрд сырых событий за месяц считается {m} мин.")
    elif v == 1:
        lines = ["-- текущий запрос: топ-100 поисковых запросов за день", "SELECT query, count() AS c FROM search_events",
                 "WHERE day = today() - 1 GROUP BY query ORDER BY c DESC LIMIT 100;  -- GROUP BY по ~2 млрд уникальных строк"]
        story = f"Топ-100 поисковых запросов нужно показывать почти в реальном времени по потоку {n} млрд событий в сутки; GROUP BY по всем уникальным запросам не влезает в память."
    else:
        lines = ["-- требование финансов: точное число уникальных плательщиков за любое скользящее окно 7–90 дней",
                 f"SELECT uniqExact(user_id) FROM payments WHERE day BETWEEN … AND …;  -- {m} мин на 90 дней"]
        story = f"Финансы требуют точное (без погрешности) число уникальных плательщиков за любое окно до 90 дней, ответ — за секунды. Платежей {n} млрд."
    opts, key = _options(rng, ["Хранить по дню и сегменту скетч uniqState(user_id) и сливать его через uniqMerge: погрешность около 1–2 %, зато состояния складываются",
                               "Count-Min Sketch по запросам и куча кандидатов (или Space-Saving): фиксированная память, небольшая погрешность в частотах",
                               "Хранить по дню битмап плательщиков (groupBitmapState) и объединять за окно: точное число без пересчёта сырых данных"], v,
                         ["Хранить по дню и сегменту готовую оценку HyperLogLog (число) и для периода брать среднее оценок, умноженное на число дней",
                          "MAU = sum(dau) × коэффициент повторных визитов, один раз посчитанный по полному месяцу"])
    return {"scene_title": "Витрина на лету", "story": story, "prompt": "Как построить витрину?", "panel": {"type": "code", "lang": "sql", "lines": lines}, "options": opts, "key": key}
