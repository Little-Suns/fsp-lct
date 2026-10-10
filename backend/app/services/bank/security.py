"""Security, сюжет «Открытая дверь» (умный дом сам выпустил Рея во двор): защитные сценарии — обнаружение, разбор кода и триаж по образцу Backend.
По 3 семейства на компетенцию сверх простого из items.py, сложность разнесена по полосам. Без рецептов атак:
задания про то, как находить и чинить дефекты, читать логи инцидента и правильно реагировать.
У каждого семейства три варианта механики (items._variant), правильные ответы других вариантов — среди дистракторов."""

from app.services.items import _log, _options, _variant, family

# диапазоны из RFC 5737 для документации — никаких реальных адресов
IP = ["192.0.2.", "198.51.100.", "203.0.113."]


def _ip(rng):
    return rng.choice(IP) + str(rng.randint(2, 250))


# ---------------------------- Веб-уязвимости ----------------------------


@family("sec_web_missing_authz", "Security", "Веб-уязвимости", "mark", 2.3, 0.4)
def _(rng):
    res = rng.choice(["invoices", "orders", "tickets"])
    model = res.capitalize()[:-1]
    v = _variant(rng, 3)
    if v == 0:
        lines = [f'@router.get("/{res}/{{item_id}}")', "async def get_item(item_id: int, user=Depends(current_user)):"]
        if rng.random() < 0.5:
            lines.append("    log.info(\"fetch\", item_id=item_id, user=user.id)")
        lines.append(f"    item = await db.get({model}, item_id)")
        key = [len(lines), len(lines) + 1]
        lines += ["    return item"]
        story = f"Проверяете API приложения умного дома: эндпоинт отдаёт {res[:-1]} по id. Аутентификация есть, но пользователь видит и чужие записи, меняя id в адресе."
    elif v == 1:
        lines = [f'@router.get("/{res}/{{item_id}}")', "async def get_item(item_id: int, user=Depends(current_user)):", f"    item = await db.get({model}, item_id)",
                 "    if item is None or item.owner_id != user.id:", "        raise NotFound()", "    return item", "", "",
                 f'@router.get("/{res}")', "async def list_items(owner_id: int, user=Depends(current_user)):"]
        if rng.random() < 0.5:
            lines.append("    log.info(\"list\", user=user.id)")
        lines.append(f"    rows = await db.list({model}, owner_id=owner_id)")
        key = len(lines)
        lines += ["    return rows"]
        story = f"Проверяете API приложения умного дома: список {res} фильтруется по владельцу. Аутентификация есть, но пользователь получает чужой список, подставив другое число в параметр."
    else:
        lines = [f'@router.delete("/{res}/{{item_id}}")', "async def delete_item(item_id: int, body: DeleteBody, user=Depends(current_user)):",
                 f"    item = await db.get({model}, item_id)", "    if item is None or item.owner_id != user.id:", "        raise Forbidden()"]
        if rng.random() < 0.5:
            lines.append("    log.info(\"delete\", item_id=item_id, user=user.id)")
        lines.append(f"    await db.delete({model}, body.id)")
        key = len(lines)
        lines += ["    return {\"ok\": True}"]
        story = f"Удаление {res[:-1]} в приложении умного дома проверяет владельца, но пользователи жалуются, что у них пропадают записи, которые они не удаляли."
    return {"scene_title": "Чужие записи", "story": story, "prompt": "Нажмите на строку, из-за которой пользователь добирается до чужих записей.",
            "panel": {"type": "code", "lang": "python", "lines": lines, "caption": f"PR #{rng.randint(400, 899)} · «{res}»"}, "key": key}


@family("sec_web_open_redirect", "Security", "Веб-уязвимости", "choice", 2.2, 1.0)
def _(rng):
    param = rng.choice(["next", "return_to", "redirect", "continue"])
    host = rng.choice(["login-check.example", "secure-pay.example", "account-help.example"])
    v = _variant(rng, 3)
    lines = [f'target = request.args.get("{param}", "/")']
    if v == 0:
        lines += ['if target.startswith(("http://", "https://")):', '    target = "/"']
        story = f"Проверку уже добавили, но ссылка на наш /login из рассылки владельцам умных замков после входа уводит на {host}."
    elif v == 1:
        lines += ['if not target.startswith("https://example.com"):', '    target = "/"']
        story = f"Разрешены только адреса нашего сайта, но ссылка из рассылки владельцам умных замков после входа уводит на example.com.{host}."
    else:
        lines += ["parts = urlsplit(target)", "if parts.netloc and parts.netloc not in ALLOWED_HOSTS:", '    target = "/"']
        story = "Чужие хосты проверка отсекает, но ссылка на наш /login из рассылки владельцам умных замков после входа выполняет скрипт на нашей странице."
    # javascript: в Location серверного 302 браузер не исполняет — у варианта со скриптом переход делает сама страница
    lines.append('return render_template("after_login.html", next_url=target)  # там: location.href = {{ next_url|tojson }}' if v == 2 else
                 "return redirect(target)")
    opts, key = _options(rng, [f"«//{host}» без схемы проходит проверку: разбирать адрес через urlsplit и пускать только путь без хоста",
                               "Проверка префиксом пропускает «example.com.другой-домен»: сравнивать хост целиком с белым списком",
                               "Схема javascript: проходит проверку хоста: разрешать только https и путь без схемы"], v,
                         [f"Экранировать {param} через urllib.parse.quote перед redirect",
                          "Добавить к ссылке CSRF-токен: без валидного токена сессии переход по чужой ссылке из рассылки просто не выполнится",
                          "Сверять target с заголовком Referer и разрешать редирект, только если запрос пришёл с нашего сайта"])
    return {"scene_title": "Ссылка после входа", "story": f"После входа пользователя возвращают на адрес из параметра {param}. {story}",
            "prompt": "Почему проверка не помогла и как исправить?", "panel": {"type": "code", "lang": "python", "lines": lines}, "options": opts, "key": key}


