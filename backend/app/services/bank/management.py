"""Management, сюжет «Квартальное планирование»: неделя менеджера, который собирает план квартала и ведёт команду через релиз —
сроки и зависимости, риски, метрики продукта, приоритизация, стейкхолдеры, процессы команды. На компетенцию — простое
семейство и 3 сценарных, плюс 4 сложных уровня Senior/Lead (b 2,4–2,9). Компании, люди и фичи вымышленные."""

import itertools
import math

from app.services.items import _choice, _log, family, simple

FEATURES = ["оплата долями", "трекинг курьера", "семейный аккаунт", "экспорт отчётов в Excel", "вход по биометрии", "чат с поддержкой",
            "программа лояльности", "подписка на доставку"]
PARTNERS = ["Логистик-Про", "ПэйТочка", "ГеоСервис", "Кредо-Банк", "СеверТрансКом"]
PEOPLE = ["Аня", "Игорь", "Марат", "Оля", "Денис", "Вика", "Сева", "Лена"]


def _dec(x: float) -> str:
    return f"{x:g}".replace(".", ",")


# --- простые семейства: по одному на компетенцию ---

simple("Management", "Планирование и сроки", -1.0, "Три оценки", "Разработчик оценил задачу «⟨f⟩»: оптимистично ⟨o⟩ дн., наиболее вероятно ⟨m⟩ дн., пессимистично ⟨p⟩ дн.",
       "Какую оценку заложить в план по PERT?", "⟨e⟩ дн. — (O + 4M + P) / 6",
       ["⟨m⟩ дн. — наиболее вероятная оценка", "⟨avg⟩ дн. — среднее трёх оценок", "⟨p⟩ дн. — пессимистичная, чтобы точно успеть"],
       lambda rng: (lambda f, o, m, p: {"f": f, "o": o, "m": m, "p": p, "e": (o + 4 * m + p) // 6, "avg": (o + m + p) // 3})(
           rng.choice(FEATURES), *rng.choice([(2, 5, 14), (3, 6, 15), (4, 7, 16), (1, 4, 13)])))
simple("Management", "Риски", -1.2, "Риск случился", "В реестре рисков проекта есть строка «⟨r⟩». Вчера это произошло.",
       "Что сделать с записью?", "Перевести в проблемы: запустить план реагирования, назначить владельца и срок",
       ["Поднять вероятность до 100 % и оставить в реестре до ретро", "Удалить: риск реализовался и больше не актуален",
        "Оставить как есть до планового пересмотра реестра"],
       {"r": ["Партнёр задержит доступ к API", "Ключевой разработчик уйдёт в отпуск до релиза", "Магазин приложений отклонит сборку"]})
simple("Management", "Метрики продукта", -0.9, "Главная метрика", "Вы выбираете North Star для сервиса ⟨svc⟩.",
       "Какая метрика подходит лучше?", "⟨right⟩",
       ["Число установок приложения за месяц", "Число зарегистрированных аккаунтов", "Средняя оценка приложения в сторах"],
       lambda rng: dict(zip(("svc", "right"), rng.choice([("доставки продуктов", "Число заказов в неделю, доставленных вовремя"),
                                                          ("онлайн-курсов", "Число учеников, прошедших урок за неделю"),
                                                          ("бронирования переговорок", "Число проведённых встреч по брони в неделю")]))))
simple("Management", "Приоритизация", -1.4, "Не влезаем в MVP", "До запуска MVP две недели, весь объём не успеть. Фича «⟨f⟩» приятная, но без неё пользователь решает свою задачу.",
       "Куда её отнести по MoSCoW?", "Could или Won't: перенести в следующий релиз",
       ["Must: без неё запуск выглядит сырым", "Should: делать параллельно, если команда успеет", "Must, но урезать до минимальной версии"],
       {"f": ["тёмная тема", "анимация на главной", "экспорт в PDF"]})
simple("Management", "Стейкхолдеры", -1.0, "Срочно в спринт", "⟨who⟩ просит добавить в текущий спринт задачу «⟨t⟩»: «это быстро».",
       "Что ответить?", "Оценить с командой и предложить обмен: что уйдёт из спринта взамен",
       ["Взять: просьба руководителя важнее плана спринта", "Отказать: спринт закрыт для любых изменений без исключений",
        "Взять без огласки, команда доделает в выходные"],
       {"who": ["Директор по продажам", "Руководитель маркетинга", "Финансовый директор"], "t": ["выгрузка для клиента", "баннер акции", "новый отчёт"]})
simple("Management", "Процессы команды", -1.6, "Пробка на доске", "На Kanban-доске в колонке «⟨col⟩» скопилось ⟨n⟩ задач, а «Готово» почти не пополняется.",
       "Что сделать в первую очередь?", "Ввести WIP-лимит и доводить начатые задачи, прежде чем брать новые",
       ["Добавить ещё одну колонку между «⟨col⟩» и «Готово»", "Попросить разработчиков брать больше задач параллельно",
        "Каждый день напоминать команде о сроках"], {"col": ["Ревью", "Тестирование", "В работе"], "n": [14, 18, 25]})


# --- Планирование и сроки ---

GANTT = [("Аналитика требований", []), ("Дизайн макетов", [0]), ("API бэкенда", [0]), ("Вёрстка экранов", [1]),
         ("Интеграция фронта с API", [2, 3]), ("Приёмочное тестирование", [4])]


@family("pm_plan_gantt", "Management", "Планирование и сроки", "mark", 2.2, -0.3)
def _(rng):
    feat = rng.choice(FEATURES)
    durs = [rng.randint(2, 6) for _ in GANTT]
    bad = rng.randint(1, len(GANTT) - 1)
    start, end = [], []
    for i, (_name, deps) in enumerate(GANTT):
        s = max((end[d] for d in deps), default=0) + 1
        if i == bad:
            s -= rng.randint(1, 2)  # стартует, пока зависимость ещё не закончена
        start.append(s)
        end.append(s + durs[i] - 1)
    lines = ["задача | дней | после | план, дни"]
    for i, (name, deps) in enumerate(GANTT):
        after = ", ".join("ABCDEF"[d] for d in deps) or "—"
        lines.append(f"{'ABCDEF'[i]}. {name} | {durs[i]} | {after} | {start[i]}–{end[i]}")
    return {"scene_title": "План фичи", "story": f"Техлид прислал план фичи «{feat}» по рабочим дням. В колонке «после» — задачи, которые должны закончиться до старта.",
            "prompt": "Нажмите на строку, из-за которой план в таком виде невыполним.", "panel": {"type": "code", "lang": "text", "lines": lines}, "key": bad + 2}


@family("pm_plan_slack", "Management", "Планирование и сроки", "choice", 2.3, 0.9)
def _(rng):
    feat = rng.choice(FEATURES)
    da, df, s = rng.randint(2, 4), rng.randint(2, 4), rng.randint(2, 4)
    crit = rng.randint(10, 13)
    split = [rng.randint(3, crit - 3), rng.randint(3, crit - s - 3)]
    back, front = (crit, crit - s) if rng.random() < 0.5 else (crit - s, crit)
    b1 = split[0] if back == crit else split[1]
    f1 = split[1] if back == crit else split[0]
    tasks = [("A", "Аналитика и требования", da, "—"), ("B", "Бэкенд: API", b1, "A"), ("C", "Дизайн экранов", f1, "A"),
             ("D", "Бэкенд: интеграция с оплатой", back - b1, "B"), ("E", "Вёрстка экранов", front - f1, "C"), ("F", "Приёмочное тестирование", df, "D, E")]
    short = ["B", "D"] if back < front else ["C", "E"]
    pick = rng.choice(short)
    x = next(t for t in tasks if t[0] == pick)
    n = rng.choice([s - 1, s + 1, s + 2]) if s > 2 else rng.choice([s + 1, s + 2])
    shift = max(0, n - s)
    wrong = [v for v in dict.fromkeys([n, 0, s, n + s, shift + 1, shift + 2]) if v != shift][:3]
    opts, key = _choice(rng, f"Сдвиг релиза: {shift} раб. дн.", [f"Сдвиг релиза: {v} раб. дн." for v in wrong])
    lines = [f"{c}. {name} — {d} дн., после: {dep}" for c, name, d, dep in tasks]
    why = rng.choice(["заболел исполнитель", "партнёр задержал тестовые доступы", "исполнителя забрали на срочный багфикс"])
    return {"scene_title": "Задержка", "story": f"План фичи «{feat}» к концу квартала. Задача «{x[1]}» задержится на {n} раб. дн.: {why}.",
            "prompt": "На сколько сдвинется релиз, если остальное пойдёт по плану?",
            "panel": {"type": "code", "lang": "text", "lines": lines, "caption": "задачи делают разные люди, каждая стартует сразу после предшественников"},
            "options": opts, "key": key}


@family("pm_plan_burnup", "Management", "Планирование и сроки", "choice", 2.3, 1.8)
def _(rng):
    while True:
        v, g, k = rng.choice([30, 36, 42]), rng.choice([6, 9, 12]), rng.randint(3, 6)
        rem = (v - g) * k
        if math.ceil(rem / v) < k:
            break
    noise = [rng.randint(-4, 4) for _ in range(3)]
    done = [v + d for d in noise + [-d for d in noise]]
    gn = [rng.randint(-2, 2) for _ in range(3)]
    grow = [g + d for d in gn + [-d for d in gn]]
    rng.shuffle(done)
    rng.shuffle(grow)
    s0 = (v - g) * (k + 6)
    cum_d = list(itertools.accumulate(done))
    cum_s = [s0 + c for c in itertools.accumulate(grow)]
    top = math.ceil(cum_s[-1] / 50) * 50
    panel = {"type": "chart", "x": [f"С{i + 1}" for i in range(6)], "series": [
        {"name": "объём бэклога, SP", "axis": "left", "max": top, "data": cum_s},
        {"name": "сделано накопительно, SP", "axis": "left", "max": top, "data": cum_d}]}
    wrong = [w for w in dict.fromkeys([math.ceil(rem / v), k + 2, k - 1, k + 1]) if w != k][:3]
    opts, key = _choice(rng, f"Спринтов до закрытия: {k}", [f"Спринтов до закрытия: {w}" for w in wrong])
    return {"scene_title": "Когда закончим", "story": f"Директор просит дату завершения проекта. За 6 спринтов команда закрывала в среднем {v} SP за спринт, "
            f"а в бэклог в среднем добавлялось {g} SP. Сейчас осталось {rem} SP.",
            "prompt": "Через сколько спринтов закроется бэклог, если обе тенденции сохранятся?", "panel": panel, "options": opts, "key": key}


@family("pm_plan_resource", "Management", "Планирование и сроки", "choice", 2.3, 2.5)
def _(rng):
    dev, other = rng.sample(PEOPLE, 2)
    feat = rng.choice(FEATURES)
    while True:
        da, db, dc, dd, de, df = rng.randint(2, 4), rng.randint(4, 7), rng.randint(3, 6), rng.randint(2, 4), rng.randint(5, 9), rng.randint(2, 3)
        naive = da + max(db + dd, dc, de) + df  # критический путь без учёта исполнителей
        real = da + max(db + max(dd, dc), de) + df  # B и C делает один человек: сначала B, тогда D идёт параллельно с C
        c_first = da + max(dc + db + dd, de) + df  # тот же человек, но сначала C
        total = da + db + dc + dd + de + df
        if len({naive, real, c_first, total}) == 4:
            break
    tasks = [("A", "Требования и макеты", da, "—", "аналитик"), ("B", "API заказов", db, "A", dev), ("C", "Интеграция с платёжным шлюзом", dc, "A", dev),
             ("D", "Админка для поддержки", dd, "B", other), ("E", "Мобильные экраны", de, "A", "мобильная команда"), ("F", "Регресс и выкладка", df, "C, D, E", "QA")]
    wrong = [naive, c_first, total]
    opts, key = _choice(rng, f"Не раньше чем через {real} раб. дн.", [f"Не раньше чем через {w} раб. дн." for w in wrong])
    lines = [f"{c}. {name} — {d} дн., после: {dep}, исполнитель: {who}" for c, name, d, dep, who in tasks]
    return {"scene_title": "Один на двоих", "story": f"Вы собираете план фичи «{feat}». Задачи с общим исполнителем идут по очереди, остальные — параллельно; "
            "задача стартует, когда закончены предшественники и свободен исполнитель.",
            "prompt": "Когда реально можно выкатить фичу при лучшем порядке работ?", "panel": {"type": "code", "lang": "text", "lines": lines},
            "options": opts, "key": key}


# --- Риски ---

RISKS = [("Партнёр задержит API доставки", "заглушка API и еженедельный созвон", "PM"), ("Уход ключевого бэкенд-разработчика", "парная работа и документация", "техлид"),
         ("Нагрузка в распродажу превысит расчёт", "нагрузочный тест за 2 недели", "техлид"), ("Магазин приложений задержит ревью", "сборка на ревью на 5 дней раньше", "мобильный лид"),
         ("Юристы не согласуют оферту вовремя", "черновик юристам уже сейчас", "продакт"), ("Дизайн-система не готова к старту вёрстки", "минимальный набор компонентов", "дизайн-лид"),
         ("Подрядчик по вёрстке сорвёт сроки", "еженедельная промежуточная приёмка", "PM")]
HIGH = [(4, 4), (3, 5), (5, 3), (4, 5), (5, 4), (5, 5)]
LOW = [(1, 3), (2, 2), (2, 3), (3, 2), (1, 5), (2, 4), (3, 3)]


@family("pm_risk_register", "Management", "Риски", "mark", 2.2, 0.0)
def _(rng):
    th = rng.choice([12, 15])
    high = [x for x in HIGH if x[0] * x[1] >= th]
    risks = rng.sample(RISKS, 6)
    roles = ["bad", "high", "low_accept", "low_accept", "low_mit", rng.choice(["high", "low_accept"])]
    rng.shuffle(roles)
    lines = [f"Правило: оценка = вероятность × влияние (1–5); при оценке ≥ {th} — план снижения", "№ | риск | вероятность | влияние | реакция | владелец"]
    key = 0
    for i, ((r, mit, owner), role) in enumerate(zip(risks, roles)):
        p, imp = rng.choice(high if role in ("bad", "high") else LOW)
        resp = "принять, наблюдать" if role in ("bad", "low_accept") else f"снизить: {mit}"
        lines.append(f"{i + 1} | {r} | {p} | {imp} | {resp} | {owner}")
        if role == "bad":
            key = len(lines)
    return {"scene_title": "Реестр рисков", "story": "Перед защитой плана квартала вы проверяете реестр рисков, который заполнила команда.",
            "prompt": "Нажмите на риск, реакция на который противоречит правилу реестра.", "panel": {"type": "code", "lang": "text", "lines": lines}, "key": key}


@family("pm_risk_feed", "Management", "Риски", "choice", 2.2, 0.8)
def _(rng):
    partner, n = rng.choice(PARTNERS), rng.randint(6, 12)
    d, sl, x, m = rng.randint(7, 14), rng.randint(4, 6), rng.randint(3, 6), rng.randint(5, 9)
    ev = [("трекер", "WARN", f"INT-{rng.randint(100, 999)}: доступ к песочнице {partner} запрошен {d} дн. назад, ответа нет; "
                             f"без неё не начать сквозную приёмку «Интеграции с {partner}»"),
          ("чат", "INFO", f"дизайнер: макеты экрана настроек будут на 2 дня позже, запас у задачи {sl} дн."),
          ("CI", "WARN", f"UI-тест «вход» упал в {x} из 40 прогонов, перезапуск проходит"),
          ("трекер", "INFO", f"QA: в регрессе найдено {m} дефектов, все minor, исправляются по плану"),
          ("почта", "INFO", "маркетинг: просит перенести демо для партнёров со среды на четверг")]
    rng.shuffle(ev)
    lines = [_log(f"{['Пн', 'Вт', 'Ср', 'Чт', 'Пт'][i]} {rng.randint(10, 17)}:{rng.randint(0, 59):02d}", src, lvl, msg) for i, (src, lvl, msg) in enumerate(ev)]
    opts, key = _choice(rng, f"Доступ к песочнице {partner}: эскалировать, блокирует критический путь", [
        "Сдвиг макетов настроек: дизайн — самый частый источник срыва сроков квартала",
        f"Нестабильный тест: падает в {x} из 40 прогонов — сигнал о качестве всего релиза",
        f"{m} дефектов в регрессе: заметно больше обычного, нужно срочно разобраться",
    ])
    return {"scene_title": "Лента недели", "story": f"До код-фриза {n} раб. дн. В пятницу вы просматриваете ленту трекера, чатов и почты за неделю.",
            "prompt": "Какой сигнал требует вашего действия в первую очередь?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


EMV = [("сбой платёжного провайдера в распродажу", "резервный провайдер", "нагрузочный тест и дежурства"),
       ("уход единственного разработчика интеграции", "второй разработчик на интеграцию", "документация и парная работа"),
       ("штраф заказчика за срыв срока сдачи", "подрядчик на вёрстку", "урезать объём по согласованию")]


@family("pm_risk_emv", "Management", "Риски", "choice", 2.2, 2.0)
def _(rng):
    risk, m1, m2 = rng.choice(EMV)
    target = rng.randrange(4)  # какой вариант окажется выгоднее — разный в клонах
    while True:
        loss, p0 = rng.choice([8, 10, 12, 15, 20]), rng.choice([20, 25, 30, 40])
        p1, p2 = rng.choice([5, 10, 15]), rng.choice([10, 15])
        c1, c2 = rng.choice([0.5, 1, 1.5, 2, 3]), rng.choice([0.5, 1, 1.5, 2])
        p12 = max(2, round(p1 * p2 / p0))
        cost = [p0 * loss / 100, c1 + p1 * loss / 100, c2 + p2 * loss / 100, c1 + c2 + p12 * loss / 100]
        best = min(range(4), key=cost.__getitem__)
        if best == target and sorted(cost)[1] - cost[best] >= 0.3:
            break
    names = ["Ничего не делать: принять риск", f"Только «{m1}»", f"Только «{m2}»", "Оба варианта сразу"]
    opts, key = _choice(rng, names[best], [x for i, x in enumerate(names) if i != best])
    lines = [f"Риск: {risk}", f"Ущерб при наступлении: {loss} млн ₽", f"Без мер: вероятность {p0} %",
             f"Вариант 1 — {m1}: {_dec(c1)} млн ₽, вероятность снижается до {p1} %",
             f"Вариант 2 — {m2}: {_dec(c2)} млн ₽, вероятность снижается до {p2} %",
             f"Оба варианта: {_dec(c1 + c2)} млн ₽, вероятность снижается до {p12} %"]
    return {"scene_title": "Стоит ли страховаться", "story": "Спонсор просит обосновать бюджет на снижение главного риска квартала. Оценки — на панели.",
            "prompt": "Какое решение выгоднее по ожидаемым потерям (затраты плюс ожидаемый ущерб)?", "panel": {"type": "code", "lang": "text", "lines": lines},
            "options": opts, "key": key}


@family("pm_risk_chain", "Management", "Риски", "choice", 2.3, 2.4)
def _(rng):
    teams = rng.sample(["платежи", "мобильное приложение", "склад", "CRM", "логистика", "антифрод"], 3)
    hist = [rng.choice([6, 7, 8, 9]) for _ in teams]
    p = hist[0] * hist[1] * hist[2] / 1000
    pct = round(p * 100)
    feat = rng.choice(FEATURES)
    wrong = [f"≈ {min(hist) * 10} %: вероятность определяет самая ненадёжная команда",
             f"≈ {round(sum(hist) / 3 * 10)} %: в среднем команды успевают так часто",
             f"≈ {round((1 - (1 - hist[0] / 10) * (1 - hist[1] / 10) * (1 - hist[2] / 10)) * 100)} %: хватит, чтобы успела хоть одна"]
    opts, key = _choice(rng, f"≈ {pct} %: нужны все три, вероятности перемножаются", wrong)
    lines = ["команда | сдала в срок за последние 10 спринтов"] + [f"{t} | {h} из 10" for t, h in zip(teams, hist)]
    lines.append(f"релиз «{feat}» требует доработок всех трёх команд; задержки команд независимы")
    return {"scene_title": "Три зависимости", "story": f"Спонсор хочет услышать, насколько вероятно выпустить «{feat}» в срок. Каждая команда говорит: «у нас всё под контролем».",
            "prompt": "Какова вероятность, что релиз выйдет в срок, если опираться на историю команд?", "panel": {"type": "code", "lang": "text", "lines": lines},
            "options": opts, "key": key}


# --- Метрики продукта ---

FUNNELS = [["Главная", "Каталог", "Карточка", "Корзина", "Оплата"], ["Установка", "Регистрация", "Профиль", "Первый поиск", "Первый заказ"],
           ["Лендинг", "Тарифы", "Форма заявки", "Подтверждение", "Оплата счёта"]]


@family("pm_met_funnel", "Management", "Метрики продукта", "choice", 2.2, -0.4)
def _(rng):
    steps = rng.choice(FUNNELS)
    worst = rng.randint(1, 3)
    rates = [rng.uniform(0.42, 0.5)] + [rng.uniform(0.6, 0.8) for _ in range(3)]
    rates[worst] = rng.uniform(0.2, 0.3)
    data = [rng.randint(8, 15) * 1000]
    for r in rates:
        data.append(round(data[-1] * r))
    panel = {"type": "chart", "x": steps, "series": [{"name": "пользователей за неделю", "axis": "left", "max": data[0], "data": data}]}
    names = [f"{steps[i]} → {steps[i + 1]}" for i in range(4)]
    opts, key = _choice(rng, names[worst], [n for i, n in enumerate(names) if i != worst])
    return {"scene_title": "Воронка", "story": "На квартал команда берёт одну гипотезу по воронке. Нужно выбрать шаг, на котором теряется больше всего пользователей относительно пришедших на него.",
            "prompt": "На каком переходе искать главную потерю?", "panel": panel, "options": opts, "key": key}


def _z(n1: int, c1: int, n2: int, c2: int) -> float:
    p = (c1 + c2) / (n1 + n2)
    return (c2 / n2 - c1 / n1) / math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))


