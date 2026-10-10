"""Банк заданий тест-квеста: параметрические шаблоны-семейства (защита от утечки).

Семейство — шаблон сцены: render(rng) подставляет другие сервисы, версии, числа, место бага, порядок
вариантов. Сложность b калибруется по семейству, клоны получают небольшой разброс (±0.1).

payload задания: {scene_title, time, story, prompt, panel, options?, comment?, time_limit_s, key}.
panel — данные для отрисовки на фронте (не картинки):
  {"type": "logs",  "lines": [{"t", "src", "lvl", "msg"}]}
  {"type": "chart", "x": [...], "series": [{"name", "axis": "left"|"right", "max", "data"}], "marker": {"i", "label"}}
  {"type": "code",  "lang", "lines": [str], "caption"?}
key: индекс варианта (choice) или номер строки кода с 1 (mark/review; может быть списком допустимых строк).
Задача на код (kind = code, семейства — services/code_items.py): payload["code"] — сигнатуры, шаблоны, открытые примеры;
key = {"seed"} — из него пересоздаются скрытые тесты, сами тесты и эталон в базе не лежат.
Ключ наружу не отдаётся — см. routers/quest.py.
"""

import random
from collections import Counter, defaultdict

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app import catalog
from app.models import Item
from app.services import code_items, irt, sandbox

TIME_LIMIT = {"choice": 240, "mark": 300, "review": 360, "code": 900}
CLONES = {"Backend": 8}  # остальным специализациям — CLONES_DEFAULT
CLONES_DEFAULT = 5
CLONES_PILOT = 4

# сюжет теста по специализации — единственный источник: вводную и финал фронт берёт из /api/meta, часы — из /api/quest.
# Сквозной герой всех веток — Рей, джек-рассел-терьер кандидата: у каждой специализации своя история с ним, и рабочие
# задачи вырастают из неё (условие задания при этом не зависит от сюжета).
# title — название, head и about — вводная, docs — чем можно пользоваться, finale — заголовок после последней сцены,
# clock — «часы» истории: время сцены зависит от её номера в сессии, а не от задания (выбор адаптивный), поэтому
# story заданий не называет текущий час или день — только прошлое и будущее как часть условия.
# С выключенным сюжетом остаются те же задания: story показывается как условие, без часов и заголовка сцены.
STORY = {
    "Backend": {
        "title": "Где Рей?", "head": "02:14: Рей сбежал, а карта GPS-ошейника пустая",
        "about": "В два ночи Рей запросился во двор, увидел кота, выдернул поводок и растворился в темноте. Ошейник с GPS у него "
                 "от сервиса, где вы бэкенд-разработчик, и именно сейчас там падает приём платежей: подписки не продлеваются, "
                 "карта у хозяев пустая, у вас тоже. Пока соседи шлют фото «кажется, ваш», впереди инциденты, ревью фиксов и вопросы коллег в чате.",
        "docs": "Python и PostgreSQL", "finale": "Рей дома, сервис жив",
        "clock": ["02:14", "02:19", "02:31", "03:05", "09:40", "10:25", "11:10", "12:40", "13:30", "14:15", "15:05", "16:20", "17:30"]},
    "Frontend": {
        "title": "Неделя до выставки", "head": "В субботу выставка джек-расселов, а сайт клуба сыпется",
        "about": "Вы фронтендер клуба любителей джек-рассел-терьеров. Рей заявлен на субботнюю выставку, а через тот же сайт идут "
                 "регистрация сотен собак, оплата взносов и магазин с атрибутикой. До пятницы — баги на предрелизном стенде, медленные экраны, "
                 "доступность и чужие PR, а Рей проверяет, сколько раз можно принести мяч на клавиатуру.",
        "docs": "MDN и вашего фреймворка", "finale": "Сайт выдержал, Рей — на ринге",
        "clock": ["Пн 10:00", "Пн 14:30", "Вт 11:00", "Вт 16:00", "Ср 10:30", "Ср 15:00", "Чт 11:00", "Чт 17:00", "Пт 10:00", "Пт 13:00", "Пт 16:00",
                  "Пт 18:00", "Пт 19:00"]},
    "Mobile": {
        "title": "Релиз на прогулке", "head": "Сборка на ревью в сторе, а Рей требует прогулку",
        "about": "Вы мобильный разработчик приложения для собачников: прогулки по карте, корм с доставкой, лента фото питомцев. "
                 "Сегодня день релиза, но джек-расселу нужно два часа бегать, так что краши, жизненный цикл экранов, офлайн, "
                 "скорость запуска и чужие PR вы разбираете с телефона в парке — между бросками мяча.",
        "docs": "платформы и вашего фреймворка", "finale": "Релиз в сторах, Рей нагулялся",
        "clock": ["09:30", "10:15", "11:00", "12:20", "13:40", "14:30", "15:10", "16:00", "16:45", "17:20", "18:00", "18:40", "19:10"]},
    "ML / DS": {
        "title": "Не бигль", "head": "Модель упорно считает Рея биглем",
        "about": "Вы ML-инженер зоомаркетплейса. Распознавание породы по фото третий день называет Рея то биглем, то фокстерьером, "
                 "и это не единственная модель, у которой поползли метрики. По графикам, логам и коду ищете, где сломалось: "
                 "в постановке, валидации, признаках, дрейфе или выкатке. Рей позирует для новых снимков и глубоко оскорблён.",
        "docs": "библиотек ML", "finale": "Рей снова джек-рассел",
        "clock": ["09:00", "09:45", "10:30", "11:20", "12:40", "13:30", "14:20", "15:10", "16:00", "16:50", "17:30", "18:10", "18:40"]},
    "Data Eng / Analytics": {
        "title": "Сгрызенный отчёт", "head": "Отчёт завтра, а Рей сгрыз черновик",
        "about": "Вы инженер данных или аналитик сети зоомагазинов. Квартальный отчёт сдавать завтра; распечатку черновика Рей "
                 "превратил в конфетти, но цифры в ней всё равно не сходились. Сегодня — запросы, модели данных, ночные загрузки, "
                 "качество данных и графики для отчёта, а Рей лежит под столом и делает вид, что он ни при чём.",
        "docs": "SQL и вашего стека данных", "finale": "Цифры сошлись, Рей прощён",
        "clock": ["08:30", "09:20", "10:10", "11:00", "12:00", "13:20", "14:10", "15:00", "15:50", "16:40", "17:20", "18:00", "18:30"]},
    "DevOps / SRE": {
        "title": "Переезд до прививки", "head": "Ночь переезда, а утром Рею на прививку",
        "about": "Вы SRE сети ветклиник. Этой ночью её сервисы — запись к врачу, карты пациентов, оплата — переезжают в облако, "
                 "а в девять у Рея прививка, и записан он через то же приложение. До рассвета — сети, Kubernetes, CI/CD, "
                 "мониторинг и план отката; Рей спит у вас в ногах и вздрагивает от каждого алерта.",
        "docs": "Kubernetes и облака", "finale": "Переезд закончен, Рей идёт на прививку",
        "clock": ["22:00", "22:20", "22:45", "23:10", "23:40", "00:15", "00:50", "01:30", "02:10", "02:50", "03:30", "04:10", "04:40"]},
    "QA": {
        "title": "Тройной завтрак", "head": "Кормушка покормила Рея трижды — выпускать ли обновление?",
        "about": "Вы тестировщик компании, которая делает умные кормушки и приложение к ним: расписание кормления, заказ корма "
                 "с доставкой, оплата и промокоды. Бета-версия у вас дома накормила Рея трижды, и Рей голосует за релиз всеми "
                 "четырьмя лапами. Решать всё же вам: за день — тест-дизайн, стенд приёмки, автотесты, API, баг-репорты и регресс.",
        "docs": "инструментов тестирования", "finale": "Решение принято, Рей на диете",
        "clock": ["10:00", "10:40", "11:20", "12:00", "13:30", "14:10", "14:50", "15:30", "16:10", "16:50", "17:30", "18:00", "18:30"]},
    "Security": {
        "title": "Открытая дверь", "head": "Час ночи: умный дом сам открыл дверь, и Рей ушёл копать",
        "about": "Вы инженер по безопасности компании, которая делает умный дом. В час ночи ваш собственный замок открылся сам, "
                 "и Рей, не веря счастью, ушёл раскапывать соседскую клумбу. Похоже, это не сбой. До рассвета — разбор инцидента, "
                 "ревью кода, сетевые атаки, криптография и реверс.",
        "docs": "по безопасности (OWASP и др.)", "finale": "Инцидент закрыт, Рей дома",
        "clock": ["01:05", "01:20", "01:40", "02:05", "02:30", "03:00", "03:30", "04:00", "04:30", "05:00", "05:30", "06:00", "06:30"]},
    "Analysis": {
        "title": "Диета для Рея", "head": "Ветеринар выписал Рею диету, а магазин о ней не знает",
        "about": "Вы системный или бизнес-аналитик зоомаркетплейса: его связывают с ветклиниками, зоогостиницами и службами доставки, "
                 "чтобы назначенный врачом корм сам приезжал домой. Рею как раз выписали диету, и интеграцию вы видите глазами клиента. "
                 "Через неделю подключаются новые партнёры, а требования расходятся. Сегодня — требования, процессы, API партнёров, "
                 "данные, спецификации и последствия изменений.",
        "docs": "по нотациям (BPMN, UML) и API партнёра", "finale": "Требования согласованы, корм едет к Рею",
        "clock": ["09:30", "10:15", "11:00", "11:45", "12:30", "13:40", "14:20", "15:00", "15:40", "16:20", "17:00", "17:40", "18:20"]},
    "Management": {
        "title": "Сервис догситтеров", "head": "Квартал на запуск догситтеров, а людей на всё не хватает",
        "about": "Вы проджект- или продакт-менеджер сервиса догситтеров. Главный бета-тестер — Рей: с ним уже посидели все догситтеры "
                 "района, и не все остались прежними. Неделя уйдёт на план квартала — сроки, риски, метрики, приоритеты, стейкхолдеров "
                 "и процессы команды, а в субботу Рей выступает на выставке, и приехать туда хочется с согласованным планом.",
        "docs": "по методологиям и вашему трекеру", "finale": "План согласован, едем с Реем на выставку",
        "clock": ["Пн 10:00", "Пн 15:00", "Вт 11:00", "Вт 16:00", "Ср 10:00", "Ср 14:00", "Чт 11:00", "Чт 16:00", "Пт 10:00", "Пт 12:00", "Пт 14:00",
                  "Пт 16:00", "Пт 18:00"]},
    "Design": {
        "title": "Новый мяч для Рея", "head": "Рей закопал мяч, а купить новый не получается",
        "about": "Вы UX/UI- или продуктовый дизайнер платформы интернет-магазинов: её чекаут стоит у десятков магазинов, от зоотоваров "
                 "до электроники. Рей закопал любимый мяч, вы трижды бросили оформление заказа на новый — и поняли, почему конверсия "
                 "чекаута падает. До пятницы — исследования, юзабилити, доступность, дизайн-система, прототипы и A/B-тесты.",
        "docs": "по WCAG и вашей дизайн-системе", "finale": "Редизайн сдан, мяч едет к Рею",
        "clock": ["Пн 10:00", "Пн 14:00", "Вт 10:30", "Вт 15:00", "Ср 11:00", "Ср 16:00", "Чт 10:00", "Чт 14:30", "Пт 10:00", "Пт 12:30", "Пт 14:00",
                  "Пт 16:00", "Пт 17:30"]},
    "SysAdmin / Support": {
        "title": "Рей в офисе", "head": "Понедельник, 8 утра: Рей в офисе, очередь заявок растёт",
        "about": "Вы сисадмин или инженер поддержки. В офисе разрешили приходить с собаками, и Рей за первые десять минут обследовал "
                 "серверную и попробовал на зуб патч-корд. До вечера — инциденты, сеть, учётки и доступы, бэкапы, серверы и заявки "
                 "пользователей, а Рей носит по этажу чужие тапки и отвечает за моральный дух.",
        "docs": "по ОС и вашему оборудованию", "finale": "Очередь разобрана, Рей спит под столом",
        "clock": ["08:00", "08:20", "08:45", "09:10", "09:40", "10:15", "10:50", "11:30", "12:10", "13:00", "14:00", "15:00", "16:00"]},
}

FAMILIES: list[dict] = []


def family(name: str, spec: str, competency: str, kind: str, a: float, b: float, pilot: bool = False):
    def reg(render):
        FAMILIES.append({"family": name, "spec": spec, "competency": competency, "kind": kind, "a": a, "b": b, "pilot": pilot, "render": render})
        return render

    return reg


def _choice(rng: random.Random, right: str, wrong: list[str]) -> tuple[list[str], int]:
    opts = [right, *wrong]
    rng.shuffle(opts)
    return opts, opts.index(right)


def _variant(rng: random.Random, n: int) -> int:
    """Вариант механики клона: у семейства n разных дефектов или ситуаций, клоны идут по ним по кругу (номер клона кладёт
    в rng.clone generate_bank), так что запомненный ответ одного клона не решает остальные. Вне банка (превью плана) — случайный."""
    i = getattr(rng, "clone", None)
    return rng.randrange(n) if i is None else i % n


def _options(rng: random.Random, rights: list[str], v: int, wrong: list[str] = ()) -> tuple[list[str], int]:
    """Варианты ответа клона варианта v: его правильный ответ, правильные ответы других вариантов как дистракторы
    (запомненный ответ чужого клона здесь неверен) и недостающие до четырёх — из wrong."""
    others = [r for i, r in enumerate(rights) if i != v]
    pool = rng.sample(others, min(3, len(others)))
    return _choice(rng, rights[v], pool + rng.sample(list(wrong), 3 - len(pool)))


def _log(t: str, src: str, lvl: str, msg: str) -> dict:
    return {"t": t, "src": src, "lvl": lvl, "msg": msg}


def _ver(rng: random.Random) -> tuple[str, str]:
    major, minor = rng.randint(2, 4), rng.randint(20, 58)
    return f"v{major}.{minor}.0", f"v{major}.{minor - 1}.{rng.randint(1, 6)}"


SVC = {"payments-api": "POST /payments", "orders-api": "POST /orders", "billing-api": "POST /invoices", "checkout-api": "POST /checkout", "wallet-api": "POST /transfers"}
UPSTREAM = ["fraud-check", "risk-scoring", "antifraud", "limits-api"]


def _svc(rng):
    s = rng.choice(list(SVC))
    return s, SVC[s]


# ============================== Backend: «Где Рей?» ==============================
# a — экспертная оценка до калибровки (сценарные задания с контекстом различают лучше «голых» вопросов);
# ponytail: a и b заданы вручную, пересчитывать по ответам пилотных заданий (MML/EM), когда наберётся ~300 ответов на семейство

# --- Диагностика инцидентов ---
# у каждого семейства — несколько вариантов механики (_variant): разные причины одного симптома или разные дефекты,
# правильные ответы других вариантов идут дистракторами (_options)


