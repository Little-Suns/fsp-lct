"""QA, сюжет «Приёмка релиза»: сценарные семейства с логами, графиками и кодом автотестов — по 3 на компетенцию сверх простых."""

from app.services.items import _choice, _log, family

# --- Тест-дизайн ---


@family("qae_td_decision", "QA", "Тест-дизайн", "mark", 2.2, -0.2)
def _(rng):
    th = rng.choice([2000, 3000, 5000])
    perk, short = rng.choice([("у клиента есть подписка", "подписка"), ("клиент в программе лояльности", "лояльность"), ("заказ в пункт выдачи", "ПВЗ")])
    op = rng.choice(["ИЛИ", "И"])
    lines = [f"Правило: доставка бесплатна, если сумма ≥ {th} ₽ {op} {perk}"]
    if rng.random() < 0.5:
        lines.append("Таблица решений к задаче DLV-" + str(rng.randint(100, 999)))
    lines.append(f"№ | сумма ≥ {th} | {short} | доставка")
    bad, key = rng.randrange(4), 0
    for i, (s, p) in enumerate([(True, True), (True, False), (False, True), (False, False)]):
        free = (s or p) if op == "ИЛИ" else (s and p)
        if i == bad:
            free = not free
        lines.append(f"{i + 1} | {'да' if s else 'нет'} | {'да' if p else 'нет'} | {'бесплатно' if free else 'платно'}")
        if i == bad:
            key = len(lines)
    return {"scene_title": "Таблица решений", "story": "Аналитик прислал таблицу решений для тестов доставки. До приёмки её нужно проверить.",
            "prompt": "Нажмите на строку таблицы с неверным ожидаемым результатом.", "panel": {"type": "code", "lang": "text", "lines": lines}, "key": key}


PARAMS = [("Браузер", ["Chrome", "Firefox", "Safari", "Edge", "Яндекс Браузер"]), ("ОС", ["Windows", "macOS", "Linux", "Android", "iOS"]),
          ("Язык", ["ru", "en", "kk", "uz", "hy"]), ("Оплата", ["карта", "СБП", "кошелёк", "рассрочка", "наличные"]),
          ("Доставка", ["курьер", "ПВЗ", "постамат", "самовывоз", "почта"])]


