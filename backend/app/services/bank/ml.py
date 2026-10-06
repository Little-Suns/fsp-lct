"""ML / DS, сюжет «Модель деградирует»: сценарные семейства с логами, графиками и кодом (Classic ML, CV, NLP / LLM)."""

from app.services.items import _choice, _log, family


def _dec(x: float, nd: int = 2) -> str:
    return f"{x:.{nd}f}".replace(".", ",")


def _rub(n: int) -> str:
    return f"{n:,}".replace(",", " ")


# --- Постановка задачи (простое семейство: b = −1.2) ---


@family("mlds_task_cost_threshold", "ML / DS", "Постановка задачи", "choice", 2.0, 0.3)
def _(rng):
    fn, fp = rng.choice([(12000, 300), (25000, 500), (8000, 150), (40000, 900)])
    what = rng.choice(["антифрода", "проверки заявок на кредит", "модерации переводов"])
    opts, key = _choice(rng, f"Выбрать порог на валидации по минимуму ожидаемой стоимости ошибок: {_rub(fn)} ₽ за пропуск, {_rub(fp)} ₽ за ложную блокировку", [
        "Оставить порог 0,5: вероятности модели уже откалиброваны, и это стандартный выбор",
        "Выбрать порог, при котором accuracy на отложенной выборке максимальна",
        "Выбрать порог, при котором precision и recall на валидации совпадают",
    ])
    return {"scene_title": "Порог срабатывания", "story": f"Модель {what} выдаёт вероятность. Бизнес посчитал: пропущенный случай стоит в среднем {_rub(fn)} ₽, "
            f"ложная блокировка клиента — {_rub(fp)} ₽ (звонок в поддержку и отток).",
            "prompt": "Как выбрать порог срабатывания?", "panel": None, "options": opts, "key": key}


@family("mlds_task_censored_label", "ML / DS", "Постановка задачи", "mark", 2.3, 1.1)
def _(rng):
    h = rng.choice([30, 45, 60])
    lines = []
    if rng.random() < 0.5:
        lines.append(f"-- owner: ml-retention, v{rng.randint(3, 9)}")
    lines += [
        f"-- обучающая выборка: отток = нет заказов {h} дней после даты среза",
        "SELECT c.client_id, f.orders_90d, f.avg_check, f.days_since_last,",
        "       NOT EXISTS (SELECT 1 FROM orders o",
        "                   WHERE o.client_id = c.client_id",
        "                     AND o.created_at > s.cut_date",
        f"                     AND o.created_at <= s.cut_date + INTERVAL '{h} days') AS churned",
        "FROM snapshots s",
        "JOIN clients c USING (client_id)",
        "JOIN features f ON f.client_id = c.client_id AND f.cut_date = s.cut_date",
        "WHERE s.cut_date <= CURRENT_DATE;",
    ]
    key = len(lines)
    who = rng.choice(["клиентов доставки", "подписчиков сервиса", "держателей карт"])
    return {"scene_title": "Отток из ниоткуда", "story": f"Модель оттока {who} на свежих срезах уверенно предсказывает уход тех, кто просто ещё не успел сделать заказ. "
            f"Метка — нет заказов {h} дней после даты среза.",
            "prompt": "Нажмите на строку, из-за которой в обучение попадают неверные метки.",
            "panel": {"type": "code", "lang": "sql", "lines": lines}, "key": key}


@family("mlds_task_uplift", "ML / DS", "Постановка задачи", "choice", 2.3, 2.0)
def _(rng):
    k, p = rng.uniform(0.8, 1.2), rng.choice([10, 15, 20])
    base = [38, 31, 25, 19, 14, 10, 7, 5, 4, 3]
    treat = [round(v * k) + rng.randint(0, 1) for v in base]
    ctrl = [max(1, t - rng.randint(0, 1)) for t in treat]
    panel = {"type": "chart", "x": [f"Д{i}" for i in range(1, 11)], "marker": {"i": 1, "label": "граница рассылки"}, "series": [
        {"name": "покупки с промокодом, %", "axis": "left", "max": 50, "data": treat},
        {"name": "покупки в контроле без промо, %", "axis": "left", "max": 50, "data": ctrl},
    ]}
    opts, key = _choice(rng, "Модель находит тех, кто купит и без промо: нужна uplift-модель — разница отклика с промо и без него", [
        "Данных мало: расширить рассылку на верхние пять децилей, и эффект станет заметен",
        "Модель недообучена: добавить признаков и деревьев, чтобы точнее ранжировать отклик",
        "Скидка слишком мала для этих клиентов: удвоить промокод для верхних децилей",
    ])
    return {"scene_title": "Промо без эффекта", "story": f"Модель отклика ранжирует клиентов по вероятности покупки, промокод {p} % получают два верхних дециля. "
            "A/B-тест: прироста выручки нет, а скидки съели маржу. На графике — покупки по децилям скора.",
            "prompt": "Что не так в постановке задачи?", "panel": panel, "options": opts, "key": key}


