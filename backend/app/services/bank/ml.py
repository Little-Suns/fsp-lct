"""ML / DS, сюжет «Не бигль» (зоомаркетплейс, у которого поползли модели): сценарные семейства с логами, графиками и кодом (Classic ML, CV, NLP / LLM).
У каждого семейства три варианта механики (items._variant), правильные ответы других вариантов — среди дистракторов."""

from app.services.items import _log, _options, _variant, family


def _dec(x: float, nd: int = 2) -> str:
    return f"{x:.{nd}f}".replace(".", ",")


def _rub(n: int) -> str:
    return f"{n:,}".replace(",", " ")


# --- Постановка задачи (простое семейство: b = −1.2) ---


@family("mlds_task_cost_threshold", "ML / DS", "Постановка задачи", "choice", 2.0, 0.3)
def _(rng):
    fn, fp = rng.choice([(12000, 300), (25000, 500), (8000, 150), (40000, 900)])
    what = rng.choice(["антифрода", "проверки заявок на кредит", "модерации переводов"])
    v = _variant(rng, 3)
    story = [f"Бизнес посчитал: пропущенный случай стоит в среднем {_rub(fn)} ₽, ложная блокировка клиента — {_rub(fp)} ₽ (звонок в поддержку и отток).",
             f"Срабатывания проверяет вручную отдел из {rng.randint(5, 12)} человек: он успевает разобрать не больше {rng.choice([300, 500, 800])} случаев в день, остальное ждёт.",
             f"Регулятор требует, чтобы проверка ловила не меньше {rng.choice([90, 95])} % подтверждённых случаев; ложные срабатывания — забота компании."][v]
    opts, key = _options(rng, [f"Подобрать на валидации порог с минимумом суммы {_rub(fn)} ₽ × пропуски + {_rub(fp)} ₽ × ложные блокировки",
                               "Отдавать на проверку столько верхних по скору случаев, сколько отдел успевает разобрать за день",
                               "Взять порог, при котором полнота на валидации не ниже требуемой, а ложных срабатываний меньше всего"], v,
                         ["Оставить порог 0,5: вероятности бустинга уже откалиброваны, а цену ошибок модель учла при обучении через веса классов",
                          "Выбрать порог, при котором accuracy на отложенной выборке максимальна", "Выбрать порог, где precision и recall на валидации равны"])
    return {"scene_title": "Порог срабатывания", "story": f"Модель {what} в платёжном сервисе маркетплейса выдаёт вероятность. {story}",
            "prompt": "Как выбрать порог срабатывания?", "panel": None, "options": opts, "key": key}


@family("mlds_task_censored_label", "ML / DS", "Постановка задачи", "mark", 2.3, 1.1)
def _(rng):
    h = rng.choice([30, 45, 60])
    v = _variant(rng, 3)
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
    ]
    lines.append("JOIN features f ON f.client_id = c.client_id  -- витрина признаков на сегодня" if v == 1 else
                 "JOIN features f ON f.client_id = c.client_id AND f.cut_date = s.cut_date")
    if v == 1:
        key = len(lines)
    lines.append("WHERE s.cut_date <= CURRENT_DATE;" if v == 0 else f"WHERE s.cut_date <= CURRENT_DATE - INTERVAL '{h} days'")
    if v == 0:
        key = len(lines)
    if v == 2:
        lines.append("  AND c.status = 'active';")
        key = len(lines)
    who = rng.choice(["клиентов доставки", "подписчиков сервиса", "держателей карт"])
    story = [f"Модель оттока {who} на свежих срезах уверенно предсказывает уход тех, кто просто ещё не успел сделать заказ.",
             f"Модель оттока {who} на исторической проверке почти идеальна, а в проде угадывает немногим лучше случайного.",
             f"Модель оттока {who} почти никогда не предсказывает уход: в обучающей выборке ушедших — доли процента."][v]
    return {"scene_title": "Обучающая выборка", "story": f"{story} Метка — нет заказов {h} дней после даты среза.",
            "prompt": "Нажмите на строку, из-за которой обучающая выборка собрана неверно.",
            "panel": {"type": "code", "lang": "sql", "lines": lines}, "key": key}


@family("mlds_task_uplift", "ML / DS", "Постановка задачи", "choice", 2.3, 2.0)
def _(rng):
    k, p = rng.uniform(0.8, 1.2), rng.choice([10, 15, 20])
    v = _variant(rng, 3)
    if v == 0:
        base = [38, 31, 25, 19, 14, 10, 7, 5, 4, 3]
        treat = [round(x * k) + rng.randint(0, 1) for x in base]
        ctrl = [max(1, t - rng.randint(0, 1)) for t in treat]
        panel = {"type": "chart", "x": [f"Д{i}" for i in range(1, 11)], "marker": {"i": 1, "label": "граница рассылки"}, "series": [
            {"name": "покупки с промокодом, %", "axis": "left", "max": 50, "data": treat},
            {"name": "покупки в контроле без промо, %", "axis": "left", "max": 50, "data": ctrl}]}
        story = (f"Модель отклика маркетплейса ранжирует клиентов по вероятности покупки, промокод {p} % получают два верхних дециля. "
                 "A/B-тест: прироста выручки нет, а скидки съели маржу. На графике — покупки по децилям скора.")
    elif v == 1:
        a, b = rng.randint(30, 45), rng.randint(8, 14)
        panel = {"type": "code", "lang": "text", "lines": [
            "период: прошлый квартал, без A/B", f"получили промокод {p} %: {_rub(rng.randint(40, 90) * 1000)} клиентов, покупали {a} %",
            f"не получили: {_rub(rng.randint(400, 900) * 1000)} клиентов, покупали {b} %", "кому давали промокод: решал менеджер, обычно — активным клиентам"]}
        story = f"Аналитик пишет: «промокод {p} % поднимает покупки в {_dec(a / b, 1)} раза, давайте раздадим его всем»."
    else:
        d, ci = rng.choice([0.3, 0.4, 0.6]), rng.choice([2.0, 2.5, 3.0])
        panel = {"type": "code", "lang": "text", "lines": [
            f"A/B промокода {p} %: группа B — 2 % трафика, {rng.randint(10, 14)} дней",
            f"выручка на клиента: B − A = +{_dec(d, 1)} %, 95 % ДИ: ±{_dec(ci, 1)} %", "ожидаемый эффект по бизнес-плану: +1 %"]}
        story = f"Команда хочет закрыть промо-направление: «A/B показал, что промокод {p} % не работает»."
    opts, key = _options(rng, ["Скор находит тех, кто купит и без промо: нужна uplift-модель — разница отклика с промо и без",
                               "Сравнение без рандомизации: промо получали самые активные — эффект нужно мерить A/B-тестом",
                               "Тест не имеет мощности: эффект меньше шума — рассчитать размер выборки и повторить"], v,
                         ["Модель недообучена: добавить признаков истории покупок и деревьев, чтобы точнее ранжировать вероятность отклика в верхних децилях",
                          "Скидка мала для этих клиентов: удвоить промокод"])
    return {"scene_title": "Эффект промо", "story": story, "prompt": "Что не так в постановке и что делать?", "panel": panel, "options": opts, "key": key}


