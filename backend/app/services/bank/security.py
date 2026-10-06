"""Security, сюжет «Ночной инцидент»: защитные сценарии — обнаружение, разбор кода и триаж по образцу Backend.
По 3 семейства на компетенцию сверх простого из items.py, сложность разнесена по полосам. Без рецептов атак:
задания про то, как находить и чинить дефекты, читать логи инцидента и правильно реагировать."""

from app.services.items import _choice, _log, family

# диапазоны из RFC 5737/3849 для документации — никаких реальных адресов
IP = ["192.0.2.", "198.51.100.", "203.0.113."]


def _ip(rng):
    return rng.choice(IP) + str(rng.randint(2, 250))


# ---------------------------- Веб-уязвимости ----------------------------


@family("sec_web_missing_authz", "Security", "Веб-уязвимости", "mark", 2.3, 0.4)
def _(rng):
    res = rng.choice(["invoices", "orders", "tickets"])
    lines = [f'@router.get("/{res}/{{item_id}}")', "async def get_item(item_id: int, user=Depends(current_user)):"]
    if rng.random() < 0.5:
        lines.append("    log.info(\"fetch\", item_id=item_id, user=user.id)")
    lines.append(f"    item = await db.get({res.capitalize()[:-1]}, item_id)")
    key = len(lines) + 1
    lines += ["    return item"]
    return {"scene_title": "Чужой документ", "story": f"Эндпоинт отдаёт {res[:-1]} по id. Аутентификация есть, но пользователь видит и чужие записи, меняя id в адресе.",
            "prompt": "Нажмите на строку, где не хватает проверки владельца (перед возвратом объекта).",
            "panel": {"type": "code", "lang": "python", "lines": lines, "caption": f"PR #{rng.randint(400, 899)} · «получение {res[:-1]}»"}, "key": [key - 1, key]}


@family("sec_web_open_redirect", "Security", "Веб-уязвимости", "choice", 2.2, 1.0)
def _(rng):
    param = rng.choice(["next", "return_to", "redirect"])
    lines = [f'target = request.args.get("{param}", "/")', "return redirect(target)"]
    opts, key = _choice(rng, f"Открытый редирект: {param} может увести на чужой домен — разрешать только относительные пути или белый список",
                        ["Экранировать target как HTML перед редиректом", "Добавить CSRF-токен к редиректу", "Проверять, что target не длиннее 2048 символов"])
    return {"scene_title": "Ссылка уводит наружу", "story": f"После входа пользователя возвращают на адрес из параметра {param}. В рассылке нашли ссылку, уводящую на поддельный сайт.",
            "prompt": "Что это и как исправить?", "panel": {"type": "code", "lang": "python", "lines": lines}, "options": opts, "key": key}


@family("sec_web_mass_assign", "Security", "Веб-уязвимости", "mark", 2.3, 2.1)
def _(rng):
    model = rng.choice(["User", "Account", "Profile"])
    lines = [f'@router.patch("/{model.lower()}/me")', "async def update(data: dict, me=Depends(current_user)):"]
    if rng.random() < 0.5:
        lines.append("    data.pop(\"id\", None)")
    lines.append("    for k, v in data.items():")
    key = len(lines)
    lines += ["        setattr(me, k, v)", "    await db.commit()", "    return me"]
    return {"scene_title": "Поле роли извне", "story": f"Пользователь патчит свой {model} произвольным телом запроса и выставляет себе is_admin=true.",
            "prompt": "Нажмите на строку, из-за которой любой атрибут перезаписывается (нужен белый список полей).",
            "panel": {"type": "code", "lang": "python", "lines": lines, "caption": f"PR #{rng.randint(400, 899)} · «обновление {model.lower()}»"}, "key": key}


# ---------------------------- Ревью кода ----------------------------


@family("sec_rv_path_traversal", "Security", "Ревью кода", "mark", 2.3, -1.0)
def _(rng):
    base = rng.choice(["uploads", "reports", "exports"])
    lines = [f'@router.get("/{base}/{{name}}")', "async def download(name: str):"]
    if rng.random() < 0.5:
        lines.append("    name = name.strip()")
    lines.append(f'    path = os.path.join("/srv/{base}", name)')
    key = len(lines)
    lines += ["    return FileResponse(path)"]
    return {"scene_title": "Скачивание файла", "story": "Файл отдаётся по имени из URL. Ревью PR: имя подставляют в путь без проверки.",
            "prompt": "Нажмите на строку, где возможен выход за каталог (обход пути).",
            "panel": {"type": "code", "lang": "python", "lines": lines, "caption": f"PR #{rng.randint(400, 899)} · «отдача {base}»"}, "key": key}