@family("pm_met_ab", "Management", "Метрики продукта", "choice", 2.3, 1.2)
def _(rng):
    base, plan = rng.choice([3, 4, 5]), rng.choice([14, 21])
    need = round(16 * base / 100 * (1 - base / 100) / 0.005 ** 2 / 1000) * 1000  # мощность 80 %, α = 5 %, эффект +0,5 п.п.
    peek = rng.random() < 0.5
    while True:
        if peek:
            n, day, diff = round(need * rng.uniform(0.12, 0.2)), rng.randint(2, 4), rng.uniform(0.4, 0.7)
        else:
            n, day, diff = need + rng.randint(0, 3000), plan, rng.uniform(0.6, 0.8)
        c1, c2 = round(n * base / 100 * rng.uniform(0.97, 1.03)), round(n * (base + diff) / 100)
        z = _z(n, c1, n, c2)
        if (peek and 0.3 < z < 1.6) or (not peek and z > 2.6 and (c2 - c1) / n >= 0.0055):
            break
    lines = [f"день теста: {day} из {plan}", "группа | пользователей | конверсий | конверсия",
             f"контроль | {n} | {c1} | {_dec(round(c1 / n * 100, 2))} %", f"тест | {n} | {c2} | {_dec(round(c2 / n * 100, 2))} %"]
    rel = round((c2 / c1 - 1) * 100)
    if peek:
        opts, key = _choice(rng, "Продолжать до расчётного объёма: пока разница в пределах шума", [
            f"Выкатывать: прирост +{rel} % к контролю — заметный эффект",
            "Остановить тест: эффекта нет, гипотеза не подтвердилась",
            "Выкатить на половину пользователей, а остальных оставить в контроле"])
    else:
        opts, key = _choice(rng, "Выкатывать: объём набран, разница значима и не ниже заложенной", [
            "Продлить тест ещё на две недели, чтобы точно убедиться в эффекте",
            "Не выкатывать: прирост меньше 1 п.п., бизнесу это неинтересно",
            "Перезапустить тест с новой случайной разбивкой пользователей"])
    return {"scene_title": "A/B-тест", "story": f"Тест новой страницы оплаты: по расчёту мощности нужно {need // 1000} тыс. пользователей на группу, чтобы заметить +0,5 п.п. "
            f"конверсии; тест запланирован на {plan} дн. Продакт пишет: «Тест в плюсе, выкатываем?»",
            "prompt": "Ваше решение?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


@family("pm_met_mix", "Management", "Метрики продукта", "choice", 2.3, 2.2)
def _(rng):
    ro, rp = rng.randint(38, 45), rng.randint(15, 22)
    s0, s1 = rng.randint(15, 25), rng.randint(55, 70)
    share = [round(s0 + (s1 - s0) * i / 7) for i in range(8)]
    org = [ro + rng.randint(-1, 1) for _ in range(8)]
    paid = [rp + rng.randint(-1, 1) for _ in range(8)]
    total = [round((s * p + (100 - s) * o) / 100) for s, o, p in zip(share, org, paid)]
    rel = rng.randint(2, 5)
    panel = {"type": "chart", "x": [f"Н{i + 1}" for i in range(8)], "marker": {"i": rel, "label": "новый онбординг"}, "series": [
        {"name": "D30 retention, органика, %", "axis": "left", "max": 60, "data": org},
        {"name": "D30 retention, платный канал, %", "axis": "left", "max": 60, "data": paid},
        {"name": "доля новых из платного канала, %", "axis": "right", "max": 100, "data": share}]}
    opts, key = _choice(rng, "Онбординг ни при чём: в каналах удержание стабильно, вырос вес канала с низким удержанием", [
        "Откатить онбординг: общий retention стал падать после релиза, а это главный показатель",
        "Это сезонность: удержание новых пользователей летом проседает, нужно подождать пару недель",
        "Сломалась аналитика: общий retention не может падать, когда в каналах он не меняется"])
    return {"scene_title": "Удержание падает", "story": f"За 8 недель общий D30 retention новых пользователей упал с {total[0]} до {total[-1]} %. "
            f"Директор по продукту требует откатить онбординг, выпущенный на {rel + 1}-й неделе.",
            "prompt": "Что на самом деле произошло?", "panel": panel, "options": opts, "key": key}


@family("pm_met_novelty", "Management", "Метрики продукта", "choice", 2.3, 2.7)
def _(rng):
    what, base = rng.choice([("новая лента", 24), ("рекомендации на главной", 18), ("сторис в приложении", 21)])
    lift0, tail = rng.uniform(0.25, 0.35), rng.uniform(0.0, 0.02)
    ctrl = [base + rng.randint(-1, 1) for _ in range(14)]
    test = [round(c * (1 + tail + (lift0 - tail) * math.exp(-i / 2.5)), 1) for i, c in enumerate(ctrl)]
    avg = round((sum(test) / sum(ctrl) - 1) * 100)
    panel = {"type": "chart", "x": [f"д{i + 1}" for i in range(14)], "series": [
        {"name": "время в приложении, тест, мин/день", "axis": "left", "max": 40, "data": test},
        {"name": "время в приложении, контроль, мин/день", "axis": "left", "max": 40, "data": ctrl}]}
    opts, key = _choice(rng, "Эффект новизны: прирост тает, в план — уровень последних дней и проверка холдаутом", [
        f"Заложить в план квартала +{avg} %: это средний прирост за весь тест, выборка большая",
        "Тест сломан: прирост должен быть постоянным, перезапустить с новой разбивкой групп",
        "Выкатить и усилить промо фичи: прирост первых дней вернётся, когда аудитория привыкнет"])
    return {"scene_title": "Новизна", "story": f"Двухнедельный A/B-тест: {what}. Продакт готовит отчёт: «время в приложении +{avg} %, закладываем в план квартала».",
            "prompt": "Что сказать про результат?", "panel": panel, "options": opts, "key": key}


# --- Приоритизация ---


def _rice(r: int, i: float, c: int, e: int) -> int:
    return round(r * i * c / 100 / e)


@family("pm_pri_rice", "Management", "Приоритизация", "mark", 2.2, -0.5)
def _(rng):
    feats = rng.sample(FEATURES, 5)
    bad, err = rng.randrange(5), rng.choice(["e", "c"])
    rows = []
    for i, f in enumerate(feats):
        r, imp = rng.randint(1, 8) * 1000, rng.choice([0.5, 1, 2, 3])
        c, e = rng.choice([50, 80, 100]), rng.choice([1, 2, 4])
        if i == bad:  # ошибка должна менять число
            c, e = (c, rng.choice([2, 4])) if err == "e" else (rng.choice([50, 80]), e)
        score = _rice(r, imp, c, e)
        if i == bad:
            score = round(r * imp * c / 100 * e) if err == "e" else round(r * imp / e)
        rows.append((score, f"{f} | {r} | {_dec(imp)} | {c} % | {e} | {score}", i == bad))
    rows.sort(key=lambda x: -x[0])
    lines = ["фича | охват за квартал | влияние | уверенность | усилия, чел.-мес. | RICE"] + [x[1] for x in rows]
    key = next(i for i, x in enumerate(rows) if x[2]) + 2
    return {"scene_title": "RICE", "story": "Продакт отсортировал кандидатов в план квартала по RICE = охват × влияние × уверенность / усилия.",
            "prompt": "Нажмите на строку с ошибкой в расчёте.", "panel": {"type": "code", "lang": "text", "lines": lines}, "key": key}


@family("pm_pri_cod", "Management", "Приоритизация", "choice", 2.3, 1.0)
def _(rng):
    feats = rng.sample(FEATURES, 3)
    while True:
        cod = [rng.choice([100, 150, 200, 300, 400, 500]) for _ in range(3)]
        dur = [rng.randint(1, 6) for _ in range(3)]
        cd3 = [c / d for c, d in zip(cod, dur)]
        if len(set(cd3)) < 3 or len(set(cod)) < 3 or len(set(dur)) < 3:
            continue
        right = tuple(sorted(range(3), key=lambda i: -cd3[i]))
        by_cod = tuple(sorted(range(3), key=lambda i: -cod[i]))
        by_dur = tuple(sorted(range(3), key=lambda i: dur[i]))
        if len({right, by_cod, by_dur}) == 3:
            break
    other = rng.choice([p for p in itertools.permutations(range(3)) if p not in (right, by_cod, by_dur)])

    def name(p):
        return " → ".join("АБВ"[i] for i in p)

    opts, key = _choice(rng, name(right), [name(by_cod), name(by_dur), name(other)])
    lines = [f"{'АБВ'[i]}. {f}: стоимость задержки {cod[i]} тыс. ₽/нед., делать {dur[i]} нед." for i, f in enumerate(feats)]
    return {"scene_title": "Очередь фич", "story": "Три фичи делает одна команда, строго по очереди. Пока фича не выпущена, компания каждую неделю недополучает её стоимость задержки.",
            "prompt": "В каком порядке делать, чтобы суммарные потери от задержки были минимальны?", "panel": {"type": "code", "lang": "text", "lines": lines},
            "options": opts, "key": key}


@family("pm_pri_debt", "Management", "Приоритизация", "choice", 2.2, 1.8)
def _(rng):
    f0, bug0, n = rng.randint(7, 9), rng.randint(10, 18), rng.randint(5, 8)
    feats = [max(1, round(f0 - i * rng.uniform(0.6, 0.9))) for i in range(8)]
    bugs = [min(80, round(bug0 + i * rng.uniform(5, 7))) for i in range(8)]
    panel = {"type": "chart", "x": [f"С{i + 1}" for i in range(8)], "series": [
        {"name": "фич выпущено за спринт", "axis": "left", "max": 10, "data": feats},
        {"name": "время на инциденты и багфикс, %", "axis": "right", "max": 100, "data": bugs}]}
    opts, key = _choice(rng, "Отдать долю каждого спринта техдолгу в аварийных местах и показать бизнесу эффект", [
        "Остановить фичи на квартал и переписать систему с нуля: так долг уйдёт быстрее",
        "Взять все фичи стратегии, а техдолгом заняться после квартала, когда спадёт нагрузка",
        "Нанять ещё двух разработчиков: больше людей — больше фич при том же техдолге"])
    return {"scene_title": "Техдолг", "story": f"CEO просит взять в следующий квартал ещё {n} фич из стратегии. На панели — восемь последних спринтов команды.",
            "prompt": "Что предложить на планировании квартала?", "panel": panel, "options": opts, "key": key}


@family("pm_pri_portfolio", "Management", "Приоритизация", "choice", 2.3, 2.6)
def _(rng):
    feats = rng.sample(FEATURES, 5)
    for _ in range(1000):
        val = [rng.randint(3, 12) * 10 for _ in range(5)]
        cost = [rng.randint(2, 7) for _ in range(5)]
        cap = rng.randint(9, 13)
        sets = [s for k in range(1, 6) for s in itertools.combinations(range(5), k) if sum(cost[i] for i in s) <= cap]
        score = {s: sum(val[i] for i in s) for s in sets}
        best = max(score.values())
        opt = [s for s in sets if score[s] == best]

        def greedy(order):
            left, out = cap, []
            for i in order:
                if cost[i] <= left:
                    out.append(i)
                    left -= cost[i]
            return tuple(sorted(out))

        g_val = greedy(sorted(range(5), key=lambda i: -val[i]))
        g_ratio = greedy(sorted(range(5), key=lambda i: -val[i] / cost[i]))
        g_cheap = greedy(sorted(range(5), key=lambda i: cost[i]))
        cand = list(dict.fromkeys([g_val, g_ratio, g_cheap]))
        if len(opt) == 1 and opt[0] not in cand and len(cand) == 3 and len(opt[0]) > 1:
            break

    def name(s):
        return ", ".join("АБВГД"[i] for i in s)

    opts, key = _choice(rng, name(opt[0]), [name(s) for s in cand])
    lines = [f"ёмкость команды на квартал: {cap} чел.-нед."] + [f"{'АБВГД'[i]}. {f}: ценность {val[i]}, усилия {cost[i]} чел.-нед." for i, f in enumerate(feats)]
    return {"scene_title": "Портфель квартала", "story": "Инициативы нельзя делать частично. Ценность — оценка бизнеса в условных баллах, инициативы друг от друга не зависят.",
            "prompt": "Какой набор даёт наибольшую ценность в пределах ёмкости?", "panel": {"type": "code", "lang": "text", "lines": lines},
            "options": opts, "key": key}


# --- Стейкхолдеры ---


@family("pm_st_promise", "Management", "Стейкхолдеры", "choice", 2.2, 0.2)
def _(rng):
    client, feat = rng.choice(["ООО «Вектор»", "сеть «Колосок»", "АО «Ориент»", "банк «Заречный»"]), rng.choice(FEATURES)
    date, w, s = rng.choice(["1 ноября", "15 ноября", "1 декабря"]), rng.randint(6, 9), rng.choice([4, 6, 12])
    m = rng.randint(10, 40)
    lines = [_log(f"10:{m:02d}", "почта", "INFO", f"{client}: ждём «{feat}» к {date}, как договаривались на встрече"),
             _log(f"10:{m + 5:02d}", "продажи", "INFO", f"директор по продажам: я подтвердил {date}, клиент подписывает договор на {s} млн ₽"),
             _log(f"10:{m + 12:02d}", "техлид", "WARN", f"«{feat}» — минимум {w} недель; к {date} реально только базовая версия без настроек"),
             _log(f"10:{m + 14:02d}", "продажи", "WARN", "сделайте что-нибудь, сделка горит")]
    opts, key = _choice(rng, "С продажами и техлидом предложить клиенту базовую версию к дате, полную — позже", [
        f"Подтвердить клиенту {date}: обещание уже дано, команда поднажмёт и успеет",
        "Ответить продажам, что их обещания клиенту — их зона ответственности, и не вмешиваться",
        f"Тихо взять «{feat}» в спринт, сдвинув остальные задачи квартала"])
    return {"scene_title": "Обещание клиенту", "story": f"В понедельник утром в рабочем чате проекта — переписка о сделке с клиентом {client}.",
            "prompt": "Что делать?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


RACI_ROLES = ["Продакт", "Техлид", "Дизайнер", "QA-лид", "Маркетинг"]
RACI_TASKS = [("Приоритеты бэклога", 0, [0]), ("Архитектура решения", 1, [1]), ("Макеты экранов", 0, [2]), ("План тестирования", 3, [3]),
              ("Текст анонса", 4, [4]), ("Дата релиза", 0, [1, 3])]


@family("pm_st_raci", "Management", "Стейкхолдеры", "mark", 2.2, 0.9)
def _(rng):
    tasks = rng.sample(RACI_TASKS, 5)
    bad, two = rng.randrange(5), rng.random() < 0.5
    lines = ["задача | " + " | ".join(RACI_ROLES)]
    for i, (t, a, rs) in enumerate(tasks):
        cells = [rng.choice(["C", "I", "—"]) for _ in RACI_ROLES]
        for r in rs:
            cells[r] = "R"
        cells[a] = "A" if a not in rs else "A/R"
        if i == bad:
            free = [j for j in range(len(cells)) if cells[j] in ("C", "I", "—")]
            if two:
                cells[rng.choice(free)] = "A"
            else:
                cells[a] = "R" if a in rs else rng.choice(["C", "I"])
        lines.append(f"{t} | " + " | ".join(cells))
    return {"scene_title": "Матрица RACI", "story": f"Перед стартом квартала вы проверяете матрицу RACI проекта «{rng.choice(FEATURES)}». Из-за неё на прошлом проекте решения висели неделями.",
            "prompt": "Нажмите на строку, которая нарушает принцип RACI.", "panel": {"type": "code", "lang": "text", "lines": lines}, "key": bad + 2}


CONFLICTS = [("служба ИБ", "обязательную двухфакторную авторизацию для всех до запуска", "маркетинг", "регистрацию в один шаг к старту рекламной кампании"),
             ("финансовый директор", "согласование каждого возврата бухгалтерией", "поддержка", "возврат клиенту за минуты без ручных шагов"),
             ("юридический отдел", "полный текст согласий отдельным экраном", "руководитель продукта", "минимум шагов при регистрации"),
             ("руководитель продаж", "отдельную сборку под крупного клиента", "техдиректор", "единую кодовую базу без форков")]


@family("pm_st_conflict", "Management", "Стейкхолдеры", "choice", 2.0, 1.9)
def _(rng):
    s1, w1, s2, w2 = rng.choice(CONFLICTS)
    w = rng.randint(2, 5)
    opts, key = _choice(rng, "Понять интересы сторон и предложить общий вариант; не сошлись — к спонсору с вариантами", [
        "Сразу эскалировать генеральному: менеджер не должен разбирать спор руководителей уровнем выше",
        "Самому выбрать сторону: посчитать, чьи потери больше, и объявить решение обоим",
        "Выполнить оба требования полностью и перенести запуск, не обсуждая это со сторонами"])
    return {"scene_title": "Два руководителя", "story": f"{s1[0].upper() + s1[1:]} требует {w1}, {s2} — {w2}. Оба выше вас по уровню, до запуска {w} нед., "
            "каждый просит «решить в его пользу».", "prompt": "Как действовать?", "panel": None, "options": opts, "key": key}


# --- Процессы команды ---

STANDUP_OK = ["ревью платёжного модуля готово, сегодня беру экспорт отчётов", "баг с часовым поясом почти готов, к обеду закрою",
              "делаю миграцию справочников, идёт по плану", "сегодня дежурю, смотрю алерты, между ними — мелкие задачи",
              "две задачи по вёрстке закрыты, беру следующую из колонки", "пишу тесты к корзине, вечером отдам в ревью",
              "с вёрсткой задержусь на полдня, у задачи запас три дня"]
STANDUP_BLOCK = ["жду доступ к продовой базе от ИБ уже третий день, пока делаю мелочи из бэклога",
                 "интеграцию проверить не могу: тестовый стенд партнёра лежит со вторника, пока пишу документацию",
                 "сборка под iOS не подписывается, сертификат истёк, пока обхожусь симулятором"]


@family("pm_proc_standup", "Management", "Процессы команды", "mark", 2.1, -0.4)
def _(rng):
    names = rng.sample(PEOPLE, 6)
    said = rng.sample(STANDUP_OK, 5)
    pos = rng.randrange(6)
    said.insert(pos, rng.choice(STANDUP_BLOCK))
    lines = [f"Дейли, {rng.choice(['вторник', 'среда', 'четверг'])}"] + [f"{n}: {s}" for n, s in zip(names, said)]
    return {"scene_title": "Дейли", "story": "Вы слушаете дейли команды. Все говорят спокойно, никто не произносит слово «блокер».",
            "prompt": "Нажмите на реплику, по которой менеджеру нужно действовать сразу после дейли.", "panel": {"type": "code", "lang": "text", "lines": lines},
            "key": pos + 2}


@family("pm_proc_little", "Management", "Процессы команды", "choice", 2.2, 1.0)
def _(rng):
    t, weeks = rng.choice([4, 5, 6]), rng.choice([3, 4, 5])
    wip = t * weeks
    w0 = rng.randint(6, 9)
    wips = [round(w0 + (wip - w0) * i / 7) for i in range(8)]
    thr = [t + rng.choice([-1, 0, 0, 1]) for _ in range(7)] + [t]
    panel = {"type": "chart", "x": [f"Н{i + 1}" for i in range(8)], "series": [
        {"name": "задач в работе (WIP)", "axis": "left", "max": 40, "data": wips},
        {"name": "закрыто задач за неделю", "axis": "left", "max": 40, "data": thr}]}
    opts, key = _choice(rng, f"≈ {weeks} нед.; ограничить WIP — срок сократится и без найма", [
        f"≈ 1 нед.: команда закрывает {t} задач в неделю, новая — одна из них",
        f"≈ {weeks} нед.; сократить срок можно, только расширив команду",
        f"≈ {weeks + 2} нед.: к среднему сроку прибавить буфер на ревью и тест"])
    return {"scene_title": "Срок поставки", "story": f"Команда стабильно закрывает около {t} задач в неделю, а в работе сейчас {wip} задач. "
            "Продакт спрашивает, когда будет готова задача, которую возьмут сегодня, и как ускориться.",
            "prompt": "Что ответить?", "panel": panel, "options": opts, "key": key}


@family("pm_proc_goodhart", "Management", "Процессы команды", "choice", 2.3, 2.1)
def _(rng):
    mk = rng.randint(2, 4)
    sp0, rel0 = rng.randint(30, 40), rng.randint(9, 12)
    sp = [sp0 + rng.randint(-2, 2) if i <= mk else round(sp0 * (1 + 0.15 * (i - mk))) + rng.randint(-2, 2) for i in range(8)]
    rel = [rel0 + rng.randint(-1, 1) if i <= mk else max(4, rel0 - (i - mk) // 2 + rng.randint(-1, 0)) for i in range(8)]
    panel = {"type": "chart", "x": [f"С{i + 1}" for i in range(8)], "marker": {"i": mk, "label": "velocity — в KPI команды"}, "series": [
        {"name": "закрыто story points", "axis": "left", "max": 100, "data": sp},
        {"name": "изменений выпущено в прод", "axis": "right", "max": 20, "data": rel}]}
    opts, key = _choice(rng, "Оценки раздуваются под KPI: убрать velocity из целей, мерить выпуск и lead time", [
        "Команда ускорилась, а релизы тормозит тестирование — нанять ещё двух тестировщиков",
        "Задачи стали крупнее и сложнее, их выпуск занимает больше спринтов — это нормально",
        "KPI работает: чтобы выпуск догнал velocity, ввести второй KPI на число релизов"])
    return {"scene_title": "Velocity растёт", "story": f"После {mk + 1}-го спринта руководство включило velocity в KPI команды. Через квартал отчёт выглядит отлично.",
            "prompt": "Что происходит и что делать?", "panel": panel, "options": opts, "key": key}