# --- Валидация моделей (простое семейство: b = 0.0) ---


@family("mlds_val_overfit", "ML / DS", "Валидация моделей", "choice", 2.1, -1.3)
def _(rng):
    k = rng.randint(4, 7)
    what = rng.choice(["снимков дефектов", "отзывов по тональности", "документов по типу"])
    train = [round(90 * 0.8 ** i) + rng.randint(0, 2) for i in range(12)]
    val = [round(92 * 0.82 ** i) + rng.randint(0, 2) if i <= k else round(92 * 0.82 ** k) + 3 * (i - k) + rng.randint(0, 2) for i in range(12)]
    panel = {"type": "chart", "x": [str(i) for i in range(1, 13)], "marker": {"i": k, "label": "минимум на валидации"}, "series": [
        {"name": "loss на обучении ×100", "axis": "left", "max": 100, "data": train},
        {"name": "loss на валидации ×100", "axis": "left", "max": 100, "data": val},
    ]}
    opts, key = _choice(rng, f"Переобучение после эпохи {k + 1}: ранняя остановка по валидации, регуляризация или аугментации", [
        "Недообучение: продолжить ещё 20 эпох с тем же learning rate",
        "Learning rate слишком мал: увеличить его в 10 раз и учить заново",
        "Ошибка в метрике: loss на обучении и валидации обязан совпадать",
    ])
    return {"scene_title": "Кривые обучения", "story": f"Классификатор {what} учили 12 эпох. Итоговая модель на тесте хуже, чем чекпойнт из середины обучения.",
            "prompt": "Что происходит и что делать?", "panel": panel, "options": opts, "key": key}