@family("sec_rv_timing_eq", "Security", "Ревью кода", "mark", 2.2, 1.2)
def _(rng):
    what = rng.choice(["api_key", "webhook_sig", "reset_token"])
    lines = [f"def verify({what}: str) -> bool:", f"    expected = settings.{what.upper()}"]
    if rng.random() < 0.5:
        lines.append(f"    if not {what}:")
        lines.append("        return False")
    lines.append(f"    return {what} == expected")
    key = len(lines)
    return {"scene_title": "Сравнение секрета", "story": f"Функция сверяет {what} со значением в конфиге обычным ==; появились признаки перебора по времени ответа.",
            "prompt": "Нажмите на строку, где нужно сравнение за постоянное время (constant-time).",
            "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("sec_rv_ssrf_review", "Security", "Ревью кода", "mark", 2.3, 2.0)
def _(rng):
    feat = rng.choice(["preview", "avatar_import", "webhook_test"])
    lines = [f"async def {feat}(url: str):"]
    if rng.random() < 0.5:
        lines.append("    url = url.strip()")
    lines.append("    resp = await http.get(url, timeout=5)")
    key = len(lines)
    lines += ["    return resp.content"]
    return {"scene_title": "Запрос по ссылке", "story": f"Сервис сам ходит по ссылке, которую дал пользователь ({feat}). Через неё дотянулись до внутреннего адреса.",
            "prompt": "Нажмите на строку, где нужна проверка адреса назначения перед запросом (SSRF).",
            "panel": {"type": "code", "lang": "python", "lines": lines, "caption": f"PR #{rng.randint(400, 899)} · «{feat}»"}, "key": key}


# ---------------------------- Сети ----------------------------


@family("sec_net_bruteforce", "Security", "Сети", "choice", 2.3, -1.2)
def _(rng):
    spike = rng.randint(3, 5)
    x = [f"0{rng.randint(1, 3)}:{10 * i:02d}" for i in range(7)]
    base = rng.randint(4, 12)
    fails = [base + rng.randint(-2, 2) if i < spike else rng.randint(900, 1400) for i in range(7)]
    ok = [rng.randint(60, 90) if i < spike else rng.randint(2, 8) for i in range(7)]
    panel = {"type": "chart", "x": x, "marker": {"i": spike, "label": f"всплеск с {_ip(rng)}"}, "series": [
        {"name": "неуспешные входы в минуту", "axis": "left", "max": 1500, "data": fails},
        {"name": "успешные входы в минуту", "axis": "right", "max": 100, "data": ok}]}
    opts, key = _choice(rng, "Подбор паролей с одного диапазона: временно ограничить попытки и заблокировать источник, проверить, не угадан ли где пароль",
                        ["Отказ базы аутентификации", "Истёк TLS-сертификат балансировщика", "Плановая выкладка увеличила задержки"])
    return {"scene_title": "Шквал входов", "story": "Ночью резко выросло число неуспешных входов, успешные почти прекратились.",
            "prompt": "Что это и первое действие?", "panel": panel, "options": opts, "key": key}


@family("sec_net_tls_version", "Security", "Сети", "choice", 2.1, 0.2)
def _(rng):
    svc = rng.choice(["api", "admin", "payments"])
    lines = [
        _log("02:11:03", "tls-scan", "WARN", f"{svc}.example.com supports TLS 1.0, TLS 1.1"),
        _log("02:11:03", "tls-scan", "INFO", "cipher suites include TLS_RSA_WITH_3DES_EDE_CBC_SHA"),
    ]
    opts, key = _choice(rng, "Отключить устаревшие TLS 1.0/1.1 и слабые шифронаборы, оставить TLS 1.2+ с современными наборами",
                        ["Перевыпустить сертификат с ключом 4096 бит", "Включить HSTS — это закроет вопрос", "Добавить вторую проверку по IP"])
    return {"scene_title": "Отчёт сканера TLS", "story": f"Скан показал, что {svc} принимает старые версии TLS и слабые шифры.",
            "prompt": "Что сделать?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("sec_net_exfil", "Security", "Сети", "choice", 2.3, 1.9)
def _(rng):
    start = rng.randint(1, 3)
    x = [f"{22 + i // 3:02d}:{20 * (i % 3):02d}" for i in range(7)]
    base = rng.randint(20, 60)
    out = [base + rng.randint(-10, 10) if i < start else base + 400 + rng.randint(-30, 30) for i in range(7)]
    panel = {"type": "chart", "x": x, "marker": {"i": start, "label": f"канал к {_ip(rng)}:443"}, "series": [
        {"name": "исходящий трафик от БД-сети, МБ/мин", "axis": "left", "max": 600, "data": out}]}
    opts, key = _choice(rng, "Похоже на утечку данных: изолировать источник, сохранить соединения и логи для разбора, затем перекрыть исходящий канал",
                        ["Перезагрузить сервер БД, чтобы сбросить соединение", "Поднять лимит трафика — узел перегружен", "Очистить логи и продолжить наблюдение"])
    return {"scene_title": "Исходящий поток", "story": "Из сегмента с базой данных ночью пошёл ровный исходящий трафик на внешний адрес, которого раньше не было.",
            "prompt": "Что это и как действовать?", "panel": panel, "options": opts, "key": key}


# ---------------------------- Криптография ----------------------------


@family("sec_crypto_jwt_alg", "Security", "Криптография", "mark", 2.3, 2.0)
def _(rng):
    lines = ["def decode(token: str) -> dict:", "    header = jwt.get_unverified_header(token)"]
    if rng.random() < 0.5:
        lines.append("    log.debug(\"alg\", alg=header[\"alg\"])")
    lines.append('    return jwt.decode(token, KEY, algorithms=[header["alg"]])')
    key = len(lines)
    return {"scene_title": "Проверка JWT", "story": "Проверка токена берёт алгоритм из его же заголовка. Появились токены с alg=none, которые проходят проверку.",
            "prompt": "Нажмите на строку, где алгоритм нельзя доверять клиенту (задать список допустимых на сервере).",
            "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("sec_crypto_iv_reuse", "Security", "Криптография", "choice", 2.2, 0.6)
def _(rng):
    lines = ["IV = b'0000000000000000'  # фиксированный", "def enc(data: bytes) -> bytes:", "    c = AES.new(KEY, AES.MODE_CBC, IV)", "    return c.encrypt(pad(data))"]
    opts, key = _choice(rng, "Постоянный IV раскрывает совпадения блоков открытого текста — генерировать случайный IV на каждое шифрование и хранить рядом с шифротекстом",
                        ["Увеличить длину ключа до 256 бит", "Шифровать дважды одним ключом", "Сжимать данные перед шифрованием"])
    return {"scene_title": "Одинаковый IV", "story": "В ревью заметили: вектор инициализации у шифрования фиксирован в коде.",
            "prompt": "Чем это опасно и как исправить?", "panel": {"type": "code", "lang": "python", "lines": lines}, "options": opts, "key": key}


@family("sec_crypto_token_entropy", "Security", "Криптография", "mark", 2.2, -1.0)
def _(rng):
    what = rng.choice(["reset", "invite", "verify"])
    lines = [f"def make_{what}_token() -> str:"]
    if rng.random() < 0.5:
        lines.append("    now = time.time()")
    lines.append("    return hashlib.md5(str(random.random()).encode()).hexdigest()")
    key = len(lines)
    return {"scene_title": "Предсказуемый токен", "story": f"Токен {what} делается из random.random(). Их удаётся угадывать и срабатывать за чужих пользователей.",
            "prompt": "Нажмите на строку, где нужен криптостойкий генератор (secrets.token_urlsafe).",
            "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


# ---------------------------- Реагирование ----------------------------


@family("sec_ir_triage_order", "Security", "Реагирование", "choice", 2.2, 0.8)
def _(rng):
    sys = rng.choice(["платёжный сервис", "биллинг", "личный кабинет"])
    lines = [
        _log("03:02:10", "edr", "ALERT", f"suspicious process on host {sys[:4]}-07, outbound to {_ip(rng)}"),
        _log("03:02:12", "edr", "INFO", "active sessions: 3; persistence via cron suspected"),
    ]
    opts, key = _choice(rng, "Изолировать хост от сети, сохранив его включённым и собрав память/логи, затем искать способ закрепления и масштаб",
                        ["Немедленно выключить хост, чтобы остановить процесс", "Переустановить ОС и вернуть в строй", "Сменить пароль админа и продолжить работу"])
    return {"scene_title": "Активный инцидент", "story": f"EDR поднял тревогу на хосте {sys}: подозрительный процесс и исходящие соединения, кто-то внутри прямо сейчас.",
            "prompt": "Какой первый шаг верен?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("sec_ir_log_gap", "Security", "Реагирование", "choice", 2.2, -1.3)
def _(rng):
    svc = rng.choice(["auth", "gateway", "admin"])
    lines = [
        _log("01:40:00", svc, "INFO", "audit log rotated"),
        _log("01:40:01", svc, "WARN", "audit sink unreachable, buffering"),
        _log("02:55:10", svc, "INFO", "audit sink restored, 0 events flushed"),
    ]
    opts, key = _choice(rng, "Между 01:40 и 02:55 аудит-события потеряны — отметить пробел, искать следы в других источниках и не считать отсутствие событий признаком чистоты",
                        ["Логи в порядке: буфер всё сохранил", "Проблема только в часах сервера", "Нужно просто перезапустить сервис логов"])
    return {"scene_title": "Дыра в логах", "story": "При разборе инцидента заметили, что в аудит-логе пропал кусок времени.",
            "prompt": "Как это трактовать?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("sec_ir_disclosure", "Security", "Реагирование", "choice", 2.0, 1.8)
def _(rng):
    what = rng.choice(["данные части клиентов", "хэши паролей", "платёжные токены"])
    opts, key = _choice(rng, "Зафиксировать объём и состав утёкшего, уведомить ответственных и регулятора в срок, оповестить затронутых и дать рекомендации — по плану реагирования",
                        ["Тихо закрыть дыру и ничего не сообщать", "Сообщить только если кто-то пожалуется", "Опубликовать все детали эксплуатации сразу же"])
    return {"scene_title": "Подтверждённая утечка", "story": f"Подтвердилось, что наружу ушли {what}. Нужно решить, что делать дальше.",
            "prompt": "Какой порядок действий правильный?", "panel": None, "options": opts, "key": key}


# ---------------------------- Реверс ----------------------------


@family("sec_rev_hardcoded", "Security", "Реверс", "choice", 2.2, 0.6)
def _(rng):
    app = rng.choice(["мобильного клиента", "десктоп-агента", "CLI-утилиты"])
    lines = [
        _log("—", "strings", "INFO", "api.example.com"),
        _log("—", "strings", "INFO", "AKIA................ (похоже на ключ доступа)"),
        _log("—", "strings", "INFO", "Bearer eyJhbGciOi... (встроенный токен)"),
    ]
    opts, key = _choice(rng, "Секреты зашиты в сборку и достаются обычным strings — считать их скомпрометированными, отозвать и перевыпустить, выдавать клиенту короткоживущие токены",
                        ["Обфусцировать строки — тогда их не найдут", "Перенести ключи в ресурсы вместо кода", "Ничего: доступ к бинарнику ограничен"])
    return {"scene_title": "Строки из бинарника", "story": f"В дизассемблере {app} простой разбор строк показал встроенные ключи и токен.",
            "prompt": "Что это значит и что делать?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("sec_rev_client_check", "Security", "Реверс", "choice", 2.1, 1.1)
def _(rng):
    what = rng.choice(["лимит переводов", "признак премиума", "право на скидку"])
    lines = ["if (user.isPremium && amount <= user.limit) {", "  sendTransfer(amount);", "}"]
    opts, key = _choice(rng, f"Проверка {what} только на клиенте обходится правкой кода на устройстве — дублировать и принимать решение на сервере",
                        ["Минифицировать и обфусцировать клиент", "Проверять ещё и в двух местах клиента", "Шифровать поле user.limit на клиенте"])
    return {"scene_title": "Проверка на клиенте", "story": f"Нашли, что {what} проверяется только в коде клиента; подменив его, удаётся обойти ограничение.",
            "prompt": "В чём корень проблемы?", "panel": {"type": "code", "lang": "javascript", "lines": lines}, "options": opts, "key": key}


@family("sec_rev_debug_endpoint", "Security", "Реверс", "choice", 2.2, 2.3)
def _(rng):
    ep = rng.choice(["/__debug", "/internal/exec", "/admin/eval"])
    lines = [
        _log("—", "apk-scan", "INFO", f"found reference to {ep} in release build"),
        _log("—", "apk-scan", "WARN", "flag enableDebug read from shared prefs"),
    ]
    opts, key = _choice(rng, "В релизной сборке остался отладочный путь, включаемый флагом — убрать его из релиза и не полагаться на то, что флаг «обычно выключен»",
                        ["Переименовать путь во что-то неочевидное", "Закрыть путь проверкой User-Agent", "Оставить, но включать только по будням"])
    return {"scene_title": "Отладка в релизе", "story": f"В релизной сборке нашли ссылку на отладочный эндпоинт {ep}, который включается локальным флагом.",
            "prompt": "Как правильно поступить?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}