@family("qae_td_pairwise", "QA", "Тест-дизайн", "choice", 2.1, 1.0)
def _(rng):
    chosen = rng.sample(PARAMS, 4)
    sizes = [rng.randint(2, 5) for _ in chosen]
    lines = [f"{name}: {', '.join(vals[:n])}" for (name, vals), n in zip(chosen, sizes)]
    s = sorted(sizes)
    full = s[0] * s[1] * s[2] * s[3]
    lower = s[2] * s[3]
    opts, key = _choice(rng, f"{lower}: столько пар значений у двух самых «широких» параметров", [
        f"{full}: попарное покрытие всё равно требует перебрать все комбинации всех параметров",
        f"{s[3]}: достаточно по одному тесту на каждое значение самого «широкого» параметра",
        f"{full // s[0]}: «узкий» параметр можно не комбинировать",
    ])
    return {"scene_title": "Комбинации", "story": f"Форму оформления нужно проверить в комбинациях {len(chosen)} параметров. Полный перебор — {full} прогонов, времени нет.",
            "prompt": "Меньше какого числа тестов попарного (pairwise) покрытия точно не получится — какова нижняя граница?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


@family("qae_td_state", "QA", "Тест-дизайн", "choice", 2.2, 2.0)
def _(rng):
    ent, st, bug = rng.choice([
        ("заказ", ["Создан", "Оплачен", "Собран", "Доставлен", "Отменён"], "отменённый заказ удалось оплатить по старой ссылке"),
        ("бронь", ["Создана", "Оплачена", "Подтверждена", "Завершена", "Отменена"], "завершённую бронь удалось отменить с возвратом денег"),
        ("заявка", ["Черновик", "Отправлена", "Одобрена", "Выдана", "Отклонена"], "отклонённую заявку удалось отправить повторно и одобрить"),
    ])
    lines = [f"{st[0]} → {st[1]}: оплата", f"{st[1]} → {st[2]}: подтверждение склада", f"{st[2]} → {st[3]}: вручение",
             f"{st[0]} → {st[4]}: отмена клиентом", f"{st[1]} → {st[4]}: отмена с возвратом"]
    rng.shuffle(lines)
    opts, key = _choice(rng, "Запрещённые переходы не проверялись: нужна таблица «состояние × событие» со всеми парами", [
        "Покрыть все пары последовательных переходов (1-switch): цепочки длины 2 найдут такие дефекты",
        "Добавить граничные значения суммы оплаты и срока действия ссылки на каждом переходе",
        "Повторить те же тесты переходов на продовом окружении с реальными данными клиентов и платежей",
    ])
    return {"scene_title": "Статусы", "story": f"Тесты покрывают все {len(lines)} переходов диаграммы статусов, но в проде {bug}.",
            "prompt": "Почему тесты это пропустили и что добавить в тест-дизайн?", "panel": {"type": "code", "lang": "text", "lines": lines,
                                                                                         "caption": f"диаграмма статусов: {ent}"}, "options": opts, "key": key}


# --- Приёмка релиза ---


@family("qae_acc_smoke", "QA", "Приёмка релиза", "choice", 2.1, -1.3)
def _(rng):
    build = f"{rng.randint(3, 5)}.{rng.randint(10, 40)}.{rng.randint(0, 9)}"
    name, err = rng.choice([("оформление заказа", "POST /api/checkout → 500 Internal Server Error"), ("оплата картой", "POST /api/payments → 502 Bad Gateway"),
                            ("вход по коду", "POST /api/auth/verify → 500 Internal Server Error")])
    ok = rng.sample(["главная страница", "поиск", "карточка товара", "корзина", "профиль", "избранное", "каталог"], rng.randint(4, 6))
    m = rng.randint(10, 50)
    runs = [("PASS", s) for s in ok]
    runs.insert(rng.randint(1, len(runs)), ("FAIL", f"{name}: {err}"))
    lines = [_log(f"10:{m:02d}:00", "smoke", "INFO", f"сборка {build} на stage, запуск смоук-набора")]
    lines += [_log(f"10:{m:02d}:{5 + 7 * i:02d}", "smoke", "ERROR" if r == "FAIL" else "INFO", f"{r} {s}") for i, (r, s) in enumerate(runs)]
    lines.append(_log(f"10:{m + 1:02d}:02", "smoke", "INFO", f"итог: {len(ok)} passed, 1 failed"))
    opts, key = _choice(rng, f"Вернуть сборку {build} в разработку с дефектом по «{name}»: смоук не пройден", [
        f"Начать полный регресс по плану, а упавший сценарий «{name}» перепроверить в самом конце",
        f"Принять сборку: упал только 1 тест из {len(ok) + 1}, остальные сценарии работают штатно",
        "Перезапускать смоук-набор, пока он не станет полностью зелёным, и только потом начинать регресс",
    ])
    return {"scene_title": "Смоук", "story": f"Сборку {build} выкатили на стенд приёмки. Прежде чем начинать регресс, прогнали смоук.",
            "prompt": "Что делать дальше?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("qae_acc_canary", "QA", "Приёмка релиза", "choice", 2.4, 1.2)
def _(rng):
    step = rng.choice(["оплаты", "оформления заказа", "добавления в корзину"])
    ver, h0 = f"{rng.randint(6, 9)}.{rng.randint(0, 30)}", rng.randint(10, 14)
    x = [f"{h0 + i}:00" for i in range(7)]
    base = rng.uniform(3.0, 3.6)
    stable = [round(base + rng.uniform(-0.15, 0.15), 1) for _ in x]
    drop = rng.uniform(0.7, 1.1)
    canary = [round(base - drop + rng.uniform(-0.15, 0.15), 1) for _ in x]
    err = [round(rng.uniform(0.2, 0.5), 1) for _ in x]
    panel = {"type": "chart", "x": x, "marker": {"i": 0, "label": f"канарейка {ver}, 10 %"}, "series": [
        {"name": f"конверсия {step}, канарейка, %", "axis": "left", "max": 5, "data": canary},
        {"name": f"конверсия {step}, стабильная версия, %", "axis": "left", "max": 5, "data": stable},
        {"name": "5xx канарейки, %", "axis": "right", "max": 5, "data": err},
    ]}
    opts, key = _choice(rng, f"Остановить раскатку: конверсия {step} у канарейки ниже — искать тихий дефект", [
        "Раскатывать дальше: доля 5xx у канарейки не выше обычной, значит, ошибок в новой версии нет",
        "Сразу раскатить на 50 %: больше трафика — быстрее наберётся статистика по конверсии",
        "Решать после раскатки на 100 %: на 10 % трафика метрики конверсии ничего не значат",
    ])
    return {"scene_title": "Канарейка", "story": f"Версию {ver} выкатили на 10 % пользователей. Через шесть часов нужно решить, раскатывать ли дальше.",
            "prompt": "Какое решение принять?", "panel": panel, "options": opts, "key": key}


@family("qae_acc_rollback", "QA", "Приёмка релиза", "choice", 2.2, 2.3)
def _(rng):
    ver = f"{rng.randint(3, 6)}.{rng.randint(0, 20)}.0"
    what, old, new, flag = rng.choice([("адресов", "city, street", "address_id", "new_addresses"), ("цен", "price, currency", "price_id", "new_pricing"),
                                       ("статусов", "status_text", "status_code", "new_statuses")])
    n = rng.randint(100, 399)
    lines = [f"Релиз {ver}", f"— миграция 0{n}: колонки {old} → {new}, старые колонки удаляются", f"— фича «Новая модель {what}» под флагом {flag}, по умолчанию выключена",
             f"— план отката: выключить {flag}, при необходимости вернуть предыдущий образ"]
    if rng.random() < 0.5:
        lines.insert(1, f"— исправлено {rng.randint(3, 9)} мелких дефектов интерфейса")
    opts, key = _choice(rng, "Работает ли предыдущая версия на схеме, где старые колонки уже удалены", [
        f"Что {flag} по умолчанию выключен — этого хватит для отката",
        "Что миграция на копии продовой базы проходит быстрее минуты и не блокирует запись",
        "Что снят свежий бэкап базы: при проблемах откат делается восстановлением из него",
    ])
    return {"scene_title": "План отката", "story": f"Перед приёмкой релиза {ver} вы читаете заметки к выпуску. Главное — убедиться, что релиз можно откатить.",
            "prompt": "Что обязательно проверить при приёмке?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


# --- Автотесты ---


@family("qae_auto_assert", "QA", "Автотесты", "mark", 2.2, -1.5)
def _(rng):
    fn, promo = rng.choice([("apply_promo", "SALE10"), ("apply_coupon", "WELCOME"), ("apply_discount", "AUTUMN15")])
    sku, qty, price = f"SKU-{rng.randint(100, 999)}", rng.randint(2, 5), rng.choice([500, 900, 1200])
    lines = [f"def test_{fn}(cart):"]
    if rng.random() < 0.5:
        lines.append('    """Промокод уменьшает сумму корзины на 10 %."""')
    lines += [f'    cart.add("{sku}", qty={qty})', f'    cart.{fn}("{promo}")', f"    cart.total == {qty * price * 9 // 10}"]
    key = len(lines)
    lines += ["", "", f"def test_{fn}_expired(cart):", f'    cart.add("{sku}", qty=1)', "    with pytest.raises(PromoExpired):", f'        cart.{fn}("OLD{promo}")']
    return {"scene_title": "Вечно зелёный", "story": f"Тест промокода зелёный уже месяц, хотя вчера промокод {promo} на стенде вообще не применялся.",
            "prompt": "Нажмите на строку, из-за которой тест не может упасть.", "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("qae_auto_shared", "QA", "Автотесты", "mark", 2.3, 0.9)
def _(rng):
    ent, scope = rng.choice(["account", "wallet", "card"]), rng.choice(["module", "session"])
    bal, w, d = rng.choice([1000, 2000, 5000]), rng.choice([300, 400, 700]), rng.choice([100, 200, 250])
    lines = ["import pytest"]
    if rng.random() < 0.5:
        lines.append("from helpers import money")
    lines += ["", f'@pytest.fixture(scope="{scope}")']
    key = len(lines)
    lines += [f"def {ent}(api):", f"    return api.create_{ent}(balance={bal})", ""]
    tests = [[f"def test_withdraw(api, {ent}):", f"    api.withdraw({ent}.id, {w})", f"    assert api.balance({ent}.id) == {bal - w}", ""],
             [f"def test_deposit(api, {ent}):", f"    api.deposit({ent}.id, {d})", f"    assert api.balance({ent}.id) == {bal + d}", ""]]
    rng.shuffle(tests)
    lines += tests[0] + tests[1][:-1]
    return {"scene_title": "Порядок тестов", "story": "По отдельности тесты баланса зелёные. В полном прогоне со случайным порядком (pytest-randomly) один из них падает.",
            "prompt": "Нажмите на строку с причиной.", "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("qae_auto_tz", "QA", "Автотесты", "choice", 2.3, 2.1)
def _(rng):
    rep = rng.choice(["выручка", "заказы", "возвраты"])
    city, off = rng.choice([("Москвы", 3), ("Екатеринбурга", 5), ("Новосибирска", 7)])
    start = rng.choice([14, 15, 16])
    hours = [(start + i) % 24 for i in range(12)]
    data = [rng.randint(85, 100) if h >= 24 - off else rng.randint(0, 3) for h in hours]
    panel = {"type": "chart", "x": [f"{h:02d}:00" for h in hours],
             "series": [{"name": f"падения теста «{rep} за сегодня», % прогонов", "axis": "left", "max": 100, "data": data}]}
    opts, key = _choice(rng, "Тест и сервис по-разному считают «сегодня»: у них разные часовые пояса", [
        "Ночью на стенде идут бэкапы, база отвечает медленнее, и запросы отчёта не укладываются в тайм-аут",
        "Ночные прогоны идут на другом браузере, и таблица отчёта там отрисовывается иначе",
        "Ночью стенд перезапускается, и первые запросы падают",
    ])
    return {"scene_title": "Ночные падения", "story": f"Тест «{rep} за сегодня» падает только в части ночных прогонов. Сервис считает отчёты по времени {city} (UTC+{off}), на графике — UTC раннера CI.",
            "prompt": "Какая причина вероятнее всего?", "panel": panel, "options": opts, "key": key}

@family("qae_auto_raises", "QA", "Автотесты", "mark", 2.3, 2.75)
def _(rng):
    exc, code, n = rng.choice(["ApiError", "HTTPError", "RequestFailed"]), rng.choice([400, 409, 422]), rng.choice([1, 100, 500])
    over = ["def test_refund_over_total_rejected(api, paid_order):"]
    if rng.random() < 0.5:
        over.append('    """Возврат больше суммы заказа отклоняется."""')
    over += [f"    with pytest.raises({exc}) as err:", f"        api.refund(paid_order.id, amount=paid_order.total + {n})",
             f"        assert err.value.status_code == {code}"]
    keys = [len(over)]
    if rng.random() < 0.5:
        over.append('        assert "exceeds" in err.value.detail')
        keys.append(len(over))
    neg = ["def test_refund_negative_rejected(api, paid_order):", f"    with pytest.raises({exc}) as err:",
           "        api.refund(paid_order.id, amount=-1)", f"    assert err.value.status_code == {code}"]
    if rng.random() < 0.5:
        lines, keys = neg + ["", ""] + over, [k + len(neg) + 2 for k in keys]
    else:
        lines = over + ["", ""] + neg
    return {"scene_title": "Проверка, которая не выполняется",
            "story": f"В проде возврат больше суммы заказа отклоняется с кодом 500 вместо {code}. Тест на этот случай при этом стабильно зелёный.",
            "prompt": "Нажмите на строку, из-за которой тест не замечает неверный код ответа.",
            "panel": {"type": "code", "lang": "python", "lines": lines}, "key": keys}


# --- API-тестирование ---


@family("qae_api_status", "QA", "API-тестирование", "choice", 2.1, -1.0)
def _(rng):
    res, field = rng.choice([("orders", "delivery_address"), ("users", "email"), ("payments", "amount"), ("bookings", "slot_id")])
    m = rng.randint(10, 50)
    lines = [
        _log(f"11:{m:02d}:12", "api-test", "INFO", f"POST /api/{res} без обязательного поля {field}"),
        _log(f"11:{m:02d}:12", "api-test", "INFO", f'← 200 OK {{"error": "field \'{field}\' is required"}}'),
        _log(f"11:{m:02d}:13", "api-test", "INFO", f"POST /api/{res} с полным телом"),
        _log(f"11:{m:02d}:13", "api-test", "INFO", f'← 201 Created {{"id": {rng.randint(1000, 9999)}}}'),
    ]
    opts, key = _choice(rng, "Да: ошибка валидации пришла с кодом 200, ожидается 400 или 422", [
        "Дефекта нет: текст ошибки есть в теле ответа, и клиент всё равно его покажет",
        "Да, но ожидается 500 Internal Server Error: сервер не смог обработать запрос",
        f"Ожидается 201: объект нужно создать, а {field} заполнить позже",
    ])
    return {"scene_title": "Неполный запрос", "story": f"Вы проверяете валидацию POST /api/{res}: отправляете запрос без обязательного поля.",
            "prompt": "Есть ли дефект?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("qae_api_order", "QA", "API-тестирование", "mark", 2.3, 0.8)
def _(rng):
    cat, n, k = rng.choice(["books", "toys", "garden", "sport"]), rng.choice([12, 20, 30]), rng.choice([15, 20, 25])
    lines = ["def test_category_items(api, seeded):"]
    if rng.random() < 0.5:
        lines.append(f"    # фикстура seeded заливает {n} товаров категории")
    lines += [f'    resp = api.get("/categories/{cat}/items", params={{"limit": 50}})', "    assert resp.status_code == 200",
              '    items = resp.json()["items"]', f"    assert len(items) == {n}"]
    if rng.random() < 0.5:
        lines.append(f'    assert all(i["category"] == "{cat}" for i in items)')
    lines.append('    assert items[0]["sku"] == seeded[0].sku')
    key = len(lines)
    lines.append('    assert all(i["price"] > 0 for i in items)')
    return {"scene_title": "Плавающий тест", "story": f"Тест категории падает примерно в одном прогоне из {k}. В упавших прогонах в ответе те же {n} товаров.",
            "prompt": "Нажмите на строку, из-за которой тест нестабилен.", "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("qae_api_race", "QA", "API-тестирование", "choice", 2.3, 2.4)
def _(rng):
    bal = rng.choice([1000, 1500, 3000])
    amt = bal // 2 + rng.choice([100, 200, 300])
    res = rng.choice(["withdrawals", "transfers", "payouts"])
    ids, m = rng.sample(range(1000, 9999), 2), rng.randint(10, 50)
    lines = [
        _log(f"14:{m:02d}:07.112", "gateway", "INFO", f"POST /api/{res} amount={amt} req={ids[0]}"),
        _log(f"14:{m:02d}:07.114", "gateway", "INFO", f"POST /api/{res} amount={amt} req={ids[1]}"),
        _log(f"14:{m:02d}:07.190", "gateway", "INFO", f"req={ids[0]} ← 201 Created"),
        _log(f"14:{m:02d}:07.193", "gateway", "INFO", f"req={ids[1]} ← 201 Created"),
        _log(f"14:{m:02d}:09.020", "ledger", "WARN", f"balance account=… is {bal - 2 * amt}"),
    ]
    opts, key = _choice(rng, "Параллельные запросы с общим стартом и проверкой, что баланс ≥ 0", [
        f"Граничные значения суммы: {bal - 1}, {bal}, {bal + 1} — последовательно, по одному запросу",
        "Строже проверить код 201 и схему тела ответа",
        "Тот же последовательный тест списания, повторённый 100 раз подряд в одном прогоне",
    ])
    return {"scene_title": "Минус на счёте", "story": f"Баланс счёта {bal}. Клиент дважды быстро нажал «Вывести {amt}», и счёт ушёл в минус. Весь регресс API при этом зелёный.",
            "prompt": "Какой тест поймал бы этот дефект?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}

@family("qae_api_redelivery", "QA", "API-тестирование", "choice", 2.4, 2.9)
def _(rng):
    event, svc, what = rng.choice([("OrderPaid", "loyalty", "баллы"), ("PaymentCaptured", "cashback", "кешбэк"), ("ReferralConfirmed", "bonus", "бонус")])
    why = rng.choice(["ack not sent: consumer timeout 30s", "ack lost: consumer group rebalance", f"ack not sent: pod {svc}-2 restarted"])
    msg, order, pts, m = f"m-{rng.randint(10000, 99999)}", rng.randint(100000, 999999), rng.choice([150, 300, 500]), rng.randint(10, 40)
    lines = [
        _log(f"18:{m:02d}:04", "broker", "INFO", f"deliver {event} msg_id={msg} order={order} attempt=1 → {svc}"),
        _log(f"18:{m:02d}:05", svc, "INFO", f"order={order}: начислено {pts} ({what})"),
        _log(f"18:{m:02d}:35", svc, "WARN", why),
        _log(f"18:{m + 1:02d}:06", "broker", "INFO", f"redeliver {event} msg_id={msg} order={order} attempt=2 → {svc}"),
        _log(f"18:{m + 1:02d}:07", svc, "INFO", f"order={order}: начислено {pts} ({what})"),
        _log(f"18:{m + 2:02d}:00", "ledger", "WARN", f"order={order}: сумма начислений {2 * pts} при ожидаемых {pts}"),
    ]
    opts, key = _choice(rng, f"Доставить {event} с тем же msg_id повторно и проверить, что {what} начислены один раз", [
        "Увеличить тайм-аут подтверждения и тестом проверять, что ack всегда укладывается в него",
        f"Контрактный тест порядка: события {event} по одному заказу обрабатываются строго по очереди",
        f"Ужесточить контракт схемы {event}: сумма обязательна, положительна и совпадает с заказом",
    ])
    return {"scene_title": "Двойное начисление",
            "story": f"Сервис {svc} покрыт контрактными тестами схемы {event} и e2e-сценарием «оплатил — получил {what}», всё зелёное. В проде части клиентов {what} пришли дважды.",
            "prompt": "Какой тест поймал бы этот дефект до прода?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Баг-репорты ---

SEV = {"hh": "Серьёзность высокая, приоритет высокий", "hl": "Серьёзность высокая, приоритет низкий",
       "lh": "Серьёзность низкая, приоритет высокий", "ll": "Серьёзность низкая, приоритет низкий"}


@family("qae_bug_severity", "QA", "Баг-репорты", "choice", 2.0, 0.2)
def _(rng):
    sit, right = rng.choice([
        ("в названии бренда на главной странице опечатка, а завтра стартует рекламная кампания", "lh"),
        ("приложение аварийно закрывается при выгрузке годового отчёта; ближайшая выгрузка через 10 месяцев, есть обходной путь", "hl"),
        ("оплата картой не проходит ни у одного пользователя", "hh"),
        ("в настройках уведомлений иконка сдвинута на 2 пикселя", "ll"),
    ])
    opts, key = _choice(rng, SEV[right], [v for k, v in SEV.items() if k != right])
    return {"scene_title": "Классификация", "story": f"Вы заводите дефект: {sit}.",
            "prompt": "Какие серьёзность (severity) и приоритет (priority) поставить?", "panel": None, "options": opts, "key": key}


DIMS = [("версия приложения", ["5.12.0", "5.11.3"]), ("ОС", ["iOS", "Android"]), ("способ оплаты", ["карта", "СБП"]), ("регион", ["RU-MOW", "RU-SVE"])]


@family("qae_bug_condition", "QA", "Баг-репорты", "choice", 2.3, 1.3)
def _(rng):
    dims = rng.sample(DIMS, 3)
    bad = rng.choice(dims[0][1])
    good = next(v for v in dims[0][1] if v != bad)
    rows = []
    for culprit in (bad, good):
        for v1 in dims[1][1]:
            for v2 in dims[2][1]:
                rows.append((culprit, v1, v2, culprit == bad))
    rng.shuffle(rows)
    m = rng.randint(10, 40)
    lines = [_log(f"09:{m:02d}:{5 * i:02d}", "payments", "ERROR" if fail else "INFO",
                  f"pay {rng.randint(10000, 99999)} {'declined: internal_error' if fail else 'ok'} | {dims[0][0]}={c} {dims[1][0]}={v1} {dims[2][0]}={v2}")
             for i, (c, v1, v2, fail) in enumerate(rows)]
    opts, key = _choice(rng, f"Воспроизводится только при «{dims[0][0]}» = {bad}; остальные параметры не влияют", [
        f"Воспроизводится только при «{dims[1][0]}» = {dims[1][1][0]}; остальные параметры не влияют",
        f"Воспроизводится только при «{dims[2][0]}» = {dims[2][1][1]}; остальные параметры не влияют",
        "Воспроизводится у всех клиентов: условие в баг-репорте указывать не нужно",
    ])
    return {"scene_title": "Условия", "story": "Поддержка: «у части клиентов не проходит оплата». Перед тем как завести дефект, вы выгрузили последние попытки.",
            "prompt": "Какое условие воспроизведения указать в баг-репорте?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("qae_bug_dupes", "QA", "Баг-репорты", "choice", 2.2, 1.8)
def _(rng):
    screens = rng.sample(["Корзина", "Каталог", "Избранное", "Заказ", "Поиск", "Профиль"], 4)
    fn, other = rng.choice([("format_price", "load_avatar"), ("render_discount", "parse_deeplink"), ("currency_symbol", "read_push_token")])
    odd = rng.randrange(4)
    ver, m = f"7.{rng.randint(1, 9)}.{rng.randint(0, 5)}", rng.randint(10, 40)
    lines = []
    for i, s in enumerate(screens):
        trace = (f"TypeError: 'NoneType' object is not subscriptable\n  at {other} (media.py:{rng.randint(20, 90)})" if i == odd
                 else f"TypeError: unsupported operand type(s) for *: 'NoneType' and 'float'\n  at {fn} (money.py:42)")
        lines.append(_log(f"16:{m + i:02d}:{rng.randint(0, 59):02d}", "crash-reports", "ERROR", f"app {ver} screen={s}\n{trace}"))
    same = [s for i, s in enumerate(screens) if i != odd]
    opts, key = _choice(rng, f"Два: общий на {fn} для экранов {', '.join(same)} и отдельный на «{screens[odd]}»", [
        "Четыре отдельных дефекта, по одному на экран: так их проще распределить по командам",
        "Один дефект на все четыре экрана: падения в одной версии и в один час — причина общая",
        f"Один дефект на самый посещаемый экран «{screens[0]}», остальные отчёты закрыть без ссылки",
    ])
    return {"scene_title": "Четыре падения", "story": f"За час после выкладки {ver} пришло четыре отчёта о падении приложения на разных экранах. Нужно завести дефекты.",
            "prompt": "Как оформить дефекты?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}

@family("qae_bug_signals", "QA", "Баг-репорты", "choice", 2.3, 2.6)
def _(rng):
    pods = ["orders-1", "orders-2", "orders-3"]
    bad = rng.choice(pods)
    good = [x for x in pods if x != bad]
    v, h, m = rng.randint(3, 8), rng.randint(10, 15), rng.randint(5, 20)
    calls = [(bad, "СБП"), (bad, "СБП"), (bad, "карта"), (good[0], "СБП"), (good[1], "СБП"), (good[0], "карта"), (good[1], rng.choice(["СБП", "карта"]))]
    rng.shuffle(calls)
    slow = rng.choice([i for i, (pod, _) in enumerate(calls) if pod != bad])
    lines = [_log(f"{h}:{m:02d}:00", bad, "INFO", f"config reload: webhook_secret v{v} → v{v + 1}")]
    for i, (pod, meth) in enumerate(calls):
        t, pay = f"{h}:{m + 3 + 4 * i:02d}:{rng.randint(0, 59):02d}", rng.randint(10000, 99999)
        if pod == bad:
            lines.append(_log(t, pod, "WARN", f"callback pay={pay} method={meth} → 401 invalid signature"))
        else:
            tail = f", provider latency {rng.uniform(2.1, 3.4):.1f}s" if i == slow else ""
            lines.append(_log(t, pod, "INFO", f"callback pay={pay} method={meth} → 200 ok{tail}"))
    opts, key = _choice(rng, f"Новый секрет только на {bad}, провайдер подписывает старым: отказывают колбэки, попавшие на {bad}", [
        "Не проходит оплата через СБП: на колбэки СБП приходится большинство отказов в выгрузке",
        "Провайдер подписывает колбэки неверно: дефект на его стороне, эскалировать провайдеру",
        "Провайдер отвечает медленно, и колбэки не укладываются в тайм-аут: его надо увеличить",
    ])
    return {"scene_title": "Заказ висит", "story": "Поддержка: «у части клиентов деньги списались, а заказ висит в статусе „ожидает оплаты“». Вы выгрузили обработку колбэков платёжного провайдера.",
            "prompt": "Какую причину и условие воспроизведения указать в баг-репорте?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Регресс ---


@family("qae_reg_notes", "QA", "Регресс", "choice", 2.1, -1.1)
def _(rng):
    ver, total = f"{rng.randint(2, 4)}.{rng.randint(10, 40)}.{rng.randint(1, 9)}", rng.choice([1200, 1800, 2400])
    screen, change = rng.choice([("экран профиля", "исправлен текст кнопки «Сохранить изменения»"), ("экран корзины", "поправлен перенос длинных названий товаров"),
                                 ("экран поиска", "изменён текст подсказки в пустой строке поиска")])
    lines = [f"Релиз {ver} (hotfix)", f"— {screen}: {change}", "— других изменений нет"]
    opts, key = _choice(rng, f"Проверить {screen} и пройти смоук основных сценариев", [
        f"Полный регресс по всем {total} кейсам, как перед обычным релизом",
        "Регресс не нужен: изменился только текст",
        "Прогнать только автотесты оплаты и корзины — они самые важные",
    ])
    return {"scene_title": "Хотфикс", "story": f"Вечером нужно выпустить хотфикс {ver}. Заметки к выпуску — на панели.",
            "prompt": "Какой регресс достаточен?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


@family("qae_reg_progress", "QA", "Регресс", "choice", 2.2, 0.4)
def _(rng):
    days = rng.choice([6, 7])
    found = sorted((rng.randint(0, 16) for _ in range(days)), reverse=True)
    found[-1], found[-2] = 0, min(found[-2], 1)
    p = rng.randint(40, 58)
    done = [round(p * (i + 1) / days) for i in range(days)]
    panel = {"type": "chart", "x": [f"день {i + 1}" for i in range(days)], "series": [
        {"name": "найдено дефектов за день", "axis": "left", "max": 20, "data": found},
        {"name": "пройдено кейсов плана, %", "axis": "right", "max": 100, "data": done},
    ]}
    opts, key = _choice(rng, f"Дефектов мало, потому что пройдено лишь около {p} % плана", [
        "Продукт стабилизировался: дефектов больше нет, регресс можно завершать",
        "Тестировщики устали — нужны новые люди",
        "План кейсов завышен: его стоит сократить до уже пройденных кейсов",
    ])
    return {"scene_title": "Тренд дефектов", "story": f"Идёт {days}-й день регресса. Менеджер: «Новых дефектов почти нет — выпускаем?»",
            "prompt": "Что говорит этот график?", "panel": panel, "options": opts, "key": key}


@family("qae_reg_flags", "QA", "Регресс", "choice", 2.3, 2.2)
def _(rng):
    sect, flag, area = rng.choice([("checkout", "new_tax_calc", "расчёта налога"), ("delivery", "smart_slots", "выбора слотов доставки"),
                                   ("payments", "split_payments", "оплаты частями")])
    other, total = rng.choice(["promo_banner", "dark_theme", "new_onboarding"]), rng.choice([800, 1400, 2100])
    lines = [f" {sect}:", f"-  {flag}: false", f"+  {flag}: true", f"   {other}: false"]
    if rng.random() < 0.5:
        lines.insert(0, "@@ config/flags.yaml @@")
    opts, key = _choice(rng, f"Прогнать тесты {area} и смоук с включённым {flag}", [
        "Регресс не нужен: код не менялся, а анализ влияния выбрал ноль тестов",
        "Только юнит-тесты модуля конфигурации флагов",
        "Выключить флаг обратно и выпустить релиз без регресса, а включить уже после выкладки",
    ])
    return {"scene_title": "Ноль тестов", "story": "Пайплайн гоняет только тесты, связанные с изменёнными файлами кода. В релиз уходит единственный дифф.",
            "prompt": "Что делать с регрессом?", "panel": {"type": "code", "lang": "text", "lines": lines,
                                                           "caption": f"анализ влияния: изменён 1 файл, выбрано 0 тестов из {total}"}, "options": opts, "key": key}


@family("qae_reg_risk", "QA", "Регресс", "choice", 2.3, 2.4)
def _(rng):
    target, auto = rng.sample(["оплата", "доставка", "возвраты", "корзина"], 2)
    low, hist = rng.choice(["профиль", "избранное", "отзывы"]), rng.choice(["каталог", "поиск", "рекомендации"])
    cap, total = rng.choice([250, 300, 350]), rng.choice([1600, 1800, 2200])
    rows = [(target, rng.randint(7, 11), rng.randint(10, 25), rng.randint(1, 2), "высокая"), (auto, rng.randint(10, 14), rng.randint(80, 90), rng.randint(1, 2), "высокая"),
            (low, rng.randint(16, 22), rng.randint(5, 15), rng.randint(0, 1), "низкая"), (hist, rng.randint(0, 1), rng.randint(50, 65), rng.randint(6, 9), "средняя")]
    rng.shuffle(rows)
    lines = ["область | PR в релизе | покрыто автотестами | инцидентов за квартал | цена ошибки"] + [f"{a} | {pr} | {cov} % | {inc} | {imp}" for a, pr, cov, inc, imp in rows]
    opts, key = _choice(rng, f"В «{target}»: изменений много, автотестов мало, цена ошибки высокая; в остальных — смоук", [
        f"В «{low}»: там больше всего PR, значит, и новых дефектов будет больше всего",
        f"В «{hist}»: по инцидентам это самая хрупкая область, её проверить первой",
        f"В «{auto}»: цена ошибки высокая, поэтому все её ручные кейсы — первыми",
    ])
    return {"scene_title": "Регресс не влезает", "story": "До релиза два дня, весь ручной регресс не успеть. Нужно решить, куда направить ручные проверки.",
            "prompt": "Куда направить ручной регресс?", "panel": {"type": "code", "lang": "text", "lines": lines,
                                                           "caption": f"на ручной регресс успеваем {cap} из {total} кейсов; автотесты в CI зелёные"}, "options": opts, "key": key}