# --- Валидация моделей (простое семейство: b = 0.0) ---


@family("mlds_val_overfit", "ML / DS", "Валидация моделей", "choice", 2.1, -1.3)
def _(rng):
    k = rng.randint(4, 7)
    what = rng.choice(["снимков дефектов", "отзывов по тональности", "документов по типу"])
    v = _variant(rng, 3)
    if v == 0:
        train = [round(90 * 0.8 ** i) + rng.randint(0, 2) for i in range(12)]
        val = [round(92 * 0.82 ** i) + rng.randint(0, 2) if i <= k else round(92 * 0.82 ** k) + 3 * (i - k) + rng.randint(0, 2) for i in range(12)]
        marker = {"i": k, "label": "минимум на валидации"}
    elif v == 1:
        train = [max(70, round(90 - 4 * i)) + rng.randint(0, 2) for i in range(12)]
        val = [t + rng.randint(1, 3) for t in train]
        marker = None
    else:
        train = [round(90 * 0.85 ** i) if i < k else rng.randint(45, 95) for i in range(12)]
        val = [t + rng.randint(1, 4) for t in train]
        marker = {"i": k, "label": "learning rate ×10 по расписанию"}
    panel = {"type": "chart", "x": [str(i) for i in range(1, 13)], "series": [
        {"name": "loss на обучении ×100", "axis": "left", "max": 100, "data": [min(t, 100) for t in train]},
        {"name": "loss на валидации ×100", "axis": "left", "max": 100, "data": [min(x, 100) for x in val]}]}
    if marker:
        panel["marker"] = marker
    opts, key = _options(rng, [f"Переобучение после эпохи {k + 1}: ранняя остановка по валидации и регуляризация",
                               "Недообучение: оба loss высокие и почти не падают — модель слишком простая для задачи",
                               "Шаг обучения слишком велик: после увеличения loss скачет — уменьшить его или включить warmup"], v,
                         ["Ошибка в метрике: loss на обучении и валидации обязан совпадать", "Нужно больше данных разметки: других выводов по кривым сделать нельзя"])
    return {"scene_title": "Кривые обучения", "story": f"Распознавание пород всё ещё не решило, кто такой Рей, а у соседей своя беда: классификатор {what} учили 12 эпох. Качество на тесте не устраивает.",
            "prompt": "Что происходит и что делать?", "panel": panel, "options": opts, "key": key}