@family("sec_web_mass_assign", "Security", "Веб-уязвимости", "mark", 2.3, 2.1)
def _(rng):
    model = rng.choice(["User", "Account", "Profile"])
    field, fname = rng.choice([("is_admin=true", "is_admin: bool = False"), ("role=\"admin\"", "role: str = \"user\""),
                               ("email_verified=true", "email_verified: bool = False")])
    v = _variant(rng, 3)
    if v == 0:
        lines = [f'@router.patch("/{model.lower()}/me")', "async def update(data: dict, me=Depends(current_user)):"]
        if rng.random() < 0.5:
            lines.append("    data.pop(\"id\", None)")
        lines.append("    for k, v in data.items():")
        key = [len(lines), len(lines) + 1]
        lines += ["        setattr(me, k, v)", "    await db.commit()", "    return me"]
        story = f"В облаке умного дома пользователь патчит свой {model} произвольным телом запроса и выставляет себе {field}."
    elif v == 1:
        lines = [f"class {model}Update(BaseModel):", "    display_name: str | None = None", "    phone: str | None = None", f"    {fname}"]
        key = len(lines)
        lines += ["", "", f'@router.patch("/{model.lower()}/me")', f"async def update(data: {model}Update, me=Depends(current_user)):",
                  "    for k, v in data.model_dump(exclude_unset=True).items():", "        setattr(me, k, v)", "    await db.commit()", "    return me"]
        story = f"Обновление {model} принимает только поля схемы, но пользователь всё равно выставляет себе {field}."
    else:
        lines = ['@router.post("/register")', "async def register(request: Request):", "    data = await request.json()"]
        if rng.random() < 0.5:
            lines.append("    validate_email(data[\"email\"])")
        lines.append("    password = data.pop(\"password\")")
        lines.append(f"    user = {model}(**data)")
        key = len(lines)
        lines += ["    user.set_password(password)", "    db.add(user)", "    await db.commit()", "    return {\"id\": user.id}"]
        story = f"Новые пользователи при регистрации получают {field}, хотя форма такого поля не содержит."
    return {"scene_title": "Лишнее поле", "story": story,
            "prompt": "Нажмите на строку, из-за которой пользователь может выставить себе привилегированный атрибут.",
            "panel": {"type": "code", "lang": "python", "lines": lines, "caption": f"PR #{rng.randint(400, 899)} · «{model.lower()}»"}, "key": key}


# ---------------------------- Ревью кода ----------------------------


@family("sec_rv_path_traversal", "Security", "Ревью кода", "mark", 2.3, -1.0)
def _(rng):
    base = rng.choice(["uploads", "reports", "exports"])
    v = _variant(rng, 3)
    # {name:path}: обычный {name} в FastAPI не пропускает «/», и «../» в него не попадёт
    if v == 0:
        lines = [f'@router.get("/{base}/{{name:path}}")', "async def download(name: str):"]
        if rng.random() < 0.5:
            lines.append("    name = name.strip()")
        lines.append(f'    path = os.path.join("/srv/{base}", name)')
        key = [len(lines), len(lines) + 1]
        lines += ["    return FileResponse(path)"]
        story = "Ревью PR в облаке умного дома: файл отдаётся по имени из URL, имя подставляют в путь без проверки."
    elif v == 1:
        lines = [f'@router.post("/{base}/import")', "async def import_archive(file: UploadFile):", f'    dest = Path("/srv/{base}") / uuid4().hex',
                 "    dest.mkdir()", '    with tarfile.open(fileobj=file.file, mode="r:gz") as tar:', "        tar.extractall(dest)"]
        key = len(lines)
        lines += ["    return {\"id\": dest.name}"]
        story = f"Архивы распаковываются в каталог /srv/{base}. После загрузки чужого архива на сервере появились файлы вне этого каталога."
    else:
        lines = [f'@router.get("/{base}/{{name:path}}")', "async def download(name: str):", f'    path = os.path.join("/srv/{base}", name)',
                 f'    if not path.startswith("/srv/{base}/"):']
        key = len(lines)
        lines += ["        raise HTTPException(404)", "    return FileResponse(path)"]
        story = "Файл отдаётся по имени из URL; проверку, что путь внутри каталога, уже добавили — но аудитор всё равно скачал файл снаружи."
    return {"scene_title": "Файлы на сервере", "story": story, "prompt": "Нажмите на строку, где возможен выход за пределы каталога.",
            "panel": {"type": "code", "lang": "python", "lines": lines, "caption": f"PR #{rng.randint(400, 899)} · «{base}»"}, "key": key}


