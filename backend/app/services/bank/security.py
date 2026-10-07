"""Security, сюжет «Ночной инцидент»: защитные сценарии — обнаружение, разбор кода и триаж по образцу Backend.
По 3 семейства на компетенцию сверх простого из items.py, сложность разнесена по полосам. Без рецептов атак:
задания про то, как находить и чинить дефекты, читать логи инцидента и правильно реагировать."""

from app.services.items import _choice, _log, family

# диапазоны из RFC 5737 для документации — никаких реальных адресов
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
    param = rng.choice(["next", "return_to", "redirect", "continue"])
    host = rng.choice(["login-check.example", "secure-pay.example", "account-help.example"])
    absolute = rng.random() < 0.5
    lines = [f'target = request.args.get("{param}", "/")']
    if absolute:
        lines += ['if target.startswith(("http://", "https://")):', '    target = "/"']
        right = f"«//{host}» без схемы проходит проверку: разбирать адрес через urlsplit и пускать только относительный путь без хоста"
    else:
        lines += ['if not target.startswith("/"):', '    target = "/"']
        right = f"«//{host}» начинается с «/», но браузер читает его как чужой хост: пускать только путь без netloc"
    lines.append("return redirect(target)")
    opts, key = _choice(rng, right, [
        f"Экранировать {param} через urllib.parse.quote перед redirect",
        "Добавить к ссылке CSRF-токен: без валидного токена сессии переход по чужой ссылке из рассылки просто не выполнится",
        "Сверять target с заголовком Referer и разрешать редирект, только если запрос пришёл с нашего сайта",
    ])
    return {"scene_title": "Ссылка уводит наружу", "story": f"После входа пользователя возвращают на адрес из параметра {param}. Проверку уже добавили, но ссылка на наш /login из рассылки после входа уводит на {host}.",
            "prompt": "Почему проверка не помогла и как исправить?", "panel": {"type": "code", "lang": "python", "lines": lines}, "options": opts, "key": key}


@family("sec_web_mass_assign", "Security", "Веб-уязвимости", "mark", 2.3, 2.1)
def _(rng):
    model = rng.choice(["User", "Account", "Profile"])
    field = rng.choice(["is_admin=true", "role=\"admin\"", "balance=1000000", "email_verified=true"])
    lines = [f'@router.patch("/{model.lower()}/me")', "async def update(data: dict, me=Depends(current_user)):"]
    if rng.random() < 0.5:
        lines.append("    data.pop(\"id\", None)")
    lines.append("    for k, v in data.items():")
    key = len(lines)
    lines += ["        setattr(me, k, v)", "    await db.commit()", "    return me"]
    return {"scene_title": "Поле роли извне", "story": f"Пользователь патчит свой {model} произвольным телом запроса и выставляет себе {field}.",
            "prompt": "Нажмите на строку, из-за которой любой атрибут перезаписывается (нужен белый список полей).",
            "panel": {"type": "code", "lang": "python", "lines": lines, "caption": f"PR #{rng.randint(400, 899)} · «обновление {model.lower()}»"}, "key": [key, key + 1]}


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
            "panel": {"type": "code", "lang": "python", "lines": lines, "caption": f"PR #{rng.randint(400, 899)} · «отдача {base}»"}, "key": [key, key + 1]}


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
    spike, hour = rng.randint(3, 5), rng.randint(1, 4)
    x = [f"{hour:02d}:{5 * i:02d}" for i in range(7)]
    base = rng.randint(4, 12)
    fails = [base + rng.randint(-2, 2) if i < spike else rng.randint(900, 1400) for i in range(7)]
    ok = [rng.randint(20, 35) for _ in range(7)]
    src = _ip(rng)
    panel = {"type": "chart", "x": x, "marker": {"i": spike, "label": f"всплеск с {src}"}, "series": [
        {"name": "неуспешные входы в минуту", "axis": "left", "max": 1500, "data": fails},
        {"name": "успешные входы в минуту", "axis": "right", "max": 100, "data": ok}]}
    right = rng.choice(["Подбор паролей с одного адреса: ограничить частоту попыток, временно заблокировать источник и проверить, были ли с него успешные входы",
                        "Перебор паролей с одного источника: лимит попыток на учётную запись и адрес, блокировка источника, проверка успешных входов с него"])
    opts, key = _choice(rng, right, [
        "Сбой базы учётных записей: часть входов падает с ошибкой, нужно переключиться на реплику и проверить её",
        "Истёк TLS-сертификат балансировщика: клиенты повторяют вход",
        "После выкладки сломалась форма входа: откатить релиз и проверить валидацию паролей",
    ])
    return {"scene_title": "Шквал входов", "story": "Ночью резко выросло число неуспешных входов. Успешные идут как обычно для этого часа.",
            "prompt": "Что это и первое действие?", "panel": panel, "options": opts, "key": key}