@family("mlds_val_shuffle_kfold", "ML / DS", "Валидация моделей", "mark", 2.3, 1.0)
def _(rng):
    target, col = rng.choice([("дефолт по кредиту", "defaulted_next_month"), ("отток", "churned_next_month"), ("просрочку платежа", "overdue_next_month")])
    cv, prod = rng.choice([("0,91", "0,74"), ("0,88", "0,71"), ("0,93", "0,77")])
    v = _variant(rng, 3)
    lines = ['df = load_transactions("2025-01-01", "2025-12-31")  # много строк на клиента', 'df = df.sort_values("event_time")',
             f'X, y = df[FEATURES], df["{col}"]', "model = LGBMClassifier(n_estimators=600, learning_rate=0.03)"]
    if rng.random() < 0.5:
        lines.append("X = X.fillna(-1)")
    if v == 0:
        lines.append("cv = KFold(n_splits=5, shuffle=True, random_state=42)")
        key = len(lines)
        lines += ['scores = cross_val_score(model, X, y, cv=cv, scoring="roc_auc")', "print(scores.mean())"]
    elif v == 1:
        lines.append("X = SelectKBest(f_classif, k=40).fit_transform(X, y)  # отбор по всем данным")
        key = len(lines)
        lines += ["cv = TimeSeriesSplit(n_splits=5)", 'scores = cross_val_score(model, X, y, cv=cv, scoring="roc_auc")', "print(scores.mean())"]
    else:
        lines += ["scores = []", "for tr, te in TimeSeriesSplit(n_splits=5).split(X):",
                  "    model.fit(X.iloc[tr], y.iloc[tr], eval_set=[(X.iloc[te], y.iloc[te])], callbacks=[early_stopping(50)])"]
        key = len(lines)
        lines += ["    scores.append(roc_auc_score(y.iloc[te], model.predict_proba(X.iloc[te])[:, 1]))", "print(np.mean(scores))"]
    return {"scene_title": "Красивая кросс-валидация", "story": f"Модель предсказывает {target} на следующий месяц. На кросс-валидации ROC-AUC {cv}, а на первом же месяце в проде — {prod}.",
            "prompt": "Нажмите на строку, из-за которой оценка на кросс-валидации завышена.",
            "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("mlds_val_calibration", "ML / DS", "Валидация моделей", "choice", 2.3, 2.2)
def _(rng):
    n_pos, ver = rng.randint(9, 30) * 1000, rng.randint(3, 9)
    rate = rng.choice([0.5, 1.0, 2.0])
    v = _variant(rng, 3)
    if v == 0:
        r = round((1 - rate / 100) / (rate / 100))
        mp = round(rng.uniform(0.12, 0.3), 2)
        times = round(mp * 100 / rate)
        lines = [_log("03:10:02", "train", "INFO", f"negatives undersampled: kept 1 of {r} → train set 1:1 (pos {n_pos}, neg {n_pos})"),
                 _log("03:41:17", "train", "INFO", f"valid ROC-AUC 0.{rng.randint(88, 93)}, model v{ver} registered"),
                 _log("23:59:00", "monitor", "WARN", f"mean predicted p_fraud = {mp:.2f}, observed fraud rate = {rate} %"),
                 _log("23:59:01", "finance", "WARN", f"loss reserve forecast exceeds actual losses ×{times}")]
        story = "Финансы говорят, что резерв под потери сильно завышен, хотя ROC-AUC отличный."
    elif v == 1:
        lines = [_log("03:10:02", "train", "INFO", "label: default within 3 months after issue; train set 2021–2025, full, no sampling"),
                 _log("03:41:17", "train", "INFO", f"valid ROC-AUC 0.{rng.randint(80, 86)}, calibration ECE 0.01, model v{ver} registered"),
                 _log("23:59:00", "finance", "INFO", "reserve = Σ p_default × exposure, horizon: 12 months (МСФО 9)"),
                 _log("23:59:01", "finance", "WARN", f"realized 12-month losses exceed reserve ×{rng.randint(3, 4)}")]
        story = "Финансы говорят, что резерв под потери занижен в разы, хотя модель хорошо откалибрована."
    else:
        new = rng.randint(15, 30)
        lines = [_log("03:41:17", "train", "INFO", f"valid ROC-AUC 0.{rng.randint(82, 88)}, ECE overall 0.01, model v{ver} registered"),
                 _log("23:59:00", "monitor", "INFO", f"mean predicted p = {_dec(rate, 1)} %, observed = {_dec(rate, 1)} % — overall OK"),
                 _log("23:59:00", "monitor", "WARN", f"segment new_clients ({new} % of exposure): predicted {_dec(rate / 2, 2)} %, observed {_dec(rate * 2, 1)} %"),
                 _log("23:59:01", "finance", "WARN", f"reserve error concentrated in new clients ({new} % of portfolio)")]
        story = "Финансы говорят, что резерв в целом сходится, но по новым клиентам систематически занижен."
    opts, key = _options(rng, ["Выборка 1:1 завысила вероятности: пересчитать их с поправкой на прореживание негативов или откалибровать",
                               "Модель предсказывает дефолт за 3 месяца, а резерв нужен на 12: обучать на метке того же горизонта",
                               "В среднем вероятности верны, но по новым клиентам занижены: проверять и калибровать по сегментам"], v,
                         ["Ранжирование сломалось после выкладки: переобучить модель с нуля на полной выборке", "Поднять порог одобрения — резерв выровняется сам"])
    return {"scene_title": "Резерв не сходится", "story": f"Вероятности модели идут в резерв под потери: резерв = Σ p × сумма. {story}",
            "prompt": "В чём причина и как исправить?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Дрейф данных (простое семейство: b = 0.6) ---


@family("mlds_drift_nulls", "ML / DS", "Дрейф данных", "choice", 2.1, -1.0)
def _(rng):
    rel = rng.randint(3, 5)
    v = _variant(rng, 3)
    # обе ошибки единиц делят значение на 12: медиана падает до ~8 % от прежней, а не до нуля (ноль — это подстановка нулей)
    f, how = rng.choice([("доход", "за месяц вместо года"), ("стаж", "в годах вместо месяцев")])
    name, data = [(f"пустые значения «{f}», %", [rng.randint(1, 4) if i < rel else rng.randint(62, 85) for i in range(8)]),
                  (f"медиана «{f}», % от прежней", [rng.randint(95, 104) if i < rel else rng.randint(7, 9) for i in range(8)]),
                  (f"нули в «{f}», %", [rng.randint(1, 3) if i < rel else rng.randint(40, 70) for i in range(8)])][v]
    panel = {"type": "chart", "x": [f"Н{i}" for i in range(1, 9)], "marker": {"i": rel, "label": f"релиз анкеты v{rng.randint(2, 6)}"}, "series": [
        {"name": name, "axis": "left", "max": 110, "data": data},
        {"name": "precision скоринга ×100", "axis": "right", "max": 100, "data": [rng.randint(71, 76) if i < rel else rng.randint(48, 56) for i in range(8)]}]}
    opts, key = _options(rng, [f"Чинить данные: найти, где после релиза теряется «{f}», и вернуть признак в поток",
                               f"«{f}» стал приходить {how}: привести единицы в пайплайне",
                               f"Анкета подставляет 0 вместо пустого «{f}»: исправить анкету, такие нули — не данные"], v,
                         ["Срочно переобучить модель на данных двух последних недель, чтобы она привыкла к новой анкете",
                          "Снизить порог модели, чтобы вернуть прежнюю долю одобрений"])
    return {"scene_title": "Признак сломался", "story": "После обновления мобильной анкеты качество скоринга заявок резко просело. Модель и её код не меняли.",
            "prompt": "Что сделать в первую очередь?", "panel": panel, "options": opts, "key": key}


@family("mlds_drift_concept", "ML / DS", "Дрейф данных", "choice", 2.3, 1.4)
def _(rng):
    w, m = rng.randint(14, 40), rng.randint(5, 11)
    p1, p2 = rng.randint(62, 70), rng.randint(31, 42)
    cat = rng.choice(["цифровые товары", "онлайн-игры", "переводы между своими счетами"])
    v = _variant(rng, 3)
    ok = f"PSI by feature: amount 0.0{rng.randint(2, 6)}, hour 0.0{rng.randint(3, 7)}, merchant_cat 0.0{rng.randint(2, 5)}, device_age 0.0{rng.randint(3, 6)} — OK"
    if v == 0:
        lines = [_log("08:00:00", "monitor", "INFO", ok), _log("08:00:01", "monitor", "INFO", f"score distribution PSI 0.0{rng.randint(3, 6)} — OK"),
                 _log("08:05:12", "feedback", "WARN", f"chargebacks, week {w}: precision@top1% 0.{p1} → 0.{p2}, recall 0.{p1 + 8} → 0.{p2 + 5}"),
                 _log("10:20:40", "analysts", "INFO", f"new scheme: series of small test payments, then large transfer; category «{cat}»")]
        story = "Распределения признаков стабильны, но по разметке чарджбэков модель стала пропускать мошенничество."
    elif v == 1:
        lines = [_log("08:00:00", "monitor", "WARN", f"PSI by feature: device_age 0.{rng.randint(28, 45)} — ALERT, amount 0.0{rng.randint(2, 6)}, hour 0.0{rng.randint(3, 7)}"),
                 _log("08:00:01", "marketing", "INFO", "акция для новых смартфонов: приток клиентов с новыми устройствами"),
                 _log("08:05:12", "feedback", "INFO", f"chargebacks, matured weeks: precision@top1% 0.{p1} → 0.{p1 - rng.randint(0, 1)}, recall stable")]
        story = "Мониторинг поднял тревогу по дрейфу признака. Команда предлагает срочно переобучить модель."
    else:
        lines = [_log("08:00:00", "monitor", "INFO", ok),
                 _log("08:05:12", "feedback", "WARN", f"chargebacks, week {w}: precision@top1% 0.{p1} → 0.{p2}"),
                 _log("09:10:00", "data-eng", "INFO", f"bank-partner-{rng.randint(2, 5)} switched chargeback export to API v2 on week {w - 1}; old file feed stopped"),
                 _log("09:10:02", "data-eng", "WARN", f"chargebacks received per week: {rng.randint(900, 1200)} → {rng.randint(300, 450)}")]
        story = "По разметке чарджбэков модель «стала хуже»: precision упал, хотя распределения признаков и скоров ровные."
    opts, key = _options(rng, ["Концепт-дрейф: изменилась связь признаков с целью — дообучить на свежей разметке",
                               "Сдвиг признака без потери качества: метрики по разметке в норме — наблюдать, не переобучать вслепую",
                               "Сломалась разметка: часть чарджбэков перестала приходить — чинить поток меток, а не модель"], v,
                         ["Дрейфа нет: просадка — шум в разметке чарджбэков, ничего не делать", "В amount появилась утечка таргета: удалить признак"])
    return {"scene_title": "Антифрод меняется", "story": f"Антифрод-модель платёжного кошелька маркетплейса работает {m} месяцев. {story}",
            "prompt": "Что это и что делать?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("mlds_drift_feedback_loop", "ML / DS", "Дрейф данных", "choice", 2.0, 2.1)
def _(rng):
    t = rng.choice(["0,7", "0,8", "0,85"])
    what, label = rng.choice([("операции", "чарджбэка"), ("заявки на кредит", "просрочки"), ("объявления", "жалобы покупателя")])
    v = _variant(rng, 3)
    story = [f"Модель блокирует {what} с p > {t}. Заблокированные не доходят до {label}, и их метка остаётся неизвестной. Модель каждый месяц переобучают на такой разметке.",
             "Модель прогнозирует спрос, магазины заказывают товар по прогнозу. Когда товар кончается на полке, продажи стоят на нуле — и на этих продажах модель переобучают.",
             f"Модель блокирует {what} и сразу сообщает клиенту точную причину отказа. Через месяц после каждого обновления пропуски мошенничества снова растут."][v]
    opts, key = _options(rng, ["Петля обратной связи: оставлять случайную долю без вмешательства модели и учитывать вероятность отбора",
                               "Продажи ограничены остатками: восстанавливать спрос с учётом дефицита, а не учиться на продажах как есть",
                               "Мошенники подстраиваются под модель: не раскрывать причины отказов и обновлять модель и правила чаще"], v,
                         ["Риска нет: модель учится на последствиях своих решений и только улучшается",
                          "Считать все заблокированные моделью случаи положительными — в уверенных решениях модель не ошибается"])
    return {"scene_title": "Модель влияет на данные", "story": story, "prompt": "Какой здесь риск и как его снизить?", "panel": None, "options": opts, "key": key}


@family("mlds_drift_label_maturity", "ML / DS", "Дрейф данных", "choice", 2.3, 2.6)
def _(rng):
    win = rng.choice([30, 45, 60])
    d0 = rng.randint(1, 9)
    x = [f"нед. {d0 + i}" for i in range(8)]
    matured = rng.choice([31, 38, 44])
    v = _variant(rng, 3)
    if v == 0:
        prec = [rng.randint(62, 68) for _ in range(5)] + [rng.randint(52, 57), rng.randint(40, 46), rng.randint(25, 33)]
        second = {"name": "PSI входных признаков ×100", "axis": "right", "max": 30, "data": [rng.randint(3, 7) for _ in range(8)]}
        story = f"Precision последних недель резко падает, PSI признаков ровный, модель не менялась. Метки — чарджбэки, окно {win} дней; за последние 14 дней созрело {matured} % меток."
    elif v == 1:
        win = 30  # на графике 8 недель: созревшими должны быть хотя бы первые недели
        prec = [68 - 4 * i + rng.randint(-1, 1) for i in range(8)]
        second = {"name": "PSI входных признаков ×100", "axis": "right", "max": 30, "data": [rng.randint(3, 7) for _ in range(8)]}
        story = f"Precision падает неделя за неделей, включая недели, по которым все метки давно созрели (окно {win} дней). PSI признаков ровный, модель не менялась."
    else:
        at = rng.randint(4, 5)
        prec = [rng.randint(62, 68) if i < at else rng.randint(38, 45) for i in range(8)]
        second = {"name": "PSI распределения скоров ×100", "axis": "right", "max": 30, "data": [rng.randint(2, 4) if i < at else rng.randint(20, 28) for i in range(8)]}
        story = f"Precision упал скачком в одну неделю — и не только в свежих, но и в созревших когортах (окно {win} дней). PSI входных признаков ровный."
    panel = {"type": "chart", "x": x, "series": [{"name": "precision@1% по меткам на сегодня, %", "axis": "left", "max": 100, "data": prec}, second]}
    opts, key = _options(rng, [f"Метки не созрели (чарджбэк — до {win} дн.): сравнивать только созревшие когорты",
                               "Падают и созревшие когорты: деградация настоящая — разбирать новые схемы и дообучать на созревшей разметке",
                               "Скоры сдвинулись скачком при ровных признаках: искать изменение в сервинге — версию модели, порог, препроцессинг"], v,
                         ["Концепт-дрейф: мошенники сменили схему, модель надо срочно переобучить на последних двух неделях",
                          "Сезонность фрода: сравнить с теми же неделями прошлого года и снизить порог"])
    return {"scene_title": "Precision падает", "story": f"Антифрод маркетплейса: {story}", "prompt": "Что происходит на самом деле?", "panel": panel, "options": opts, "key": key}


# --- Feature engineering (простое семейство: b = 1.2) ---


@family("mlds_fe_target_in_x", "ML / DS", "Feature engineering", "mark", 2.1, -1.4)
def _(rng):
    target, what, post = rng.choice([("churned", "оттока", "closure_request_ts"), ("defaulted", "дефолта", "collection_stage"), ("is_fraud", "мошенничества", "chargeback_amount")])
    v = _variant(rng, 3)
    lines = [f'df = pd.read_parquet("clients_2025q{rng.randint(1, 4)}.parquet")']
    if rng.random() < 0.5:
        lines.append('df = df[df["is_test"] == 0]')
    if v == 1:
        lines.append(f'df = df.merge(cases[["client_id", "{post}"]], on="client_id", how="left")  # данные разбора кейсов')
        key = len(lines)
    if v == 2:
        lines.append(f'df = pd.concat([df] + [df[df["{target}"] == 1]] * 5)  # балансируем классы')
        key = len(lines)
    lines.append(f'y = df["{target}"]')
    lines.append('X = df.drop(columns=["client_id"])' if v == 0 else f'X = df.drop(columns=["client_id", "{target}"])')
    if v == 0:
        key = len(lines)
    lines += ["X_train, X_val, y_train, y_val = train_test_split(X, y, test_size=0.2, random_state=0)", "model.fit(X_train, y_train)",
              f"print(roc_auc_score(y_val, model.predict_proba(X_val)[:, 1]))  # {rng.choice(['1.0', '0.99', '0.998'])}"]
    return {"scene_title": "Идеальная модель", "story": f"Новичок в команде маркетплейса показывает модель {what}: ROC-AUC на валидации почти 1,0 — не то что у модели, которая не узнаёт Рея. Слишком хорошо, чтобы быть правдой.",
            "prompt": "Нажмите на строку с ошибкой.", "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("mlds_fe_high_cardinality", "ML / DS", "Feature engineering", "choice", 2.2, 0.2)
def _(rng):
    rows, card, cc, n_num = rng.randint(12, 30) * 100_000, rng.randint(40, 90) * 1000, rng.randint(800, 1500), rng.randint(30, 60)
    v = _variant(rng, 3)
    if v == 0:
        cols = card + cc + n_num
        lines = [_log("11:02:10", "train", "INFO", f"features: {n_num} numeric; categorical: merchant_id ({card} unique), city ({cc} unique)"),
                 _log("11:02:11", "train", "INFO", "pd.get_dummies(df, columns=['merchant_id', 'city'])"),
                 _log("11:02:58", "train", "ERROR", f"MemoryError: Unable to allocate {rows * cols * 8 // 2 ** 30} GiB for an array with shape ({rows}, {cols}) and data type float64")]
        story = "После добавления merchant_id обучение падает."
    elif v == 1:
        lines = [_log("11:02:10", "train", "INFO", f"features: {n_num} numeric + created_at as unix seconds"),
                 _log("11:30:40", "eval", "INFO", "valid (случайное разбиение): AUC +0.004; out-of-time (следующий месяц): AUC −0.03"),
                 _log("11:30:41", "eval", "INFO", "top split: created_at > 1767225600 — все значения теста выше всех значений обучения")]
        story = "Добавили время операции, чтобы модель учла ночной и выходной фрод. На новых данных стало хуже."
    else:
        uniq = rng.randint(2_000_000, 4_000_000)
        lines = [_log("11:02:10", "train", "INFO", f"features: {n_num} numeric; payment_comment — свободный текст, {_dec(uniq / 1e6, 1)} млн уникальных строк"),
                 _log("11:02:11", "train", "INFO", "pd.get_dummies(df, columns=['payment_comment'])"),
                 _log("11:02:58", "train", "ERROR", f"MemoryError: Unable to allocate array with shape ({rows}, {uniq + n_num})")]
        story = "Добавили комментарий к платежу — в нём часто видно назначение и признаки мошенничества."
    opts, key = _options(rng, ["Out-of-fold target encoding со сглаживанием, редкие значения — в общую категорию",
                               "Вместо абсолютного времени — циклические признаки: час, день недели, праздник",
                               "Векторизовать текст (TF-IDF по словам или эмбеддинги), а не one-hot по строкам целиком"], v,
                         ["Удалить признак: высокая кардинальность или «странные» значения — это шум", "Label encoding 0…N и подать в логистическую регрессию как число"])
    return {"scene_title": "Новый признак", "story": f"Модель риска платежей маркетплейса на градиентном бустинге. {story}", "prompt": "Как подготовить признак?",
            "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("mlds_fe_te_leak", "ML / DS", "Feature engineering", "mark", 2.4, 2.3)
def _(rng):
    ent, target = rng.choice([("merchant_id", "is_fraud"), ("hotel_id", "is_cancelled"), ("seller_id", "is_returned")])
    cv, ho = rng.choice([("0,97", "0,81"), ("0,95", "0,79"), ("0,96", "0,83")])
    v = _variant(rng, 3)
    lines = ["df = load_dataset()"]
    if rng.random() < 0.5:
        lines.append('df["hour"] = df["created_at"].dt.hour')
    if v == 0:
        lines.append(f'te = df.groupby("{ent}")["{target}"].mean()')
        key = [len(lines), len(lines) + 1]
        lines += [f'df["{ent}_te"] = df["{ent}"].map(te)', f'X, y = df[NUM_FEATURES + ["{ent}_te"]], df["{target}"]']
    elif v == 1:
        lines += ['df = df.sort_values("created_at")', f'df["{ent}_rate_30"] = (df.groupby("{ent}")["{target}"]',
                  "    .transform(lambda s: s.rolling(30, min_periods=1).mean()))"]
        key = [len(lines) - 1, len(lines)]
        lines += [f'X, y = df[NUM_FEATURES + ["{ent}_rate_30"]], df["{target}"]']
    else:
        lines += [f'X, y = df[NUM_FEATURES], df["{target}"]', "X, y = SMOTE(k_neighbors=5).fit_resample(X, y)"]
        key = len(lines)
    # одинаковая схема CV во всех вариантах: иначе случайный KFold без групп при GroupKFold в соседних клонах читается как второй дефект
    lines += ["cv = StratifiedKFold(n_splits=5, shuffle=True, random_state=0)",
              'print(cross_val_score(LGBMClassifier(), X, y, cv=cv, scoring="roc_auc").mean())']
    return {"scene_title": "Отложенная выборка", "story": f"На кросс-валидации ROC-AUC {cv}, а на отложенной выборке, которую не трогали при подготовке данных, — {ho}. "
            f"У многих {ent} всего несколько записей.",
            "prompt": "Нажмите на строку, из-за которой кросс-валидация завышена.", "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("mlds_fe_asof_lookahead", "ML / DS", "Feature engineering", "mark", 2.4, 2.75)
def _(rng):
    view, ev = rng.choice([("user_daily_stats", "events"), ("merchant_daily_agg", "transactions"), ("device_profile_daily", "logins")])
    v = _variant(rng, 3)
    lines = []
    if v == 2:
        # текущие значения, помеченные временем появления сущности, приклеиваются ко всей её истории
        lines.append(f'feats = feature_store.read_latest("{view}")  # текущие значения признаков')
        lines.append('feats["snapshot_ts"] = feats["first_seen_at"]  # момент появления сущности')
        key = [len(lines) - 1, len(lines)]
    else:
        lines.append(f'feats = feature_store.read("{view}")  # снапшот признаков на конец дня')
        if v == 1:
            lines.append('feats["snapshot_ts"] = pd.to_datetime(feats["snapshot_date"])  # дата снапшота → полночь')
            key = len(lines)
    lines.append(f'{ev} = {ev}.sort_values("ts")')
    if rng.random() < 0.5:
        lines.append('feats = feats.dropna(subset=["snapshot_ts"])')
    lines += ["train = pd.merge_asof(", f'    {ev}, feats.sort_values("snapshot_ts"),', '    left_on="ts", right_on="snapshot_ts", by="entity_id",',
              f'    direction="{rng.choice(["nearest", "forward"]) if v == 0 else "backward"}",']
    if v == 0:
        key = len(lines)
    tol = rng.choice([1, 2, 3])
    if v != 2:  # с допуском текущие значения доставались бы только событиям первых дней после появления сущности
        lines.append(f'    tolerance=pd.Timedelta("{tol}d"),')
    lines += [")", "model.fit(train[FEATURES], train.label)"]
    return {"scene_title": "Офлайн лучше онлайна", "story": f"Выборка {ev} собирается point-in-time join'ом со снапшотами признаков. Офлайн-AUC на {rng.randint(3, 8)} п.п. выше прода, "
                                                            "хотя train/test разделены по времени.",
            "prompt": "Нажмите на строку, из-за которой в обучение попадают данные из будущего.", "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


# --- MLOps (простое семейство: b = 1.8) ---


@family("mlds_ops_feature_mismatch", "ML / DS", "MLOps", "choice", 2.1, -1.1)
def _(rng):
    n, ver, k = rng.randint(40, 60), f"v{rng.randint(2, 5)}.{rng.randint(10, 40)}", rng.randint(60, 100)
    f = rng.choice(["days_since_last_login", "avg_check_30d", "device_age_days"])
    m = rng.randint(10, 50)
    v = _variant(rng, 3)
    event, err = [(f"feature-pipeline {ver} deployed (added feature '{f}')", f"ValueError: X has {n + 1} features, but LGBMClassifier is expecting {n} features as input"),
                  (f"scoring-api image rebuilt: scikit-learn 1.{rng.randint(2, 3)} → 1.{rng.randint(5, 6)}", "ModuleNotFoundError: No module named 'sklearn.ensemble._gb_losses' (loading model.pkl)"),
                  (f"feature-pipeline {ver} deployed (source for '{f}' switched to new CRM)", f"ValueError: Input X contains NaN (column '{f}')")][v]
    lines = [_log(f"09:{m:02d}:00", "deployer", "INFO", event), _log(f"09:{m + 4:02d}:12", "scoring-api", "ERROR", err),
             _log(f"09:{m + 4:02d}:13", "scoring-api", "WARN", f"fallback to rule-based score: {k} % of requests")]
    opts, key = _options(rng, ["Пайплайн признаков и модель разошлись по версиям: признак выкатили раньше модели",
                               "В сервинге другая версия библиотеки, чем при обучении: фиксировать версии вместе с моделью",
                               "В признаке появились пропуски, а модель их не принимает: обрабатывать пропуски в пайплайне и проверять вход"], v,
                         ["Файл модели повредился при загрузке в хранилище: перезалить тот же артефакт и перезапустить сервис скоринга",
                          "Сервису не хватает памяти на новый признак: увеличить лимиты пода"])
    return {"scene_title": "Запасные правила", "story": "Кто-то выкатил обновление, и через пять минут сервис скоринга маркетплейса перешёл на запасные правила.",
            "prompt": "В чём причина?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("mlds_ops_dynamic_batching", "ML / DS", "MLOps", "choice", 2.2, 0.4)
def _(rng):
    what = rng.choice(["классификатор обращений", "модель модерации отзывов", "NER для документов"])
    h0 = rng.randint(9, 11)
    lat = [rng.randint(500, 700) + i * rng.randint(280, 360) for i in range(8)]
    v = _variant(rng, 3)
    name, data, story = [("загрузка GPU, %", [rng.randint(12, 24) for _ in range(8)], "GPU почти простаивает: сервер берёт запросы по одному."),
                         ("загрузка GPU, %", [min(100, 70 + 5 * i + rng.randint(0, 3)) for i in range(8)], "GPU загружена полностью, батчинг уже включён."),
                         ("загрузка CPU пода, %", [min(100, 60 + 6 * i + rng.randint(0, 3)) for i in range(8)],
                          "GPU загружена на треть, а текст перед моделью токенизируется в одном потоке Python.")][v]
    panel = {"type": "chart", "x": [f"{h0 + i}:00" for i in range(8)], "series": [
        {"name": "p95 задержки, мс", "axis": "left", "max": 4000, "data": lat}, {"name": name, "axis": "right", "max": 100, "data": data}]}
    opts, key = _options(rng, ["Включить динамический батчинг: копить запросы в пачки по несколько мс",
                               "Масштабировать горизонтально: добавить GPU-реплики и балансировку по наименьшей очереди",
                               "Узкое место — токенизация на CPU: быстрый токенизатор и предобработка в нескольких процессах"], v,
                         ["Перенести модель на CPU: GPU всё равно почти не загружена", "Увеличить таймаут клиента до 10 секунд"])
    return {"scene_title": "Задержка растёт", "story": f"{what.capitalize()} маркетплейса на трансформере работает на одной GPU. Днём поток растёт, и p95 уходит за 2 секунды. {story}",
            "prompt": "Что сделать первым?", "panel": panel, "options": opts, "key": key}


@family("mlds_ops_snapshot", "ML / DS", "MLOps", "mark", 2.3, 1.3)
def _(rng):
    m, tbl = rng.choice([("оттока", "client_events"), ("скоринга", "loan_features"), ("рекомендаций", "user_sessions")])
    a1, a2 = rng.choice([("0,84", "0,79"), ("0,81", "0,86"), ("0,78", "0,74")])
    v = _variant(rng, 3)
    # без глобального np.random.seed: иначе модель без своего сида всё равно воспроизводима (sklearn берёт глобальный генератор numpy)
    lines = [f"# train.py, коммит {rng.randint(0x100000, 0xffffff):06x}", "SEED = 42"]
    if rng.random() < 0.5:
        lines.append(f'mlflow.set_experiment("{tbl}-model")')
    if v == 2:
        lines.append(f'df = feature_store.get_dataset("{tbl}").to_pandas()  # последняя версия датасета')
        key = len(lines)
    else:
        lines.append(f"df = pd.read_sql(\"SELECT * FROM {tbl} WHERE dt >= now() - interval '90 days'\", conn)" if v == 0 else
                     f"df = pd.read_sql(\"SELECT * FROM {tbl} WHERE dt BETWEEN '2026-06-01' AND '2026-08-31'\", conn)")
        if v == 0:
            key = len(lines)
    lines.append("X_train, X_val, y_train, y_val = split_by_time(df, val_days=14)")
    if v == 1:
        lines.append("model = MLPClassifier(hidden_layer_sizes=(256, 128), early_stopping=True).fit(X_train, y_train)")
        key = len(lines)
    else:
        lines.append("model = CatBoostClassifier(random_seed=SEED, iterations=800).fit(X_train, y_train)")
    lines += ['mlflow.log_metric("auc", roc_auc_score(y_val, model.predict_proba(X_val)[:, 1]))', 'mlflow.sklearn.log_model(model, "model")']
    return {"scene_title": "Невоспроизводимо", "story": f"Модель {m} переобучили тем же коммитом через неделю: AUC {a1} → {a2}. Понять, виноват код или данные, не получается.",
            "prompt": "Нажмите на строку, из-за которой обучение невоспроизводимо.",
            "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("mlds_ops_freshness_skew", "ML / DS", "MLOps", "choice", 2.3, 2.9)
def _(rng):
    feat = rng.choice(["txn_count_1h", "sessions_30m", "failed_logins_1h"])
    off_mean, on_mean = rng.choice([(0.6, 3.1), (0.4, 2.7), (0.9, 4.2)])
    model = rng.choice(["fraud-v8", "risk-v3", "ato-v2"])
    v = _variant(rng, 3)
    if v == 0:
        lines = [_log("10:00:00", "train-job", "INFO", f"{model}: {feat} from daily batch (value at 23:59 of previous day), mean={_dec(off_mean)}"),
                 _log("10:15:22", "scoring-api", "INFO", f"{model}: {feat} from streaming store (value at request time), mean={_dec(on_mean)}"),
                 _log("10:15:23", "monitor", "WARN", f"{feat}: online/offline distribution mismatch, KS=0,{rng.randint(41, 63)}")]
        story = f"После перевода {model} на стриминговые признаки срабатываний стало в разы больше, хотя модель та же."
    elif v == 1:
        lines = [_log("10:00:00", "train-job", "INFO", f"{model}: hour_of_day computed in Spark from event_ts (UTC)"),
                 _log("10:15:22", "scoring-api", "INFO", f"{model}: hour_of_day computed in Java service from local time (Europe/Moscow)"),
                 _log("10:15:23", "monitor", "WARN", "hour_of_day: online distribution shifted by +3 vs training")]
        story = f"После переписывания сервинга {model} на Java срабатываний ночью стало вдвое больше, днём — меньше. Модель та же."
    else:
        lines = [_log("10:00:00", "train-job", "INFO", f"{model}: {feat} missing in {rng.randint(12, 25)} % of rows → kept as NaN (model handles missing)"),
                 _log("10:15:22", "scoring-api", "INFO", f"{model}: {feat} not found in online store (TTL expired) → default 0"),
                 _log("10:15:23", "monitor", "WARN", f"{feat}=0 share: training 0.4 %, online {rng.randint(12, 25)} %")]
        story = f"После запуска {model} в проде срабатываний заметно больше, чем в теневом тесте на исторических данных. Модель та же."
    lines.append(_log("10:20:05", "monitor", "WARN", f"{model}: alert rate ×{rng.randint(2, 6)} vs shadow test"))
    # в каждом ответе — диагноз: «логировать признаки и учиться на логах» лечит любой перекос, и без диагноза подходил бы ко всем вариантам
    opts, key = _options(rng, ["Свежесть признака разная: логировать признаки при скоринге и обучать на них",
                               "Признак считают два разных кода: один код для обучения и сервинга, время в одной зоне",
                               "Пропуски обработаны по-разному: в сервинге отсутствующий признак — NaN, как в обучении"], v,
                         ["Переобучать модель ежечасно на том же дневном батче — так она догонит свежие данные",
                          f"Нормализовать {feat} в сервинге z-score по статистике обучения, чтобы распределения совпали",
                          "Модель переобучилась на старом окне: усилить регуляризацию и расширить окно обучения до года"])
    return {"scene_title": "Та же модель, другие срабатывания", "story": story, "prompt": "Какое архитектурное решение устраняет причину?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Алгоритмы (простое семейство: b = −0.4) ---


@family("mlds_alg_vectorize", "ML / DS", "Алгоритмы", "choice", 2.1, -1.5)
def _(rng):
    n, col = rng.randint(3, 20), rng.choice(["amount", "price", "total"])
    v = _variant(rng, 3)
    lines, story = [(["for i in range(len(df)):", f'    df.loc[i, "{col}_rub"] = df.loc[i, "{col}"] * rates[df.loc[i, "currency"]]'],
                     f"Пересчёт сумм заказов маркетплейса в рубли по {n} млн строк перед обучением идёт больше часа."),
                    (["result = pd.DataFrame()", "for path in daily_files:  # 365 файлов", "    result = pd.concat([result, pd.read_parquet(path)])"],
                     f"Склейка дневных файлов в одну выборку ({n} млн строк) с каждым файлом идёт всё медленнее и занимает больше часа."),
                    (["totals = {}", "for c in df.client_id.unique():", f'    totals[c] = df[df.client_id == c]["{col}"].sum()'],
                     f"Подсчёт суммы по каждому клиенту ({n} млн строк, сотни тысяч клиентов) идёт больше часа.")][v]
    opts, key = _options(rng, [f'Векторизовать: df["{col}"] * df["currency"].map(rates)',
                               "Собрать кадры в список и сделать один pd.concat в конце",
                               f'Один проход: df.groupby("client_id")["{col}"].sum()'], v,
                         ["Распараллелить этот цикл на четыре потока через threading", "Заменить df.loc на df.iloc внутри того же цикла"])
    return {"scene_title": "Медленный pandas", "story": story, "prompt": "Как ускорить?", "panel": {"type": "code", "lang": "python", "lines": lines}, "options": opts, "key": key}


@family("mlds_alg_softmax", "ML / DS", "Алгоритмы", "mark", 2.3, 0.9)
def _(rng):
    ep, big = rng.randint(3, 12), rng.choice([800, 1200, 2500])
    v = _variant(rng, 3)
    if v == 0:
        lines = ["def cross_entropy(logits: np.ndarray, y: np.ndarray) -> float:"]
        if rng.random() < 0.5:
            lines.append("    logits = logits.astype(np.float64)")
        lines.append("    exp = np.exp(logits)")
        key = len(lines)
        lines += ["    probs = exp / exp.sum(axis=1, keepdims=True)", "    return float(-np.log(probs[np.arange(len(y)), y]).mean())"]
        story, prompt = f"На {ep}-й эпохе loss самописного классификатора пород — того, что путает Рея с биглем, — стал nan. Логиты к этому моменту доходят до {big}.", "Нажмите на строку, где возникает переполнение."
    elif v == 1:
        lines = ["def bce(p: np.ndarray, y: np.ndarray) -> float:"]
        if rng.random() < 0.5:
            lines.append("    p = p.astype(np.float64)")
        lines.append("    loss = -(y * np.log(p) + (1 - y) * np.log(1 - p))")
        key = len(lines)
        lines += ["    return float(loss.mean())"]
        story, prompt = f"На {ep}-й эпохе loss бинарного классификатора стал inf: модель уверенно выдаёт ровно 0 и 1 для части примеров.", "Нажмите на строку, где появляется бесконечность."
    else:
        # аккумулятор — массив float16: скаляр np.float16 при сложении с float64 сам повышается до float64, и ошибки бы не было
        lines = ["def total_weight(weights: np.ndarray) -> float:", "    acc = np.zeros(1, dtype=np.float16)"]
        key = len(lines)
        lines += ["    for w in weights:  # десятки миллионов весов, почти все равны 1", "        acc[0] += w", "    return float(acc[0])"]
        story, prompt = "Сумма весов выборки перестала расти на 2048, хотя весов десятки миллионов.", "Нажмите на строку, из-за которой сумма перестала расти."
    return {"scene_title": "Численная ошибка", "story": story, "prompt": prompt, "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("mlds_alg_auc_ranks", "ML / DS", "Алгоритмы", "choice", 2.2, 1.9)
def _(rng):
    n, p = rng.choice([20, 50, 120]), rng.choice([5, 10, 20])
    w = rng.choice([1000, 5000, 10000])
    v = _variant(rng, 3)
    lines, story = [(["def auc(scores, labels):", "    pos = [s for s, l in zip(scores, labels) if l == 1]", "    neg = [s for s, l in zip(scores, labels) if l == 0]",
                      "    hits = sum((a > b) + 0.5 * (a == b) for a in pos for b in neg)", "    return hits / (len(pos) * len(neg))"],
                     f"Самописный ROC-AUC для ежедневного отчёта по {n} млн строк с долей положительных {p} % не укладывается в ночное окно."),
                    ([f"def rolling_median(xs, w={w}):", "    out = []", "    for i in range(w, len(xs) + 1):", "        out.append(sorted(xs[i - w:i])[w // 2])", "    return out"],
                     f"Скользящая медиана по окну {w} для {n} млн точек телеметрии считается часами."),
                    (["def cum_share(xs):", "    total = sum(xs)", "    return [sum(xs[:i + 1]) / total for i in range(len(xs))]"],
                     f"Накопленная доля выручки для кривой Лоренца по {n} млн клиентов считается часами.")][v]
    opts, key = _options(rng, ["Через ранги: AUC = (сумма рангов положительных − n₊(n₊+1)/2) / (n₊·n₋), ничьи — средним рангом",
                               "Две кучи или отсортированное окно с вставкой и удалением за O(log w) вместо сортировки окна на каждом шаге",
                               "Префиксные суммы (np.cumsum): весь массив за один проход"], v,
                         ["Оценить ответ по случайной выборке из 1000 элементов — получится точное значение за секунды",
                          "Распараллелить двойной цикл на 32 процесса: квадратичная сложность здесь приемлема"])
    return {"scene_title": "Считается часами", "story": story, "prompt": "Как посчитать то же самое быстро и точно?",
            "panel": {"type": "code", "lang": "python", "lines": lines}, "options": opts, "key": key}


# --- уровень Lead: компромиссы постановки, диагностика по нескольким сигналам, тонкие утечки, архитектура сервинга ---


@family("mlds_task_profit_vs_auc", "ML / DS", "Постановка задачи", "choice", 2.3, 2.4)
def _(rng):
    prod = rng.choice(["кредитных лимитов", "BNPL-рассрочек", "кредитных карт"])
    auc_a, auc_b = rng.choice([(0.81, 0.84), (0.78, 0.82), (0.83, 0.86)])
    small, big = rng.choice([(30, 300), (50, 500), (20, 250)])
    d_small, d_big = rng.uniform(0.3, 0.6), rng.uniform(0.4, 0.9)
    weeks = rng.choice([3, 4, 6])
    v = _variant(rng, 3)
    if v == 0:
        lines = ["сегмент суммы         AUC A   AUC B   дефолты B − A, п.п.",
                 f"до {small} тыс. ₽          {_dec(auc_a - 0.01)}    {_dec(auc_b + 0.01)}    −{_dec(d_small)}",
                 f"{small}–{big} тыс. ₽       {_dec(auc_a)}    {_dec(auc_b - 0.01)}    +{_dec(d_big / 3)}",
                 f"от {big} тыс. ₽          {_dec(auc_a + 0.01)}    {_dec(auc_a - 0.02)}    +{_dec(d_big)}",
                 f"итого                 {_dec(auc_a)}    {_dec(auc_b)}    прибыль B − A: −{rng.randint(4, 9)} %"]
        story = f"Скоринг {prod}: новая модель B лучше по ROC-AUC ({_dec(auc_a)} → {_dec(auc_b)}), но в A/B прибыль портфеля ниже, чем у A."
    elif v == 1:
        pa, pb = rng.randint(38, 45), rng.randint(27, 33)
        lines = ["метрика                      A       B", f"ROC-AUC по всем клиентам     {_dec(auc_a)}    {_dec(auc_b)}",
                 f"precision в топ-1 % скора    {pa} %    {pb} %", "решение: звонок менеджера только клиентам из топ-1 %"]
        story = f"Модель отбора клиентов для звонков с предложением {prod}: B лучше по ROC-AUC, но конверсия звонков упала."
    else:
        lines = ["история выдач: одобряла только модель A (одобрено 38 % заявок)", "метки дефолта есть только у одобренных A",
                 f"офлайн на одобренных A: AUC A {_dec(auc_a)}, AUC B {_dec(auc_b)}", f"B одобрила бы {rng.randint(12, 18)} % заявок, которые A отклонила, — по ним меток нет"]
        story = f"Скоринг {prod}: B сравнили с A офлайн на истории выдач и хотят сразу заменить A на всём потоке."
    opts, key = _options(rng, ["Цель не та: AUC не взвешивает заявки по сумме — оптимизировать ожидаемую прибыль портфеля",
                               "Решение принимается только в верхушке скора: сравнивать модели по precision в рабочей зоне, а не AUC по всем",
                               "Метки есть только у одобренных старой моделью: офлайн-оценка смещена — нужна случайная доля решений или reject inference"], v,
                         [f"A/B шёл всего {weeks} нед.: дефолты созревают дольше, прибыль B занижена — продлить тест и катить B",
                          "Откалибровать B изотонической регрессией: AUC не изменится, а результат сравняется с A",
                          "B переобучилась на мелких заявках, которых в выборке большинство: усилить регуляризацию и стратифицировать валидацию по сумме"])
    return {"scene_title": "AUC выше — толку меньше", "story": story, "prompt": "В чём ошибка постановки и что менять?",
            "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}