@family("mlds_val_shuffle_kfold", "ML / DS", "Валидация моделей", "mark", 2.3, 1.0)
def _(rng):
    target, col = rng.choice([("дефолт по кредиту", "defaulted_next_month"), ("отток", "churned_next_month"), ("просрочку платежа", "overdue_next_month")])
    cv, prod = rng.choice([("0,91", "0,74"), ("0,88", "0,71"), ("0,93", "0,77")])
    lines = [
        'df = load_transactions("2025-01-01", "2025-12-31")  # много строк на клиента',
        'df = df.sort_values("event_time")',
        f'X, y = df[FEATURES], df["{col}"]',
        "model = LGBMClassifier(n_estimators=600, learning_rate=0.03)",
    ]
    if rng.random() < 0.5:
        lines.append("X = X.fillna(-1)")
    lines.append("cv = KFold(n_splits=5, shuffle=True, random_state=42)")
    key = len(lines)
    lines += ['scores = cross_val_score(model, X, y, cv=cv, scoring="roc_auc")', "print(scores.mean())"]
    return {"scene_title": "Красивая кросс-валидация", "story": f"Модель предсказывает {target} на следующий месяц. На кросс-валидации ROC-AUC {cv}, а на первом же месяце в проде — {prod}.",
            "prompt": "Нажмите на строку, из-за которой оценка на кросс-валидации завышена.",
            "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("mlds_val_calibration", "ML / DS", "Валидация моделей", "choice", 2.3, 2.2)
def _(rng):
    n_pos, v = rng.randint(9, 30) * 1000, rng.randint(3, 9)
    rate = rng.choice([0.5, 1.0, 2.0])
    q = rate / 100
    r = round((1 - q) / q)  # во сколько раз прорежены негативы, чтобы выборка стала 1:1
    mp = round((1 - q) / (2 - q) - rng.uniform(0, 0.04), 2)  # вероятность после обучения на 1:1 ≈ 0,5
    lines = [
        _log("03:10:02", "train", "INFO", f"negatives undersampled: kept 1 of {r} → train set 1:1 (pos {n_pos}, neg {n_pos})"),
        _log("03:41:17", "train", "INFO", f"valid ROC-AUC 0.{rng.randint(88, 93)}, model v{v} registered"),
        _log("09:00:05", "deployer", "INFO", f"fraud-model v{v} serving 100 % traffic"),
        _log("23:59:00", "monitor", "WARN", f"mean predicted p_fraud = {mp:.2f}, observed fraud rate = {rate} %"),
        _log("23:59:01", "finance", "WARN", f"loss reserve forecast exceeds actual losses ×{round(mp * 100 / rate)}"),
    ]
    opts, key = _choice(rng, "Обучение на выборке 1:1 сдвинуло вероятности вверх: поправить их на долю отброшенных негативов или откалибровать на данных с реальной долей", [
        "Ранжирование сломалось после выкладки: модель нужно переобучить с нуля на полной выборке",
        "Модель переобучилась: уменьшить глубину деревьев и число итераций бустинга",
        "Поднять порог блокировки до 0,9 — тогда сумма резерва уменьшится сама",
    ])
    return {"scene_title": "Завышенный резерв", "story": "Вероятности антифрод-модели идут в резерв под потери: резерв = Σ p × сумма операции. "
            "Финансы говорят, что резерв завышен в десятки раз, хотя ROC-AUC отличный.",
            "prompt": "В чём причина и как исправить?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Дрейф данных (простое семейство: b = 0.6) ---


@family("mlds_drift_nulls", "ML / DS", "Дрейф данных", "choice", 2.1, -1.0)
def _(rng):
    f = rng.choice(["доход", "стаж", "семейное положение"])
    rel = rng.randint(3, 5)
    nulls = [rng.randint(1, 4) if i < rel else rng.randint(62, 85) for i in range(8)]
    prec = [rng.randint(71, 76) if i < rel else rng.randint(48, 56) for i in range(8)]
    panel = {"type": "chart", "x": [f"Н{i}" for i in range(1, 9)], "marker": {"i": rel, "label": f"релиз анкеты v{rng.randint(2, 6)}"}, "series": [
        {"name": f"пустые значения «{f}», %", "axis": "left", "max": 100, "data": nulls},
        {"name": "precision скоринга ×100", "axis": "right", "max": 100, "data": prec},
    ]}
    opts, key = _choice(rng, f"Чинить данные: после релиза признак «{f}» перестал приходить — найти, где он теряется, и вернуть в поток", [
        "Срочно переобучить модель на данных двух последних недель",
        "Заполнить пропуски медианой прошлого месяца и работать дальше",
        "Снизить порог модели, чтобы вернуть прежнюю долю одобрений",
    ])
    return {"scene_title": "Пустой признак", "story": "После обновления мобильной анкеты качество скоринга заявок резко просело. Модель и её код не меняли.",
            "prompt": "Что сделать в первую очередь?", "panel": panel, "options": opts, "key": key}


@family("mlds_drift_concept", "ML / DS", "Дрейф данных", "choice", 2.3, 1.4)
def _(rng):
    w, m = rng.randint(14, 40), rng.randint(5, 11)
    p1, p2 = rng.randint(62, 70), rng.randint(31, 42)
    cat = rng.choice(["цифровые товары", "онлайн-игры", "переводы между своими счетами"])
    lines = [
        _log("08:00:00", "monitor", "INFO", f"PSI by feature: amount 0.0{rng.randint(2, 6)}, hour 0.0{rng.randint(3, 7)}, merchant_cat 0.0{rng.randint(2, 5)}, device_age 0.0{rng.randint(3, 6)} — OK"),
        _log("08:00:01", "monitor", "INFO", f"score distribution PSI 0.0{rng.randint(3, 6)} — OK"),
        _log("08:05:12", "feedback", "WARN", f"chargebacks, week {w}: precision@top1% 0.{p1} → 0.{p2}, recall 0.{p1 + 8} → 0.{p2 + 5}"),
        _log("10:20:40", "analysts", "INFO", f"new scheme: series of small test payments, then large transfer; category «{cat}»"),
    ]
    opts, key = _choice(rng, "Концепт-дрейф: связь признаков с целью изменилась — дообучить на свежей разметке и мониторить метрики по ней, а не только PSI", [
        "Дрейфа нет: PSI по всем признакам в норме, просадка — шум в разметке чарджбэков",
        "Ковариатный сдвиг: перевзвесить обучающие примеры по importance weights и обучить заново",
        "В признаке amount появилась утечка таргета: удалить его и переобучить модель",
    ])
    return {"scene_title": "Тихая деградация", "story": f"Антифрод-модель работает {m} месяцев. Распределения признаков стабильны, но по разметке чарджбэков она стала пропускать мошенничество.",
            "prompt": "Что это и что делать?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("mlds_drift_feedback_loop", "ML / DS", "Дрейф данных", "choice", 2.0, 2.1)
def _(rng):
    t = rng.choice(["0,7", "0,8", "0,85"])
    what, label = rng.choice([("операции", "чарджбэка"), ("заявки на кредит", "просрочки"), ("объявления", "жалобы покупателя")])
    opts, key = _choice(rng, "Петля обратной связи: оставить малую случайную долю без вмешательства модели и учитывать вероятность отбора при обучении", [
        "Риска нет: модель учится на последствиях своих решений и со временем только улучшается",
        "Считать все заблокированные моделью случаи положительными и обучать на такой разметке",
        "Переобучать не раз в месяц, а каждый день — тогда разметка будет свежее",
    ])
    return {"scene_title": "Модель учит сама себя", "story": f"Модель блокирует {what} с p > {t}. Заблокированные не доходят до {label}, и их метка остаётся неизвестной. "
            "Модель каждый месяц переобучают на такой разметке.",
            "prompt": "Какой здесь риск и как его снизить?", "panel": None, "options": opts, "key": key}


# --- Feature engineering (простое семейство: b = 1.2) ---


@family("mlds_fe_target_in_x", "ML / DS", "Feature engineering", "mark", 2.1, -1.4)
def _(rng):
    target, what = rng.choice([("churned", "оттока"), ("defaulted", "дефолта"), ("is_fraud", "мошенничества")])
    lines = [f'df = pd.read_parquet("clients_2025q{rng.randint(1, 4)}.parquet")']
    if rng.random() < 0.5:
        lines.append('df = df[df["is_test"] == 0]')
    lines.append(f'y = df["{target}"]')
    lines.append('X = df.drop(columns=["client_id"])')
    key = len(lines)
    lines += [
        "X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=0)",
        "model.fit(X_train, y_train)",
        "print(roc_auc_score(y_val, model.predict_proba(X_val)[:, 1]))  # 1.0",
    ]
    return {"scene_title": "Идеальная модель", "story": f"Стажёр показывает модель {what}: ROC-AUC на валидации — ровно 1,0. Слишком хорошо, чтобы быть правдой.",
            "prompt": "Нажмите на строку с ошибкой.", "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("mlds_fe_high_cardinality", "ML / DS", "Feature engineering", "choice", 2.2, 0.2)
def _(rng):
    rows, card, cc, n_num = rng.randint(12, 30) * 100_000, rng.randint(40, 90) * 1000, rng.randint(800, 1500), rng.randint(30, 60)
    cols = card + cc + n_num
    gb = rows * cols * 8 // 2 ** 30
    lines = [
        _log("11:02:10", "train", "INFO", f"features: {n_num} numeric; categorical: merchant_id ({card} unique), city ({cc} unique)"),
        _log("11:02:11", "train", "INFO", "pd.get_dummies(df, columns=['merchant_id', 'city'])"),
        _log("11:02:58", "train", "ERROR", f"MemoryError: Unable to allocate {gb} GiB for an array with shape ({rows}, {cols}) and data type float64"),
    ]
    opts, key = _choice(rng, "Target encoding по фолдам (out-of-fold) со сглаживанием к среднему, редкие значения — в общую категорию", [
        f"Оставить one-hot, но взять машину с памятью {gb * 2} ГиБ — признаки не потеряются",
        "Label encoding 0…N и подать в логистическую регрессию как число",
        "Удалить merchant_id: признак с высокой кардинальностью — всегда шум",
    ])
    return {"scene_title": "Миллион колонок", "story": "Модель риска мерчантов на градиентном бустинге. После добавления merchant_id обучение падает.",
            "prompt": "Как закодировать merchant_id?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("mlds_fe_te_leak", "ML / DS", "Feature engineering", "mark", 2.4, 2.3)
def _(rng):
    ent, target = rng.choice([("merchant_id", "is_fraud"), ("hotel_id", "is_cancelled"), ("seller_id", "is_returned")])
    cv, ho = rng.choice([("0,97", "0,81"), ("0,95", "0,79"), ("0,96", "0,83")])
    lines = ["df = load_dataset()"]
    if rng.random() < 0.5:
        lines.append('df["hour"] = df["created_at"].dt.hour')
    lines.append(f'te = df.groupby("{ent}")["{target}"].mean()')
    key = len(lines)
    lines += [
        f'df["{ent}_te"] = df["{ent}"].map(te)',
        f'X, y = df[NUM_FEATURES + ["{ent}_te"]], df["{target}"]',
        "cv = GroupKFold(n_splits=5)",
        'print(cross_val_score(LGBMClassifier(), X, y, cv=cv, groups=df["client_id"], scoring="roc_auc").mean())',
    ]
    return {"scene_title": "Кодирование категорий", "story": f"На кросс-валидации ROC-AUC {cv}, а на отложенной выборке, которую не трогали при подготовке признаков, — {ho}. "
            f"У многих {ent} всего несколько записей.",
            "prompt": "Нажмите на строку, из-за которой кросс-валидация завышена.",
            "panel": {"type": "code", "lang": "python", "lines": lines}, "key": [key, key + 1]}


# --- MLOps (простое семейство: b = 1.8) ---


@family("mlds_ops_feature_mismatch", "ML / DS", "MLOps", "choice", 2.1, -1.1)
def _(rng):
    n, v, k = rng.randint(40, 60), f"v{rng.randint(2, 5)}.{rng.randint(10, 40)}", rng.randint(60, 100)
    f = rng.choice(["days_since_last_login", "avg_check_30d", "device_age_days"])
    m = rng.randint(10, 50)
    lines = [
        _log(f"09:{m:02d}:00", "deployer", "INFO", f"feature-pipeline {v} deployed (added feature '{f}')"),
        _log(f"09:{m + 4:02d}:12", "scoring-api", "ERROR", f"ValueError: X has {n + 1} features, but LGBMClassifier is expecting {n} features as input"),
        _log(f"09:{m + 4:02d}:13", "scoring-api", "WARN", f"fallback to rule-based score: {k} % of requests"),
    ]
    opts, key = _choice(rng, "Пайплайн признаков и модель разошлись по версиям: новый признак выкатили раньше модели, обученной на нём", [
        "Файл модели повредился при загрузке: перезалить тот же артефакт в хранилище",
        "Сервису не хватает памяти на новый признак: увеличить лимиты пода",
        "В новых данных появились пропуски, а модель не принимает NaN",
    ])
    return {"scene_title": "Запасные правила", "story": "Утром обновили пайплайн признаков. Через пять минут сервис скоринга перешёл на запасные правила.",
            "prompt": "В чём причина?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("mlds_ops_dynamic_batching", "ML / DS", "MLOps", "choice", 2.2, 0.4)
def _(rng):
    what = rng.choice(["классификатор обращений", "модель модерации отзывов", "NER для документов"])
    h0 = rng.randint(9, 11)
    lat = [rng.randint(500, 700) + i * rng.randint(280, 360) for i in range(8)]
    gpu = [rng.randint(12, 24) for _ in range(8)]
    panel = {"type": "chart", "x": [f"{h0 + i}:00" for i in range(8)], "series": [
        {"name": "p95 задержки, мс", "axis": "left", "max": 4000, "data": lat},
        {"name": "загрузка GPU, %", "axis": "right", "max": 100, "data": gpu},
    ]}
    opts, key = _choice(rng, "Включить динамический батчинг на сервере инференса: собирать запросы в пачки за несколько миллисекунд", [
        "Добавить ещё три GPU и поставить балансировщик перед ними",
        "Перенести модель на CPU: GPU всё равно почти не загружена",
        "Увеличить таймаут клиента до 10 секунд, чтобы запросы не падали",
    ])
    return {"scene_title": "GPU скучает", "story": f"{what.capitalize()} на трансформере работает на одной GPU. Днём поток растёт, p95 уходит за 2 секунды, "
            "а GPU почти простаивает. Сервер обрабатывает запросы по одному.",
            "prompt": "Что сделать первым?", "panel": panel, "options": opts, "key": key}


@family("mlds_ops_snapshot", "ML / DS", "MLOps", "mark", 2.3, 1.3)
def _(rng):
    m, tbl = rng.choice([("оттока", "client_events"), ("скоринга", "loan_features"), ("рекомендаций", "user_sessions")])
    a1, a2 = rng.choice([("0,84", "0,79"), ("0,81", "0,86"), ("0,78", "0,74")])
    lines = [f"# train.py, коммит {rng.randint(0x100000, 0xffffff):06x}", "SEED = 42", "np.random.seed(SEED); random.seed(SEED)"]
    if rng.random() < 0.5:
        lines.append(f'mlflow.set_experiment("{tbl}-model")')
    lines.append(f"df = pd.read_sql(\"SELECT * FROM {tbl} WHERE dt >= now() - interval '90 days'\", conn)")
    key = len(lines)
    lines += [
        "X_train, X_val, y_train, y_val = split_by_time(df, val_days=14)",
        "model = CatBoostClassifier(random_seed=SEED, iterations=800).fit(X_train, y_train)",
        'mlflow.log_metric("auc", roc_auc_score(y_val, model.predict_proba(X_val)[:, 1]))',
        'mlflow.catboost.log_model(model, "model")',
    ]
    return {"scene_title": "Невоспроизводимо", "story": f"Модель {m} переобучили тем же коммитом через неделю: AUC {a1} → {a2}. Понять, виноват код или данные, не получается.",
            "prompt": "Нажмите на строку, из-за которой обучение невоспроизводимо.",
            "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


# --- Алгоритмы (простое семейство: b = −0.4) ---


@family("mlds_alg_vectorize", "ML / DS", "Алгоритмы", "choice", 2.1, -1.5)
def _(rng):
    n, col = rng.randint(3, 20), rng.choice(["amount", "price", "total"])
    lines = ["for i in range(len(df)):", f'    df.loc[i, "{col}_rub"] = df.loc[i, "{col}"] * rates[df.loc[i, "currency"]]']
    opts, key = _choice(rng, f'Векторизовать: df["{col}"] * df["currency"].map(rates) — одна операция над столбцами', [
        "Заменить df.loc на df.iloc внутри того же цикла по строкам",
        "Распараллелить этот цикл на четыре потока через threading",
        "Отсортировать df по currency, затем пройти тем же циклом",
    ])
    return {"scene_title": "Пересчёт в рубли", "story": f"Пересчёт сумм в рубли по {n} млн строк перед обучением идёт больше часа.",
            "prompt": "Как ускорить?", "panel": {"type": "code", "lang": "python", "lines": lines}, "options": opts, "key": key}


@family("mlds_alg_softmax", "ML / DS", "Алгоритмы", "mark", 2.3, 0.9)
def _(rng):
    ep, big = rng.randint(3, 12), rng.choice([800, 1200, 2500])
    lines = ["def cross_entropy(logits: np.ndarray, y: np.ndarray) -> float:"]
    if rng.random() < 0.5:
        lines.append("    logits = logits.astype(np.float64)")
    lines.append("    exp = np.exp(logits)")
    key = len(lines)
    lines += ["    probs = exp / exp.sum(axis=1, keepdims=True)", "    return float(-np.log(probs[np.arange(len(y)), y]).mean())"]
    return {"scene_title": "loss = nan", "story": f"На {ep}-й эпохе loss самописного классификатора стал nan. Логиты к этому моменту доходят до {big}.",
            "prompt": "Нажмите на строку, где возникает переполнение.", "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("mlds_alg_auc_ranks", "ML / DS", "Алгоритмы", "choice", 2.2, 1.9)
def _(rng):
    n, p = rng.choice([20, 50, 120]), rng.choice([5, 10, 20])
    lines = [
        "def auc(scores, labels):",
        "    pos = [s for s, l in zip(scores, labels) if l == 1]",
        "    neg = [s for s, l in zip(scores, labels) if l == 0]",
        "    hits = sum((a > b) + 0.5 * (a == b) for a in pos for b in neg)",
        "    return hits / (len(pos) * len(neg))",
    ]
    opts, key = _choice(rng, "Через ранги: отсортировать по скору, AUC = (сумма рангов положительных − n₊(n₊+1)/2) / (n₊·n₋), ничьи — средним рангом", [
        "Посчитать долю верных пар на случайных 1000 парах и домножить её на число всех пар",
        "Заменить ROC-AUC на accuracy при пороге 0,5: для отчёта это та же метрика",
        "Распараллелить двойной цикл на 32 процесса: квадратичная сложность здесь приемлема",
    ])
    return {"scene_title": "Ночной отчёт", "story": f"Самописный ROC-AUC для ежедневного отчёта по {n} млн строк с долей положительных {p} % не укладывается в ночное окно.",
            "prompt": "Как посчитать ту же метрику быстро и точно?", "panel": {"type": "code", "lang": "python", "lines": lines}, "options": opts, "key": key}