@family("sec_rv_timing_eq", "Security", "Ревью кода", "mark", 2.2, 1.2)
def _(rng):
    what = rng.choice(["api_key", "webhook_sig", "partner_sig"])
    v = _variant(rng, 3)
    if v == 0:
        lines = [f"def verify({what}: str) -> bool:", f"    expected = settings.{what.upper()}"]
        if rng.random() < 0.5:
            lines += [f"    if not {what}:", "        return False"]
        lines.append(f"    return {what} == expected")
        key = len(lines)
        story = f"Функция сверяет {what} со значением в конфиге; аудит нашёл признаки подбора по времени ответа."
    elif v == 1:
        lines = ["def sign(body: bytes) -> str:", f"    return hashlib.sha256(settings.{what.upper()} + body).hexdigest()"]
        key = len(lines)
        lines += ["", "", f"def verify(body: bytes, {what}: str) -> bool:", f"    return hmac.compare_digest(sign(body), {what})"]
        story = f"Подпись {what} считается от секрета и тела запроса. Аудит показал, что к подписанному телу можно дописать данные и получить верную подпись."
    else:
        lines = [f"def verify(body: bytes, {what}: str | None) -> None:", f"    expected = hmac.new(settings.{what.upper()}, body, hashlib.sha256).hexdigest()"]
        if rng.random() < 0.5:
            lines.append(f'    log.debug("verify", has_sig={what} is not None)')
        lines.append(f"    if {what} and not hmac.compare_digest(expected, {what}):")
        key = len(lines)
        lines += ["        raise Unauthorized()"]
        story = f"Подпись {what} проверяется HMAC и сравнением за постоянное время, но аудит прислал запрос, который прошёл проверку без подписи."
    return {"scene_title": "Проверка подписи", "story": story, "prompt": "Нажмите на строку с уязвимостью.",
            "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("sec_rv_ssrf_review", "Security", "Ревью кода", "mark", 2.3, 2.0)
def _(rng):
    feat = rng.choice(["preview", "avatar_import", "webhook_test"])
    v = _variant(rng, 3)
    lines = [f"async def {feat}(url: str):"]
    if rng.random() < 0.5:
        lines.append("    url = url.strip()")
    if v == 0:
        lines.append("    resp = await http.get(url, timeout=5)")
        key = len(lines)
        story = f"Облачный сервис умного дома сам ходит по ссылке, которую дал пользователь ({feat}). Через неё дотянулись до внутреннего адреса."
    elif v == 1:
        lines.append('    if "localhost" in url or "127.0.0.1" in url or "169.254.169.254" in url:')
        key = len(lines)
        lines += ["        raise Forbidden()", "    resp = await http.get(url, timeout=5)"]
        story = f"Сервис ходит по ссылке пользователя ({feat}), внутренние адреса запрещены, но аудитор всё равно дотянулся до метаданных облака."
    else:
        lines += ["    host = urlsplit(url).hostname", "    if any(ip.is_private for ip in resolve(host)):", "        raise Forbidden()",
                  "    client = httpx.AsyncClient(follow_redirects=True)"]
        key = len(lines)
        lines.append("    resp = await client.get(url, timeout=5)")
        story = f"Сервис ходит по ссылке пользователя ({feat}) и проверяет, что адрес назначения не внутренний. Аудитор дал ссылку на свой сервер, тот ответил 302 на внутренний адрес — и запрос туда дошёл."
    lines.append("    return resp.content")
    return {"scene_title": "Запрос по ссылке", "story": story, "prompt": "Нажмите на строку, из-за которой сервис можно заставить сходить во внутреннюю сеть.",
            "panel": {"type": "code", "lang": "python", "lines": lines, "caption": f"PR #{rng.randint(400, 899)} · «{feat}»"}, "key": key}


# ---------------------------- Сети ----------------------------


@family("sec_net_bruteforce", "Security", "Сети", "choice", 2.3, -1.2)
def _(rng):
    spike, hour = rng.randint(3, 5), rng.randint(1, 4)
    x = [f"{hour:02d}:{5 * i:02d}" for i in range(7)]
    base = rng.randint(4, 12)
    fails = [base + rng.randint(-2, 2) if i < spike else rng.randint(900, 1400) for i in range(7)]
    v = _variant(rng, 3)
    if v == 0:
        mark = f"всплеск с {_ip(rng)}"
        series = [{"name": "неуспешные входы в минуту", "axis": "left", "max": 1500, "data": fails},
                  {"name": "успешные входы в минуту", "axis": "right", "max": 100, "data": [rng.randint(20, 35) for _ in range(7)]}]
    elif v == 1:
        mark = "всплеск"
        series = [{"name": "неуспешные входы в минуту", "axis": "left", "max": 1500, "data": fails},
                  {"name": "успешные входы в минуту", "axis": "left", "max": 1500, "data": [rng.randint(20, 35) if i < spike else rng.randint(45, 70) for i in range(7)]},
                  {"name": "уникальных адресов-источников", "axis": "right", "max": 5000, "data": [rng.randint(15, 40) if i < spike else rng.randint(2500, 4800) for i in range(7)]}]
    else:
        mark = f"релиз {rng.randint(2, 5)}.{rng.randint(0, 30)}"
        series = [{"name": "неуспешные входы в минуту", "axis": "left", "max": 1500, "data": fails},
                  {"name": "успешные входы в минуту", "axis": "right", "max": 100, "data": [rng.randint(20, 35) if i < spike else rng.randint(0, 2) for i in range(7)]}]
    panel = {"type": "chart", "x": x, "marker": {"i": spike, "label": mark}, "series": series}
    opts, key = _options(rng, ["Подбор паролей с одного адреса: ограничить частоту попыток, временно заблокировать источник и проверить его успешные входы",
                               "Перебор по утёкшим базам с тысяч адресов: проверять пароли по базам утечек и включить второй фактор",
                               "После выкладки сломался вход: откатить релиз и проверить проверку паролей"], v,
                         ["Сбой базы учётных записей: часть входов падает по таймауту, переключиться на реплику и проверить пул соединений",
                          "Истёк TLS-сертификат балансировщика: клиенты повторяют вход"])
    return {"scene_title": "Шквал входов", "story": "Пока Рей роет клумбу, SOC шлёт алерт: число неуспешных входов в приложение умного дома резко выросло. Перед вами график за последние полчаса.", "prompt": "Что это и первое действие?",
            "panel": panel, "options": opts, "key": key}


@family("sec_net_tls_version", "Security", "Сети", "choice", 2.2, 1.0)
def _(rng):
    svc = rng.choice(["api", "admin", "payments", "partners"])
    m = rng.randint(10, 50)
    t = lambda s: f"02:{m:02d}:{s:02d}"  # noqa: E731
    v = _variant(rng, 3)
    if v == 0:
        protos = rng.choice(["TLS 1.0, TLS 1.1, TLS 1.2", "SSLv3, TLS 1.0, TLS 1.2", "TLS 1.0, TLS 1.2"])
        cipher = rng.choice(["TLS_RSA_WITH_3DES_EDE_CBC_SHA", "TLS_RSA_WITH_RC4_128_SHA", "TLS_RSA_WITH_AES_128_CBC_SHA"])
        lines = [_log(t(3), "tls-scan", "WARN", f"{svc}.example.com supports {protos}"), _log(t(3), "tls-scan", "WARN", f"cipher suites include {cipher}"),
                 _log(t(4), "tls-scan", "INFO", "certificate RSA 2048, valid, chain ok")]
    elif v == 1:
        lines = [_log(t(3), "tls-scan", "INFO", f"{svc}.example.com supports TLS 1.2, TLS 1.3, ECDHE + AEAD only"),
                 _log(t(4), "tls-scan", "WARN", f"certificate RSA 2048, expires in {rng.randint(3, 9)} days"),
                 _log(t(5), "acme", "ERROR", f"renew {svc}.example.com: http-01 challenge failed (404)")]
    else:
        lines = [_log(t(3), "tls-scan", "INFO", f"{svc}.example.com supports TLS 1.2, TLS 1.3, ECDHE + AEAD only"),
                 _log(t(4), "tls-scan", "WARN", "certificate chain incomplete: intermediate CA not sent"),
                 _log(t(5), "support", "INFO", "жалобы: старые Android-клиенты — handshake failure, unable to get local issuer certificate")]
    opts, key = _options(rng, ["Отключить старые протоколы и слабые наборы: оставить TLS 1.2+ с ECDHE и AEAD-шифрами",
                               "Починить автопродление и перевыпустить сертификат до истечения, поставить алерт на срок",
                               "Отдавать полную цепочку: добавить промежуточный сертификат в конфигурацию сервера"], v,
                         ["Оставить старые версии для старых клиентов и включить TLS_FALLBACK_SCSV — этого достаточно",
                          "Включить OCSP stapling — сканер перестанет предупреждать"])
    return {"scene_title": "Отчёт сканера TLS", "story": f"Ночной скан периметра облака умного дома выдал предупреждения по {svc}.example.com.",
            "prompt": "Что сделать?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("sec_net_exfil", "Security", "Сети", "choice", 2.3, 1.9)
def _(rng):
    dom = rng.choice(["cdn-metrics.example", "update-check.example", "telemetry-sync.example"])
    host = f"10.{rng.randint(10, 40)}.{rng.randint(1, 9)}.{rng.randint(10, 90)}"
    n = rng.randint(30, 90)
    m = rng.randint(10, 40)
    v = _variant(rng, 3)
    if v == 0:
        chars = "abcdefghijklmnopqrstuvwxyz234567"
        sub = lambda: "".join(rng.choice(chars) for _ in range(rng.randint(40, 56)))  # noqa: E731
        lines = [_log(f"03:{m:02d}:01", "dns", "INFO", f"{host} TXT {sub()}.{dom}"), _log(f"03:{m:02d}:01", "dns", "INFO", f"{host} TXT {sub()}.{dom}"),
                 _log(f"03:{m:02d}:02", "dns", "INFO", f"{host} TXT {sub()}.{dom}"),
                 _log(f"03:{m + 5:02d}:00", "dns-stats", "WARN", f"{host}: {n} тыс. уникальных поддоменов {dom} за час, ответы NXDOMAIN/TXT"),
                 _log(f"03:{m + 5:02d}:00", "fw", "INFO", f"{host} (db-replica): прямых исходящих TCP-соединений наружу нет")]
    elif v == 1:
        dst, s0 = _ip(rng), rng.randint(2, 57)
        lines = [_log(f"03:{m:02d}:{s0:02d}", "fw", "INFO", f"{host} → {dst}:443 TLS, {rng.randint(300, 420)} B out / {rng.randint(150, 260)} B in"),
                 _log(f"03:{m + 1:02d}:{s0 + rng.randint(-2, 2):02d}", "fw", "INFO", f"{host} → {dst}:443 TLS, {rng.randint(300, 420)} B out / {rng.randint(150, 260)} B in")]
        lines += [_log(f"03:{m + 5:02d}:00", "netflow", "WARN", f"{host}: соединения с {dst} каждые 60 ± 2 с уже {rng.randint(3, 9)} суток, объём всегда маленький"),
                  _log(f"03:{m + 5:02d}:00", "dns", "INFO", f"{dst}: нет обратной записи, домен зарегистрирован {rng.randint(5, 9)} дней назад")]
    else:
        lines = [_log(f"03:{m:02d}:00", "proxy", "INFO", f"{host} PUT https://storage.cloud.example/{rng.choice(['backup-tmp', 'sync-7f3', 'arch-q'])}/part-001 (512 MB)"),
                 _log(f"03:{m:02d}:40", "proxy", "INFO", f"{host} PUT …/part-002 (512 MB)"),
                 _log(f"03:{m + 5:02d}:00", "netflow", "WARN", f"{host}: {rng.randint(18, 60)} ГБ наружу за ночь; обычный объём — меньше 100 МБ"),
                 _log(f"03:{m + 5:02d}:00", "cmdb", "INFO", f"{host} (db-replica): облачных бэкапов в это хранилище не настроено")]
    opts, key = _options(rng, ["Утечка через DNS-туннель: пускать узлы во внешний DNS только через свой резолвер с фильтрацией",
                               "Маячок управления (C2): изолировать хост, найти процесс и закрепление, заблокировать адрес",
                               "Выгрузка данных во внешнее облако: исходящий доступ узлов — только по белому списку, найти процесс и учётку"], v,
                         ["Сбой кэша резолвера: узел повторяет запросы, поднять TTL записей и перезапустить кэш",
                          "Телеметрия ОС: так шлёт данные агент обновлений, добавить адрес в исключения мониторинга"])
    return {"scene_title": "Странный трафик", "story": f"Пока вы выясняете, кто открыл дверь Рею, мониторинг сети поднял тревогу: реплика БД {host} ведёт себя необычно.",
            "prompt": "Что это и что делать?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# ---------------------------- Криптография ----------------------------


@family("sec_crypto_jwt_alg", "Security", "Криптография", "mark", 2.3, 2.0)
def _(rng):
    fn, keyvar = rng.choice([("decode", "KEY"), ("verify_token", "PUBLIC_KEY"), ("parse_jwt", "settings.JWT_KEY")])
    v = _variant(rng, 3)
    if v == 0:
        lines = [f"def {fn}(token: str) -> dict:", "    header = jwt.get_unverified_header(token)"]
        if rng.random() < 0.5:
            lines.append("    log.debug(\"alg\", alg=header[\"alg\"])")
        lines.append(f'    return jwt.decode(token, {keyvar}, algorithms=[header["alg"]])')
        key = len(lines)
        trick = rng.choice(["alg=none", "alg=HS256, подписанные открытым ключом сервиса", "alg=none и пустой подписью"])
        story = f"Замок, который выпустил Рея, принимает команды с JWT. Проверка токена берёт алгоритм из его же заголовка. Появились токены с {trick}, которые проходят {fn}."
    elif v == 1:
        lines = [f"def {fn}(token: str) -> dict:", f'    return jwt.decode(token, {keyvar}, algorithms=["RS256"])', "", "",
                 "def current_user(request) -> User:", '    token = request.headers["Authorization"].removeprefix("Bearer ")',
                 '    claims = jwt.decode(token, options={"verify_signature": False})']
        key = len(lines)
        lines += ['    return users.get(claims["sub"])']
        story = f"API умного дома принимает JWT: {fn} проверяет подпись правильно, но токен с чужим sub и произвольной подписью всё равно открывает чужой профиль."
    else:
        lines = [f'JWT_SECRET = "{rng.choice(["secret", "changeme", "jwt-key"])}"']
        key = len(lines)
        lines += ["", "", f"def {fn}(token: str) -> dict:"]
        if rng.random() < 0.5:
            lines.append('    log.debug("decode", length=len(token))')
        lines.append('    return jwt.decode(token, JWT_SECRET, algorithms=["HS256"], audience="lk")')
        story = f"API умного дома принимает JWT: {fn} фиксирует алгоритм и проверяет аудиторию, но аудит сумел подписать токен сам и пройти проверку."
    return {"scene_title": "Проверка JWT", "story": story, "prompt": "Нажмите на строку, из-за которой поддельный токен проходит проверку.",
            "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


@family("sec_crypto_iv_reuse", "Security", "Криптография", "choice", 2.2, 0.6)
def _(rng):
    field = rng.choice(["номер паспорта", "номер карты", "телефон", "СНИЛС"])
    iv = rng.choice(["b'0000000000000000'", "b'\\x00' * 16", "b'fsp-career-iv-01'"])
    v = _variant(rng, 3)
    if v == 0:
        lines = [f"IV = {iv}", "def enc(data: bytes) -> bytes:", "    c = AES.new(KEY, AES.MODE_CBC, IV)", "    return c.encrypt(pad(data, 16))"]
    elif v == 1:
        lines = [f"NONCE = {iv}[:12]", "def enc(data: bytes) -> bytes:", "    c = AES.new(KEY, AES.MODE_GCM, nonce=NONCE)", "    return c.encrypt(data) + c.digest()"]
    else:
        lines = ["def enc(data: bytes) -> bytes:", "    iv = os.urandom(16)", "    return iv + AES.new(KEY, AES.MODE_CBC, iv).encrypt(pad(data, 16))", "",
                 "def dec(blob: bytes) -> bytes:", "    c = AES.new(KEY, AES.MODE_CBC, blob[:16])", "    return unpad(c.decrypt(blob[16:]), 16)  # ValueError → 400 «bad padding»"]
    opts, key = _options(rng, ["Фиксированный IV в CBC: одинаковые значения дают одинаковый шифротекст и выдают совпадения — новый случайный IV на каждую запись",
                               "Повтор nonce в GCM раскрывает XOR открытых текстов и ломает аутентичность: уникальный nonce на запись",
                               "Шифротекст можно незаметно менять, а ошибки паддинга дают оракула: AEAD (GCM) или HMAC поверх шифротекста"], v,
                         ["IV — открытый параметр и секретом не является: его и так передают рядом с шифротекстом, поэтому фиксированное значение ничем не опасно",
                          "Риск только в длине ключа: перейти на AES-256, и фиксированный IV перестанет быть проблемой",
                          "Хранить IV в переменной окружения вместо кода: если его никто не знает, повтор не страшен"])
    return {"scene_title": "Шифрование поля", "story": f"В ревью — PR с шифрованием поля «{field}» в базе.",
            "prompt": "Чем это опасно и как исправить?", "panel": {"type": "code", "lang": "python", "lines": lines}, "options": opts, "key": key}


@family("sec_crypto_token_entropy", "Security", "Криптография", "mark", 2.2, -1.0)
def _(rng):
    what = rng.choice(["reset", "invite", "verify"])
    v = _variant(rng, 3)
    lines = [f"def make_{what}_token(user) -> str:"]
    if v == 0:
        if rng.random() < 0.5:
            lines.append("    now = time.time()")
        lines.append("    return hashlib.md5(str(random.random()).encode()).hexdigest()")
        key = len(lines)
        story = f"Токены {what} в приложении умного дома удаётся угадать — и по ним действуют за чужих пользователей."
    elif v == 1:
        lines += ["    raw = f\"{user.id}:{int(time.time())}\"", "    return base64.urlsafe_b64encode(raw.encode()).decode()"]
        key = [len(lines) - 1, len(lines)]
        story = f"Токены {what} в приложении умного дома удаётся угадать — и по ним действуют за чужих пользователей."
    else:
        lines += ["    token = secrets.token_urlsafe(32)", "    store.save(user.id, sha256(token), ttl=900)", f'    log.info("{what} token issued", user=user.id, token=token)']
        key = len(lines)
        lines += ["    return token"]
        story = f"Токены {what} в приложении умного дома генерируются криптостойко и хранятся хешами, но ими воспользовались люди с доступом к системе сбора логов."
    return {"scene_title": "Токен по ссылке", "story": story, "prompt": "Нажмите на строку, из-за которой токен попадает в чужие руки.",
            "panel": {"type": "code", "lang": "python", "lines": lines}, "key": key}


# ---------------------------- Реагирование ----------------------------


@family("sec_ir_triage_order", "Security", "Реагирование", "choice", 2.2, 0.8)
def _(rng):
    name, sys = rng.choice([("pay", "платёжного сервиса"), ("billing", "биллинга"), ("lk", "личного кабинета")])
    host = f"{name}-{rng.randint(1, 12):02d}"
    m = rng.randint(0, 50)
    v = _variant(rng, 3)
    if v == 0:
        story = f"EDR поднял тревогу на хосте {host} {sys}: подозрительный процесс и исходящие соединения, кто-то внутри прямо сейчас."
        lines = [_log(f"03:{m:02d}:10", "edr", "ALERT", f"suspicious process on host {host}, outbound to {_ip(rng)}:443"),
                 _log(f"03:{m:02d}:12", "edr", "INFO", f"active sessions: {rng.randint(2, 5)}; persistence via {rng.choice(['cron', 'systemd unit', 'ssh authorized_keys'])} suspected")]
    elif v == 1:
        ticket = f"CHG-{rng.randint(1000, 9999)}"
        story = f"EDR поднял тревогу на хосте {host} {sys}: удалённый запуск административной утилиты от имени админа."
        lines = [_log(f"03:{m:02d}:10", "edr", "ALERT", f"remote service execution on {host} by admin.{name} (PsExec-like)"),
                 _log(f"03:{m:02d}:11", "itsm", "INFO", f"{ticket}: плановое обновление агента на {host}, окно 03:00–04:00, исполнитель admin.{name}"),
                 _log(f"03:{m:02d}:15", "edr", "INFO", f"{host}: other indicators — none")]
    else:
        n = rng.randint(30, 80)
        story = f"Сотрудникам {sys} пришло письмо «Обновите пароль»; трое уже перешли по ссылке."
        lines = [_log(f"09:{m:02d}:10", "mail-gw", "WARN", f"{n} писем от it-support@{rng.choice(['corp-helpdesk', 'it-portal', 'sso-update'])}.example, ссылка на форму входа"),
                 _log(f"09:{m:02d}:40", "proxy", "INFO", "3 сотрудника открыли ссылку, 1 отправил форму")]
    opts, key = _options(rng, ["Изолировать хост сетевыми правилами, не выключая: снять память и логи, затем искать закрепление",
                               "Сверить с заявкой на изменение и исполнителем: если работы согласованы — закрыть как легитимные, правило уточнить",
                               "Удалить письмо из всех ящиков, заблокировать домен отправителя, сбросить пароль отправившему форму"], v,
                         ["Сразу выключить хост: процесс остановится, а образ диска можно снять потом спокойно",
                          "Переустановить ОС из эталонного образа и вернуть хост в строй — так быстрее всего",
                          "Сменить пароли администраторов и пока наблюдать за хостом, чтобы понять, что нужно атакующему и кто он"])
    return {"scene_title": "Тревога", "story": story, "prompt": "Какой первый шаг верен?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("sec_ir_log_gap", "Security", "Реагирование", "choice", 2.2, -1.3)
def _(rng):
    svc = rng.choice(["auth", "gateway", "admin"])
    sink = rng.choice(["siem-collector", "audit-kafka", "log-shipper"])
    h, m0, dur = rng.randint(0, 2), rng.randint(5, 40), rng.randint(40, 110)
    end = h * 60 + m0 + dur
    a, b = f"{h:02d}:{m0:02d}", f"{end // 60:02d}:{end % 60:02d}"
    buf = rng.choice([5000, 10000, 20000])
    v = _variant(rng, 3)
    if v == 0:
        small = rng.choice([500, 1000, 2000])
        lines = [_log(f"{a}:00", svc, "INFO", "audit log rotated"),
                 _log(f"{a}:01", svc, "WARN", f"{sink} unreachable, buffering (buffer size {small} events)"),
                 _log(f"{a}:09", svc, "WARN", "buffer full, dropping events"),
                 _log(f"{b}:10", svc, "INFO", f"{sink} restored, {small} events flushed, {rng.randint(20000, 90000)} dropped")]
    elif v == 1:
        lines = [_log(f"{a}:00", svc, "INFO", "audit log rotated"),
                 _log(f"{a}:01", "chronyd", "WARN", f"system clock stepped by +{dur * 60}.0 s"),
                 _log(f"{b}:02", svc, "INFO", f"{sink} ok, events in order, no drops")]
    else:
        lines = [_log(f"{a}:00", svc, "INFO", "audit log rotated"),
                 _log(f"{a}:01", svc, "WARN", f"{sink} unreachable, buffering (buffer size {buf} events)"),
                 _log(f"{b}:10", svc, "INFO", f"{sink} restored, {rng.randint(800, buf // 3)} events flushed, 0 dropped")]
    opts, key = _options(rng, [f"Это пробел: события за {a}–{b} потеряны, искать следы в других источниках",
                               "Это скачок часов сервера: события есть, но записаны с другой временной меткой",
                               "Пробела нет: буфер сохранил события и отправил их после восстановления"], v,
                         ["Пробел не важен: раз событий в журнале нет, в это время в системе ничего не происходило"])
    return {"scene_title": "Дыра в логах", "story": f"Восстанавливаете хронологию инцидента в облаке умного дома: в аудит-логе {svc} разрыв по времени.",
            "prompt": "Как это трактовать?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("sec_ir_disclosure", "Security", "Реагирование", "choice", 2.0, 1.8)
def _(rng):
    what = rng.choice(["ФИО и телефоны клиентов", "почты и хэши паролей", "паспортные данные части клиентов", "адреса доставки и телефоны"])
    n = rng.randint(3, 90)
    when = rng.choice(["в пятницу в 23:40", "в понедельник в 09:15", "в субботу в 02:30"])
    v = _variant(rng, 3)
    story = [f"{when.capitalize()} подтвердилось, что наружу ушли {what} — около {n} тыс. записей.",
             "Клиент прислал запрос: какие его персональные данные компания обрабатывает, зачем и кому передаёт.",
             "Клиент отозвал согласие на обработку персональных данных; других оснований хранить его данные у компании нет."][v]
    opts, key = _options(rng, ["Уведомить Роскомнадзор об инциденте в течение 24 часов, о результатах расследования — в течение 72 часов",
                               "Ответить субъекту в течение 10 рабочих дней; срок можно продлить ещё на 5, сообщив ему причину",
                               "Прекратить обработку и уничтожить данные в течение 30 дней с даты отзыва"], v,
                         ["Уведомить регулятора в течение 72 часов с момента обнаружения, как требует GDPR, а итоги расследования — в течение месяца",
                          "Уведомлять регулятора не нужно, если утёкшие данные были зашифрованы или захешированы",
                          "Сначала завершить расследование, а затем один раз уведомить регулятора в течение 10 рабочих дней"])
    return {"scene_title": "152-ФЗ", "story": f"{story} Компания — оператор ПДн по 152-ФЗ.",
            "prompt": "Что и в какие сроки требует закон?", "panel": None, "options": opts, "key": key}


# ---------------------------- Реверс ----------------------------


@family("sec_rev_hardcoded", "Security", "Реверс", "choice", 2.2, 0.6)
def _(rng):
    app = rng.choice(["мобильного клиента", "десктоп-агента", "CLI-утилиты"])
    host = rng.choice(["api.example.com", "files.example.net", "sync.example.org"])
    v = _variant(rng, 3)
    if v == 0:
        secret = rng.choice(["AKIA................ (похоже на ключ облачного хранилища)", "sk_live_............ (ключ платёжного шлюза)",
                             "ghp_................ (токен репозитория)"])
        lines = [_log("—", "strings", "INFO", host), _log("—", "strings", "INFO", secret), _log("—", "strings", "INFO", "Bearer eyJhbGciOi... (встроенный токен)")]
    elif v == 1:
        lines = [_log("—", "strings", "INFO", host), _log("—", "strings", "INFO", f"sha256/{rng.choice(['Xq3', 'k9P', 'Lm2'])}…= (pin для {host})"),
                 _log("—", "strings", "INFO", "-----BEGIN PUBLIC KEY----- … (рядом с кодом проверки сертификата)")]
    else:
        lines = [_log("—", "strings", "INFO", "http://192.168.1.1:8080/admin (встроенная веб-панель устройства)"),
                 _log("—", "strings", "INFO", "admin / admin (учётные данные по умолчанию, одинаковые во всех сборках)")]
    opts, key = _options(rng, ["Считать секреты скомпрометированными: отозвать, перевыпустить и не класть их в сборку",
                               "Это открытый ключ для проверки сертификата (пиннинг): он не секрет, отзывать нечего",
                               "Убрать общий пароль по умолчанию: уникальный на устройство или смена при первом входе"], v,
                         ["Обфусцировать строки в сборке: без открытых строк ключи статическим анализом уже не достать",
                          "Перенести ключи из кода в файл ресурсов приложения — strings их там не увидит",
                          "Риска нет: бинарник подписан издателем"])
    return {"scene_title": "Строки из бинарника", "story": f"Прогнали strings по релизной сборке {app} для умного дома. Вот что нашлось.",
            "prompt": "Что это значит и что делать?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("sec_rev_client_check", "Security", "Реверс", "choice", 2.1, 1.1)
def _(rng):
    what, lang, code = rng.choice([
        ("лимит переводов", "javascript", ["if (user.isPremium && amount <= user.limit) {", "  sendTransfer(amount);", "}"]),
        ("признак премиума", "kotlin", ["if (prefs.getBoolean(\"premium\", false)) {", "    api.downloadReport(id)", "}"]),
        ("право на скидку", "swift", ["if user.discountAllowed {", "    order.total *= 0.8", "}", "api.submit(order)"]),
    ])
    v = _variant(rng, 3)
    if v == 0:
        lines, story = code, f"Нашли, что {what} проверяется только в коде клиента; подменив его, удаётся обойти ограничение."
    elif v == 1:
        lang, lines = "kotlin", ["object TrustAll : X509TrustManager {", "    override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) {}",
                                 "    override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) {}",
                                 "    override fun getAcceptedIssuers() = arrayOf<X509Certificate>()", "}"]
        story = "В публичной Wi-Fi сети трафик приложения банка удаётся читать прокси с самоподписанным сертификатом."
    else:
        lang, lines = "kotlin", ["webView.settings.javaScriptEnabled = true", 'webView.addJavascriptInterface(NativeApi(context), "Native")',
                                 "webView.loadUrl(intent.getStringExtra(\"url\")!!)"]
        story = "Страница, открытая по внешней ссылке во встроенном браузере приложения умного дома, вызвала нативные методы и прочитала данные пользователя."
    opts, key = _options(rng, [f"Проверку «{what}» на устройстве обходят правкой кода: сервер должен проверять это сам",
                               "Клиент доверяет любому сертификату: убрать «доверять всем» и проверять цепочку, для критичных хостов — пиннинг",
                               "Мост в нативный код доступен любой загруженной странице: в WebView только свои адреса, мост — только для них"], v,
                         ["Включить обфускацию и проверку целостности приложения: изменённый клиент просто не запустится на устройстве",
                          "Подписывать запросы ключом, вшитым в клиент: подделанный запрос сервер сразу отклонит",
                          "Хранить флаг в зашифрованном хранилище устройства, чтобы его нельзя было подменить"])
    return {"scene_title": "Разбор клиента", "story": story, "prompt": "В чём корень проблемы?", "panel": {"type": "code", "lang": lang, "lines": lines}, "options": opts, "key": key}


@family("sec_rev_debug_endpoint", "Security", "Реверс", "choice", 2.1, -1.0)
def _(rng):
    ep = rng.choice(["/__debug", "/internal/exec", "/admin/eval"])
    tool, store = rng.choice([("apk-scan", "shared prefs"), ("ipa-scan", "UserDefaults"), ("bin-scan", "config.json рядом с бинарником")])
    ver = f"{rng.randint(2, 5)}.{rng.randint(0, 19)}.{rng.randint(0, 9)}"
    v = _variant(rng, 3)
    if v == 0:
        lines = [_log("—", tool, "INFO", f"release {ver}: found reference to {ep}"), _log("—", tool, "WARN", f"flag enableDebug read from {store}")]
    elif v == 1:  # android:debuggable, adb и logcat — Android, поэтому сканер всегда apk-scan
        lines = [_log("—", "apk-scan", "WARN", f"release {ver}: android:debuggable=\"true\" in manifest"),
                 _log("—", "apk-scan", "INFO", "к процессу на обычном телефоне подключается отладчик через adb")]
    else:
        lines = [_log("—", "logcat", "DEBUG", f"release {ver}: HTTP POST /auth/refresh → 200 {{\"access_token\": \"eyJ…\", \"refresh_token\": \"rt_…\"}}"),
                 _log("—", "apk-scan", "INFO", "уровень логов в релизе: VERBOSE")]
    opts, key = _options(rng, ["Убрать отладочный путь из релизной сборки: флаг на устройстве легко включить самому",
                               "Собирать релиз с выключенным debuggable: иначе к процессу подключаются отладчиком",
                               "Убрать подробные логи из релиза и не писать токены в логи вовсе"], v,
                         ["Переименовать путь во что-то неочевидное: не зная имени, его никто не вызовет",
                          "Закрыть проверкой заголовка User-Agent: запросы примет, только если он как у официального приложения",
                          "Оставить как есть: пользователи об этом не знают"])
    return {"scene_title": "Отладка в релизе", "story": f"Сканер прошёлся по релизной сборке {ver} приложения умного дома и нашёл остатки отладки.",
            "prompt": "Как правильно поступить?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# ---------------------------- уровень Lead ----------------------------
# сложнее H-полосы: защита формально есть, но обходится в деталях, или нужен выбор архитектуры с компромиссами


@family("sec_rv_refresh_race", "Security", "Ревью кода", "mark", 2.3, 2.4)
def _(rng):
    tbl, fn = rng.choice([("refresh_tokens", "rotate_refresh"), ("sessions", "renew_session"), ("device_tokens", "refresh_device")])
    v = _variant(rng, 3)
    lines = [f"async def {fn}(token: str) -> TokenPair:", "    h = sha256(token)"]
    if rng.random() < 0.5:
        lines.append(f'    metrics.inc("{fn}")')
    if v == 0:
        lines.append(f'    row = await db.fetchrow("SELECT user_id, revoked FROM {tbl} WHERE token_hash = $1", h)')
        key = [len(lines), len(lines) + 5]
        lines += ['    if row is None or row["revoked"]:', "        await revoke_family(h)  # повторное использование — отзываем всю цепочку",
                  "        raise Unauthorized()", '    pair = await issue_pair(row["user_id"])',
                  f'    await db.execute("UPDATE {tbl} SET revoked = true WHERE token_hash = $1", h)', "    return pair"]
        story = (f"Приложение умного дома держит сессии на refresh-токенах. Ротация с обнаружением повторного использования: старый токен отзывается при обмене. "
                 f"В логах — {rng.randint(2, 4)} новые пары по одному старому токену за одну миллисекунду, а цепочка не отозвана.")
        prompt = "Нажмите на строку, которую нужно переписать, чтобы проверка и отзыв токена стали одной атомарной операцией."
    else:
        lines += ["    row = await db.fetchrow(", f'        "UPDATE {tbl} SET revoked = true WHERE token_hash = $1 AND NOT revoked RETURNING user_id, family_id", h)',
                  "    if row is None:"]
        if v == 1:
            lines.append("        raise Unauthorized()")
            key = len(lines)
            lines += ['    pair = await issue_pair(row["user_id"])']
            story = "Ротация атомарная. Но когда украденный refresh-токен успели обменять раньше владельца, владелец получает 401, а пара злоумышленника продолжает жить."
            prompt = "Нажмите на строку, где теряется обнаружение повторного использования токена."
        else:
            lines += ['        await revoke_family(h)  # повторное использование — отзываем всю цепочку', "        raise Unauthorized()",
                      '    pair = await issue_pair(row["user_id"])']
            key = len(lines)
            story = "Ротация атомарная, повторное использование отзывает цепочку. Но по политике сессия живёт не дольше 30 дней с входа, а у активных пользователей — месяцами."
            prompt = "Нажмите на строку, из-за которой сессия продлевается бесконечно."
        lines += ["    return pair"]
    return {"scene_title": "Ротация токенов", "story": story, "prompt": prompt,
            "panel": {"type": "code", "lang": "python", "lines": lines, "caption": f"PR #{rng.randint(400, 899)} · «{fn}»"}, "key": key}


@family("sec_crypto_jku_trust", "Security", "Криптография", "mark", 2.3, 2.6)
def _(rng):
    fn, aud = rng.choice([("verify_partner_token", "partner-api"), ("verify_sso", "lk"), ("verify_service_token", "billing")])
    v = _variant(rng, 3)
    lines = [f"async def {fn}(token: str) -> dict:", "    header = jwt.get_unverified_header(token)"]
    if rng.random() < 0.5:
        lines += ['    if header.get("alg") != "RS256":', "        raise Unauthorized()"]
    if v == 0:
        lines.append('    jwks = await jwks_cache.get(header["jku"])  # кэш на 10 минут')
        key = len(lines)
        lines += ['    signing_key = jwks.find(header["kid"])', f'    return jwt.decode(token, signing_key, algorithms=["RS256"], audience="{aud}")']
        story = f"{fn} проверяет подпись RS256, алгоритм зафиксирован, aud сверяется. Аудит нашёл токены, подписанные ключом, которого нет у нашего IdP, — и они проходят проверку."
    elif v == 1:
        lines += ["    jwks = await jwks_cache.get(IDP_JWKS_URL)  # кэш на 10 минут", '    signing_key = jwks.find(header["kid"])',
                  '    return jwt.decode(token, signing_key, algorithms=["RS256"])']
        key = len(lines)
        story = f"{fn} проверяет подпись ключом нашего IdP. Аудит показал, что токен, который IdP выдал мобильному приложению партнёра, принимается и нашим API."
    else:
        # подпись проверяется у access-токена, а роли читаются из соседнего id_token без проверки (тот же token подделать нельзя: decode упадёт)
        lines[0] = f"async def {fn}(token: str, id_token: str) -> dict:"
        lines += ["    jwks = await jwks_cache.get(IDP_JWKS_URL)  # кэш на 10 минут", '    signing_key = jwks.find(header["kid"])',
                  f'    jwt.decode(token, signing_key, algorithms=["RS256"], audience="{aud}")',
                  '    claims = json.loads(b64url_decode(id_token.split(".")[1]))']
        key = len(lines)
        lines += ["    return claims"]
        story = (f"{fn} проверяет подпись ключом нашего IdP и аудиторию. Аудит прислал настоящий токен, а рядом — id_token "
                 "с исправленной вручную ролью, и роль применилась.")
    return {"scene_title": "Чей это токен", "story": story, "prompt": "Нажмите на строку, из-за которой проходит токен, который не должен проходить.",
            "panel": {"type": "code", "lang": "python", "lines": lines, "caption": f"PR #{rng.randint(400, 899)} · «{fn}: ротация ключей IdP»"}, "key": key}


@family("sec_ir_supply_chain", "Security", "Реагирование", "choice", 2.4, 2.75)
def _(rng):
    pkg, ver = rng.choice([("left-padder", "3.1.4"), ("fast-yaml-x", "2.0.9"), ("color-logz", "1.7.2")])
    runner, m = f"ci-runner-{rng.randint(1, 9)}", rng.randint(10, 50)
    secret = rng.choice(["NPM_TOKEN", "DEPLOY_KEY", "REGISTRY_PASSWORD"])
    v = _variant(rng, 3)
    if v == 0:
        story = f"В ночной сборке приложения умного дома на {runner} транзитивная зависимость {pkg} обновилась до {ver}. Через час в реестр зашли с нового адреса."
        prompt = "Что делать в первую очередь?"
        lines = [_log(f"04:{m:02d}:01", runner, "INFO", f"npm ci: added {pkg}@{ver} (transitive, via build tooling)"),
                 _log(f"04:{m:02d}:07", runner, "WARN", f"postinstall {pkg}: outbound https to {_ip(rng)}"),
                 _log(f"04:{m:02d}:09", "egress-proxy", "INFO", f"{runner} POST {rng.randint(2, 9)}.4 KB to {rng.choice(['cdn-sync', 'pkg-mirror', 'stats-hub'])}.example"),
                 _log(f"05:{m:02d}:40", "registry", "WARN", f"login with {secret} from {_ip(rng)} (new ASN)")]
    elif v == 1:
        story = f"Инцидент разобран и секреты перевыпущены: сборка на {runner} взяла из публичного реестра пакет с именем нашего внутреннего."
        prompt = "Какая мера закрывает этот путь атаки?"
        lines = [_log(f"04:{m:02d}:01", runner, "INFO", f"npm install: @corp/{pkg}@99.0.{rng.randint(1, 9)} from registry.npmjs.org (internal registry has 2.{rng.randint(1, 9)}.0)"),
                 _log(f"04:{m:02d}:03", runner, "WARN", f"package.json: \"@corp/{pkg}\": \"^2.1.0\" — lock-файл в сборке не используется")]
    else:
        story = f"Инцидент разобран и секреты перевыпущены: в сборку на {runner} попал чужой код через сторонний GitHub Action."
        prompt = "Какая мера закрывает этот путь атаки?"
        lines = [_log(f"04:{m:02d}:01", runner, "INFO", f"uses: tools-org/setup-{pkg}@v3"),
                 _log(f"04:{m:02d}:01", "github", "WARN", f"tag v3 of tools-org/setup-{pkg} moved to a new commit {rng.randint(10**6, 10**7 - 1):x} yesterday"),
                 _log(f"04:{m:02d}:05", runner, "WARN", f"step setup-{pkg}: env dump sent to {_ip(rng)}")]
    opts, key = _options(rng, ["Считать утёкшими все секреты этих сборок: отозвать и перевыпустить их, заморозить релизы, проверить артефакты с момента появления версии",
                               "Привязать внутренний скоуп только к своему реестру (scope → registry) и собирать строго по lock-файлу",
                               "Закреплять сторонние actions по SHA коммита, а не по тегу, и обновлять их через ревью"], v,
                         [f"Откатить {pkg} в lock-файле и пересобрать: вредоносный postinstall уйдёт, а раннер эфемерный — секреты живут на нём только на время сборки и после неё недоступны",
                          f"Отозвать {secret}, замеченный во входе в реестр, и закрыть раннеру исходящий доступ к этому адресу — остальное не трогать",
                          f"Удалить {pkg}@{ver} из зеркала пакетов и включить npm ci --ignore-scripts"])
    return {"scene_title": "Цепочка поставок", "story": story, "prompt": prompt, "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("sec_web_tenant_authz", "Security", "Веб-уязвимости", "choice", 2.3, 2.9)
def _(rng):
    svcs = rng.sample(["invoices", "reports", "contracts", "exports", "tickets", "files"], 3)
    n, direct = rng.randint(4, 9), rng.randint(7, 15)
    v = _variant(rng, 3)
    if v == 0:
        lines = [_log(f"{i + 1:02d}.0{rng.randint(1, 9)}", "bug-bounty", "WARN", f"IDOR в {s}: объект другого клиента по id, исправлено точечно") for i, s in enumerate(svcs)]
        lines.append(_log("сводка", "appsec", "INFO", f"за полгода {n} похожих отчётов; сервисов с прямым доступом к общей БД: {direct}"))
        story = f"Мультитенантный SaaS для управляющих компаний умных домов: каждый сервис сам проверяет владельца объекта. IDOR находят снова и снова — это уже {n}-й отчёт."
    elif v == 1:
        lines = [_log(f"{i + 1:02d}.0{rng.randint(1, 9)}", "bug-bounty", "WARN", f"{s}: файл другого клиента скачан по прямой ссылке /files/<id>") for i, s in enumerate(svcs)]
        lines.append(_log("сводка", "appsec", "INFO", f"за полгода {n} похожих отчётов; файлы всех сервисов отдаются из общего бакета по id без проверки прав"))
        story = f"Мультитенантный SaaS для управляющих компаний умных домов: API проверяет клиента, но к чужим файлам добираются снова и снова — это уже {n}-й отчёт."
    else:
        lines = [_log(f"{i + 1:02d}.0{rng.randint(1, 9)}", "bug-bounty", "WARN", f"GraphQL: {s} → вложенное поле отдаёт записи другого клиента") for i, s in enumerate(svcs)]
        # слой данных и RLS уже есть — иначе ответ варианта 0 закрывал бы и этот случай; дыра в кэше загрузчика, до БД запрос не доходит
        lines.append(_log("сводка", "appsec", "INFO", f"за полгода {n} похожих отчётов; утечки только во вложенных полях под нагрузкой; "
                                                      "DataLoader один на процесс, кэш по id общий для всех запросов и клиентов"))
        story = (f"Мультитенантный SaaS для управляющих компаний умных домов на GraphQL: фильтр tenant_id в слое данных и row-level security в БД уже есть, "
                 f"но чужие данные находят снова и снова — это уже {n}-й отчёт.")
    opts, key = _options(rng, ["Фильтр tenant_id из сессии — в общем слое доступа к данным, row-level security в БД вторым рубежом и тест «чужой клиент → отказ» на каждый эндпоинт",
                               "Закрыть бакет и отдавать файлы по короткоживущим подписанным ссылкам, которые выдаются только после проверки прав",
                               "Создавать загрузчик данных на каждый запрос, чтобы его кэш не переживал запрос и не смешивал объекты разных клиентов"], v,
                         ["Перейти с последовательных id на случайные UUID во всех сервисах и общей БД: подобрать идентификатор чужого объекта станет практически невозможно, а код проверок трогать не придётся",
                          "Проверять клиента в API-шлюзе: шлюз сверяет X-Tenant-Id с токеном и не пускает чужие запросы дальше",
                          "Закрепить точечные исправления: пункт про проверку владельца в чек-листе ревью и правило WAF на перебор id подряд"])
    return {"scene_title": "Снова чужие данные", "story": story,
            "prompt": "Какое решение закрывает класс уязвимостей, а не очередной случай?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}
