"""QA, сюжет «Приёмка релиза»: сценарные семейства с логами, графиками и кодом автотестов — по 3 на компетенцию сверх простых.
У каждого семейства три варианта механики (items._variant), правильные ответы других вариантов — среди дистракторов."""

from app.services.items import _choice, _log, _options, _variant, family

# --- Тест-дизайн ---


@family("qae_td_decision", "QA", "Тест-дизайн", "mark", 2.2, -0.2)
def _(rng):
    v = _variant(rng, 3)
    lines = []
    if v == 0:
        th = rng.choice([2000, 3000, 5000])
        perk, short = rng.choice([("у клиента есть подписка", "подписка"), ("клиент в программе лояльности", "лояльность"), ("заказ в пункт выдачи", "ПВЗ")])
        op = rng.choice(["ИЛИ", "И"])
        lines.append(f"Правило: доставка бесплатна, если сумма ≥ {th} ₽ {op} {perk}")
        if rng.random() < 0.5:
            lines.append("Таблица решений к задаче DLV-" + str(rng.randint(100, 999)))
        lines.append(f"№ | сумма ≥ {th} | {short} | доставка")
        rows = []
        for s, p in [(True, True), (True, False), (False, True), (False, False)]:
            free = (s or p) if op == "ИЛИ" else (s and p)
            rows.append((f"{'да' if s else 'нет'} | {'да' if p else 'нет'}", "бесплатно" if free else "платно", "платно" if free else "бесплатно"))
        story = "Аналитик прислал таблицу решений для тестов доставки. До приёмки её нужно проверить."
    elif v == 1:
        field, lo, hi = rng.choice([("Возраст", 18, 65), ("Количество", 1, 99), ("Срок, мес.", 3, 36)])
        lines.append(f"Требование: поле «{field}» принимает целые числа от {lo} до {hi} включительно")
        lines.append("значение | ожидание")
        rows = [(str(lo - 1), "ошибка валидации", "принято"), (str(lo), "принято", "ошибка валидации"),
                (str(hi), "принято", "ошибка валидации"), (str(hi + 1), "ошибка валидации", "принято")]
        story = "Коллега прислал граничные значения для тестов формы. До приёмки их нужно проверить."
    else:
        lo, hi = rng.choice([(1000, 5000), (2000, 10000), (3000, 15000)])
        lines.append(f"Требование: до {lo - 1} ₽ — без скидки, от {lo} до {hi - 1} ₽ — 5 %, от {hi} ₽ — 10 %")
        lines.append("сумма | скидка")
        rows = [(f"{lo - 1} ₽", "0 %", "5 %"), (f"{lo} ₽", "5 %", "0 %"), (f"{hi - 1} ₽", "5 %", "10 %"), (f"{hi} ₽", "10 %", "5 %")]
        story = "Коллега прислал классы эквивалентности и границы для тестов скидки. До приёмки их нужно проверить."
    bad = rng.randrange(4)
    for i, (cond, ok, wrong) in enumerate(rows):
        lines.append(f"{i + 1} | {cond} | {wrong if i == bad else ok}" if v == 0 else f"{cond} | {wrong if i == bad else ok}")
        if i == bad:
            key = len(lines)
    return {"scene_title": "Ожидаемые результаты", "story": story,
            "prompt": "Нажмите на строку таблицы с неверным ожидаемым результатом.", "panel": {"type": "code", "lang": "text", "lines": lines}, "key": key}


PARAMS = [("Браузер", ["Chrome", "Firefox", "Safari", "Edge", "Яндекс Браузер"]), ("ОС", ["Windows", "macOS", "Linux", "Android", "iOS"]),
          ("Язык", ["ru", "en", "kk", "uz", "hy"]), ("Оплата", ["карта", "СБП", "кошелёк", "рассрочка", "наличные"]),
          ("Доставка", ["курьер", "ПВЗ", "постамат", "самовывоз", "почта"])]
FIELDS = [("Возраст", 18, 65), ("Количество", 1, 99), ("Срок, мес.", 3, 36), ("Сумма, ₽", 100, 50000), ("Этаж", 1, 40)]
CONDS = ["есть подписка", "сумма от 2000 ₽", "доставка в город", "первый заказ", "оплата онлайн", "есть промокод"]