@family("be_inc_env", "Backend", "Диагностика инцидентов", "choice", 2.2, -1.6)
def _(rng):
    svc, _ep = _svc(rng)
    ver, _prev = _ver(rng)
    var = rng.choice(["PSP_API_KEY", "REDIS_URL", "KAFKA_BROKERS", "JWT_SECRET", "LEDGER_DSN"])
    m, r = rng.randint(10, 50), rng.randint(3, 6)
    t = lambda s: f"01:{m:02d}:{s:02d}"  # noqa: E731
    v = _variant(rng, 3)
    img = f"registry.internal/{svc}:{ver}"
    if v == 0:
        mid = [_log(t(9), svc, "ERROR", f"Traceback: settings.py line {rng.randint(18, 60)}, in <module>\n    {var.lower()} = os.environ[\"{var}\"]\nKeyError: '{var}'"),
               _log(t(10), "kubelet", "WARN", f"Back-off restarting failed container {svc} (restart {r})"),
               _log(t(31), "kubelet", "WARN", "Readiness probe failed: connection refused")]
    elif v == 1:
        lim = rng.choice([256, 384, 512])
        mid = [_log(t(6), svc, "INFO", f"loading tariffs into memory ({rng.randint(4, 9)} M rows)"),
               _log(t(9), "kubelet", "WARN", f"Container {svc} terminated: reason OOMKilled, exit code 137 (memory limit {lim}Mi)"),
               _log(t(10), "kubelet", "WARN", f"Back-off restarting failed container {svc} (restart {r})"),
               _log(t(31), "kubelet", "WARN", "Readiness probe failed: connection refused")]
    else:
        mid = [_log(t(5), "kubelet", "WARN", f'Failed to pull image "{img}": manifest unknown'),
               _log(t(6), "kubelet", "WARN", "Error: ErrImagePull"),
               _log(t(28), "kubelet", "INFO", f'Back-off pulling image "{img}" (ImagePullBackOff)')]
    lines = [_log(t(2), "deployer", "INFO", f"rollout {svc} {ver} started"), *mid,
             _log(t(40), "deployer", "INFO", f"rollout {svc} {ver}: 0/3 pods ready, previous ReplicaSet still serving")]
    opts, key = _options(rng, [f"В окружении нового релиза не задана переменная {var}", "Контейнер превышает лимит памяти, его убивает OOM-killer",
                               f"Kubernetes не может скачать образ {ver}"], v,
                         ["Readiness-проба настроена слишком строго", "На узлах кончилось место на диске"])
    return {"scene_title": "Выкладка в темноте", "story": f"Ещё до побега Рея кто-то выкатил фикс: выкладка {ver} застряла, "
                                                       f"новые поды {svc} не поднимаются, старые пока держат трафик.",
            "prompt": "В чём причина?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("be_inc_pool", "Backend", "Диагностика инцидентов", "choice", 2.4, 0.0)
def _(rng):
    """Сцена 1 макета: «Пейджер во дворе»."""
    svc, ep = _svc(rng)
    up = rng.choice(UPSTREAM)
    ver, _prev = _ver(rng)
    pool, maxc = rng.choice([5, 10, 20]), rng.choice([100, 200])
    m, ms = rng.randint(5, 40), rng.randint(2050, 2400)
    t = lambda dm, s: f"02:{m + dm:02d}:{s:02d}"  # noqa: E731
    v = _variant(rng, 3)
    if v == 0:
        pool_err = f"TimeoutError: QueuePool limit of size {pool}\n  overflow 0 reached, timeout 2.00"
        mid = [_log(t(1, 40), svc, "WARN", f"db pool: waiting for connection {rng.uniform(1.8, 2.4):.1f}s"),
               _log(t(1, 41), svc, "ERROR", pool_err),
               _log(t(1, 41), svc, "ERROR", f"{ep} 503 ({ms} ms)"),
               _log(t(2, 5), "pg-primary", "LOG", f"connections: {maxc - rng.randint(1, 3)} of max_connections {maxc}"),
               _log(t(2, 30), svc, "ERROR", pool_err)]
    elif v == 1:
        pg_err = 'OperationalError: connection to server at "pg-primary", port 5432 failed: Connection refused'
        mid = [_log(t(1, 38), "pg-primary", "FATAL", "the database system is shutting down"),
               _log(t(1, 40), svc, "ERROR", pg_err),
               _log(t(1, 40), svc, "ERROR", f"{ep} 503 ({rng.randint(3, 15)} ms)"),
               _log(t(2, 5), "patroni", "WARN", "leader lock expired, no healthy replica to promote"),
               _log(t(2, 30), svc, "ERROR", pg_err)]
    else:
        to_err = f"{up}: request timed out after 2.0s (POST /check)"
        mid = [_log(t(1, 40), svc, "WARN", to_err),
               _log(t(1, 41), svc, "ERROR", f"{ep} 504 ({ms} ms)"),
               _log(t(2, 5), svc, "INFO", f"db pool: {rng.randint(1, pool // 2)}/{pool} in use"),
               _log(t(2, 6), up, "WARN", f"GC pause {rng.randint(900, 1800)} ms, heap {rng.randint(95, 99)} %"),
               _log(t(2, 30), svc, "WARN", to_err)]
    lines = [_log(t(0, 58), svc, "INFO", f"deploy {ver} finished (3/3 pods)"), *mid, _log(t(2, 31), svc, "INFO", f"GET /health 200 ({rng.randint(2, 6)} ms)")]
    opts, key = _options(rng, [f"Пул соединений к базе исчерпан после релиза {ver}: запросы держат соединения дольше",
                               "Отказ pg-primary: база недоступна",
                               f"{up} отвечает медленно, и вызовы к нему из {svc} падают по таймауту"], v, [f"Сетевые потери между подами {svc}"])
    return {"scene_title": "Пейджер во дворе", "story": f"Пейджер пищит, пока вы зовёте Рея у подъезда: доля 5xx на {ep} — {rng.randint(22, 45)} %. Открываете логи.",
            "prompt": "Что вероятнее всего стало первопричиной?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("be_inc_rollback", "Backend", "Диагностика инцидентов", "choice", 2.4, 0.6)
def _(rng):
    """Сцена 2 макета: «Графики»."""
    svc, ep = _svc(rng)
    ver, prev = _ver(rng)
    rel, m0 = rng.randint(2, 4), rng.randint(0, 30)
    x = [f"02:{m0 + 2 * i:02d}" for i in range(8)]
    base, peak = rng.randint(160, 200), rng.randint(1900, 2300)
    p95 = [base + rng.randint(-15, 15) if i < rel else int(base * 1.4) if i == rel else peak + rng.randint(-120, 120) for i in range(8)]
    v = _variant(rng, 3)
    if v == 0:
        mark, right = f"релиз {ver}", {"name": "соединения с pg-primary из 100", "axis": "right", "max": 100,
                                       "data": [rng.randint(38, 45) if i < rel else rng.randint(55, 65) if i == rel else rng.randint(96, 99) for i in range(8)]}
    elif v == 1:
        mark, right = "push-рассылка", {"name": f"CPU подов {svc}, %", "axis": "right", "max": 100,
                                        "data": [rng.randint(40, 50) if i < rel else rng.randint(75, 85) if i == rel else rng.randint(95, 99) for i in range(8)]}
    else:
        mark, right = "скрипт сверки в pg-primary", {"name": "запросы в ожидании блокировки", "axis": "right", "max": 200,
                                                     "data": [rng.randint(0, 2) if i < rel else rng.randint(30, 60) if i == rel else rng.randint(140, 190) for i in range(8)]}
    panel = {"type": "chart", "x": x, "marker": {"i": rel, "label": mark}, "series": [
        {"name": f"p95 {ep}, мс", "axis": "left", "max": 2500, "data": p95}, right]}
    opts, key = _options(rng, [f"Откатить на {prev}, затем разбирать, что держит соединения",
                               f"Добавить реплики {svc}: поды упёрлись в CPU",
                               "Найти блокирующий запрос в pg_stat_activity и снять его"], v,
                         ["Поднять max_connections на pg-primary до 300", "Перезапустить pg-primary, чтобы сбросить соединения"])
    return {"scene_title": "Графики", "story": "Тимлид в чате: «Что делаем?». Перед вами графики за 15 минут, и каждая минута — это неуспешные платежи "
                                            "и хозяева, которые, как и вы, не видят своих собак на карте.",
            "prompt": "Какое действие сделать первым?", "panel": panel, "options": opts, "key": key}


@family("be_inc_retry_storm", "Backend", "Диагностика инцидентов", "choice", 2.3, 1.6)
def _(rng):
    svc, _ep = _svc(rng)
    dep = rng.choice(["ledger", "limits-db", "accounts-api", "psp-gateway"])
    m0, blip = rng.randint(0, 20), rng.randint(2, 3)
    x = [f"03:{m0 + 2 * i:02d}" for i in range(8)]
    norm = [rng.randint(1150, 1300) for _ in range(8)]
    v = _variant(rng, 3)
    if v == 0:
        series = [{"name": f"входящие запросы {svc}, RPS", "axis": "left", "max": 6000, "data": norm},
                  {"name": f"запросы {svc} → {dep}, RPS", "axis": "left", "max": 6000, "data": [rng.randint(1200, 1350) if i < blip else rng.randint(4200, 5200) for i in range(8)]},
                  {"name": f"ошибки {dep}, %", "axis": "right", "max": 100, "data": [rng.randint(0, 2) if i < blip else 90 if i == blip else rng.randint(35, 60) for i in range(8)]}]
    elif v == 1:
        series = [{"name": f"входящие запросы {svc}, RPS", "axis": "left", "max": 6000, "data": norm},
                  {"name": f"запросы {svc} → {dep}, RPS", "axis": "left", "max": 6000, "data": [rng.randint(1200, 1350) if i < blip else 0 for i in range(8)]},
                  {"name": f"ошибки {svc}, %", "axis": "right", "max": 100, "data": [rng.randint(0, 2) if i < blip else rng.randint(55, 70) for i in range(8)]}]
    else:
        series = [{"name": f"запросы {svc} → {dep}, RPS", "axis": "left", "max": 6000, "data": norm},
                  {"name": f"входящие в {dep} по его метрикам, RPS", "axis": "left", "max": 6000, "data": [n - rng.randint(0, 30) if i < blip else 0 for i, n in enumerate(norm)]},
                  {"name": f"ошибки {svc}, %", "axis": "right", "max": 100, "data": [rng.randint(0, 2) if i < blip else rng.randint(55, 70) for i in range(8)]}]
    panel = {"type": "chart", "x": x, "marker": {"i": blip, "label": f"сбой {dep} 30 с"}, "series": series}
    opts, key = _options(rng, [f"Клиент {dep} повторяет запросы без задержки и джиттера: шторм повторов держит {dep} под перегрузкой",
                               f"Предохранитель {svc} к {dep} остался разомкнутым: пробные запросы не идут",
                               f"{svc} ходит на старый адрес {dep} (кэш DNS и живые соединения), до нового экземпляра запросы не доходят"], v,
                         [f"В {dep} утекает память после сбоя", f"Автоскейлер не успел добавить поды {svc}"])
    return {"scene_title": "Эхо сбоя", "story": f"{dep} лежал 30 секунд и поднялся на новом узле. Прошло 10 минут, а ошибки не уходят — "
                                             "и точка Рея на карте так и не появилась.",
            "prompt": "Почему ошибки не уходят?", "panel": panel, "options": opts, "key": key}


# --- Базы данных и транзакции ---


@family("be_db_index", "Backend", "Базы данных и транзакции", "choice", 2.0, -1.2)
def _(rng):
    v = _variant(rng, 3)
    tbl, col = rng.choice([[("payments", "external_id"), ("orders", "tracking_code"), ("invoices", "number")],
                           [("users", "email"), ("customers", "email"), ("merchants", "login")],
                           [("users", "phone"), ("orders", "tracking_code"), ("cards", "account_no")]][v])
    n, ms, num = rng.randint(3, 40) * 1_000_000, rng.randint(900, 4800), rng.randint(10**9, 10**10 - 1)
    where, flt, idx = [(f"{col} = $1", f"({col} = $1)", f"{tbl}_pkey btree (id)"),
                       (f"lower({col}) = lower($1)", f"(lower(({col})::text) = lower($1))", f"{tbl}_{col}_idx btree ({col})"),
                       (f"{col} = {num}", f"(({col})::numeric = '{num}'::numeric)", f"{tbl}_{col}_idx btree ({col}), {col} — text")][v]
    lines = [
        f"-- индексы: {idx}",
        f"EXPLAIN ANALYZE SELECT * FROM {tbl} WHERE {where};",
        f"Seq Scan on {tbl}  (cost=0.00..{n // 9:,}.00 rows=1 width=212)".replace(",", " "),
        f"  Filter: {flt}",
        f"  Rows Removed by Filter: {n - 1}",
        f"Execution Time: {ms}.{rng.randint(100, 999)} ms",
    ]
    opts, key = _options(rng, [f"Создать индекс по {tbl}({col})", f"Создать индекс по выражению lower({col})",
                               f"Сравнивать {col} со строкой: из-за приведения типа индекс не используется"], v,
                         [f"VACUUM FULL {tbl}", "Увеличить work_mem", "Добавить LIMIT 1000"])
    return {"scene_title": "Медленный запрос", "story": f"Поддержку завалили вопросами «где моя собака», а поиск по {col} в админке тормозит: "
                                                    f"{ms} мс на запрос, таблица — {n // 1_000_000} млн строк.",
            "prompt": "Что поможет?", "panel": {"type": "code", "lang": "sql", "lines": lines}, "options": opts, "key": key}


@family("be_db_lost_update", "Backend", "Базы данных и транзакции", "mark", 2.3, 0.4)
def _(rng):
    fn, tbl = rng.choice(["add_bonus", "top_up", "credit"]), rng.choice(["wallets", "accounts", "balances"])
    lines = [f"async def {fn}(user_id: int, amount: int):"]
    if rng.random() < 0.5:
        lines.append(f'    log.info("{fn}", user_id=user_id, amount=amount)')
    v = _variant(rng, 3)
    story = ""
    if v == 0:
        lines += ["    async with db.transaction():", "        row = await db.fetchrow("]
        key = [len(lines), len(lines) + 1]
        lines += [f'            "SELECT balance FROM {tbl} WHERE id = $1", user_id)', '        new_balance = row["balance"] + amount',
                  "        await db.execute(", f'            "UPDATE {tbl} SET balance = $1 WHERE id = $2",', "            new_balance, user_id)"]
        key += [len(lines) - 2, len(lines) - 1, len(lines)]  # или FOR UPDATE в SELECT, или атомарный balance = balance + $1
    elif v == 1:
        lines += [f'    key = f"{tbl}:{{user_id}}"', "    balance = int(await redis.get(key) or 0)"]
        key = [len(lines), len(lines) + 1]
        lines += ["    await redis.set(key, balance + amount)", '    log.info("balance updated", user_id=user_id)']
        story = " Баланс хранится в Redis."
    else:
        lines += ["    row = await db.fetchrow(", f'        "SELECT balance, version FROM {tbl} WHERE id = $1", user_id)', "    await db.execute("]
        key = [len(lines), len(lines) + 3]
        lines += [f'        "UPDATE {tbl} SET balance = $1, version = version + 1 "', '        "WHERE id = $2 AND version = $3",',
                  '        row["balance"] + amount, user_id, row["version"])', f'    log.info("{fn} done", user_id=user_id)']
        story = " Версию строки для оптимистической блокировки уже добавили."
    return {"scene_title": "Потерянные бонусы", "story": f"Поддержка: при одновременных начислениях часть денег пропадает — в том числе бонусы соседям, "
                                                     f"которые помогают искать собак. Два воркера вызывают {fn} для одного пользователя.{story}",
            "prompt": "Нажмите на строку, которую нужно исправить, чтобы начисление не терялось.",
            "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("be_db_migration", "Backend", "Базы данных и транзакции", "choice", 2.2, 1.4)
def _(rng):
    tbl, col, ref = rng.choice([("payments", "merchant_id", "merchants"), ("orders", "customer_id", "customers"),
                                ("events", "session_id", "sessions"), ("transfers", "account_id", "accounts")])
    rows, w, no = rng.randint(80, 400), rng.randint(5, 30), rng.randint(100, 399)
    v = _variant(rng, 3)
    lines = [[f"-- 0{no}_{tbl}_{col}_idx.sql", f"CREATE INDEX idx_{tbl}_{col} ON {tbl} ({col});"],
             [f"-- 0{no}_{tbl}_{col}_bigint.sql", f"ALTER TABLE {tbl} ALTER COLUMN {col} TYPE bigint;"],
             [f"-- 0{no}_{tbl}_{col}_fk.sql", f"ALTER TABLE {tbl} ADD CONSTRAINT {tbl}_{col}_fk", f"    FOREIGN KEY ({col}) REFERENCES {ref} (id);"]][v]
    opts, key = _options(rng, ["CREATE INDEX CONCURRENTLY вне транзакции миграции, затем проверить, что индекс валиден",
                               "Новая колонка bigint, перенос данных пачками и переключение: смена типа переписывает таблицу",
                               "Добавить ограничение как NOT VALID, а существующие строки проверить отдельно через VALIDATE CONSTRAINT"], v,
                         ["Выполнить ночью: блокировка будет короткой", "Сначала VACUUM ANALYZE, потом та же миграция",
                          "Поднять maintenance_work_mem — тогда блокировки не будет"])
    return {"scene_title": "Миграция", "story": f"Таблица {tbl}: {rows} млн строк, около {w} тыс. вставок в минуту. "
                                             "Миграцию выкатывают днём, а Рей, будем надеяться, найдётся раньше.",
            "prompt": "Как выкатить её без остановки записи?", "panel": {"type": "code", "lang": "sql", "lines": lines}, "options": opts, "key": key}


@family("be_db_write_skew", "Backend", "Базы данных и транзакции", "choice", 2.2, 2.2)
def _(rng):
    v = _variant(rng, 3)
    if v == 0:
        tbl, who = rng.choice([("oncall", "дежурных"), ("courier_slots", "курьеров на слоте"), ("support_shift", "операторов смены")])
        title, story = "Пустая смена", f"Правило: в смене должен остаться хотя бы один из {who}. Двое одновременно снялись — и не осталось никого."
        lines = ["BEGIN ISOLATION LEVEL REPEATABLE READ;", f"SELECT count(*) FROM {tbl} WHERE shift_id = $1 AND active;", "-- если больше одного, можно уйти",
                 f"UPDATE {tbl} SET active = false WHERE shift_id = $1 AND person_id = $2;", "COMMIT;"]
    elif v == 1:
        tbl, seq = rng.choice([("invoices", "invoice_no"), ("acts", "act_no"), ("receipts", "receipt_no")])
        a = rng.randint(1000, 9000)
        title, story = "Дыры в нумерации", f"Бухгалтерия требует номера {tbl} без пропусков, а в выгрузке после отменённых операций дыры: {a}, {a + 2}, {a + 3}, {a + 5}."
        lines = ["BEGIN;", f"INSERT INTO {tbl} (number, customer_id, amount)", f"    VALUES (nextval('{seq}'), $1, $2);",
                 "-- проверка лимитов клиента; при превышении — ROLLBACK", "COMMIT;"]
    else:
        field = rng.choice(["display_name", "phone", "delivery_address"])
        title, story = "Старые данные", ("Вы сами только что на это наткнулись, обновляя свой профиль, чтобы нашедшие Рея могли с вами связаться: после сохранения профиля "
                                         "пользователь иногда видит старое значение, а через секунду — новое. Чтения идут с асинхронной реплики.")
        lines = ["-- сохранение: primary", f"UPDATE profiles SET {field} = $1 WHERE id = $2;",
                 "-- ответ клиенту, затем фронт сразу перечитывает профиль: replica", f"SELECT {field} FROM profiles WHERE id = $2;"]
    opts, key = _options(rng, ["Перейти на SERIALIZABLE и повторять транзакцию при ошибке сериализации",
                               "Брать номер из таблицы-счётчика под блокировкой строки в той же транзакции",
                               "Читать после своей записи с primary или ждать, пока реплика догонит позицию записи"], v,
                         ["Перейти на READ COMMITTED", "Ничего: REPEATABLE READ уже защищает от этого", "Добавить индекс по столбцу из условия"])
    return {"scene_title": title, "story": story, "prompt": "Что исправит проблему?", "panel": {"type": "code", "lang": "sql", "lines": lines}, "options": opts, "key": key}


# --- Ревью кода ---


@family("be_rv_sqli", "Backend", "Ревью кода", "mark", 2.2, -1.0)
def _(rng):
    res, tbl = rng.choice([("products", "products"), ("articles", "articles"), ("merchants", "merchants")])
    v = _variant(rng, 3)
    sig = "async def search(q: str, limit: int = 20, cursor: str | None = None):" if v == 2 else "async def search(q: str, limit: int = 20):"
    lines = [f'@router.get("/{res}/search")', sig, "    limit = min(limit, 100)"]
    if rng.random() < 0.5:
        lines.append("    q = q.strip()")
    if v == 0:
        lines.append(f"    sql = f\"SELECT id, title FROM {tbl} WHERE title ILIKE '%{{q}}%' LIMIT {{limit}}\"")
        key = len(lines)
        lines += ["    rows = await db.fetch(sql)", "    return [dict(r) for r in rows]"]
    elif v == 1:
        lines += [f'    sql = "SELECT id, title FROM {tbl} WHERE title ILIKE $1 LIMIT $2"', '    rows = await db.fetch(sql, f"%{q}%", limit)',
                  "    items = \"\".join(f\"<li>{escape(r['title'])}</li>\" for r in rows)",
                  '    return HTMLResponse(f"<h2>Результаты по «{q}»</h2><ul>{items}</ul>")']
        key = len(lines)
    else:
        lines.append("    after = pickle.loads(base64.b64decode(cursor)) if cursor else 0")
        key = len(lines)
        lines += [f'    sql = "SELECT id, title FROM {tbl} WHERE title ILIKE $1 AND id > $2 ORDER BY id LIMIT $3"',
                  '    rows = await db.fetch(sql, f"%{q}%", after, limit)', "    return [dict(r) for r in rows]"]
    return {"scene_title": "PR стажёра", "story": "Стажёр прислал PR с поиском и обещает выйти искать Рея, как только вы его одобрите. Ревью за вами.", "prompt": "Нажмите на строку с уязвимостью.",
            "panel": {"type": "code", "lang": "python", "lines": lines, "caption": f"PR #{rng.randint(600, 999)} · «поиск по {res}»"}, "key": key}


@family("be_rv_mutable_default", "Backend", "Ревью кода", "mark", 2.0, -0.2)
def _(rng):
    fn, field = rng.choice([("collect_tags", "tags"), ("merge_labels", "labels"), ("gather_ids", "ids")])
    v = _variant(rng, 3)
    lines = []
    if v == 0:
        if rng.random() < 0.5:
            lines.append("@trace")
        lines.append(f"def {fn}(event: dict, acc: list = []) -> list:")
        key = len(lines)
        lines += [f'    for x in event.get("{field}", []):', "        if x not in acc:", "            acc.append(x)", "    return acc",
                  "", "", "def handle(event: dict) -> dict:", f'    return {{"{field}": {fn}(event)}}']
    elif v == 1:
        if rng.random() < 0.5:
            lines.append(f"# собранные {field}")
        lines.append(f"_{field}: list = []")
        key = len(lines)
        lines += ["", "", f"def {fn}(event: dict) -> list:", f'    for x in event.get("{field}", []):', f"        if x not in _{field}:",
                  f"            _{field}.append(x)", f"    return _{field}", "", "", "def handle(event: dict) -> dict:", f'    return {{"{field}": {fn}(event)}}']
    else:
        lines += ["@lru_cache(maxsize=None)", f"def default_{field}() -> list:", f'    return config.load("{field}")', "", "",
                  "def handle(event: dict) -> dict:", f"    {field} = default_{field}()"]
        key = [len(lines), len(lines) + 1]
        lines += [f'    {field}.extend(event.get("{field}", []))', f'    return {{"{field}": {field}}}']
    return {"scene_title": "Растущий список", "story": f"В ответах API {field} из разных запросов «перетекают» друг в друга, и список растёт с каждым вызовом.",
            "prompt": "Нажмите на строку с причиной.", "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("be_rv_double_charge", "Backend", "Ревью кода", "review", 2.5, 1.2)
def _(rng):
    """Сцена 3 макета: «Ревью фикса» от ИИ-ассистента."""
    psp, fn, k = rng.choice(["psp", "acquirer", "gateway"]), rng.choice(["charge", "pay_order", "capture"]), rng.choice([3, 4, 5])
    v = _variant(rng, 3)
    lines = [f"async def {fn}(order_id: str, amount: int):", "    async with db.transaction():", "        order = await orders.get(order_id, for_update=True)"]
    if v == 2:
        lines += ['        if order.status in ("paid", "pending"):', "            return order", "        attempt = await orders.next_attempt(order_id)", "    try:",
                  f'        resp = await {psp}.charge(order.card_token, amount, idempotency_key=f"{{order_id}}:{{attempt}}")', "    except TimeoutError:",
                  "        await orders.mark_failed(order_id)"]
        key = len(lines)
        lines += ['        raise PaymentFailed("Оплата не прошла, попробуйте ещё раз")', "    await orders.mark_paid(order_id, resp.id)", "    return order"]
        title, caption = "Ревью фикса", f"«понятная ошибка при таймауте {psp}»"
    else:
        lines += ['        if order.status == "paid":', "            return order"]
        if rng.random() < 0.5:
            lines.append(f'    log.info("{fn} start", order_id=order_id)')
        lines += [f"    for attempt in range({k}):"]
        if v == 0:
            lines += ["        try:", f"            resp = await {psp}.charge(order.card_token, amount)"]
            key = len(lines)
        else:
            lines += ["        idem = str(uuid4())"]
            key = len(lines)
            lines += ["        try:", f"            resp = await {psp}.charge(order.card_token, amount, idempotency_key=idem)"]
        lines += ["            break", "        except TimeoutError:", "            await asyncio.sleep(2 ** attempt)  # backoff",
                  "    async with db.transaction():", "        await orders.mark_paid(order_id, resp.id)", "    return order"]
        title, caption = "Ревью фикса", f"«retry для {psp}.charge при таймауте»"
    return {"scene_title": title, "story": "После инцидента ИИ-ассистент предложил фикс для оплаты заказа, пока вы обходили гаражи с фонариком. Ревью за вами.",
            "prompt": "Нажмите на строку, из-за которой клиент может получить двойное списание. Коротко объясните, что не так.",
            "panel": {"type": "code", "lang": "python", "lines": lines, "caption": f"PR #{rng.randint(700, 999)} · {caption} · автор: ИИ-ассистент"},
            "comment": True, "key": key}


@family("be_rv_outbox", "Backend", "Ревью кода", "review", 2.3, 2.0)
def _(rng):
    ent, topic, step = rng.choice([("order", "orders.created", "await stock.reserve(order.items)"),
                                   ("booking", "bookings.created", "await slots.hold(booking.slot_id)"),
                                   ("shipment", "shipments.created", "await limits.check(shipment.merchant_id)")])
    v = _variant(rng, 3)
    if v == 0:
        lines = [f"async def create_{ent}(cmd) -> {ent.capitalize()}:", "    async with db.transaction():", f"        {ent} = await {ent}s.insert(cmd)"]
        if rng.random() < 0.5:
            lines.append(f"        metrics.inc(\"{ent}_created\")")
        lines.append(f'        await kafka.send("{topic}", {ent}.to_event())')
        key = len(lines)
        lines += [f"        {step}", f"    return {ent}"]
        title, story = "Призрачные события", f"Соседняя команда жалуется: им приходят события {topic} о записях, которых нет в базе."
    elif v == 1:
        lines = ["async def relay():"]
        if rng.random() < 0.5:
            lines.append(f'    log.info("outbox relay start", topic="{topic}")')
        lines += ["    while True:", "        rows = await outbox.fetch_unsent(limit=100)", "        for row in rows:", "            await outbox.mark_sent(row.id)"]
        key = len(lines)
        lines += ["            await kafka.send(row.topic, row.payload)", "        await asyncio.sleep(1)"]
        title, story = "Пропавшие события", f"Запись {ent} и строка outbox пишутся в одной транзакции, но после рестартов relay часть событий {topic} так и не доходит."
    else:
        lines = [f'async def consume_{ent}s():', f'    async for msg in consumer.subscribe("{topic}"):', "        event = json.loads(msg.value)", "        async with db.transaction():",
                 f'            await db.execute("INSERT INTO ledger ({ent}_id, amount) VALUES ($1, $2)", event["id"], event["amount"])']
        key = len(lines)
        lines += ["        await consumer.commit(msg)"]
        title, story = "Дубли проводок", f"Консьюмер {topic} пишет проводки. После ребалансировки группы в журнале появились дубли."
    return {"scene_title": title, "story": story, "prompt": "Нажмите на строку с проблемой и предложите исправление.",
            "panel": {"type": "code", "lang": "python", "lines": lines, "caption": f"PR #{rng.randint(700, 999)} · «{topic}»"}, "comment": True, "key": key}


# --- Проектирование API ---


@family("be_api_status", "Backend", "Проектирование API", "choice", 1.9, -1.8)
def _(rng):
    cases = [
        ("запрос без токена авторизации", "401 Unauthorized"),
        ("токен валиден, но роли пользователя этот метод запрещён: обычный клиент вызывает админский эндпоинт", "403 Forbidden"),
        ("регистрация с почтой, которая уже занята", "409 Conflict"),
        ("заказ с таким id не существует", "404 Not Found"),
        ("клиент превысил лимит запросов в минуту", "429 Too Many Requests"),
        ("заказ создан, в ответе — новый ресурс и его адрес", "201 Created"),
        ("заказ удалён, тело ответа не нужно", "204 No Content"),
        ("отчёт поставлен в очередь, будет готов через несколько минут", "202 Accepted"),
    ]
    sit, right = cases[_variant(rng, len(cases))]
    opts, key = _choice(rng, right, rng.sample([c for _, c in cases if c != right], 3))
    return {"scene_title": "Вопрос из чата", "story": "Фронтенд-разработчик пишет в чат, пока вы проверяете третий двор подряд: какой код ответа ждать от API?",
            "prompt": f"Какой код вернуть, если {sit}?", "panel": None, "options": opts, "key": key}


@family("be_api_pagination", "Backend", "Проектирование API", "choice", 2.2, 0.2)
def _(rng):
    feed, lim = rng.choice(["операций", "уведомлений", "заказов", "отзывов"]), rng.choice([20, 50, 100])
    v = _variant(rng, 3)
    title, story = [("Дубли в ленте", f"Лента {feed} отдаётся через ?offset=&limit={lim}. Пока пользователь листает, появляются новые записи, и он видит дубли."),
                    ("Медленный счётчик", f"Лента {feed} отдаётся с полем total — точным числом записей. На таблице в {rng.randint(80, 400)} млн строк этот COUNT(*) занимает секунды, сами страницы — миллисекунды."),
                    ("Выгрузка всего", f"Партнёр запрашивает ленту {feed} с limit={rng.choice([50_000, 200_000, 1_000_000])}: ответ собирается минуту, и под его запросами падает сервис.")][v]
    opts, key = _options(rng, ["Курсорная пагинация: курсор по (created_at, id) и записи «после курсора»",
                               "Не считать точный total: запросить limit + 1 и отдать признак следующей страницы",
                               "Ограничить limit на сервере разумным максимумом, большие выгрузки — асинхронным экспортом"], v,
                         ["Кэшировать каждую страницу на 5 минут", "Сортировать по случайному ключу с сидом"])
    return {"scene_title": title, "story": story, "prompt": "Как исправить?", "panel": None, "options": opts, "key": key}


@family("be_api_idem", "Backend", "Проектирование API", "choice", 2.3, 0.8)
def _(rng):
    res, thing = rng.choice([("payments", "платежа"), ("transfers", "перевода"), ("orders", "заказа")])
    v = _variant(rng, 3)
    title, story = [("Двойные записи", f"Мобильное приложение повторяет POST /{res} при обрыве сети — а во дворах, где вы ищете Рея, "
                                       f"связь рвётся постоянно. Иногда создаются два {thing}."),
                    ("Долгий отчёт", f"POST /reports/{res} собирает выписку {rng.randint(2, 4)} минуты, а клиенты и балансировщик рвут соединение через 30 секунд."),
                    ("Затёртая правка", f"Два оператора одновременно открыли карточку {thing} в админке и сохранили: правки первого молча пропали.")][v]
    opts, key = _options(rng, ["Клиент шлёт Idempotency-Key, сервер хранит ключ с результатом и на повтор отдаёт сохранённый ответ",
                               "Принимать задачу асинхронно: 202 Accepted с id задачи, статус и результат — отдельным GET",
                               "Версия ресурса в ETag и запись с If-Match: при несовпадении — 412, клиент перечитывает"], v,
                         ["Заменить POST на PUT без изменений на сервере", "Дедуплицировать по сумме и времени запроса в окне 10 секунд"])
    return {"scene_title": title, "story": story, "prompt": "Как спроектировать API?", "panel": None, "options": opts, "key": key}


@family("be_api_breaking", "Backend", "Проектирование API", "choice", 2.2, 1.8)
def _(rng):
    res, old, new = rng.choice([("profile", "phone", "phone_e164"), ("orders", "sum", "amount"), ("cards", "num", "masked_pan")])
    v = _variant(rng, 3)
    story = [f"Поле {old} в GET /{res} нужно переименовать в {new}.",
             f"В статус GET /{res} добавляется новое значение partially_refunded, а старые клиенты падают на незнакомом значении.",
             f"Параметр currency в POST /{res} был необязательным (по умолчанию RUB), теперь его хотят сделать обязательным."][v]
    opts, key = _options(rng, [f"Добавить {new}, оставить {old} помеченным как устаревшее и убрать, когда метрики покажут, что старых клиентов не осталось",
                               "Отдавать новое значение только клиентам, которые объявили его поддержку, остальным — ближайшее старое",
                               "Оставить параметр необязательным с прежним значением по умолчанию, обязательным сделать только в новой версии"], v,
                         ["Перенести весь API в /v2 и сразу выключить /v1", "Выпустить изменение вместе с новой версией приложения"])
    return {"scene_title": "Совместимость", "story": f"{story} Старые версии мобильного приложения живут ещё полгода.",
            "prompt": "Что делать?", "panel": None, "options": opts, "key": key}


# --- Конкурентность ---


@family("be_cc_blocking", "Backend", "Конкурентность", "mark", 2.0, -0.6)
def _(rng):
    v = _variant(rng, 3)
    if v == 0:
        fn, call = rng.choice([("fetch_rates", 'requests.get(f"{RATES_URL}/{cur}", timeout=5)'), ("load_limits", 'requests.post(LIMITS_URL, json={"cur": cur}, timeout=5)'),
                               ("fetch_fees", 'requests.get(FEES_URL, params={"cur": cur}, timeout=5)')])
        lines = [f"async def {fn}(currencies: list[str]) -> dict:", "    result = {}", "    for cur in currencies:", f"        resp = {call}"]
        key = len(lines)
        lines += ['        result[cur] = resp.json()["rate"]', "    return result"]
    elif v == 1:
        fn = rng.choice(["push_events", "send_webhook", "report_usage"])
        lines = [f"async def {fn}(payload: dict) -> dict:", "    for attempt in range(5):", "        resp = await client.post(URL, json=payload)",
                 "        if resp.status_code != 429:", "            return resp.json()", "        time.sleep(2 ** attempt)"]
        key = len(lines)
        lines += ['    raise RuntimeError("rate limited")']
    else:
        fn = rng.choice(["check_password", "verify_pin", "login"])
        lines = [f"async def {fn}(user, secret: str) -> bool:", f'    digest = hashlib.pbkdf2_hmac("sha256", secret.encode(), user.salt, {rng.choice([600_000, 800_000, 1_200_000]):_})']
        key = len(lines)
        lines += ["    return hmac.compare_digest(digest, user.secret_hash)"]
    return {"scene_title": "Замирание", "story": f"Пока выполняется {fn}, весь сервис перестаёт отвечать, даже /health, "
                                                "а с ним замирает и карта, на которой вы ждёте точку Рея.",
            "prompt": "Нажмите на строку с причиной.", "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("be_cc_race", "Backend", "Конкурентность", "mark", 2.3, 0.6)
def _(rng):
    v = _variant(rng, 3)
    if v == 0:
        new, old, revoked, fn = rng.choice([("новый токен", "старый", "отозванный токен", "get_token"),
                                            ("новую сессию", "старую", "отозванную сессию", "get_session"),
                                            ("новый ключ", "старый", "отозванный ключ", "get_key")])
        lines = ["_cache: dict[str, str] = {}", ""]
        if rng.random() < 0.5:
            lines += ["", "# выдача отзывает предыдущее значение"]
        lines += [f"async def {fn}(client_id: str) -> str:", "    if client_id not in _cache:", "        _cache[client_id] = await auth.issue(client_id)"]
        key = [len(lines) - 1, len(lines)]
        lines.append("    return _cache[client_id]")
        story = f"Сервис авторизации, выдавая {new}, отзывает {old}. Под нагрузкой часть запросов получает {revoked}."
    elif v == 1:
        what, n = rng.choice([("платежи", "payments"), ("письма", "emails"), ("заказы", "orders")]), rng.choice([8, 16, 32])
        lines = ["processed = 0", "", "", "def handle(item):", "    global processed", "    process(item)", "    processed += 1"]
        key = len(lines)
        lines += ["", "", f"with ThreadPoolExecutor({n}) as pool:", f"    list(pool.map(handle, {what[1]}))", 'log.info("done", processed=processed)']
        story = f"Воркер обрабатывает {what[0]} в {n} потоков. Итог в логе иногда меньше, чем обработано на самом деле."
    else:
        room = rng.choice(["Room", "Channel", "Topic"])
        lines = [f"class {room}:", "    def __init__(self):", "        self.subscribers: list = []", "", "    async def broadcast(self, msg):", "        for s in self.subscribers:"]
        key = len(lines)
        lines += ["            await s.send(msg)", "", "    def leave(self, s):", "        self.subscribers.remove(s)"]
        story = "Если кто-то отписывается во время рассылки, часть оставшихся подписчиков сообщение не получает."
    return {"scene_title": "Гонка", "story": story, "prompt": "Нажмите на строку, где возникает гонка.",
            "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("be_cc_gather", "Backend", "Конкурентность", "choice", 2.2, 1.4)
def _(rng):
    v = _variant(rng, 3)
    if v == 0:
        n = rng.randint(20, 90) * 1000
        lines = ["async def notify_all(users):", "    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=None)) as client:",
                 "        await asyncio.gather(*(notify(client, u) for u in users))"]
        story = f"Рассылка {n} уведомлений «рядом потерялась собака» падает с OSError: [Errno 24] Too many open files, а сервис уведомлений отвечает 429."
    elif v == 1:
        lines = ["async def notify_all(users):", "    async with httpx.AsyncClient() as client:", "        results = await asyncio.gather(*(notify(client, u) for u in users))",
                 "    return delivery_report(users, results)"]
        story = f"Объявление о пропаже Рея рассылается {rng.randint(2, 9) * 100} соседям: если хотя бы одно уведомление падает, notify_all падает целиком и отчёт о доставке не строится."
    else:
        lines = ["async def notify(u):", "    async with httpx.AsyncClient() as client:", "        await client.post(NOTIFY_URL, json=u.message())", "", "",
                 "async def notify_all(users):", "    for chunk in batched(users, 100):", "        await asyncio.gather(*(notify(u) for u in chunk))"]
        story = "Рассылка объявлений о пропавших собаках идёт в десятки раз медленнее, чем сервис уведомлений способен принимать: на каждое уведомление — новое TLS-рукопожатие."
    opts, key = _options(rng, ["Ограничить параллелизм asyncio.Semaphore (например, на 100) вокруг вызова notify",
                               "Добавить return_exceptions=True в gather и разобрать ошибки по каждому получателю",
                               "Создать один AsyncClient на всю рассылку и переиспользовать соединения"], v,
                         ["Увеличить timeout у HTTP-клиента", "Запустить notify в ThreadPoolExecutor"])
    return {"scene_title": "Объявление о пропаже", "story": story, "prompt": "Как исправить с минимальными изменениями?",
            "panel": {"type": "code", "lang": "python", "lines": lines}, "options": opts, "key": key}


@family("be_cc_deadlock", "Backend", "Конкурентность", "choice", 2.2, 2.4)
def _(rng):
    p1, p2, t1, t2 = rng.randint(3000, 4999), rng.randint(5000, 6999), rng.randint(9000, 9999), rng.randint(10000, 10999)
    tbl = rng.choice(["accounts", "wallets", "balances"])
    v = _variant(rng, 3)
    if v == 0:
        title, story = "Взаимная блокировка", f"Перевод делает два UPDATE в {tbl}: сначала счёт отправителя, потом получателя. Изредка переводы падают."
        lines = [_log("14:02:11", "pg-primary", "ERROR", "deadlock detected"),
                 _log("14:02:11", "pg-primary", "DETAIL", f"Process {p1} waits for ShareLock on transaction {t2}; blocked by process {p2}.\n"
                                                          f"Process {p2} waits for ShareLock on transaction {t1}; blocked by process {p1}."),
                 _log("14:02:11", "pg-primary", "CONTEXT", f'while updating tuple (12,7) in relation "{tbl}"')]
    elif v == 1:
        title, story = "Зависшие переводы", f"Переводы по {tbl} периодически висят по 30 секунд и падают по таймауту, хотя нагрузка обычная."
        lines = [_log("14:02:01", "transfers-api", "INFO", f"tx begin, UPDATE {tbl} SET hold = true WHERE id = $1"),
                 _log("14:02:01", "transfers-api", "INFO", "calling antifraud (timeout 30s)"),
                 _log("14:02:20", "pg_stat_activity", "INFO", f"pid {p1}: state = idle in transaction, xact_start 14:02:01"),
                 _log("14:02:20", "pg_stat_activity", "INFO", f"pid {p2}: state = active, wait_event = Lock:transactionid, UPDATE {tbl} … WHERE id = $1"),
                 _log("14:02:31", "transfers-api", "ERROR", "antifraud: timeout, rollback")]
    else:
        title, story = "Всё встало", f"Днём выкатили миграцию {tbl} — и через минуту встали все запросы к таблице, даже чтения."
        lines = [_log("14:02:00", "migrator", "INFO", f"ALTER TABLE {tbl} ADD COLUMN note text"),
                 _log("14:02:01", "pg-primary", "LOG", f"process {p1} still waiting for AccessExclusiveLock on relation {tbl} after 1000.0 ms"),
                 _log("14:02:01", "pg-primary", "DETAIL", f"Process holding the lock: {p2}. Wait queue: {p1}, {p1 + 7}, {p1 + 12}, {p1 + 31}."),
                 _log("14:02:30", "pg_stat_activity", "INFO", f"pid {p2}: state = active, SELECT … FROM {tbl} JOIN … (выгрузка аналитики), running 00:{rng.randint(20, 59)}:12")]
    opts, key = _options(rng, ["Блокировать счета в одном порядке: сначала меньший id, потом больший",
                               "Не держать транзакцию открытой во время внешних вызовов и задать idle_in_transaction_session_timeout",
                               "Задать миграции lock_timeout и повторять её: ALTER в очереди блокирует всех, кто пришёл после"], v,
                         ["Увеличить deadlock_timeout", "Перейти на SERIALIZABLE"])
    return {"scene_title": title, "story": story, "prompt": "Что устранит причину?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Алгоритмы ---


@family("be_alg_set", "Backend", "Алгоритмы", "choice", 1.9, -1.4)
def _(rng):
    n, m = rng.randint(200, 900), rng.randint(50, 300)
    v = _variant(rng, 3)
    lines, story = [(["def find_blocked(payments: list, blocked: list[str]) -> list:", "    return [p for p in payments if p.card_hash in blocked]"],
                     f"Платежей ~{n} тыс., заблокированных карт ~{m} тыс. Сверка идёт десятки минут."),
                    (["def drain(queue: list) -> int:", "    total = 0", "    while queue:", "        p = queue.pop(0)", "        total += p.amount", "    return total"],
                     f"Очередь из ~{n} тыс. платежей разбирается десятки минут."),
                    (["def over_limit(payments: list, limits: dict) -> list:", "    return [p for p in payments if p.amount > max(limits.values())]"],
                     f"Платежей ~{n} тыс., лимитов ~{m} тыс. Отбор идёт десятки минут.")][v]
    opts, key = _options(rng, ["Сделать blocked множеством (set): проверка станет O(1), всего O(n + m)",
                               "Заменить список на collections.deque: popleft() за O(1) вместо pop(0) за O(n)",
                               "Посчитать max(limits.values()) один раз до цикла, а не на каждый платёж"], v,
                         ["Переписать list comprehension на цикл for", "Распараллелить на 4 потока", "Отсортировать payments перед проверкой"])
    return {"scene_title": "Медленная сверка", "story": story, "prompt": "Как ускорить?", "panel": {"type": "code", "lang": "python", "lines": lines}, "options": opts, "key": key}


@family("be_alg_topk", "Backend", "Алгоритмы", "choice", 2.2, 0.2)
def _(rng):
    n, k = rng.randint(50, 500), rng.choice([10, 50, 100])
    v = _variant(rng, 3)
    title, story = [("Топ платежей", f"Из потока ~{n} млн платежей за сутки нужен топ-{k} крупнейших. Память сервиса ограничена, поток читается один раз."),
                    ("Перцентили", f"Нужны p50 и p99 времени ответа за сутки по ~{n} млн запросов. Память ограничена, поток читается один раз, погрешность 1 % допустима."),
                    ("Повторы", f"Из потока ~{n} млн платежей за сутки нужно отсеять повторы по id. Память ограничена, редкий ложный «повтор» уйдёт на ручную проверку.")][v]
    opts, key = _options(rng, [f"Мин-куча размера {k}: O(n log k) по времени, O(k) по памяти",
                               "Гистограмма с фиксированными корзинами (или t-digest): память не зависит от числа запросов",
                               "Фильтр Блума по id: фиксированная память, ложные срабатывания редки"], v,
                         ["Сортировать все платежи: O(n log n), память O(n)", "Бинарный поиск по потоку"])
    return {"scene_title": title, "story": story, "prompt": "Какой подход выбрать?", "panel": None, "options": opts, "key": key}


@family("be_alg_intervals", "Backend", "Алгоритмы", "choice", 2.2, 1.2)
def _(rng):
    ent, n = rng.choice(["задач", "звонков", "сессий"]), f"{rng.randint(1, 9) * 100_000:,}".replace(",", " ")
    v = _variant(rng, 3)
    story = [f"В логах {n} интервалов {ent} [start, end). Нужно найти, сколько их шло одновременно в пике.",
             f"В календаре {n} бронирований переговорок [start, end). Для экрана занятости пересекающиеся бронирования нужно слить в сплошные блоки.",
             f"На единственный тестовый стенд — {n} заявок [start, end). Нужно удовлетворить как можно больше заявок без пересечений."][v]
    opts, key = _options(rng, ["Отсортировать 2n событий (начало +1, конец −1; при равенстве конец раньше) и пройти, считая сумму: O(n log n)",
                               "Отсортировать по началу и сливать с последним блоком, пока интервалы пересекаются: O(n log n)",
                               "Отсортировать по концу и жадно брать интервал, который не пересекается с уже взятыми: O(n log n)"], v,
                         ["Для каждого интервала посчитать пересечения с остальными: O(n log n)"])
    return {"scene_title": "Интервалы", "story": story, "prompt": "Какой алгоритм корректен и эффективен?", "panel": None, "options": opts, "key": key}


@family("be_alg_rehash", "Backend", "Алгоритмы", "choice", 2.3, 2.2)
def _(rng):
    n = rng.randint(3, 12)
    v = _variant(rng, 3)
    story = [f"Ключи кэша распределены по {n} шардам как hash(key) mod {n}. Добавляем ещё один шард.",
             f"Ключи кэша распределены по {n} шардам консистентным хешированием (кольцо, по 100 виртуальных узлов на шард). Добавляем ещё один шард.",
             f"Ключи кэша распределены по {n} шардам как hash(key) mod {n}. Удваиваем кластер: hash(key) mod {2 * n}."][v]
    opts, key = _options(rng, [f"≈ {round(100 * n / (n + 1))} %: почти все ключи", f"≈ {round(100 / (n + 1))} %: только доля нового шарда", "≈ 50 %: половина ключей"], v,
                         ["0 %, если хеш-функция стабильная"])
    return {"scene_title": "Ещё шарды", "story": story, "prompt": "Какая доля ключей сменит шард?", "panel": None, "options": opts, "key": key}


# --- пилотные (калибровка, на грейд не влияют) ---


@family("be_pilot_stampede", "Backend", "Конкурентность", "choice", 1.5, 1.0, pilot=True)
def _(rng):
    thing = rng.choice(["курса валют", "каталога", "тарифов"])
    v = _variant(rng, 3)
    title, story = [("Лавина в кэше", f"Ключ кэша {thing} истекает, и сотни запросов одновременно идут в базу."),
                    ("Горячий ключ", f"Ключ {thing} читают 40 % всех запросов: один шард Redis упёрся в CPU, остальные простаивают."),
                    ("Промахи мимо кэша", f"Боты запрашивают данные {thing} по несуществующим id: в кэше их нет, и каждый запрос идёт в базу.")][v]
    opts, key = _options(rng, ["Пересчитывать значение одним запросом под блокировкой (single-flight), остальным отдавать старое значение",
                               "Держать копию ключа в памяти процесса на несколько секунд (или реплицировать ключ на несколько шардов)",
                               "Кэшировать и отрицательный ответ «нет такого id» на короткое время"], v,
                         ["Уменьшить TTL", "Увеличить пул соединений к базе"])
    return {"scene_title": title, "story": story, "prompt": "Как защититься?", "panel": None, "options": opts, "key": key}


@family("be_pilot_percentiles", "Backend", "Диагностика инцидентов", "choice", 1.5, -0.5, pilot=True)
def _(rng):
    avg = rng.randint(90, 160)
    v = _variant(rng, 3)
    story = [f"Среднее время ответа {avg} мс, а пользователи жалуются на тормоза.",
             f"Доля 5xx по сервису — 0,{rng.randint(1, 4)} %, а крупный мерчант жалуется, что у него отказывает почти каждый запрос.",
             f"По метрикам самого сервиса p99 — {avg + rng.randint(150, 300)} мс, а клиенты видят таймауты по {rng.choice([3, 5])} с."][v]
    opts, key = _options(rng, ["Перцентили p95/p99 по эндпоинтам", "Ошибки в разрезе клиентов и эндпоинтов",
                               "Время на балансировщике вместе с очередью до сервиса"], v,
                         ["Число запросов в секунду", "Среднее за сутки вместо часа"])
    return {"scene_title": "Жалобы", "story": story, "prompt": "Что смотреть в первую очередь?", "panel": None, "options": opts, "key": key}


# ============================== остальные специализации ==============================
# по одному простому семейству на компетенцию; сценарные семейства с панелями — в пакете bank/


def _fill(s, v: dict):
    if isinstance(s, list):
        return [_fill(x, v) for x in s]
    for k, val in v.items():
        s = s.replace(f"⟨{k}⟩", str(val))
    return s


def simple(spec: str, comp: str, b: float, title: str, prompt: str, cases: list[tuple], wrong: list[str], vars=None):
    """Простое семейство: выбор из 4 вариантов. cases — ситуации (сюжет, правильный ответ[, строки кода]), клоны идут по ним
    по кругу; правильные ответы других ситуаций — дистракторы, недостающие — из wrong. ⟨переменные⟩ подставляются из vars."""

    def render(rng):
        v = vars(rng) if callable(vars) else {k: rng.choice(opts) for k, opts in (vars or {}).items()}
        i = _variant(rng, len(cases))
        story, _right, *code = cases[i]
        opts, key = _options(rng, _fill([c[1] for c in cases], v), i, _fill(wrong, v))
        panel = {"type": "code", "lang": "text", "lines": _fill(code[0], v)} if code else None
        return {"scene_title": title, "story": _fill(story, v), "prompt": _fill(prompt, v), "panel": panel, "options": opts, "key": key}

    FAMILIES.append({"family": "", "spec": spec, "competency": comp, "kind": "choice", "a": 1.7, "b": b, "pilot": False, "render": render})


simple("Frontend", "Отладка UI", -1.2, "Капризная кнопка", "Что проверить первым?", [
    ("На предрелизном стенде сайта клуба кнопка «⟨btn⟩» перестала нажиматься. В DevTools поверх неё лежит прозрачный ⟨el⟩.", "z-index и pointer-events перекрывающего элемента"),
    ("Кнопка «⟨btn⟩» в заявке на выставку нажимается, но ничего не происходит — и нет, Рей по клавиатуре не ходил. "
     "В консоли: Uncaught TypeError: Cannot read properties of undefined (reading 'id').",
     "Ошибку в консоли: обработчик падает до отправки запроса"),
    ("Кнопка «⟨btn⟩» на сайте клуба срабатывает, но запрос уходит дважды: во вкладке Network два одинаковых POST с разницей в 5 мс.",
     "Не навешен ли обработчик дважды (повторная подписка или двойной рендер)"),
], ["Кэш браузера", "Версию фреймворка", "Шрифты страницы"], {"btn": ["Оплатить", "Оформить", "Сохранить"], "el": ["баннер cookies", "оверлей модалки", "блок промо"]})
simple("Frontend", "Производительность", 0.6, "Тормозит интерфейс", "Что даст основной выигрыш?", [
    ("Архив результатов выставок (Рей надеется скоро туда попасть) — список из ⟨n⟩ строк — тормозит при прокрутке: каждая строка — тяжёлый компонент.", "Виртуализация: рендерить только видимые строки"),
    ("На выставках хозяева открывают сайт клуба прямо с поля, а на медленном мобильном интернете вёрстка и картинки уже видны, а текст появляется только через 3 секунды, когда догружается файл веб-шрифта.",
     "font-display: swap и предзагрузка основного шрифта, чтобы текст показывался сразу"),
    ("Первая загрузка на мобильном — 9 секунд: бандл ⟨mb⟩ МБ, половина — редактор графиков, который нужен на одном экране.",
     "Разделить код: грузить редактор динамическим import() только на его экране"),
], ["Заменить CSS-классы на inline-стили", "Перенести список в iframe", "Добавить debounce на onScroll"], {"n": [5000, 12000, 30000], "mb": [4, 6, 8]})
simple("Frontend", "Ревью кода", 0.0, "Ревью для магазина клуба", "Что не так в коде?", [
    ("В PR компонент карточки ⟨res⟩ получает id из пропсов. При переходе на другую карточку данные не меняются.",
     "В массиве зависимостей нет id: при смене id эффект не перезапускается",
     ["useEffect(() => {", "  fetch(`/api/items/${id}`)", "    .then(r => r.json())", "    .then(setData);", "}, []);"]),
    ("В списке позиций ⟨res⟩ после удаления строки введённые в поля количества значения «переезжают» на соседние строки.",
     "key по индексу: при удалении React путает строки — нужен стабильный id в key",
     ["{items.map((item, i) => (", "  <Row key={i} item={item} onRemove={remove} />", "))}"]),
    ("Кнопка «Добавить» в списке ⟨res⟩ ничего не меняет на экране, хотя в консоли массив растёт.",
     "Состояние мутируется: push не создаёт новый массив — setItems([...items, x])",
     ["const add = (x) => {", "  items.push(x);", "  setItems(items);", "};"]),
], ["fetch нельзя вызывать внутри useEffect", "setData нужно обернуть в useCallback", "Нужно использовать XMLHttpRequest"],
    {"res": ["товара", "заказа", "пользователя"]})
simple("Frontend", "Архитектура клиента", 1.2, "Как устроен сайт клуба", "Как исправить архитектурно?", [
    ("На сайте клуба состояние ⟨what⟩ хранится в store, в localStorage и в URL. После перезагрузки они расходятся.",
     "Один источник правды в store; localStorage и URL синхронизируются из него в одну сторону"),
    ("В магазине клуба форма оформления заказа из 40 полей: у каждого поля свой useState, правила проверки разбросаны по обработчикам и расходятся с сервером.",
     "Одна библиотека форм и схема проверки, общая с сервером"),
    ("У клуба пять проектов, от сайта выставки до магазина: кнопки и поля ввода копируют в каждый из них и правят на месте; исправление в одном не доходит до остальных.",
     "Вынести компоненты в общий версионируемый пакет UI-кита"),
], ["Синхронизировать все копии по setInterval", "Хранить всё только в localStorage и читать на каждый рендер", "Перейти на другой фреймворк"],
    {"what": ["корзины", "фильтров", "черновика"]})
simple("Frontend", "Доступность", -0.4, "Сайт для всех хозяев", "Как исправить?", [
    ("На сайте клуба кнопка-иконка «⟨icon⟩» — без текста. Скринридер читает просто «кнопка».", "Добавить aria-label с названием действия"),
    ("Подписи в карточке ⟨card⟩ набраны светло-серым #aaa на белом: часть пользователей их не может прочитать.", "Поднять контраст текста до 4,5:1 (WCAG AA)"),
    ("Ошибка в поле формы ⟨card⟩ видна только по красной рамке; часть пользователей её не замечает.", "Текст ошибки у поля, связанный через aria-describedby, а не только цвет"),
], ["Добавить role=\"img\" к иконке", "Увеличить иконку", "Добавить title странице"],
    {"icon": ["корзина", "закрыть", "поиск"], "card": ["товара", "заказа", "статьи"]})
simple("Frontend", "Алгоритмы", 1.8, "Данные на клиенте", "Какую структуру выбрать?", [
    ("В каталоге клуба, от родословных до атрибутики, нужен поиск по ⟨n⟩ тыс. названий на клиенте: подсказки по префиксу на каждое нажатие клавиши.",
     "Отсортированный массив с бинарным поиском границ префикса или префиксное дерево"),
    ("В редакторе шаблонов писем участникам выставки (⟨n⟩ тыс. символов) нужно на лету подсвечивать незакрытые и перепутанные теги.", "Стек открытых тегов: один проход по тексту"),
    ("События приходят по WebSocket, нужно всегда показывать 10 самых срочных из ⟨n⟩ тыс. по приоритету.", "Двоичная куча по приоритету: вставка и извлечение за O(log n)"),
], ["filter + includes на каждый ввод — это быстро при любом объёме", "Регулярное выражение по склеенной строке"], {"n": [50, 200, 500]})

simple("Mobile", "Отладка", -1.2, "Краш на прогулке", "Что исправить?", [
    ("Приложение падает при повороте телефона на экране «⟨scr⟩» — вы как раз перехватывали поводок Рея. Колбэк загрузки обращается к уже уничтоженному view.",
     "Отменять загрузку и отписываться от колбэков при уничтожении экрана"),
    ("Экран «⟨scr⟩» падает только на Android 14: SecurityException при регистрации BroadcastReceiver без флага экспорта.",
     "С Android 14 явно указывать RECEIVER_EXPORTED или RECEIVER_NOT_EXPORTED при registerReceiver"),
    ("Экран «⟨scr⟩» у части пользователей падает с OutOfMemoryError при открытии фото питомца.", "Загружать фото с уменьшением до размера экрана, а не в полном разрешении"),
], ["Запретить поворот экрана во всём приложении", "Обернуть колбэк в try/catch", "Увеличить таймаут загрузки"], {"scr": ["Профиль", "Корзина", "Заказ"]})
simple("Mobile", "Жизненный цикл приложения", 0.0, "Свернули и вернулись", "Что сделать?", [
    ("Хозяин свернул приложение во время ⟨what⟩, чтобы отобрать у своего пса чужой мяч, вернулся через 20 минут — экран пустой: система убила процесс.",
     "Сохранять состояние экрана и восстанавливать его после пересоздания процесса"),
    ("Видео в ленте питомцев продолжает играть со звуком после того, как пользователь свернул приложение.",
     "Ставить плеер на паузу при уходе экрана с переднего плана и освобождать его при остановке"),
    ("Пользователь выдал доступ к камере в настройках и вернулся, а экран сканера всё равно пишет «нет доступа».",
     "Перепроверять разрешение при каждом возвращении на экран, а не только при создании"),
], ["Перезапускать приложение с главного экрана", "Хранить состояние в статической переменной", "Попросить пользователя не сворачивать приложение"],
    {"what": ["оформления заказа", "заполнения анкеты", "записи к врачу"]})
simple("Mobile", "Ревью кода", 0.6, "Ревью на скамейке", "Что не так?", [
    ("В PR запрос ⟨req⟩ выполняется синхронно в обработчике нажатия кнопки.", "Сеть на главном потоке: интерфейс зависнет; запрос — в фон, UI обновлять на главном"),
    ("В PR ответ запроса ⟨req⟩ приходит в фоновом потоке, и в том же колбэке меняется текст на экране.", "UI меняется не с главного потока: обновление экрана перенести на главный поток"),
    ("В PR токен авторизации для запроса ⟨req⟩ сохраняется в SharedPreferences / UserDefaults открытым текстом.", "Секрет хранить в Keystore / Keychain, а не в обычных настройках"),
], ["Ничего, если запрос быстрый", "Нужно добавить индикатор загрузки, этого достаточно", "Кнопку нужно отключать после нажатия, остальное в порядке"],
    {"req": ["профиля", "баланса", "истории заказов"]})
simple("Mobile", "Сеть и офлайн", 1.2, "Связь в парке", "Как реализовать?", [
    ("В парке связь то и дело пропадает. Заказ ⟨what⟩, оформленный без сети, должен уйти, когда связь появится, и не задвоиться.",
     "Локальная очередь исходящих запросов с идемпотентным ключом и повтором при появлении сети"),
    ("Каталог ⟨what⟩ должен открываться без сети и обновляться при связи, не скачивая всё заново.", "Локальная база как источник для экрана и синхронизация изменений дельтой"),
    ("Картинки в ленте ⟨what⟩ при каждом открытии скачиваются заново, и пользователи жалуются на мобильный трафик.",
     "Дисковый кэш картинок и HTTP-кэш с учётом Cache-Control и ETag"),
], ["Показать ошибку и попросить повторить позже", "Повторять запрос каждую секунду до успеха", "Отправить по SMS"], {"what": ["такси", "еды", "билетов"]})
simple("Mobile", "Производительность", -0.4, "Медленно и дёргано", "Что поможет больше всего?", [
    ("Лента фотографий питомцев (⟨res⟩) дёргается при прокрутке: картинки декодируются целиком на главном потоке.",
     "Уменьшать картинки до размера ячейки и декодировать вне главного потока"),
    ("Приложение весит 180 МБ, и часть пользователей не скачивает его по мобильной сети.",
     "Публиковать App Bundle с разделением по архитектурам и плотностям, сжать ресурсы и удалить неиспользуемые"),
    ("Список заказов перерисовывается целиком при изменении одного элемента: мигание и просадки кадров.",
     "Обновлять список по диффу (DiffUtil, diffable data source), а не целиком"),
], ["Отключить анимации", "Перейти на PNG", "Загружать все картинки при старте"], {"res": ["4000×3000", "12 Мп", "в полном размере"]})
simple("Mobile", "Алгоритмы", 1.8, "Поиск на устройстве", "Как искать?", [
    ("Нужно показывать ⟨k⟩ ближайших точек самовывоза корма из 50 тыс. и обновлять при сдвиге карты.",
     "Пространственный индекс (геохеш или k-d дерево) и запрос по окрестности"),
    ("Нужен самый быстрый маршрут курьера между двумя из ⟨k⟩ тыс. перекрёстков по дорогам со временем проезда.",
     "Алгоритм Дейкстры (или A*) по графу дорог со временем проезда как весом"),
    ("Подсказки по контактам: пользователь вводит начало имени, контактов ⟨k⟩ тыс., ответ — на каждое нажатие.",
     "Отсортированный список с бинарным поиском границ префикса или префиксное дерево"),
], ["Сортировать все точки по широте и брать первые", "Хеш-таблица по названию города", "Кэшировать ответ на сутки"], {"k": [10, 20, 50]})

simple("ML / DS", "Постановка задачи", -1.2, "Запрос маркетплейса", "Что уточнить первым?", [
    ("Бизнес зоомаркетплейса просит «предсказать отток ⟨who⟩».", "Что считается оттоком, горизонт прогноза и какое действие примут по прогнозу"),
    ("Бизнес зоомаркетплейса просит модель, которая «найдёт мошенников» среди ⟨who⟩, но размеченных случаев нет.", "Откуда взять разметку: расследования, правила или экспертная разметка выборки"),
    ("Бизнес зоомаркетплейса просит «модель лучше текущей» для скоринга ⟨who⟩.", "Какой метрикой и на каком отложенном периоде сравнивать с текущим решением"),
], ["Какую нейросеть использовать", "Сколько GPU выделят", "Какой будет accuracy"], {"who": ["клиентов", "мерчантов", "подписчиков"]})
simple("ML / DS", "Валидация моделей", 0.0, "Слишком хорошо", "Что это значит?", [
    ("Антифрод маркетплейса: доля мошеннических транзакций ⟨p⟩ %. Модель показывает accuracy ⟨acc⟩ %.", "Почти ничего: константа «не мошенник» даёт ⟨base⟩ %; нужны precision/recall или PR-AUC"),
    ("У каждого клиента десятки заявок, разбиение — случайное по заявкам. На валидации ROC-AUC 0,93, на новых клиентах — 0,78.",
     "Одни и те же клиенты попали и в обучение, и в валидацию: делить по клиентам (GroupKFold)"),
    ("Гиперпараметры подобрали по 200 запускам на одной валидационной выборке и на ней же отчитались: 0,91.",
     "Оценка завышена: на валидации подбирали, нужна отдельная отложенная тестовая выборка"),
], ["Модель отличная, можно выкатывать", "Нужно поднять порог до 0,9", "Нужно добавить больше деревьев"],
    lambda rng: (lambda p: {"p": f"{p:.1f}".replace(".", ","), "acc": f"{100 - p * 0.8:.1f}".replace(".", ","), "base": f"{100 - p:.1f}".replace(".", ",")})(rng.choice([0.5, 1.0, 2.0])))
simple("ML / DS", "Дрейф данных", 0.6, "Скоринг ползёт вниз", "Что делать?", [
    ("Через ⟨w⟩ недель после запуска метрика скоринга упала. Распределение признака «⟨f⟩» сдвинулось, PSI = ⟨psi⟩.",
     "Это дрейф: проверить источник данных, затем переобучить на свежем окне и настроить мониторинг PSI"),
    ("Метрика скоринга упала только в одном регионе: туда пришёл партнёр с клиентами другого профиля, в остальных регионах всё ровно.",
     "Сдвиг состава клиентов: смотреть метрики по сегментам и дообучить с данными нового сегмента"),
    ("Метрика скоринга каждый год проседает в декабре и возвращается в феврале; модель обучена на данных марта — октября.",
     "Сезонность: обучать на окне, которое покрывает полный год, и добавить календарные признаки"),
], ["Увеличить глубину деревьев", "Поднять порог классификации", "Игнорировать: это шум"],
    {"w": [5, 6, 8], "f": ["доход", "регион", "устройство"], "psi": ["0,31", "0,38", "0,45"]})
simple("ML / DS", "Feature engineering", 1.2, "Подозрительный признак", "В чём проблема?", [
    ("В модели оттока покупателей корма признак «⟨feat⟩» считается по всем заказам клиента, включая заказы после даты прогноза. ROC-AUC на валидации ⟨auc⟩.",
     "Утечка из будущего: считать признак только по данным до точки прогноза"),
    ("Линейная модель: признак «дней с последнего заказа» от 0 до 3000 с длинным хвостом; почти вся информация — в первых 30 днях. ROC-AUC 0,84 у бустинга, у логрегрессии — 0,71.",
     "Длинный хвост: логарифмировать признак или разбить на интервалы для линейной модели"),
    ("Линейная модель с L2: «доход» в рублях (до 10⁷) и «⟨feat⟩» (доли от 0 до 1) поданы как есть. Вес «⟨feat⟩» почти нулевой.",
     "Признаки в разных масштабах: стандартизировать, иначе штраф давит мелкие"),
], ["Признак слишком шумный, его надо логарифмировать", "Не хватает регуляризации", "Нужно больше деревьев"],
    {"feat": ["доля возвратов", "доля отмен", "доля ночных заказов"], "auc": ["0,97", "0,98", "0,99"]})
simple("ML / DS", "MLOps", 1.8, "Модель маркетплейса в проде", "В чём причина и что делать?", [
    ("Модель ⟨m⟩ в проде отвечает иначе, чем в ноутбуке, на тех же сырых данных.",
     "Препроцессинг в обучении и в сервинге разный: вынести его в общий пайплайн и версионировать с моделью"),
    ("После переобучения модель ⟨m⟩ стала хуже, а откатиться не на что: прошлый артефакт перезаписан, данные обучения не сохранились.",
     "Нет версионирования: хранить артефакты, данные и параметры обучения в реестре моделей"),
    ("Модель ⟨m⟩ отвечает за 800 мс при SLA 100 мс: признаки собираются запросами к хранилищу прямо во время ответа.",
     "Готовить признаки заранее в онлайн-хранилище, при ответе только читать"),
], ["В проде другая версия CPU", "Модель недообучена", "Нужно включить float64 в проде"], {"m": ["скоринга", "рекомендаций", "антифрода"]})
simple("ML / DS", "Алгоритмы", -0.4, "Выбор метода", "Что использовать?", [
    ("Чтобы по фото Рея находить похожих собак, нужно найти ⟨k⟩ ближайших эмбеддингов среди ⟨n⟩ млн за 20 мс.", "Приближённый поиск ближайших соседей (HNSW или IVF)"),
    ("Нужно разбить ⟨n⟩ тыс. клиентов на сегменты по поведению: число сегментов неизвестно, есть выбросы.", "Кластеризация по плотности (DBSCAN или HDBSCAN)"),
    ("Нужно найти почти дословные копии среди ⟨n⟩ млн объявлений маркетплейса: тексты отличаются парой слов, эмбеддингов нет.", "MinHash и LSH по шинглам"),
], ["Полный перебор косинусов на CPU", "Сортировку по норме вектора", "Линейную регрессию"], {"k": [10, 50, 100], "n": [10, 50, 200]})

simple("Data Eng / Analytics", "SQL", -1.2, "Запрос для отчёта", "Как написать запрос?", [
    ("Для отчёта сети нужна выручка по ⟨dim⟩, включая те, где продаж не было.", "LEFT JOIN продаж к справочнику ⟨dim2⟩ и COALESCE(sum, 0)"),
    ("Нужен список ⟨dim2⟩, у которых выручка за квартал больше миллиона.", "GROUP BY и условие на сумму в HAVING"),
    ("Нужна последняя продажа в разрезе ⟨dim2⟩ — по одной строке на каждый.", "ROW_NUMBER() OVER (PARTITION BY … ORDER BY дата DESC) и первая строка"),
], ["INNER JOIN и GROUP BY", "UNION ALL справочника и продаж", "SELECT DISTINCT по продажам"],
    lambda rng: dict(zip(("dim", "dim2"), rng.choice([("регионам", "регионов"), ("категориям", "категорий"), ("магазинам", "магазинов")]))))
simple("Data Eng / Analytics", "Моделирование данных", 0.6, "Измерения", "Как спроектировать?", [
    ("Менеджер у ⟨who⟩ меняется, а отчёты за прошлые кварталы должны показывать прежнего.", "SCD Type 2: версии строк измерения с датами действия"),
    ("У ⟨who⟩ может быть несколько менеджеров одновременно, и выручку нужно показывать по каждому.",
     "Таблица-мост между ⟨who2⟩ и менеджерами (с долями, если выручку делят)"),
    ("В телефоне ⟨who⟩ исправили опечатку; историю старого значения хранить не нужно.", "SCD Type 1: перезаписать значение в измерении"),
], ["Хранить менеджера в JSON заказа", "Пересчитывать старые отчёты вручную", "Хранить каждую версию в отдельной таблице"],
    lambda rng: dict(zip(("who", "who2"), rng.choice([("клиента", "клиентами"), ("дилера", "дилерами"), ("партнёра", "партнёрами")]))))
simple("Data Eng / Analytics", "Пайплайны", 0.0, "Ночная загрузка", "Как исправить загрузку?", [
    ("Ежедневная загрузка ⟨src⟩ упала посередине, её перезапустили — данные за день задвоились.",
     "Сделать её идемпотентной: перезаписывать партицию дня целиком (delete + insert или MERGE)"),
    ("Загрузка ⟨src⟩ каждую ночь забирает таблицу целиком (2 млрд строк) и не успевает к утру; меняется около 1 % строк.",
     "Инкрементальная загрузка по метке изменения (или CDC) вместо полной"),
    ("Загрузка ⟨src⟩ из API источника упирается в лимит 100 запросов в минуту, падает с 429 и каждый раз начинает с нуля.",
     "Соблюдать лимит и повторять по Retry-After, сохраняя прогресс, чтобы продолжать с места сбоя"),
], ["Запускать DISTINCT после каждой загрузки по всей таблице", "Не перезапускать упавшие загрузки", "Увеличить ретраи"], {"src": ["заказов", "событий", "платежей"]})
simple("Data Eng / Analytics", "Качество данных", -0.4, "Плохие данные", "Как ловить такое раньше?", [
    ("В витрине ⟨tbl⟩ вчера оказалось на 40 % меньше строк, заметили только в черновике отчёта — том самом, который потом сгрыз Рей.", "Автоматические проверки объёма и свежести с алертом до публикации витрины"),
    ("В витрине ⟨tbl⟩ у части строк сумма отрицательная, а в источнике таких нет: ошибка в трансформации.",
     "Тесты инвариантов (сумма ≥ 0, уникальность ключа) на каждом запуске пайплайна"),
    ("Источник ⟨tbl⟩ без предупреждения переименовал колонку, и загрузка тихо заполнила её NULL.", "Контракт схемы с источником и проверка схемы при загрузке: падать, а не лить NULL"),
], ["Раз в неделю смотреть дашборд", "Добавить индексы", "Перейти на другой формат хранения"], {"tbl": ["sales", "orders", "visits"]})
simple("Data Eng / Analytics", "Визуализация", -1.6, "Выбор графика", "Какой график выбрать?", [
    ("Для квартального отчёта нужно сравнить доли ⟨n⟩ каналов привлечения по кварталам.", "Столбцы с накоплением до 100 % по кварталам"),
    ("Нужно показать, как ⟨n⟩ метрик менялись по дням за год.", "Линейный график по дням, по линии на метрику"),
    ("Нужно показать связь цены и числа продаж по ⟨n⟩ тыс. товаров.", "Диаграмма рассеяния: цена по одной оси, продажи по другой"),
], ["Круговую диаграмму на каждый квартал", "3D-столбцы", "Таблицу с цветной заливкой"], {"n": [4, 5, 6]})
simple("Data Eng / Analytics", "Алгоритмы", 1.8, "Большой поток", "Что использовать?", [
    ("Нужно число уникальных пользователей за ⟨d⟩ дней по ⟨n⟩ млрд событий, погрешность до 2 % допустима.", "HyperLogLog: скетчи по дням, которые можно объединять"),
    ("Нужны p50 и p99 времени доставки за ⟨d⟩ дней по ⟨n⟩ млрд событий за один проход: память ограничена, погрешность 1 % допустима.",
     "Квантильный скетч (t-digest или KLL), который можно объединять по дням"),
    ("Нужно на лету отсекать повторно пришедшие события по id в потоке ⟨n⟩ млрд за ⟨d⟩ дней; редкий ложный «повтор» допустим.", "Фильтр Блума по id"),
], ["COUNT(DISTINCT) по сырым событиям каждый раз", "Сумму дневных уникальных", "Выборку 1 % событий и умножение на 100"], {"d": [7, 30, 90], "n": [2, 5, 20]})

simple("DevOps / SRE", "Диагностика инцидентов", -1.2, "Под не работает", "Что происходит?", [
    ("В новом кластере под ⟨svc⟩ в CrashLoopBackOff, в describe: Last State: Terminated, Reason: OOMKilled.",
     "Контейнер превышает лимит памяти: проверить потребление, поднять limits или найти утечку"),
    ("В новом кластере под ⟨svc⟩ в ImagePullBackOff, в событиях: pull access denied, repository does not exist or may require authorization.",
     "Образ не скачивается: проверить имя и тег образа и imagePullSecrets"),
    ("В новом кластере под ⟨svc⟩ Running, но 0/1 Ready; в событиях: Readiness probe failed: HTTP probe failed with statuscode: 503.",
     "Не проходит readiness-проба: смотреть логи и зависимости, которые проверяет /ready"),
], ["Закончилось место на диске узла", "Сломан DNS кластера", "Истёк сертификат API-сервера"], {"svc": ["billing", "search", "gateway"]})
simple("DevOps / SRE", "Сети", 0.6, "Сеть в кластере", "Куда смотреть и что сделать?", [
    ("После переезда из пода ⟨svc⟩ не резолвится db.internal, а по IP подключение проходит.", "DNS: CoreDNS и resolv.conf пода (search, ndots)"),
    ("Из пода ⟨svc⟩ имя db.internal резолвится, но подключение к 5432 висит до таймаута; из другого namespace всё работает.",
     "NetworkPolicy: исходящий трафик из namespace пода до базы не разрешён"),
    ("Сервис ⟨svc⟩ за облачным балансировщиком: в логах и лимитах у всех клиентов один и тот же IP — адрес балансировщика.",
     "Передавать адрес клиента (X-Forwarded-For или PROXY protocol) и доверять ему только от балансировщика"),
], ["Сертификат базы истёк", "Не хватает реплик сервиса", "Лимит CPU пода"], {"svc": ["orders", "auth", "reports"]})
simple("DevOps / SRE", "Kubernetes", 0.0, "Поды не в строю", "Что настроить?", [
    ("Во время каждой выкладки ⟨svc⟩ около 30 секунд отдаёт 502.",
     "Readiness-пробу и корректное завершение (preStop, SIGTERM), чтобы под уходил из балансировки до остановки"),
    ("При плановом обновлении узлов ⟨svc⟩ на несколько минут полностью недоступен: все реплики оказались на одном узле.",
     "PodDisruptionBudget и anti-affinity: реплики на разных узлах и не выселяются все разом"),
    ("Новые поды ⟨svc⟩ висят в Pending: 0/6 nodes are available: Insufficient memory, хотя узлы заняты по факту на 40 %.",
     "Планировщик считает по requests: выставить requests по реальному потреблению"),
], ["Увеличить число реплик вдвое", "Перейти на стратегию Recreate", "Убрать все пробы"], {"svc": ["api", "frontend", "payments"]})
simple("DevOps / SRE", "CI/CD", -0.4, "Сборка образа", "Как исправить?", [
    ("Сборка образа ⟨svc⟩ каждый раз ставит зависимости с нуля, ⟨m⟩ минут: Рей успевает дважды перевернуться на другой бок.",
     "Копировать lock-файл и ставить зависимости до копирования кода, чтобы слой кэшировался"),
    ("Образ ⟨svc⟩ весит 2 ГБ: внутри компилятор, исходники и кэш пакетов.", "Многоэтапная сборка: в итоговый образ копировать только артефакт"),
    ("Сборка ⟨svc⟩ на одном и том же коммите то проходит, то нет: зависимости ставятся без lock-файла.", "Фиксировать версии lock-файлом и ставить строго по нему"),
], ["Собирать на более мощном раннере", "Отключить тесты", "Собирать образ раз в сутки"], {"svc": ["api", "worker", "admin"], "m": [8, 12, 15]})
simple("DevOps / SRE", "Наблюдаемость", 1.2, "Слепые зоны", "Что изменить?", [
    ("Алерт «CPU > 80 %» на ⟨svc⟩ срабатывает по ночам, но пользователи ничего не замечают — вздрагивает от него только Рей.",
     "Алертить по симптомам: SLO по ошибкам и задержке, скорость сжигания бюджета ошибок"),
    ("Инцидент в ⟨svc⟩ искали час: метрики есть, но непонятно, какой из 12 сервисов в цепочке тормозил.", "Распределённая трассировка с пробросом trace-id через все сервисы"),
    ("Логи ⟨svc⟩ — свободный текст на подах; ошибку по конкретному заказу ищут grep по десяти подам.",
     "Структурированные логи с id запроса и центральный сбор с поиском"),
], ["Поднять порог до 95 %", "Отключить ночные алерты", "Добавить алерт на память"], {"svc": ["api", "search", "billing"]})
simple("DevOps / SRE", "План отката", 1.8, "Обратимая выкладка", "Как выкатить, чтобы откат оставался возможен?", [
    ("Новая версия ⟨svc⟩ переименовывает колонку ⟨col⟩ в БД.",
     "Expand/contract: добавить новую колонку, писать в обе, переключить чтение, старую удалить в следующем релизе"),
    ("Новая версия ⟨svc⟩ меняет формат сообщений в очереди; старые и новые поды какое-то время работают одновременно.",
     "Сначала научить поды читать оба формата, писать в новом — когда старых читателей не осталось"),
    ("Новая версия ⟨svc⟩ включает переработанный расчёт ⟨col⟩; при проблемах его нужно выключить за минуты без выкладки.",
     "Флаг функции: выкатить выключенным, включать постепенно, откат — выключением флага"),
], ["Выкатить и при проблеме восстановить из бэкапа", "Выкатить ночью", "Сделать снапшот диска перед выкладкой"],
    {"svc": ["orders", "billing", "crm"], "col": ["user_name", "amount", "status"]})

simple("QA", "Тест-дизайн", -1.2, "Набор тестов", "Какой набор тестов выбрать?", [
    ("Поле «⟨field⟩» принимает целые числа от ⟨lo⟩ до ⟨hi⟩. Нужен минимальный набор, покрывающий границы.", "Граничные значения: ⟨lo1⟩, ⟨lo⟩, ⟨hi⟩, ⟨hi1⟩"),
    ("Скидка зависит от суммы: до 999 ₽ — нет, от 1000 до 4999 ₽ — 5 %, от 5000 ₽ — 10 %. Нужен минимальный набор по классам эквивалентности.",
     "По одному значению из каждого класса, например 500, 3000 и 7000"),
    ("Доставка зависит от трёх условий: подписка (да/нет), сумма от 2000 ₽ (да/нет), регион (город/область). Нужно покрыть все сочетания.",
     "Таблица решений: 2 × 2 × 2 = 8 сочетаний"),
], ["Середина диапазона: ⟨mid⟩", "Все значения от ⟨lo⟩ до ⟨hi⟩", "Случайные значения: 0, −1, 999999"],
    lambda rng: (lambda f, lo, hi: {"field": f, "lo": lo, "hi": hi, "lo1": lo - 1, "hi1": hi + 1, "mid": (lo + hi) // 2})(
        *rng.choice([("Возраст", 18, 65), ("Количество", 1, 99), ("Срок, мес.", 3, 36)])))
simple("QA", "Приёмка релиза", 0.6, "Решение о релизе", "Что делать?", [
    ("За час до релиза найден баг: ⟨bug⟩. Фикс есть, но регресс по нему не пройден.",
     "Оценить риск с владельцем продукта: выключить фичу флагом или перенести релиз, решение зафиксировать"),
    ("Релиз раскатили на 5 % пользователей; через 20 минут доля ошибок оплаты выросла с 0,2 % до ⟨err⟩ %.", "Остановить раскатку и откатить, потом разбираться"),
    ("К релизу готово всё, кроме мелкого бага: ⟨minor⟩ — только на старой версии Android, ею пользуются 0,3 %.",
     "Выпускать, описав проблему в известных ограничениях, и завести задачу на следующий релиз"),
], ["Выкатить фикс без регресса", "Выпустить как есть, никому не сообщая", "Отложить релиз на неделю без обсуждения"],
    {"bug": ["промокод применяется дважды", "в корзине не пересчитывается доставка", "кнопка оплаты пропадает на iPhone SE"],
     "err": [2, 3, 5], "minor": ["съезжает подпись под переключателем", "иконка в меню на пиксель ниже", "в профиле обрезается длинная фамилия"]})
simple("QA", "Автотесты", 0.0, "Нестабильный тест", "Как стабилизировать?", [
    ("UI-тест «⟨t⟩» падает примерно в одном прогоне из десяти: элемент не найден.", "Явное ожидание нужного состояния элемента и стабильные локаторы (data-testid)"),
    ("Тесты «⟨t⟩» проходят по одному, но падают в общем прогоне: тест видит данные, оставленные предыдущим.",
     "Изолировать тесты: свои данные на каждый тест и очистка после"),
    ("Тест «⟨t⟩» падает каждую ночь около полуночи: он проверяет, что заказ «создан сегодня».", "Зафиксировать время в тесте (подменить часы)"),
], ["Добавить sleep(5)", "Перезапускать упавшие тесты трижды", "Отключить тест"], {"t": ["оформление заказа", "вход", "поиск"]})
simple("QA", "API-тестирование", -0.4, "Ожидаемый ответ", "Какой результат ожидаем?", [
    ("POST /⟨res⟩ повторяется с тем же Idempotency-Key.", "Тот же ответ, что и в первый раз, без второй записи"),
    ("GET /⟨res⟩/⟨n⟩ — запись, которая принадлежит другому пользователю.", "403 или 404 — без данных чужой записи"),
    ("POST /⟨res⟩ с суммой −100 в теле.", "400 с понятной ошибкой валидации, запись не создаётся"),
], ["Новая запись с новым id", "500 Internal Server Error", "200 и пустой ответ"], {"res": ["payments", "orders", "transfers"], "n": [1042, 7731, 318]})
simple("QA", "Баг-репорты", -1.6, "Баг на экране", "Как правильно поступить?", [
    ("Приложение кормушки падает на экране «⟨scr⟩». Вы заводите баг-репорт.", "Указать шаги воспроизведения, ожидаемый и фактический результат, окружение и версию"),
    ("Баг на экране «⟨scr⟩» воспроизводится лишь иногда, примерно в одном случае из пяти. Шаги, окружение и версия в репорте уже есть, "
     "но разработчик пишет «не воспроизводится».", "Описать частоту и условия, приложить логи и запись экрана"),
    ("Разработчик закрыл баг на экране «⟨scr⟩» с пометкой «исправлено».", "Перепроверить по шагам из репорта на новой сборке и прогнать смежные сценарии"),
], ["Скриншот и слово «срочно»", "Указать разработчика, который виноват", "Закрыть без проверки"], {"scr": ["Корзина", "Профиль", "Оплата"]})
simple("QA", "Регресс", 1.4, "План тестирования", "Как спланировать тестирование?", [
    ("Изменили расчёт ⟨what⟩. Полный регресс из 2000 кейсов до релиза не успеть.", "Кейсы по анализу влияния изменения (связанные модули и сценарии оплаты) плюс смоук"),
    ("Новый расчёт ⟨what⟩ нужно проверить, а требования описаны в двух строках и постоянно меняются.",
     "Исследовательское тестирование по чартерам, кейсы — когда требования устоятся"),
    ("Ручной регресс по расчёту ⟨what⟩ из 300 кейсов гоняют каждую неделю, и он занимает три дня.",
     "Автоматизировать стабильные повторяющиеся кейсы по приоритету риска"),
], ["Случайные 10 % кейсов", "Только новые кейсы", "Только автотесты, ручные пропустить"], {"what": ["скидки в корзине", "стоимости доставки", "налога"]})

simple("Security", "Веб-уязвимости", -1.2, "Отчёт с багбаунти", "Что это и как исправить?", [
    ("В приложении умного дома GET /⟨res⟩?id=⟨n⟩ возвращает чужие данные, если поменять id.", "IDOR: проверять на сервере, что объект принадлежит пользователю"),
    ("Комментарий с текстом <script>…</script> к ⟨res⟩ выполняется в браузере у каждого, кто открывает страницу.", "Хранимая XSS: экранировать вывод по контексту и добавить CSP"),
    ("Чужой сайт отправляет форму на POST /⟨res⟩/delete, и у залогиненного пользователя удаляется запись.", "CSRF: токен в форме и SameSite у сессионной cookie"),
], ["SQL-инъекция: параметризовать запрос", "Брутфорс: ограничить попытки входа", "Открытый редирект: проверять адрес перехода"],
    {"res": ["invoices", "orders", "profile"], "n": [1042, 7731, 318]})
simple("Security", "Ревью кода", 0.6, "Админка умного дома", "Какая уязвимость в коде?", [
    ("В админке есть проверка доступности хоста по имени, которое вводит пользователь.", "Внедрение команд: shell=True и пользовательский ввод в строке команды",
     ['host = request.args["host"]', 'subprocess.run(f"ping -c 1 {host}", shell=True, timeout=5)']),
    ("В админке есть импорт настроек из файла, который загружает пользователь.", "Небезопасная десериализация: pickle выполняет код из файла, нужен JSON со схемой",
     ['data = request.files["config"].read()', "settings = pickle.loads(data)"]),
    ("В админке есть шаблон письма, который редактирует пользователь.", "Внедрение в шаблон (SSTI): пользовательский текст рендерится как шаблон Jinja",
     ['tpl = request.form["template"]', "html = Environment().from_string(tpl).render(user=current_user)"]),
], ["Утечка памяти", "Ничего, есть таймаут", "Гонка при записи файла"])
simple("Security", "Сети", 0.0, "Атака на периметр", "Что это и что сделать?", [
    ("С ⟨n⟩ тыс. адресов идут SYN без завершения рукопожатия, облако умного дома перестало принимать соединения.", "SYN flood: SYN cookies и фильтрация на периметре"),
    ("DNS-резолвер компании отвечает на рекурсивные запросы с любых адресов; провайдер жалуется на исходящий трафик ⟨n⟩ Гбит/с.",
     "Резолвер используют для DNS-амплификации: закрыть рекурсию для внешних адресов"),
    ("С ⟨n⟩ тыс. адресов идут HTTP-запросы, заголовки которых досылаются по байту раз в 10 секунд; все воркеры веб-сервера заняты.",
     "Slowloris: таймауты на заголовки и прокси, который буферизует запрос целиком"),
], ["Брутфорс: fail2ban", "ARP-спуфинг: статические записи", "Утечка памяти: перезапуск по расписанию"], {"n": [12, 40, 90]})
simple("Security", "Криптография", 1.2, "Самодельная криптография", "Как правильно?", [
    ("Пароли пользователей хранятся как ⟨h⟩(password).", "Медленная функция с солью: argon2id или bcrypt"),
    ("Номера карт шифруются AES-ECB одним ключом; у одинаковых карт в базе одинаковый шифротекст.", "Аутентифицированный режим (AES-GCM) с уникальным nonce на каждую запись"),
    ("Токен сброса пароля генерируется как ⟨h⟩(email + время).", "Криптографически стойкий случайный токен с коротким сроком жизни"),
], ["sha512 вместо ⟨h⟩", "⟨h⟩ дважды", "Base64 поверх текущего значения"], {"h": ["sha256", "md5", "sha1"]})
simple("Security", "Реагирование", -0.4, "Счёт на минуты", "Первое действие?", [
    ("Ключ ⟨key⟩ попал в публичный репозиторий два часа назад.", "Отозвать и перевыпустить ключ, затем проверить журналы его использования"),
    ("EDR на рабочей станции ⟨who⟩ сработал на шифровальщик: файлы на общем диске начали переименовываться.",
     "Изолировать машину от сети, затем сохранить артефакты для разбора"),
    ("Сотрудник сообщил, что десять минут назад ввёл пароль от почты на фишинговой странице.",
     "Сбросить пароль и завершить сессии, проверить правила пересылки и входы в ящик"),
], ["Удалить коммит из истории", "Написать в чат команды", "Дождаться утра и разобраться"],
    {"key": ["облачного хранилища", "платёжного шлюза", "почтового сервиса"], "who": ["бухгалтера", "менеджера", "кадровика"]})
simple("Security", "Реверс", 1.8, "В дизассемблере", "Что это значит и что делать?", [
    ("В бинарнике ⟨app⟩ проверка лицензии сравнивает введённый ключ через strcmp с константой.", "Ключ достаётся статическим анализом строк; проверку надо переносить на сервер"),
    ("В мобильном приложении ⟨app2⟩ зашит ключ API партнёра; код обфусцирован.", "Ключ всё равно извлекается: ходить к партнёру через свой бэкенд по токену пользователя"),
    ("Сэмпл ⟨mal⟩ из инцидента проверяет, не запущен ли он под отладчиком или в виртуальной машине, и тогда ведёт себя безобидно.",
     "Антиотладка: разбирать статически и в изолированной среде, скрывающей признаки ВМ"),
], ["Защита надёжна, если бинарник обфусцирован", "Нужно заменить strcmp на memcmp", "Достаточно упаковать UPX"],
    {"app": ["агента", "десктоп-клиента", "плагина"], "app2": ["банка", "доставки", "такси"], "mal": ["загрузчика", "шифровальщика", "стилера"]})

# задачи на код — одни и те же семейства у всех специализаций с «Алгоритмами»; выдаются отдельным слотом (irt.choose)
for _spec in code_items.SPECS:
    for _f in code_items.FAMILIES.values():
        FAMILIES.append({"family": _f["name"], "spec": _spec, "competency": code_items.COMPETENCY, "kind": "code", "a": _f["a"], "b": _f["b"],
                         "pilot": _f["pilot"], "render": lambda rng, name=_f["name"]: code_items.render(name, rng)})
# сценарные семейства остальных специализаций (логи, графики, код) — по 3 на компетенцию сверх простых, см. bank/
from app.services import bank  # noqa: F401

# уникальные имена семейств для простых шаблонов
for i, f in enumerate(FAMILIES):
    if not f["family"]:
        f["family"] = f"{f['spec'].split()[0].lower()}_{i:03d}"


def generate_bank() -> list[dict]:
    """Все клоны всех семейств как словари полей Item. Детерминировано: сид = семейство + номер клона (+ попытка, если клон повторил уже выпавший)."""
    out = []
    for f in FAMILIES:
        n = CLONES_PILOT if f["pilot"] else CLONES.get(f["spec"], CLONES_DEFAULT)
        seen = set()
        for i in range(n):
            # клон, совпавший с уже выпавшим (данных у варианта мало), перегенерируется с другим сидом в том же варианте
            for t in range(20):
                rng = random.Random(f"{f['family']}:{i}" + (f":{t}" if t else ""))
                rng.clone = i  # номер клона → вариант механики (_variant)
                payload = f["render"](rng)
                sig = repr({**payload, "key": None, "options": sorted(payload.get("options") or [])})
                if sig not in seen:
                    break
            seen.add(sig)
            payload["time_limit_s"] = TIME_LIMIT[f["kind"]]
            out.append({"family": f["family"], "spec": f["spec"], "competency": f["competency"], "kind": f["kind"],
                        "a": round(f["a"] * rng.uniform(0.95, 1.05), 3), "b": round(f["b"] + rng.uniform(-0.1, 0.1), 3),
                        "payload": payload, "pilot": f["pilot"]})
    return out


SEED_LOCK = 0x46535002  # ключ advisory-блокировки засева банка (миграции — app.db.MIGRATE_LOCK)


def seed_items(db: Session) -> int:
    """Засеять банк и привести засеянный к текущей версии шаблонов (пустой банк — целиком; на старом стенде — новые семейства
    и изменённые клоны). Ключ — (семейство, специализация, номер клона): задачи на код с одним именем есть у нескольких
    специализаций, номер клона в базе — порядок id внутри семейства (клоны сеются по порядку). Засеянный клон обновляется
    на месте, id не меняется: на него ссылаются ответы в сессиях, а правильность ответа записана в самом ответе.
    Клоны сверх числа в шаблоне (семейство стало короче) остаются в базе. Возвращает число добавленных и обновлённых заданий.
    Засев идёт при каждом старте API (app.main), в seed.generate и CLI: параллельные засевы сериализует advisory-блокировка,
    иначе оба прочли бы пустой банк и задублировали клоны — ключ клона в базе не уникален. Блокировка транзакционная и
    держится до commit в конце; банк читается уже под ней, поэтому второй засев видит клоны первого и ничего не добавляет."""
    db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": SEED_LOCK})
    have = defaultdict(list)
    for it in db.scalars(select(Item).order_by(Item.id)):
        have[(it.family, it.spec)].append(it)
    n, seen = 0, Counter()
    for row in generate_bank():
        k = (row["family"], row["spec"])
        old = have[k][seen[k]] if seen[k] < len(have[k]) else None
        seen[k] += 1
        if old is None:
            db.add(Item(**row))
        elif any(getattr(old, f) != v for f, v in row.items()):
            for f, v in row.items():
                setattr(old, f, v)
        else:
            continue
        n += 1
    db.commit()
    return n


# ============================== план теста под вакансию ==============================
# навык → компетенции, которые его проверяют (берутся те, что есть у специализации)
SKILL_COMP = {
    "PostgreSQL": ["Базы данных и транзакции", "SQL"], "MySQL": ["Базы данных и транзакции", "SQL"], "SQL": ["Базы данных и транзакции", "SQL", "Данные и SQL"],
    "MongoDB": ["Базы данных и транзакции", "Моделирование данных"], "ClickHouse": ["Базы данных и транзакции", "SQL", "Моделирование данных"],
    "Redis": ["Базы данных и транзакции", "Проектирование API"],
    "Kafka": ["Конкурентность", "Пайплайны"], "RabbitMQ": ["Конкурентность"], "asyncio": ["Конкурентность"],
    "FastAPI": ["Проектирование API"], "Django": ["Проектирование API"], "gRPC": ["Проектирование API", "Сеть и офлайн"],
    "Kubernetes": ["Kubernetes", "Диагностика инцидентов", "MLOps", "План отката"], "Docker": ["CI/CD", "Kubernetes", "MLOps", "Диагностика инцидентов"],
    "Terraform": ["CI/CD", "План отката"], "Prometheus": ["Наблюдаемость", "Диагностика инцидентов"], "Linux": ["Сети", "Диагностика инцидентов", "Серверы и ОС"],
    "Python": ["Ревью кода", "Feature engineering", "Автотесты"], "Go": ["Ревью кода", "Конкурентность"], "Java": ["Ревью кода"], "Kotlin": ["Ревью кода", "Жизненный цикл приложения"],
    "C#": ["Ревью кода"], "Node.js": ["Ревью кода", "Проектирование API"], "TypeScript": ["Ревью кода", "Архитектура клиента"], "JavaScript": ["Ревью кода", "Отладка UI"],
    "React": ["Архитектура клиента", "Производительность"], "Vue": ["Архитектура клиента"], "Angular": ["Архитектура клиента"],
    "Swift": ["Ревью кода", "Жизненный цикл приложения"], "Flutter": ["Жизненный цикл приложения", "Производительность"],
    "Spark": ["Пайплайны", "Алгоритмы"], "Airflow": ["Пайплайны", "Качество данных"],
    "PyTorch": ["Валидация моделей", "MLOps"], "scikit-learn": ["Валидация моделей", "Feature engineering"], "LLM": ["Постановка задачи", "Валидация моделей"],
    "Computer Vision": ["Валидация моделей", "Feature engineering"], "Selenium": ["Автотесты", "Регресс"], "Pentest": ["Веб-уязвимости", "Реагирование"],
    "BPMN": ["Моделирование процессов"], "UML": ["Моделирование процессов", "Спецификации"], "REST": ["Интеграции и API", "Проектирование API"],
    "Jira": ["Процессы команды", "Планирование и сроки"], "Confluence": ["Спецификации", "Стейкхолдеры"], "Scrum": ["Процессы команды", "Планирование и сроки"],
    "A/B-тесты": ["Метрики продукта", "Метрики и эксперименты"], "CustDev": ["Исследования", "Приоритизация", "Выявление требований"],
    "Figma": ["Прототипирование", "Дизайн-системы"], "Windows Server": ["Учётные записи и доступ", "Серверы и ОС"], "Bash": ["Серверы и ОС", "Резервное копирование"],
    "ITIL": ["Работа с обращениями"], "Zabbix": ["Диагностика инцидентов"],
}
MUST_W, NICE_W, MAX_W = 0.25, 0.1, 1.5
SHARE_OF_LIMIT = 0.75  # ponytail: время ≈ 75 % лимита на сцену; заменить медианой реальных прохождений


def plan_for_need(spec: str, must: list[str], nice: list[str], grade: str) -> dict:
    """Как система собирает тест под вакансию: веса компетенций из навыков, сложность вокруг порога грейда, семейства банка.
    Веса уходят в QuestSession.focus и только сдвигают выбор заданий; грейд считается по всем компетенциям одинаково."""
    if spec not in catalog.COMPETENCIES:
        raise ValueError(f"Неизвестная специализация: {spec}")
    grade = grade if grade in catalog.GRADES else "Middle"
    names = catalog.COMPETENCIES[spec]
    w, why = {n: 1.0 for n in names}, {n: [] for n in names}
    for skills, add in ((must or [], MUST_W), (nice or [], NICE_W)):
        for sk in skills:
            for c in SKILL_COMP.get(sk, []):
                if c in w and sk not in why[c]:
                    w[c] = min(MAX_W, w[c] + add)
                    why[c].append(sk)
    c0 = irt.grade_anchor(grade)
    lo, hi = round(c0 - 1.0, 2), round(c0 + 1.0, 2)
    # задачи на код — только при включённой песочнице и одна на сессию (слот irt.CODE_AT)
    fams = [f for f in FAMILIES if f["spec"] == spec and not f["pilot"] and (f["kind"] != "code" or sandbox.enabled())]
    has_code = any(f["kind"] == "code" for f in fams)
    chosen = [f for f in fams if lo <= f["b"] <= hi] or sorted(fams, key=lambda f: abs(f["b"] - c0))[:6]
    chosen.sort(key=lambda f: (-w[f["competency"]], abs(f["b"] - c0)))
    families = []
    for f in chosen:
        sample = f["render"](random.Random(f"{f['family']}:preview"))  # отдельный сид: в банке такого клона нет
        families.append({"family": f["family"], "competency": f["competency"], "kind": f["kind"], "b": f["b"],
                         "scene_title": sample["scene_title"], "sample_prompt": f"{sample['story']} {sample['prompt']}"})
    plain = [f for f in chosen if f["kind"] != "code"]
    items_total = min(irt.MAX_ITEMS, sum(f["kind"] != "code" for f in fams) + has_code)
    avg_limit = (sum(TIME_LIMIT[f["kind"]] for f in plain) / max(len(plain), 1)) * (items_total - has_code) / max(items_total, 1) \
        + TIME_LIMIT["code"] * has_code / max(items_total, 1)
    return {
        "spec": spec, "grade": grade,
        "competencies": sorted(({"n": n, "weight": round(w[n], 2), "why": why[n]} for n in names), key=lambda c: -c["weight"]),
        "difficulty": {"b_from": lo, "b_to": hi},
        "families": families,
        "items_total": items_total,
        "minutes": round(items_total * avg_limit * SHARE_OF_LIMIT / 60),
        "focus": {n: round(w[n], 2) for n in names},
    }


if __name__ == "__main__":
    # привести засеянный банк к текущим шаблонам (новые семейства и изменённые клоны, стенд без --reset): python -m app.services.items
    # под __main__ модуль — копия: bank/ зарегистрировал семейства в импортированном app.services.items, берём его seed_items
    from app.db import SessionLocal, init_db
    from app.services import items

    init_db()
    with SessionLocal() as db:
        print(f"Банк заданий: добавлено и обновлено {items.seed_items(db)} заданий")