@family("sec_net_tls_version", "Security", "Сети", "choice", 2.2, 1.0)
def _(rng):
    svc = rng.choice(["api", "admin", "payments", "partners"])
    protos = rng.choice(["TLS 1.0, TLS 1.1, TLS 1.2", "SSLv3, TLS 1.0, TLS 1.2", "TLS 1.0, TLS 1.2"])
    cipher = rng.choice(["TLS_RSA_WITH_3DES_EDE_CBC_SHA", "TLS_RSA_WITH_RC4_128_SHA", "TLS_RSA_WITH_AES_128_CBC_SHA"])
    m = rng.randint(10, 50)
    lines = [
        _log(f"02:{m:02d}:03", "tls-scan", "WARN", f"{svc}.example.com supports {protos}"),
        _log(f"02:{m:02d}:03", "tls-scan", "WARN", f"cipher suites include {cipher}"),
        _log(f"02:{m:02d}:04", "tls-scan", "INFO", "certificate RSA 2048, valid, chain ok"),
    ]
    opts, key = _choice(rng, "Отключить старые протоколы и слабые наборы: оставить TLS 1.2+ с ECDHE и AEAD-шифрами", [
        "Перевыпустить сертификат с ключом RSA 4096: слабость в длине ключа, а не в версии протокола",
        "Включить HSTS с preload: браузеры перестанут договариваться о старых версиях TLS",
        "Оставить старые версии для старых клиентов и включить TLS_FALLBACK_SCSV — этого достаточно",
    ])
    return {"scene_title": "Отчёт сканера TLS", "story": f"Ночной скан периметра показал, что {svc}.example.com принимает старые версии протокола и слабые шифронаборы.",
            "prompt": "Что сделать?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("sec_net_exfil", "Security", "Сети", "choice", 2.3, 1.9)
def _(rng):
    dom = rng.choice(["cdn-metrics.example", "update-check.example", "telemetry-sync.example"])
    host = f"10.{rng.randint(10, 40)}.{rng.randint(1, 9)}.{rng.randint(10, 90)}"
    n = rng.randint(30, 90)
    chars = "abcdefghijklmnopqrstuvwxyz234567"
    sub = lambda: "".join(rng.choice(chars) for _ in range(rng.randint(40, 56)))
    m = rng.randint(10, 40)
    lines = [
        _log(f"03:{m:02d}:01", "dns", "INFO", f"{host} TXT {sub()}.{dom}"),
        _log(f"03:{m:02d}:01", "dns", "INFO", f"{host} TXT {sub()}.{dom}"),
        _log(f"03:{m:02d}:02", "dns", "INFO", f"{host} TXT {sub()}.{dom}"),
        _log(f"03:{m + 5:02d}:00", "dns-stats", "WARN", f"{host}: {n} тыс. уникальных поддоменов {dom} за час, ответы NXDOMAIN/TXT"),
        _log(f"03:{m + 5:02d}:00", "fw", "INFO", f"{host} (db-replica): прямых исходящих TCP-соединений наружу нет"),
    ]
    opts, key = _choice(rng, "Утечка через DNS-туннель: пускать узлы во внешний DNS только через свой резолвер с фильтрацией", [
        "Сбой кэша резолвера: узел повторяет запросы, поднять TTL записей и перезапустить кэш",
        f"Атака на наш DNS: включить ограничение частоты ответов (RRL) на сервере зоны {dom}",
        "Телеметрия ОС: так шлёт данные агент обновлений, добавить домен в исключения мониторинга",
    ])
    return {"scene_title": "Странный DNS", "story": f"Реплика БД {host} ночью шлёт тысячи DNS-запросов с длинными случайными поддоменами. Наружу по TCP она не ходит.",
            "prompt": "Что это и какой контроль закроет канал?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# ---------------------------- Криптография ----------------------------


@family("sec_crypto_jwt_alg", "Security", "Криптография", "mark", 2.3, 2.0)
def _(rng):
    fn, keyvar = rng.choice([("decode", "KEY"), ("verify_token", "PUBLIC_KEY"), ("parse_jwt", "settings.JWT_KEY")])
    lines = [f"def {fn}(token: str) -> dict:", "    header = jwt.get_unverified_header(token)"]
    if rng.random() < 0.5:
        lines.append("    log.debug(\"alg\", alg=header[\"alg\"])")
    lines.append(f'    return jwt.decode(token, {keyvar}, algorithms=[header["alg"]])')
    key = len(lines)
    trick = rng.choice(["alg=none", "alg=HS256, подписанные открытым ключом сервиса", "alg=none и пустой подписью"])
    return {"scene_title": "Проверка JWT", "story": f"Проверка токена берёт алгоритм из его же заголовка. Появились токены с {trick}, которые проходят {fn}.",
            "prompt": "Нажмите на строку, где алгоритм нельзя доверять клиенту (задать список допустимых на сервере).",
            "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("sec_crypto_iv_reuse", "Security", "Криптография", "choice", 2.2, 0.6)
def _(rng):
    field = rng.choice(["номер паспорта", "номер карты", "телефон", "СНИЛС"])
    iv = rng.choice(["b'0000000000000000'", "b'\\x00' * 16", "b'fsp-career-iv-01'"])
    if rng.random() < 0.5:
        lines = [f"IV = {iv}", "def enc(data: bytes) -> bytes:", "    c = AES.new(KEY, AES.MODE_CBC, IV)", "    return c.encrypt(pad(data, 16))"]
        right = "Одинаковые значения дают одинаковый шифротекст и выдают совпадения: новый случайный IV на каждую запись"
    else:
        lines = [f"NONCE = {iv}[:12]", "def enc(data: bytes) -> bytes:", "    c = AES.new(KEY, AES.MODE_GCM, nonce=NONCE)", "    return c.encrypt(data) + c.digest()"]
        right = "Повтор nonce в GCM раскрывает XOR открытых текстов и ломает аутентичность: уникальный nonce на запись"
    opts, key = _choice(rng, right, [
        "IV — открытый параметр и секретом не является: его и так передают рядом с шифротекстом, поэтому фиксированное значение ничем не опасно",
        "Риск только в длине ключа: перейти на AES-256, и фиксированный IV перестанет быть проблемой",
        "Хранить IV в переменной окружения вместо кода: если его никто не знает, повтор не страшен",
    ])
    return {"scene_title": "Одинаковый IV", "story": f"В ревью шифрования поля «{field}» заметили, что вектор инициализации задан константой в коде.",
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
    name, sys = rng.choice([("pay", "платёжного сервиса"), ("billing", "биллинга"), ("lk", "личного кабинета")])
    host = f"{name}-{rng.randint(1, 12):02d}"
    m = rng.randint(0, 50)
    lines = [
        _log(f"03:{m:02d}:10", "edr", "ALERT", f"suspicious process on host {host}, outbound to {_ip(rng)}:443"),
        _log(f"03:{m:02d}:12", "edr", "INFO", f"active sessions: {rng.randint(2, 5)}; persistence via {rng.choice(['cron', 'systemd unit', 'ssh authorized_keys'])} suspected"),
    ]
    opts, key = _choice(rng, "Изолировать хост сетевыми правилами, не выключая: снять память и логи, затем искать закрепление", [
        "Сразу выключить хост: процесс остановится, а образ диска можно снять потом спокойно",
        "Переустановить ОС из эталонного образа и вернуть хост в строй — так быстрее всего",
        "Сменить пароли администраторов и пока наблюдать за хостом, чтобы понять, что нужно атакующему и кто он",
    ])
    return {"scene_title": "Активный инцидент", "story": f"EDR поднял тревогу на хосте {host} {sys}: подозрительный процесс и исходящие соединения, кто-то внутри прямо сейчас.",
            "prompt": "Какой первый шаг верен?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("sec_ir_log_gap", "Security", "Реагирование", "choice", 2.2, -1.3)
def _(rng):
    svc = rng.choice(["auth", "gateway", "admin"])
    sink = rng.choice(["siem-collector", "audit-kafka", "log-shipper"])
    h, m0, dur = rng.randint(0, 2), rng.randint(5, 40), rng.randint(40, 110)
    end = h * 60 + m0 + dur
    a, b = f"{h:02d}:{m0:02d}", f"{end // 60:02d}:{end % 60:02d}"
    lines = [
        _log(f"{a}:00", svc, "INFO", "audit log rotated"),
        _log(f"{a}:01", svc, "WARN", f"{sink} unreachable, buffering (buffer size {rng.choice([500, 1000, 2000])} events)"),
        _log(f"{b}:10", svc, "INFO", f"{sink} restored, 0 events flushed"),
    ]
    opts, key = _choice(rng, f"Это пробел: события за {a}–{b} потеряны, искать следы в других источниках", [
        "Пробела нет: буфер сохранил события и отдаст их при следующей ротации журнала",
        "Это сдвиг часов сервера: события есть, просто записаны с другой временной меткой",
        "Пробел не важен: раз событий в журнале нет, в это время в системе ничего не происходило",
    ])
    return {"scene_title": "Дыра в логах", "story": f"При разборе инцидента в аудит-логе {svc} пропал кусок времени.",
            "prompt": "Как это трактовать?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("sec_ir_disclosure", "Security", "Реагирование", "choice", 2.0, 1.8)
def _(rng):
    what = rng.choice(["ФИО и телефоны клиентов", "почты и хэши паролей", "паспортные данные части клиентов", "адреса доставки и телефоны"])
    n = rng.randint(3, 90)
    when = rng.choice(["в пятницу в 23:40", "в понедельник в 09:15", "в субботу в 02:30"])
    opts, key = _choice(rng, "Уведомить Роскомнадзор об инциденте в течение 24 часов, о результатах расследования — в течение 72 часов", [
        "Уведомить регулятора в течение 72 часов с момента обнаружения, как требует GDPR, а итоги расследования — в течение месяца",
        "Уведомлять регулятора не нужно, если утёкшие данные были зашифрованы или захешированы",
        "Сначала завершить расследование, а затем один раз уведомить регулятора в течение 10 рабочих дней",
    ])
    return {"scene_title": "Подтверждённая утечка", "story": f"{when.capitalize()} подтвердилось, что наружу ушли {what} — около {n} тыс. записей. Компания — оператор ПДн по 152-ФЗ.",
            "prompt": "Что и в какие сроки требует закон?", "panel": None, "options": opts, "key": key}


# ---------------------------- Реверс ----------------------------


@family("sec_rev_hardcoded", "Security", "Реверс", "choice", 2.2, 0.6)
def _(rng):
    app = rng.choice(["мобильного клиента", "десктоп-агента", "CLI-утилиты"])
    secret = rng.choice(["AKIA................ (похоже на ключ облачного хранилища)", "sk_live_............ (ключ платёжного шлюза)",
                         "ghp_................ (токен репозитория)"])
    lines = [
        _log("—", "strings", "INFO", rng.choice(["api.example.com", "files.example.net", "sync.example.org"])),
        _log("—", "strings", "INFO", secret),
        _log("—", "strings", "INFO", "Bearer eyJhbGciOi... (встроенный токен)"),
    ]
    opts, key = _choice(rng, "Считать секреты скомпрометированными: отозвать, перевыпустить и не класть их в сборку", [
        "Обфусцировать строки в сборке: без открытых строк ключи статическим анализом уже не достать",
        "Перенести ключи из кода в файл ресурсов приложения — strings их там не увидит",
        "Риска нет: ключ выдан только этому клиенту, а бинарник подписан издателем",
    ])
    return {"scene_title": "Строки из бинарника", "story": f"Разбор строк в сборке {app} показал встроенные ключи и токен.",
            "prompt": "Что это значит и что делать?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("sec_rev_client_check", "Security", "Реверс", "choice", 2.1, 1.1)
def _(rng):
    what, lang, lines = rng.choice([
        ("лимит переводов", "javascript", ["if (user.isPremium && amount <= user.limit) {", "  sendTransfer(amount);", "}"]),
        ("признак премиума", "kotlin", ["if (prefs.getBoolean(\"premium\", false)) {", "    api.downloadReport(id)", "}"]),
        ("право на скидку", "swift", ["if user.discountAllowed {", "    order.total *= 0.8", "}", "api.submit(order)"]),
    ])
    opts, key = _choice(rng, f"Проверку «{what}» на устройстве обходят правкой кода: сервер должен проверять это сам", [
        "Включить обфускацию и проверку целостности приложения: изменённый клиент просто не запустится на устройстве",
        "Подписывать запросы ключом, вшитым в клиент: подделанный запрос сервер сразу отклонит",
        "Хранить флаг в зашифрованном хранилище устройства, чтобы его нельзя было подменить",
    ])
    return {"scene_title": "Проверка на клиенте", "story": f"Нашли, что {what} проверяется только в коде клиента; подменив его, удаётся обойти ограничение.",
            "prompt": "В чём корень проблемы?", "panel": {"type": "code", "lang": lang, "lines": lines}, "options": opts, "key": key}


@family("sec_rev_debug_endpoint", "Security", "Реверс", "choice", 2.1, -1.0)
def _(rng):
    ep = rng.choice(["/__debug", "/internal/exec", "/admin/eval"])
    tool, store = rng.choice([("apk-scan", "shared prefs"), ("ipa-scan", "UserDefaults"), ("bin-scan", "config.json рядом с бинарником")])
    ver = f"{rng.randint(2, 5)}.{rng.randint(0, 19)}.{rng.randint(0, 9)}"
    lines = [
        _log("—", tool, "INFO", f"release {ver}: found reference to {ep}"),
        _log("—", tool, "WARN", f"flag enableDebug read from {store}"),
    ]
    opts, key = _choice(rng, "Убрать отладочный путь из релизной сборки: флаг на устройстве легко включить самому", [
        "Переименовать путь во что-то неочевидное: не зная имени, его никто не вызовет",
        "Закрыть путь проверкой заголовка User-Agent: запросы примет, только если он как у официального приложения",
        "Оставить как есть: по умолчанию флаг выключен, а пользователи о нём не знают",
    ])
    return {"scene_title": "Отладка в релизе", "story": f"В релизной сборке {ver} нашли ссылку на отладочный эндпоинт {ep}, который включается локальным флагом.",
            "prompt": "Как правильно поступить?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# ---------------------------- уровень Lead ----------------------------
# сложнее H-полосы: защита формально есть, но обходится в деталях, или нужен выбор архитектуры с компромиссами


@family("sec_rv_refresh_race", "Security", "Ревью кода", "mark", 2.3, 2.4)
def _(rng):
    tbl, fn = rng.choice([("refresh_tokens", "rotate_refresh"), ("sessions", "renew_session"), ("device_tokens", "refresh_device")])
    lines = [f"async def {fn}(token: str) -> TokenPair:", "    h = sha256(token)"]
    if rng.random() < 0.5:
        lines.append(f'    metrics.inc("{fn}")')
    lines.append(f'    row = await db.fetchrow("SELECT user_id, revoked FROM {tbl} WHERE token_hash = $1", h)')
    key = len(lines)
    lines += ['    if row is None or row["revoked"]:',
              "        await revoke_family(h)  # повторное использование — отзываем всю цепочку",
              "        raise Unauthorized()",
              '    pair = await issue_pair(row["user_id"])',
              f'    await db.execute("UPDATE {tbl} SET revoked = true WHERE token_hash = $1", h)',
              "    return pair"]
    n = rng.randint(2, 4)
    return {"scene_title": "Ротация токенов", "story": f"Ротация с обнаружением повторного использования: старый токен отзывается при обмене. "
                                                       f"В логах — {n} новые пары по одному старому токену за одну миллисекунду, а цепочка не отозвана.",
            "prompt": "Нажмите на строку, которую нужно переписать, чтобы проверка и отзыв токена стали одной атомарной операцией.",
            "panel": {"type": "code", "lang": "python", "lines": lines, "caption": f"PR #{rng.randint(400, 899)} · «{fn}»"}, "key": [key, key + 5]}


@family("sec_crypto_jku_trust", "Security", "Криптография", "mark", 2.3, 2.6)
def _(rng):
    fn, aud = rng.choice([("verify_partner_token", "partner-api"), ("verify_sso", "lk"), ("verify_service_token", "billing")])
    lines = [f"async def {fn}(token: str) -> dict:", "    header = jwt.get_unverified_header(token)"]
    if rng.random() < 0.5:
        lines += ['    if header.get("alg") != "RS256":', "        raise Unauthorized()"]
    lines.append('    jwks = await jwks_cache.get(header["jku"])  # кэш на 10 минут')
    key = len(lines)
    lines += ['    signing_key = jwks.find(header["kid"])',
              f'    return jwt.decode(token, signing_key, algorithms=["RS256"], audience="{aud}")']
    return {"scene_title": "Чей это ключ", "story": f"{fn} проверяет подпись RS256, алгоритм зафиксирован, aud сверяется. Аудит нашёл токены, подписанные ключом, "
                                                    "которого нет у нашего IdP, — и они проходят проверку.",
            "prompt": "Нажмите на строку, где проверка доверяет данным из самого токена.",
            "panel": {"type": "code", "lang": "python", "lines": lines, "caption": f"PR #{rng.randint(400, 899)} · «{fn}: ротация ключей IdP»"}, "key": key}


@family("sec_ir_supply_chain", "Security", "Реагирование", "choice", 2.4, 2.75)
def _(rng):
    pkg, ver = rng.choice([("left-padder", "3.1.4"), ("fast-yaml-x", "2.0.9"), ("color-logz", "1.7.2")])
    runner, m = f"ci-runner-{rng.randint(1, 9)}", rng.randint(10, 50)
    secret = rng.choice(["NPM_TOKEN", "DEPLOY_KEY", "REGISTRY_PASSWORD"])
    lines = [
        _log(f"04:{m:02d}:01", runner, "INFO", f"npm ci: added {pkg}@{ver} (transitive, via build tooling)"),
        _log(f"04:{m:02d}:07", runner, "WARN", f"postinstall {pkg}: outbound https to {_ip(rng)}"),
        _log(f"04:{m:02d}:09", "egress-proxy", "INFO", f"{runner} POST {rng.randint(2, 9)}.4 KB to {rng.choice(['cdn-sync', 'pkg-mirror', 'stats-hub'])}.example"),
        _log(f"05:{m:02d}:40", "registry", "WARN", f"login with {secret} from {_ip(rng)} (new ASN)"),
    ]
    opts, key = _choice(rng, "Считать утёкшими все секреты этих сборок: отозвать и перевыпустить их, заморозить релизы, проверить артефакты с момента появления версии", [
        f"Откатить {pkg} в lock-файле и пересобрать: вредоносный postinstall уйдёт, а раннер эфемерный — секреты живут на нём только на время сборки и после неё недоступны",
        f"Отозвать {secret}, замеченный во входе в реестр, и закрыть раннеру исходящий доступ к этому адресу — остальное не трогать",
        f"Удалить {pkg}@{ver} из зеркала пакетов и включить npm ci --ignore-scripts",
    ])
    return {"scene_title": "Сборка звонит наружу", "story": f"В ночной сборке на {runner} транзитивная зависимость {pkg} обновилась до {ver}. Через час в реестр зашли с нового адреса.",
            "prompt": "Что делать в первую очередь?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("sec_web_tenant_authz", "Security", "Веб-уязвимости", "choice", 2.3, 2.9)
def _(rng):
    svcs = rng.sample(["invoices", "reports", "contracts", "exports", "tickets", "files"], 3)
    n, direct = rng.randint(4, 9), rng.randint(7, 15)
    lines = [_log(f"{i + 1:02d}.0{rng.randint(1, 9)}", "bug-bounty", "WARN", f"IDOR в {s}: объект другого клиента по id, исправлено точечно") for i, s in enumerate(svcs)]
    lines.append(_log("сводка", "appsec", "INFO", f"за полгода {n} похожих отчётов; сервисов с прямым доступом к общей БД: {direct}"))
    opts, key = _choice(rng, "Фильтр tenant_id из сессии — в общем слое доступа к данным, row-level security в БД вторым рубежом и тест «чужой клиент → отказ» на каждый эндпоинт", [
        "Перейти с последовательных id на случайные UUID во всех сервисах и общей БД: подобрать идентификатор чужого объекта станет практически невозможно, а код проверок трогать не придётся",
        "Проверять клиента в API-шлюзе: шлюз сверяет X-Tenant-Id с токеном и не пускает чужие запросы дальше",
        "Закрепить точечные исправления: пункт про проверку владельца в чек-листе ревью и правило WAF на перебор id подряд",
    ])
    return {"scene_title": "Снова чужие данные", "story": f"Мультитенантный SaaS: каждый сервис сам проверяет владельца объекта. IDOR находят снова и снова — это уже {n}-й отчёт.",
            "prompt": "Какое решение закрывает класс уязвимостей, а не очередной случай?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}