@family("qae_td_pairwise", "QA", "Тест-дизайн", "choice", 2.1, 1.0)
def _(rng):
    v = _variant(rng, 3)
    if v == 0:
        chosen = rng.sample(PARAMS, 4)
        sizes = [rng.randint(2, 5) for _ in chosen]
        lines = [f"{name}: {', '.join(vals[:n])}" for (name, vals), n in zip(chosen, sizes)]
        s = sorted(sizes)
        full = s[0] * s[1] * s[2] * s[3]
        story = f"Форму оформления нужно проверить в комбинациях {len(chosen)} параметров. Полный перебор — {full} прогонов, времени нет."
        prompt = "Меньше какого числа тестов попарного (pairwise) покрытия точно не получится?"
        right, wrong = f"{s[2] * s[3]}: столько пар значений у двух самых «широких» параметров", [
            f"{full}: попарное покрытие всё равно требует перебрать все комбинации всех параметров",
            f"{s[3]}: достаточно по одному тесту на каждое значение самого «широкого» параметра",
            f"{full // s[0]}: «узкий» параметр можно не комбинировать"]
    elif v == 1:
        n = rng.randint(2, 4)
        chosen = rng.sample(FIELDS, n)
        lines = [f"{name}: целое от {lo} до {hi}" for name, lo, hi in chosen]
        story = f"В форме {n} независимых числовых поля с диапазонами. Ошибки ожидаем на границах, и обычно по одной за раз."
        prompt = "Сколько проверок нужно для анализа граничных значений по двухточечной схеме?"
        right, wrong = f"{4 * n}: по четыре значения на поле (у каждой границы и за ней), остальные поля — в норме", [
            f"{4 ** n}: все сочетания граничных значений всех полей",
            f"{2 * n}: по два значения на поле — сами границы",
            f"{n}: по одному значению из середины каждого диапазона"]
    else:
        n = rng.randint(3, 5)
        lines = [f"Условие {i + 1}: {c} — да/нет" for i, c in enumerate(rng.sample(CONDS, n))]
        story = f"Стоимость доставки зависит от {n} независимых условий «да/нет», и все они влияют на результат вместе."
        prompt = "Сколько правил будет в полной таблице решений?"
        right, wrong = f"{2 ** n}: все сочетания {n} условий «да/нет»", [
            f"{2 * n}: по два значения на каждое условие",
            f"{n + 1}: по одному тесту на условие плюс базовый",
            f"{n * n}: каждое условие в паре с каждым"]
    opts, key = _choice(rng, right, wrong)
    return {"scene_title": "Сколько тестов", "story": story, "prompt": prompt, "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


@family("qae_td_state", "QA", "Тест-дизайн", "choice", 2.2, 2.0)
def _(rng):
    ent, st, bugs = rng.choice([
        ("заказ", ["Создан", "Оплачен", "Собран", "Доставлен", "Отменён"],
         ["отменённый заказ удалось оплатить по старой ссылке", "после частичного возврата и повторной отмены деньги вернулись дважды",
          "заказ, оплаченный в последнюю секунду перед автоотменой, отменился, а деньги списались"]),
        ("бронь", ["Создана", "Оплачена", "Подтверждена", "Завершена", "Отменена"],
         ["завершённую бронь удалось отменить с возвратом денег", "после переноса и повторной отмены бронь осталась занятой",
          "бронь, оплаченная за секунду до истечения 15 минут, отменилась, а деньги списались"]),
        ("заявка", ["Черновик", "Отправлена", "Одобрена", "Выдана", "Отклонена"],
         ["отклонённую заявку удалось отправить повторно и одобрить", "после возврата на доработку и повторной отправки заявка потеряла документы",
          "заявку, отправленную в последнюю минуту срока, автоматически отклонили"]),
    ])
    lines = [f"{st[0]} → {st[1]}: оплата", f"{st[1]} → {st[2]}: подтверждение склада", f"{st[2]} → {st[3]}: вручение",
             f"{st[0]} → {st[4]}: отмена клиентом", f"{st[1]} → {st[4]}: отмена с возвратом", f"{st[0]} → {st[4]}: автоотмена через 15 минут без оплаты"]
    rng.shuffle(lines)
    v = _variant(rng, 3)
    opts, key = _options(rng, ["Запрещённые переходы не проверялись: нужна таблица «состояние × событие» со всеми парами",
                               "Дефект проявляется только в цепочке переходов: покрыть пары последовательных переходов (1-switch)",
                               "Автопереход по таймеру не проверяли на границе: событие в последнюю секунду и сразу после тайм-аута"], v,
                         ["Повторить те же тесты переходов на продовом окружении с реальными данными клиентов и платежей",
                          "Добавить нагрузочный тест на каждый переход: дефекты появляются под нагрузкой"])
    return {"scene_title": "Статусы", "story": f"Тесты покрывают все {len(lines)} переходов диаграммы статусов, но в проде {bugs[v]}.",
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
    v = _variant(rng, 3)
    runs = [("PASS", s) for s in ok]
    if v == 0:
        runs.insert(rng.randint(1, len(runs)), ("FAIL", f"{name}: {err}"))
    elif v == 1:
        runs.insert(rng.randint(1, len(runs)), ("PASS", name))
    else:
        dep = rng.choice(["recommendations-api", "reviews-api", "geo-api"])
        runs[-1] = ("FAIL", f"{runs[-1][1]}: {dep} на стенде не развёрнут (503 от stage-gateway, сборка {build} его не меняла)")
    failed = sum(r == "FAIL" for r, _ in runs)
    lines = [_log(f"10:{m:02d}:00", "smoke", "INFO", f"сборка {build} на stage, запуск смоук-набора")]
    lines += [_log(f"10:{m:02d}:{5 + 7 * i:02d}", "smoke", "ERROR" if r == "FAIL" else "INFO", f"{r} {s}") for i, (r, s) in enumerate(runs)]
    lines.append(_log(f"10:{m + 1:02d}:02", "smoke", "INFO", f"итог: {len(runs) - failed} passed, {failed} failed"))
    opts, key = _options(rng, [f"Вернуть сборку {build} в разработку с дефектом по «{name}»: смоук не пройден",
                               f"Смоук пройден: начинать регресс сборки {build} по плану",
                               "Упало из-за стенда, а не сборки: поднять зависимость на стенде, перезапустить упавший тест и начинать регресс"], v,
                         ["Принять сборку без регресса: смоук в целом прошёл, остальные сценарии работают штатно",
                          "Перезапускать весь смоук-набор, пока он не станет полностью зелёным, и только потом разбираться"])
    return {"scene_title": "Смоук", "story": f"Сборку {build} выкатили на стенд приёмки. Прежде чем начинать регресс, прогнали смоук.",
            "prompt": "Что делать дальше?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("qae_acc_canary", "QA", "Приёмка релиза", "choice", 2.4, 1.2)
def _(rng):
    step = rng.choice(["оплаты", "оформления заказа", "добавления в корзину"])
    ver, h0 = f"{rng.randint(6, 9)}.{rng.randint(0, 30)}", rng.randint(10, 14)
    x = [f"{h0 + i}:00" for i in range(7)]
    base = rng.uniform(3.0, 3.6)
    stable = [round(base + rng.uniform(-0.15, 0.15), 1) for _ in x]
    v = _variant(rng, 3)
    if v == 0:
        drop = rng.uniform(0.7, 1.1)
        canary = [round(base - drop + rng.uniform(-0.15, 0.15), 1) for _ in x]
    elif v == 1:
        canary = [round(s + rng.uniform(-0.1, 0.1), 1) for s in stable]
    else:
        at, drop = rng.randint(3, 4), rng.uniform(0.8, 1.2)
        stable = [round(s - (drop if i >= at else 0), 1) for i, s in enumerate(stable)]
        canary = [round(s + rng.uniform(-0.1, 0.1), 1) for s in stable]
    err = [round(rng.uniform(0.2, 0.5), 1) for _ in x]
    panel = {"type": "chart", "x": x, "marker": {"i": 0, "label": f"канарейка {ver}, 10 %"}, "series": [
        {"name": f"конверсия {step}, канарейка, %", "axis": "left", "max": 5, "data": canary},
        {"name": f"конверсия {step}, стабильная версия, %", "axis": "left", "max": 5, "data": stable},
        {"name": "5xx канарейки, %", "axis": "right", "max": 5, "data": err},
    ]}
    wrong = [["Раскатывать дальше: доля 5xx у канарейки не выше обычной, значит, ошибок в новой версии нет",
              "Решать после раскатки на 100 %: на 10 % трафика метрики конверсии ничего не значат"],
             ["Сразу раскатить на 100 %: раз метрики равны, промежуточные шаги не нужны",
              "Решать после раскатки на 100 %: на 10 % трафика метрики конверсии ничего не значат"],
             ["Откатить канарейку: конверсия упала уже после её запуска",
              "Решать после раскатки на 100 %: на 10 % трафика метрики конверсии ничего не значат"]][v]
    opts, key = _options(rng, [f"Остановить раскатку: конверсия {step} у канарейки ниже — искать тихий дефект",
                               "Метрики канарейки не хуже стабильной: переходить к следующему шагу раскатки",
                               "Конверсия просела у обеих версий одновременно: искать общую внешнюю причину, канарейка ни при чём"], v, wrong)
    return {"scene_title": "Канарейка", "story": f"Версию {ver} выкатили на 10 % пользователей. Через шесть часов нужно решить, раскатывать ли дальше.",
            "prompt": "Какое решение принять?", "panel": panel, "options": opts, "key": key}


@family("qae_acc_rollback", "QA", "Приёмка релиза", "choice", 2.2, 2.3)
def _(rng):
    ver = f"{rng.randint(3, 6)}.{rng.randint(0, 20)}.0"
    what, old, new, flag = rng.choice([("адресов", "city, street", "address_id", "new_addresses"), ("цен", "price, currency", "price_id", "new_pricing"),
                                       ("статусов", "status_text", "status_code", "new_statuses")])
    n = rng.randint(100, 399)
    v = _variant(rng, 3)
    if v == 0:
        lines = [f"Релиз {ver}", f"— миграция 0{n}: колонки {old} → {new}, старые колонки удаляются", f"— фича «Новая модель {what}» под флагом {flag}, по умолчанию выключена",
                 f"— план отката: выключить {flag}, при необходимости вернуть предыдущий образ"]
    elif v == 1:
        lines = [f"Релиз {ver}", "— миграций нет", f"— «Новая модель {what}» под флагом {flag}: включается сразу, код старой модели переписан под общий интерфейс",
                 f"— план отката: выключить {flag}"]
    else:
        lines = [f"Релиз мобильного приложения {ver}", "— миграций нет", f"— новые экраны «Новая модель {what}» включены в сборку",
                 "— план отката: «откатить релиз»"]
    if rng.random() < 0.5:
        lines.insert(1, f"— исправлено {rng.randint(3, 9)} мелких дефектов интерфейса")
    opts, key = _options(rng, ["Работает ли предыдущая версия на схеме, где старые колонки уже удалены",
                               f"Что с выключенным {flag} эта сборка ведёт себя как прошлая: старая модель переписана и её надо прогнать заново",
                               "Что новые экраны можно выключить с сервера: релиз из магазина приложений не откатить"], v,
                         ["Что миграция на копии продовой базы проходит быстрее минуты и не блокирует запись",
                          "Что снят свежий бэкап базы: при проблемах откат делается восстановлением из него"])
    return {"scene_title": "План отката", "story": f"Перед приёмкой релиза {ver} вы читаете заметки к выпуску. Главное — убедиться, что релиз можно откатить.",
            "prompt": "Что обязательно проверить при приёмке?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


# --- Автотесты ---


@family("qae_auto_assert", "QA", "Автотесты", "mark", 2.2, -1.5)
def _(rng):
    fn, promo = rng.choice([("apply_promo", "SALE10"), ("apply_coupon", "WELCOME"), ("apply_discount", "AUTUMN15")])
    sku, qty, price = f"SKU-{rng.randint(100, 999)}", rng.randint(2, 5), rng.choice([500, 900, 1200])
    total = qty * price * 9 // 10
    v = _variant(rng, 3)
    lines = []
    if v == 2:
        lines += ["ACTIVE_PROMOS = stand.load_active_promos()  # список промокодов с сервера стенда", "", "", '@pytest.mark.parametrize("promo", ACTIVE_PROMOS)']
        key = len(lines)
        lines.append(f"def test_{fn}(cart, promo):")
    else:
        lines.append(f"def test_{fn}(cart):")
    if rng.random() < 0.5:
        lines.append('    """Промокод уменьшает сумму корзины на 10 %."""')
    lines.append(f'    cart.add("{sku}", qty={qty})')
    if v == 0:
        lines += [f'    cart.{fn}("{promo}")', f"    cart.total == {total}"]
        key = len(lines)
    elif v == 1:
        lines += ["    try:", f'        cart.{fn}("{promo}")', f"        assert cart.total == {total}", "    except Exception:"]
        key = [len(lines), len(lines) + 1]
        lines += ["        pass"]
    else:
        lines += [f"    cart.{fn}(promo)", f"    assert cart.total == {total}"]
    lines += ["", "", f"def test_{fn}_expired(cart):", f'    cart.add("{sku}", qty=1)', "    with pytest.raises(PromoExpired):", f'        cart.{fn}("OLD{promo}")']
    story = (f"Тест промокода в CI не красный уже месяц, хотя вчера промокод {promo} на стенде вообще не применялся. В отчёте рядом с тестом — «got empty parameter set»."
             if v == 2 else f"Тест промокода зелёный уже месяц, хотя вчера промокод {promo} на стенде вообще не применялся.")
    return {"scene_title": "Вечно зелёный", "story": story,
            "prompt": "Нажмите на строку, из-за которой тест не может упасть.", "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("qae_auto_shared", "QA", "Автотесты", "mark", 2.3, 0.9)
def _(rng):
    ent, scope = rng.choice(["account", "wallet", "card"]), rng.choice(["module", "session"])
    bal, w, d = rng.choice([1000, 2000, 5000]), rng.choice([300, 400, 700]), rng.choice([100, 200, 250])
    v = _variant(rng, 3)
    lines = ["import pytest"]
    if rng.random() < 0.5:
        lines.append("from helpers import money")
    if v == 0:
        lines += ["", f'@pytest.fixture(scope="{scope}")']
        key = len(lines)
        lines += [f"def {ent}(api):", f"    return api.create_{ent}(balance={bal})", ""]
        tests = [[f"def test_withdraw(api, {ent}):", f"    api.withdraw({ent}.id, {w})", f"    assert api.balance({ent}.id) == {bal - w}", ""],
                 [f"def test_deposit(api, {ent}):", f"    api.deposit({ent}.id, {d})", f"    assert api.balance({ent}.id) == {bal + d}", ""]]
        rng.shuffle(tests)
        lines += tests[0] + tests[1][:-1]
        story = "По отдельности тесты баланса зелёные. В полном прогоне со случайным порядком (pytest-randomly) один из них падает."
    elif v == 1:
        lines += ["", "CREATED = {}", "", "", f"def test_create_{ent}(api):", f"    acc = api.create_{ent}(balance={bal})", f'    CREATED["{ent}"] = acc.id',
                  f"    assert api.balance(acc.id) == {bal}", "", "", "def test_withdraw(api):", f'    acc_id = CREATED["{ent}"]']
        key = len(lines)
        lines += [f"    api.withdraw(acc_id, {w})", f"    assert api.balance(acc_id) == {bal - w}"]
        story = "Каждый тест отдельно и полный прогон по порядку — зелёные. Со случайным порядком (pytest-randomly) тест списания падает с KeyError."
    else:
        lines += ["import random", "", "", "def test_withdraw(api, catalog):", "    item = random.choice(catalog.items())"]
        key = len(lines)
        lines += [f"    {ent} = api.create_{ent}(balance=item.price)", f"    api.buy({ent}.id, item.id)", f"    assert api.balance({ent}.id) == 0"]
        story = "Тест покупки падает примерно в одном прогоне из десяти — при любом порядке и даже при запуске в одиночку."
    return {"scene_title": "Нестабильный тест", "story": story, "prompt": "Нажмите на строку с причиной.", "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("qae_auto_tz", "QA", "Автотесты", "choice", 2.3, 2.1)
def _(rng):
    rep = rng.choice(["выручка", "заказы", "возвраты"])
    city, off = rng.choice([("Москвы", 3), ("Екатеринбурга", 5), ("Новосибирска", 7)])
    v = _variant(rng, 3)
    if v == 0:
        start = rng.choice([14, 15, 16])
        hours = [(start + i) % 24 for i in range(12)]
        x, data = [f"{h:02d}:00" for h in hours], [rng.randint(85, 100) if h >= 24 - off else rng.randint(0, 3) for h in hours]
        name = f"падения теста «{rep} за сегодня», % прогонов по часам (UTC раннера)"
        story = f"Тест «{rep} за сегодня» падает только в части ночных прогонов. Сервис считает отчёты по времени {city} (UTC+{off})."
    elif v == 1:
        days = [25, 26, 27, 28, 29, 30, 31, 1, 2, 3]
        x, data = [str(d) for d in days], [rng.randint(85, 100) if d >= 30 else rng.randint(0, 3) for d in days]
        name = f"падения теста «{rep} за следующий месяц», % прогонов по числам месяца"
        story = f"Тест «{rep} за следующий месяц» считает период как сегодня + 30 дней. Падает только в отдельные дни месяца."
    else:
        workers = [1, 2, 4, 8, 16]
        x, data = [f"{n} пот." for n in workers], [0 if n == 1 else min(100, n * rng.randint(4, 7)) for n in workers]
        name = f"падения теста «{rep} за сегодня», % прогонов по числу потоков pytest-xdist"
        story = f"Тест «{rep} за сегодня» создаёт заказы под общим тестовым магазином и проверяет сумму по магазину. Падает не всегда."
    panel = {"type": "chart", "x": x, "series": [{"name": name, "axis": "left", "max": 100, "data": data}]}
    opts, key = _options(rng, ["Тест и сервис по-разному считают «сегодня»: у них разные часовые пояса",
                               "«Следующий месяц» как +30 дней в конце месяца уводит дату на месяц дальше: считать календарно",
                               "Тесты пишут в общий магазин и при параллельном запуске мешают друг другу: отдельные данные на тест"], v,
                         ["Ночью на стенде идут бэкапы, база отвечает медленнее, и запросы отчёта не укладываются в тайм-аут",
                          "На стенде иногда перезапускается сервис, и первые запросы падают"])
    return {"scene_title": "Падает не всегда", "story": story, "prompt": "Какая причина вероятнее всего?", "panel": panel, "options": opts, "key": key}


@family("qae_auto_raises", "QA", "Автотесты", "mark", 2.3, 2.75)
def _(rng):
    exc, code, n = rng.choice(["ApiError", "HTTPError", "RequestFailed"]), rng.choice([400, 409, 422]), rng.choice([1, 100, 500])
    v = _variant(rng, 3)
    neg = ["def test_refund_negative_rejected(api, paid_order):", f"    with pytest.raises({exc}) as err:",
           "        api.refund(paid_order.id, amount=-1)", f"    assert err.value.status_code == {code}"]
    if v == 0:
        over = ["def test_refund_over_total_rejected(api, paid_order):"]
        if rng.random() < 0.5:
            over.append('    """Возврат больше суммы заказа отклоняется."""')
        over += [f"    with pytest.raises({exc}) as err:", f"        api.refund(paid_order.id, amount=paid_order.total + {n})",
                 f"        assert err.value.status_code == {code}"]
        keys = [len(over)]
        if rng.random() < 0.5:
            over.append('        assert "exceeds" in err.value.detail')
            keys.append(len(over))
        story = f"В проде возврат больше суммы заказа отклоняется с кодом 500 вместо {code}. Тест на этот случай при этом стабильно зелёный."
        prompt = "Нажмите на строку, из-за которой тест не замечает неверный код ответа."
    elif v == 1:
        over = ["def test_refund_over_total_rejected(api, paid_order):", "    with pytest.raises(Exception):"]
        keys = [len(over), len(over) + 1]
        over += [f"        api.refund(paid_order.id, amout=paid_order.total + {n})"]
        story = "В проде возврат больше суммы заказа проходит — деньги уходят клиенту. Тест «возврат больше суммы отклоняется» при этом стабильно зелёный."
        prompt = "Нажмите на строку, из-за которой тест не замечает, что возврат не отклоняется."
    else:
        over = ["def test_refund_over_total_rejected(api, paid_order, mocker):", '    mocker.patch("payments.client.refund", return_value=None)']
        keys = [len(over)]
        over += [f"    with pytest.raises({exc}) as err:", f"        api.refund(paid_order.id, amount=paid_order.total + {n})",
                 f"    assert err.value.status_code == {code}"]
        story = "Тест возвратов зелёный, но в журнале тестового кабинета провайдера видны реальные возвраты из прогонов CI. Сервис делает «from payments.client import refund»."
        prompt = "Нажмите на строку, из-за которой тест ходит в настоящий провайдер вместо подмены."
    if rng.random() < 0.5:
        lines, keys = neg + ["", ""] + over, [k + len(neg) + 2 for k in keys]
    else:
        lines = over + ["", ""] + neg
    return {"scene_title": "Проверка, которая не проверяет", "story": story, "prompt": prompt,
            "panel": {"type": "code", "lang": "python", "lines": lines}, "key": keys}


# --- API-тестирование ---


@family("qae_api_status", "QA", "API-тестирование", "choice", 2.1, -1.0)
def _(rng):
    res, field = rng.choice([("orders", "delivery_address"), ("users", "email"), ("payments", "amount"), ("bookings", "slot_id")])
    m, oid = rng.randint(10, 50), rng.randint(1000, 9999)
    v = _variant(rng, 3)
    if v == 0:
        story = f"Вы проверяете валидацию POST /api/{res}: отправляете запрос без обязательного поля."
        lines = [_log(f"11:{m:02d}:12", "api-test", "INFO", f"POST /api/{res} без обязательного поля {field}"),
                 _log(f"11:{m:02d}:12", "api-test", "INFO", f'← 200 OK {{"error": "field \'{field}\' is required"}}')]
    elif v == 1:
        story = f"Вы проверяете доступ к GET /api/{res}/{oid}: отправляете запрос без токена."
        lines = [_log(f"11:{m:02d}:12", "api-test", "INFO", f"GET /api/{res}/{oid} без заголовка Authorization"),
                 _log(f"11:{m:02d}:12", "api-test", "INFO", '← 500 Internal Server Error {"error": "NoneType has no attribute user_id"}')]
    else:
        story = f"Вы проверяете GET /api/{res}/{{id}}: запрашиваете id, которого нет."
        lines = [_log(f"11:{m:02d}:12", "api-test", "INFO", f"GET /api/{res}/{oid + 900000} (такого объекта нет)"), _log(f"11:{m:02d}:12", "api-test", "INFO", "← 200 OK {}")]
    lines += [_log(f"11:{m:02d}:13", "api-test", "INFO", f"POST /api/{res} с полным телом"), _log(f"11:{m:02d}:13", "api-test", "INFO", f'← 201 Created {{"id": {oid}}}')]
    opts, key = _options(rng, ["Да: ошибка валидации пришла с кодом 200, ожидается 400 или 422",
                               "Да: на запрос без токена ожидается 401, а не 500",
                               "Да: для несуществующего объекта ожидается 404, а не 200 с пустым телом"], v,
                         ["Дефекта нет: клиент всё равно разберёт тело ответа", "Дефекта нет: главное, что запрос с полным телом проходит"])
    return {"scene_title": "Коды ответа", "story": story, "prompt": "Есть ли дефект?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("qae_api_order", "QA", "API-тестирование", "mark", 2.3, 0.8)
def _(rng):
    cat, n, k = rng.choice(["books", "toys", "garden", "sport"]), rng.choice([12, 20, 30]), rng.choice([15, 20, 25])
    v = _variant(rng, 3)
    lines = ["def test_category_items(api, seeded):"]
    if rng.random() < 0.5:
        lines.append(f"    # фикстура seeded заливает {n} товаров категории")
    lines += [f'    resp = api.get("/categories/{cat}/items", params={{"limit": 50}})', "    assert resp.status_code == 200", '    items = resp.json()["items"]']
    if v == 0:
        lines.append(f"    assert len(items) == {n}")
        if rng.random() < 0.5:
            lines.append(f'    assert all(i["category"] == "{cat}" for i in items)')
        lines.append('    assert items[0]["sku"] == seeded[0].sku')
        key = len(lines)
        story = f"Тест категории падает примерно в одном прогоне из {k}. В упавших прогонах в ответе те же {n} товаров."
    elif v == 1:
        lines.append(f"    assert len(items) == {n}")
        lines.append('    assert items[0]["updated_at"] == seeded[0].updated_at.isoformat()')
        lines.append('    assert resp.json()["generated_at"] == datetime.now().isoformat(timespec="seconds")')
        key = len(lines)
        story = f"Тест категории падает примерно в одном прогоне из {k}. В упавших прогонах товары и их данные совпадают с ожидаемыми."
    else:
        lines.append(f'    assert all(i["category"] == "{cat}" for i in items)')
        lines.append(f'    assert api.get("/items/count").json()["total"] == {n}')
        key = len(lines)
        story = "Тест категории падает только в параллельном прогоне CI, где рядом идут тесты, создающие товары. Товары категории в ответе верные."
    lines.append('    assert all(i["price"] > 0 for i in items)')
    return {"scene_title": "Плавающий тест", "story": story, "prompt": "Нажмите на строку, из-за которой тест нестабилен.",
            "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("qae_api_race", "QA", "API-тестирование", "choice", 2.3, 1.8)
def _(rng):
    bal = rng.choice([1000, 1500, 3000])
    amt = bal // 2 + rng.choice([100, 200, 300])
    res = rng.choice(["withdrawals", "transfers", "payouts"])
    ids, m = rng.sample(range(1000, 9999), 2), rng.randint(10, 50)
    v = _variant(rng, 3)
    if v == 0:
        story = f"Баланс счёта {bal}. Клиент дважды быстро нажал «Вывести {amt}», и счёт ушёл в минус."
        lines = [_log(f"14:{m:02d}:07.112", "gateway", "INFO", f"POST /api/{res} amount={amt} req={ids[0]}"),
                 _log(f"14:{m:02d}:07.114", "gateway", "INFO", f"POST /api/{res} amount={amt} req={ids[1]}"),
                 _log(f"14:{m:02d}:07.190", "gateway", "INFO", f"req={ids[0]} ← 201 Created"), _log(f"14:{m:02d}:07.193", "gateway", "INFO", f"req={ids[1]} ← 201 Created"),
                 _log(f"14:{m:02d}:09.020", "ledger", "WARN", f"balance account=… is {bal - 2 * amt}")]
    elif v == 1:
        key_ = f"idem-{rng.randint(1000, 9999)}"
        story = f"В метро приложение повторило запрос «Вывести {amt}» после обрыва связи — деньги ушли дважды."
        lines = [_log(f"14:{m:02d}:07.112", "gateway", "INFO", f"POST /api/{res} amount={amt} Idempotency-Key={key_} req={ids[0]}"),
                 _log(f"14:{m:02d}:09.500", "gateway", "WARN", f"req={ids[0]}: client disconnected"),
                 _log(f"14:{m:02d}:11.020", "gateway", "INFO", f"POST /api/{res} amount={amt} Idempotency-Key={key_} req={ids[1]}"),
                 _log(f"14:{m:02d}:11.090", "gateway", "INFO", f"req={ids[1]} ← 201 Created (new id)")]
    else:
        story = f"Клиент увидел в приложении чужой вывод средств на {amt}, подставив другой id в ссылку."
        lines = [_log(f"14:{m:02d}:07.112", "gateway", "INFO", f"GET /api/{res}/{ids[0]} user=client-A"),
                 _log(f"14:{m:02d}:07.130", "gateway", "INFO", f"← 200 OK owner=client-B amount={amt}")]
    opts, key = _options(rng, ["Параллельные запросы с общим стартом и проверкой, что баланс ≥ 0",
                               "Повтор запроса с тем же Idempotency-Key и проверка, что создана одна запись",
                               "Запрос чужого объекта от другого пользователя с ожиданием 403 или 404"], v,
                         ["Строже проверить код 201 и схему тела ответа", "Тот же последовательный тест, повторённый 100 раз подряд в одном прогоне"])
    return {"scene_title": "Регресс зелёный", "story": f"{story} Весь регресс API при этом зелёный.",
            "prompt": "Какой тест поймал бы этот дефект?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("qae_api_redelivery", "QA", "API-тестирование", "choice", 2.4, 2.9)
def _(rng):
    event, svc, what, came, done = rng.choice([("OrderPaid", "loyalty", "баллы", "пришли", "начислены"), ("PaymentCaptured", "cashback", "кешбэк", "пришёл", "начислен"),
                                               ("ReferralConfirmed", "bonus", "бонус", "пришёл", "начислен")])
    msg, order, pts, m = f"m-{rng.randint(10000, 99999)}", rng.randint(100000, 999999), rng.choice([150, 300, 500]), rng.randint(10, 40)
    v = _variant(rng, 3)
    if v == 0:
        why = rng.choice(["ack not sent: consumer timeout 30s", "ack lost: consumer group rebalance", f"ack not sent: pod {svc}-2 restarted"])
        bug = f"части клиентов {what} {came} дважды"
        lines = [_log(f"18:{m:02d}:04", "broker", "INFO", f"deliver {event} msg_id={msg} order={order} attempt=1 → {svc}"),
                 _log(f"18:{m:02d}:05", svc, "INFO", f"order={order}: начислено {pts} ({what})"), _log(f"18:{m:02d}:35", svc, "WARN", why),
                 _log(f"18:{m + 1:02d}:06", "broker", "INFO", f"redeliver {event} msg_id={msg} order={order} attempt=2 → {svc}"),
                 _log(f"18:{m + 1:02d}:07", svc, "INFO", f"order={order}: начислено {pts} ({what})"),
                 _log(f"18:{m + 2:02d}:00", "ledger", "WARN", f"order={order}: сумма начислений {2 * pts} при ожидаемых {pts}")]
    elif v == 1:
        bug = f"клиентам, которые отменили заказ, {what} всё равно {done}"
        lines = [_log(f"18:{m:02d}:04", "broker", "INFO", f"deliver OrderCancelled order={order} partition=3 → {svc}"),
                 _log(f"18:{m:02d}:04", svc, "INFO", f"order={order}: отмена — начислений нет, пропускаем"),
                 _log(f"18:{m:02d}:05", "broker", "INFO", f"deliver {event} order={order} partition=7 → {svc}"),
                 _log(f"18:{m:02d}:05", svc, "INFO", f"order={order}: начислено {pts} ({what})"),
                 _log(f"18:{m + 2:02d}:00", "ledger", "WARN", f"order={order}: отменён, но {what} {done}")]
    else:
        bug = f"у части клиентов {what} видны в приложении, а в бухгалтерском журнале их нет"
        lines = [_log(f"18:{m:02d}:04", "broker", "INFO", f"deliver {event} msg_id={msg} order={order} → {svc}"),
                 _log(f"18:{m:02d}:05", svc, "INFO", f"order={order}: баланс клиента +{pts} (запись 1 из 2)"),
                 _log(f"18:{m:02d}:05", svc, "ERROR", "ledger write failed: connection reset; message acked"),
                 _log(f"18:{m + 2:02d}:00", "reconcile", "WARN", f"order={order}: баланс {pts}, в журнале 0")]
    opts, key = _options(rng, [f"Доставить {event} с тем же msg_id повторно и проверить, что {what} {done} один раз",
                               f"Подать события одного заказа не по порядку (отмена раньше {event}) и проверить итог",
                               "Уронить обработчик между двумя записями и проверить, что после повтора данные согласованы"], v,
                         ["Увеличить тайм-аут подтверждения и тестом проверять, что ack всегда укладывается в него",
                          f"Ужесточить контракт схемы {event}: сумма обязательна, положительна и совпадает с заказом"])
    return {"scene_title": "Начисления",
            "story": f"Сервис {svc} покрыт контрактными тестами схемы {event} и e2e-сценарием «оплатил — получил {what}», всё зелёное. В проде {bug}.",
            "prompt": "Какой тест поймал бы этот дефект до прода?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Баг-репорты ---

SEV = {"hh": "Серьёзность высокая, приоритет высокий", "hl": "Серьёзность высокая, приоритет низкий",
       "lh": "Серьёзность низкая, приоритет высокий", "ll": "Серьёзность низкая, приоритет низкий"}


@family("qae_bug_severity", "QA", "Баг-репорты", "choice", 2.0, 0.2)
def _(rng):
    sit, right = [
        ("в названии бренда на главной странице опечатка, а завтра стартует рекламная кампания", "lh"),
        ("приложение аварийно закрывается при выгрузке годового отчёта; ближайшая выгрузка через 10 месяцев, есть обходной путь", "hl"),
        ("оплата картой не проходит ни у одного пользователя", "hh"),
        ("в настройках уведомлений иконка сдвинута на 2 пикселя", "ll"),
    ][_variant(rng, 4)]
    opts, key = _choice(rng, SEV[right], [v for k, v in SEV.items() if k != right])
    return {"scene_title": "Классификация", "story": f"Вы заводите дефект: {sit}.",
            "prompt": "Какие серьёзность (severity) и приоритет (priority) поставить?", "panel": None, "options": opts, "key": key}


DIMS = [("версия приложения", ["5.12.0", "5.11.3"]), ("ОС", ["iOS", "Android"]), ("способ оплаты", ["карта", "СБП"]), ("регион", ["RU-MOW", "RU-SVE"])]


@family("qae_bug_condition", "QA", "Баг-репорты", "choice", 2.3, 1.3)
def _(rng):
    dims = rng.sample(DIMS, 3)
    bad = rng.choice(dims[0][1])
    bad1 = rng.choice(dims[1][1])
    v = _variant(rng, 3)
    rows = []
    for c in dims[0][1]:
        for v1 in dims[1][1]:
            for v2 in dims[2][1]:
                amount = rng.choice([1200, 3400, 8700, 16500, 23900])
                fail = [c == bad, c == bad and v1 == bad1, amount > 15000][v]
                rows.append((c, v1, v2, amount, fail))
    if v == 2 and not any(r[4] for r in rows):
        rows[0] = (*rows[0][:3], 18200, True)
    if v < 2 and all(r[3] > 15000 for r in rows if r[4]):  # сумма не должна случайно объяснять отказы
        i = next(i for i, r in enumerate(rows) if r[4])
        rows[i] = (*rows[i][:3], 3400, True)
    rng.shuffle(rows)
    m = rng.randint(10, 40)
    lines = [_log(f"09:{m:02d}:{5 * i:02d}", "payments", "ERROR" if fail else "INFO",
                  f"pay {rng.randint(10000, 99999)} {'declined: internal_error' if fail else 'ok'} | {amount} ₽ | {dims[0][0]}={c} {dims[1][0]}={v1} {dims[2][0]}={v2}")
             for i, (c, v1, v2, amount, fail) in enumerate(rows)]
    opts, key = _options(rng, [f"Только при «{dims[0][0]}» = {bad}; остальные параметры не влияют",
                               f"Только при сочетании «{dims[0][0]}» = {bad} и «{dims[1][0]}» = {bad1}; по отдельности не воспроизводится",
                               "Только при сумме платежа больше 15 000 ₽; остальные параметры не влияют"], v,
                         ["Воспроизводится у всех клиентов: условие в баг-репорте указывать не нужно",
                          f"Только при «{dims[2][0]}» = {dims[2][1][1]}; остальные параметры не влияют"])
    return {"scene_title": "Условия", "story": "Поддержка: «у части клиентов не проходит оплата». Перед тем как завести дефект, вы выгрузили последние попытки.",
            "prompt": "Какое условие воспроизведения указать в баг-репорте?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("qae_bug_dupes", "QA", "Баг-репорты", "choice", 2.2, 1.8)
def _(rng):
    screens = rng.sample(["Корзина", "Каталог", "Избранное", "Заказ", "Поиск", "Профиль"], 4)
    fn, other = rng.choice([("format_price", "load_avatar"), ("render_discount", "parse_deeplink"), ("currency_symbol", "read_push_token")])
    others = [f"KeyError: 'id'\n  at parse_deeplink (links.py:{rng.randint(20, 90)})", f"IndexError: list index out of range\n  at load_avatar (media.py:{rng.randint(20, 90)})",
              f"ValueError: invalid literal for int()\n  at read_push_token (push.py:{rng.randint(20, 90)})",
              f"ZeroDivisionError: division by zero\n  at rating_stars (reviews.py:{rng.randint(20, 90)})"]
    common = f"TypeError: unsupported operand type(s) for *: 'NoneType' and 'float'\n  at {fn} (money.py:42)"
    odd = rng.randrange(4)
    ver, m = f"7.{rng.randint(1, 9)}.{rng.randint(0, 5)}", rng.randint(10, 40)
    v = _variant(rng, 3)
    traces = [[(f"TypeError: 'NoneType' object is not subscriptable\n  at {other} (media.py:{rng.randint(20, 90)})" if i == odd else common) for i in range(4)],
              [common] * 4, others][v]
    lines = [_log(f"16:{m + i:02d}:{rng.randint(0, 59):02d}", "crash-reports", "ERROR", f"app {ver} screen={s}\n{traces[i]}") for i, s in enumerate(screens)]
    same = [s for i, s in enumerate(screens) if i != odd]
    opts, key = _options(rng, [f"Два: общий на {fn} для экранов {', '.join(same)} и отдельный на «{screens[odd]}»",
                               f"Один дефект на {fn} со списком всех четырёх экранов: стек у всех одинаковый",
                               "Четыре отдельных дефекта: стеки у всех разные, общей причины в отчётах не видно"], v,
                         [f"Один дефект на самый посещаемый экран «{screens[0]}», остальные отчёты закрыть без ссылки",
                          "Один дефект «падения после выкладки» без стеков: разработчики сами разберутся"])
    return {"scene_title": "Четыре падения", "story": f"За час после выкладки {ver} пришло четыре отчёта о падении приложения на разных экранах. Нужно завести дефекты.",
            "prompt": "Как оформить дефекты?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("qae_bug_signals", "QA", "Баг-репорты", "choice", 2.3, 2.6)
def _(rng):
    pods = ["orders-1", "orders-2", "orders-3"]
    bad = rng.choice(pods)
    good = [x for x in pods if x != bad]
    sv, h, m = rng.randint(3, 8), rng.randint(10, 15), rng.randint(5, 20)
    calls = [(bad, "СБП"), (bad, "СБП"), (bad, "карта"), (good[0], "СБП"), (good[1], "СБП"), (good[0], "карта"), (good[1], rng.choice(["СБП", "карта"]))]
    rng.shuffle(calls)
    v = _variant(rng, 3)
    if v == 0:
        lines = [_log(f"{h}:{m:02d}:00", bad, "INFO", f"config reload: webhook_secret v{sv} → v{sv + 1}")]
    elif v == 1:
        lines = [_log(f"{h}:{m:02d}:00", "orders", "INFO", "callback handler: provider status request timeout 3s")]
    else:
        lines = [_log(f"{h}:{m:02d}:00", "provider-news", "INFO", "с сегодняшнего дня колбэки СБП подписываются по схеме signature v2 (см. документацию)")]
    slow = {i for i in range(len(calls)) if rng.random() < 0.45} or {0}
    for i, (pod, meth) in enumerate(calls):
        t, pay = f"{h}:{m + 3 + 4 * i:02d}:{rng.randint(0, 59):02d}", rng.randint(10000, 99999)
        lat = rng.uniform(3.1, 4.2) if i in slow else rng.uniform(0.2, 0.9)
        fail = [pod == bad, i in slow, meth == "СБП"][v]
        msg = ["401 invalid signature", "504 provider status timeout after 3.0s", "401 unsupported signature version v2"][v]
        lines.append(_log(t, pod, "WARN" if fail else "INFO", f"callback pay={pay} method={meth}, provider latency {lat:.1f}s → {msg if fail else '200 ok'}"))
    wrong = [["Не проходит оплата через СБП: на колбэки СБП приходится большинство отказов в выгрузке, а карточные оплаты в основном проходят",
              "Провайдер подписывает колбэки неверно: дефект на его стороне, эскалировать провайдеру"],
             ["Провайдер подписывает колбэки неверно: дефект на его стороне, эскалировать провайдеру",
              "Не проходит оплата через СБП: на колбэки СБП приходится большинство отказов в выгрузке"],
             ["Провайдер подписывает колбэки неверно: дефект на его стороне, эскалировать провайдеру",
              f"Отказы только на одном поде: перезапустить {bad}"]][v]
    opts, key = _options(rng, [f"Секрет обновлён только на {bad}, провайдер подписывает старым: отклоняются колбэки, попавшие на этот под",
                               "Колбэки обрываются, когда провайдер отвечает дольше 3 с: условие — медленный ответ, а не метод или под",
                               "Колбэки СБП приходят с подписью новой версии, которую сервис не поддерживает: условие — СБП на любом поде"], v, wrong)
    return {"scene_title": "Заказ висит", "story": "Поддержка: «у части клиентов деньги списались, а заказ висит в статусе „ожидает оплаты“». Вы выгрузили обработку колбэков платёжного провайдера.",
            "prompt": "Какую причину и условие воспроизведения указать в баг-репорте?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Регресс ---


@family("qae_reg_notes", "QA", "Регресс", "choice", 2.1, -1.1)
def _(rng):
    ver, total = f"{rng.randint(2, 4)}.{rng.randint(10, 40)}.{rng.randint(1, 9)}", rng.choice([1200, 1800, 2400])
    screen, change = rng.choice([("экран профиля", "исправлен текст кнопки «Сохранить изменения»"), ("экран корзины", "поправлен перенос длинных названий товаров"),
                                 ("экран поиска", "изменён текст подсказки в пустой строке поиска")])
    v = _variant(rng, 3)
    body = [[f"— {screen}: {change}", "— других изменений нет"],
            [f"— обновлена общая библиотека форматирования денег money-fmt {rng.randint(2, 3)}.{rng.randint(0, 9)} → {rng.randint(4, 5)}.0", "— других изменений нет"],
            [f"— миграция: новый индекс по orders(created_at), {rng.randint(40, 300)} млн строк", "— интерфейс и API не менялись"]][v]
    lines = [f"Релиз {ver} (hotfix)", *body]
    opts, key = _options(rng, [f"Проверить {screen} и пройти смоук основных сценариев",
                               "Проверить все экраны и сценарии, где выводятся суммы: общая библиотека задевает их все",
                               "Прогнать миграцию на копии продовых данных (время, блокировки) и смоук"], v,
                         [f"Полный регресс по всем {total} кейсам, как перед обычным релизом", "Регресс не нужен: изменения мелкие"])
    return {"scene_title": "Хотфикс", "story": f"Вечером нужно выпустить хотфикс {ver}. Заметки к выпуску — на панели.",
            "prompt": "Какой регресс достаточен?", "panel": {"type": "code", "lang": "text", "lines": lines}, "options": opts, "key": key}


@family("qae_reg_progress", "QA", "Регресс", "choice", 2.2, 0.4)
def _(rng):
    days = rng.choice([6, 7])
    v = _variant(rng, 3)
    p = rng.randint(40, 58)
    if v == 0:
        found = sorted((rng.randint(0, 16) for _ in range(days)), reverse=True)
        found[-1], found[-2] = 0, min(found[-2], 1)
        done = [round(p * (i + 1) / days) for i in range(days)]
        quote = "Новых дефектов почти нет — выпускаем?"
    elif v == 1:
        found = sorted((rng.randint(0, 16) for _ in range(days)), reverse=True)
        found[-1], found[-2] = 0, min(found[-2], 1)
        done = [min(100, round(100 * (i + 1) / (days - 1))) for i in range(days)]
        quote = "План пройден, новых дефектов почти нет, критичные закрыты — выпускаем?"
    else:
        found = sorted(rng.randint(2, 18) for _ in range(days))
        done = [round(90 * (i + 1) / days) for i in range(days)]
        quote = "Пройдено почти 90 % — выпускаем?"
    panel = {"type": "chart", "x": [f"день {i + 1}" for i in range(days)], "series": [
        {"name": "найдено дефектов за день", "axis": "left", "max": 20, "data": found},
        {"name": "пройдено кейсов плана, %", "axis": "right", "max": 100, "data": done},
    ]}
    opts, key = _options(rng, [f"Дефектов мало, потому что пройдено лишь около {p} % плана: выпускать рано",
                               "План пройден, находки сошли на нет: критерии выхода выполнены, регресс можно завершать",
                               "Находок с каждым днём больше: продукт нестабилен, выпускать рано"], v,
                         ["Тестировщики устали — нужны новые люди", "План кейсов завышен: его стоит сократить до уже пройденных кейсов"])
    return {"scene_title": "Тренд дефектов", "story": f"Идёт {days}-й день регресса. Менеджер: «{quote}»",
            "prompt": "Что говорит этот график?", "panel": panel, "options": opts, "key": key}


@family("qae_reg_flags", "QA", "Регресс", "choice", 2.3, 2.2)
def _(rng):
    sect, flag, area = rng.choice([("checkout", "new_tax_calc", "расчёта налога"), ("delivery", "smart_slots", "выбора слотов доставки"),
                                   ("payments", "split_payments", "оплаты частями")])
    other, total = rng.choice(["promo_banner", "dark_theme", "new_onboarding"]), rng.choice([800, 1400, 2100])
    v = _variant(rng, 3)
    if v == 0:
        lines = [f" {sect}:", f"-  {flag}: false", f"+  {flag}: true", f"   {other}: false"]
        head = "@@ config/flags.yaml @@"
    elif v == 1:
        lib = rng.choice(["httpx", "requests", "aiohttp"])
        lines = [f'-{lib} = "{rng.randint(0, 2)}.{rng.randint(20, 27)}.0"', f'+{lib} = "{rng.randint(0, 2)}.{rng.randint(28, 31)}.0"']
        head = "@@ requirements.lock @@"
    else:
        lines = ['-"checkout.pay": "Оплатить"', '+"checkout.pay": "Перейти к оплате заказа"', '-"cart.empty": "Пусто"', '+"cart.empty": "В корзине пока ничего нет — загляните в каталог"']
        head = "@@ i18n/ru.json @@"
    if rng.random() < 0.5:
        lines.insert(0, head)
    opts, key = _options(rng, [f"Прогнать тесты {area} и смоук с включённым {flag}",
                               "Прогнать интеграционные тесты всего, что ходит по HTTP: новая версия библиотеки задевает всех её пользователей",
                               "Проверить экраны с изменёнными строками на переносы и обрезку длинного текста"], v,
                         ["Регресс не нужен: код не менялся, а анализ влияния выбрал ноль тестов", "Только юнит-тесты модуля, где лежит изменённый файл"])
    return {"scene_title": "Ноль тестов", "story": "Пайплайн гоняет только тесты, связанные с изменёнными файлами кода. В релиз уходит единственный дифф.",
            "prompt": "Что делать с регрессом?", "panel": {"type": "code", "lang": "text", "lines": lines,
                                                           "caption": f"анализ влияния: изменён 1 файл, выбрано 0 тестов из {total}"}, "options": opts, "key": key}


@family("qae_reg_risk", "QA", "Регресс", "choice", 2.3, 1.8)
def _(rng):
    target, auto, newf = rng.sample(["оплата", "доставка", "возвраты", "корзина", "подписки"], 3)
    low, hist = rng.choice(["профиль", "избранное", "отзывы"]), rng.choice(["каталог", "поиск", "рекомендации"])
    cap, total = rng.choice([250, 300, 350]), rng.choice([1600, 1800, 2200])
    v = _variant(rng, 3)
    if v == 0:
        rows = [(target, rng.randint(7, 11), f"{rng.randint(10, 25)} %", rng.randint(1, 2), "высокая"), (auto, rng.randint(10, 14), f"{rng.randint(80, 90)} %", rng.randint(1, 2), "высокая"),
                (low, rng.randint(16, 22), f"{rng.randint(5, 15)} %", rng.randint(0, 1), "низкая"), (hist, rng.randint(0, 1), f"{rng.randint(50, 65)} %", rng.randint(6, 9), "средняя")]
    elif v == 1:
        rows = [(target, rng.randint(1, 2), f"{rng.randint(70, 85)} %", rng.randint(0, 1), "высокая"), (auto, 0, f"{rng.randint(92, 97)} %", 0, "высокая"),
                (low, rng.randint(3, 5), f"{rng.randint(60, 75)} %", rng.randint(0, 1), "низкая"), (hist, rng.randint(1, 2), f"{rng.randint(60, 70)} %", rng.randint(1, 2), "средняя")]
    else:
        rows = [(f"{newf} (новая)", rng.randint(12, 18), "0 %", "—", "высокая"), (auto, rng.randint(2, 4), f"{rng.randint(85, 92)} %", rng.randint(0, 1), "высокая"),
                (low, rng.randint(3, 5), f"{rng.randint(40, 60)} %", rng.randint(0, 1), "низкая"), (hist, rng.randint(1, 2), f"{rng.randint(60, 70)} %", rng.randint(1, 2), "средняя")]
    rng.shuffle(rows)
    lines = ["область | PR в релизе | покрыто автотестами | инцидентов за квартал | цена ошибки"] + [f"{a} | {pr} | {cov} | {inc} | {imp}" for a, pr, cov, inc, imp in rows]
    opts, key = _options(rng, [f"Основной ручной ресурс — в «{target}»: много изменений, мало автотестов, высокая цена ошибки; остальное — смоук",
                               f"В «{auto}» ручной регресс можно сократить до смоука: изменений нет, автотесты покрывают почти всё",
                               f"Основной ручной ресурс — в новую «{newf}»: ни автотестов, ни истории; проверять исследовательски по чартерам"], v,
                         [f"Основной ручной ресурс — в «{low}»: там больше всего PR в релизе, значит, и новых дефектов будет больше всего",
                          f"Основной ручной ресурс — в «{hist}»: по инцидентам за квартал это самая хрупкая область, её проверять первой и полностью"])
    return {"scene_title": "Регресс не влезает", "story": "До релиза два дня, весь ручной регресс не успеть. Нужно решить, как распределить ручные проверки.",
            "prompt": "Какое решение по ручному регрессу верно?", "panel": {"type": "code", "lang": "text", "lines": lines,
                                                                           "caption": f"на ручной регресс успеваем {cap} из {total} кейсов; автотесты в CI зелёные"}, "options": opts, "key": key}
