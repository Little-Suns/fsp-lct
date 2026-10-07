"""Mobile, сюжет «Релиз в сторах»: сценарные семейства с логами, графиками и кодом (Swift, Kotlin, Dart).
По три семейства на компетенцию сверх простого шаблона из items.py; b — по полосам сложности."""

from app.services.items import _choice, _log, family


def _ver(rng) -> str:
    return f"{rng.randint(3, 6)}.{rng.randint(0, 19)}.{rng.randint(0, 4)}"


def _ts(rng, h: int):
    m = rng.randint(0, 40)
    return lambda dm, s: f"{h:02d}:{m + dm:02d}:{s:02d}"


# --- Отладка ---


@family("mob_dbg_iboutlet", "Mobile", "Отладка", "choice", 2.2, -0.3)
def _(rng):
    vc, outlet = rng.choice([("CheckoutViewController", "payButton"), ("ProfileViewController", "avatarView"), ("OrderViewController", "statusLabel")])
    ver, t = _ver(rng), _ts(rng, 10)
    lines = [
        _log(t(0, 5), "git", "INFO", "refactor: rename outlets in Main.storyboard"),
        _log(t(1, 12), "xcodebuild", "INFO", f"Archive {ver} ({rng.randint(400, 900)}) succeeded"),
        _log(t(9, 47), "app", "INFO", f"{vc}.viewDidLoad()"),
        _log(t(9, 47), "app", "ERROR", f"Fatal error: Unexpectedly found nil while implicitly unwrapping an Optional value\n  {vc}.swift:{rng.randint(30, 90)}  {outlet}.isHidden = false"),
        _log(t(9, 47), "crash", "ERROR", "EXC_BREAKPOINT (SIGTRAP), Thread 0 Crashed: com.apple.main-thread"),
    ]
    opts, key = _choice(rng, f"После переименования связь @IBOutlet {outlet} со storyboard потеряна, outlet остался nil", [
        "Экран создаётся не на главном потоке, и UIKit падает на первом обращении к view",
        f"Системе не хватило памяти: в сборке {ver} экран тяжелее, и его view выгружается ещё до вызова viewDidLoad",
        "Сборка подписана неверным профилем, поэтому приложение падает при открытии экранов",
    ])
    return {"scene_title": "Краш на открытии", "story": f"Сборка {ver} для TestFlight. Тестировщик открывает экран — приложение сразу падает. Перед сборкой был небольшой рефакторинг.",
            "prompt": "В чём причина?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("mob_dbg_r8_reflection", "Mobile", "Отладка", "choice", 2.3, 1.1)
def _(rng):
    dto, field, screen = rng.choice([("OrderDto", "deliveryAddress", "Заказ"), ("ProfileDto", "displayName", "Профиль"), ("TariffDto", "monthlyPrice", "Тарифы")])
    ver, t = _ver(rng), _ts(rng, 11)
    lines = [
        _log(t(0, 2), "ci", "INFO", f"assembleRelease {ver}: isMinifyEnabled=true (R8)"),
        _log(t(4, 30), "qa", "INFO", f"debug {ver}: {dto}({field}=\"…\") — экран «{screen}» OK"),
        _log(t(6, 11), "app", "WARN", f"release {ver}: parsed {dto}(a=null, b=null, c=0)"),
        _log(t(6, 11), "AndroidRuntime", "ERROR", f"java.lang.NullPointerException: Parameter specified as non-null is null: method {screen.lower()}Binder.bind, parameter {field}"),
    ]
    opts, key = _choice(rng, "R8 переименовал поля DTO, а Gson ищет поля по именам через рефлексию: нужны @SerializedName или keep-правила", [
        "Release-сборка ходит на другой стенд, и он отдаёт другой JSON: сверить BASE_URL release-конфигурации и контракт API с бэкендом",
        "В release-сборке отключено логирование, поэтому значения полей в логах выглядят пустыми",
        "Kotlin data class в release-сборке не поддерживает null: поля нужно сделать var",
    ])
    return {"scene_title": "Только в релизе", "story": f"Release-сборка {ver}: экран «{screen}» пустой и падает. Debug-сборка с тем же сервером и тем же аккаунтом работает.",
            "prompt": "Что вероятнее всего?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("mob_dbg_tx_too_large", "Mobile", "Отладка", "choice", 2.3, 1.9)
def _(rng):
    screen = rng.choice(["CatalogActivity", "GalleryActivity", "ChatActivity"])
    n, size, t = rng.randint(800, 3000), rng.randint(1_050_000, 1_900_000), _ts(rng, 14)
    lines = [
        _log(t(0, 3), "ActivityTaskManager", "INFO", f"Displayed ru.demo.app/.{screen}"),
        _log(t(3, 40), "app", "DEBUG", f"onSaveInstanceState: putParcelableArrayList(\"items\", size={n})"),
        _log(t(3, 40), "ActivityTaskManager", "INFO", f"{screen}: paused → stopped (Home pressed)"),
        _log(t(3, 41), "AndroidRuntime", "ERROR", f"FATAL EXCEPTION: main\njava.lang.RuntimeException: android.os.TransactionTooLargeException: data parcel size {size} bytes\n"
                                                    "  at android.app.servertransaction.PendingTransactionActions$StopInfo.run"),
    ]
    opts, key = _choice(rng, f"Весь список ({n} шт.) кладётся в saved state, а Bundle через Binder ограничен ~1 МБ: сохранять id и позицию", [
        f"Утечка памяти в {screen}: адаптер держит все {n} элементов, поэтому в onStop нужно очищать адаптер и вызывать System.gc(), чтобы освободить место",
        "Процесс убивает система из-за нехватки памяти, это поведение ОС, и в коде его не исправить",
        "Приложение получило слишком большой push, и его обработка не уложилась в лимит сервиса",
    ])
    return {"scene_title": "Краш при сворачивании", "story": f"Краши приходят у тех, кто свернул приложение на экране {screen} после долгой прокрутки. На коротких списках не воспроизводится.",
            "prompt": "В чём причина и как исправить?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Жизненный цикл приложения ---


@family("mob_lc_remember", "Mobile", "Жизненный цикл приложения", "mark", 2.1, -1.1)
def _(rng):
    fn, var, init, label, op, btn = rng.choice([("QuantityPicker", "count", "1", "Количество", "count++", "Ещё"),
                                                ("TipSelector", "tip", "10", "Чаевые, %", "tip += 5", "+5 %"),
                                                ("SeatCounter", "seats", "1", "Мест", "seats++", "Добавить")])
    lines = ["@Composable", f"fun {fn}() {{"]
    if rng.random() < 0.5:
        lines.append("    val haptics = LocalHapticFeedback.current")
    lines.append(f"    var {var} by remember {{ mutableStateOf({init}) }}")
    key = len(lines)
    lines += ["    Column {", f"        Text(\"{label}: ${var}\")", f"        Button(onClick = {{ {op} }}) {{ Text(\"{btn}\") }}", "    }", "}"]
    return {"scene_title": "Поворот экрана", "story": f"Пользователь выбрал значение «{label}», повернул телефон — и значение сбросилось к {init}.",
            "prompt": "Нажмите на строку, которую нужно изменить, чтобы значение пережило поворот экрана.",
            "panel": {"type": "code", "lang": "kotlin", "lines": lines}, "key": key}


@family("mob_lc_bg_upload", "Mobile", "Жизненный цикл приложения", "choice", 2.2, 1.0)
def _(rng):
    size, n, t = rng.randint(80, 600), rng.randint(100, 999), _ts(rng, 13)
    lines = [
        _log(t(0, 4), "app", "INFO", f"upload started: video_{n}.mov ({size} MB), URLSessionConfiguration.default"),
        _log(t(0, 31), "UIApplication", "INFO", "applicationDidEnterBackground"),
        _log(t(0, 31), "app", "INFO", "beginBackgroundTask(withName: \"upload\") granted"),
        _log(t(1, 2), "UIApplication", "WARN", "Background task \"upload\" expired, ending"),
        _log(t(1, 2), "CFNetwork", "ERROR", "Task <…>.<1> finished with error [-999] cancelled"),
    ]
    opts, key = _choice(rng, "Перенести загрузку в URLSession с background-конфигурацией: файл передаёт система, результат придёт даже после выгрузки приложения", [
        "Вызывать beginBackgroundTask заново каждые 25 секунд, пока загрузка не закончится",
        "Включить фоновый режим аудио и проигрывать тишину, чтобы приложение не засыпало",
        "Увеличить timeoutIntervalForRequest до 10 минут, чтобы запрос не прерывался",
    ])
    return {"scene_title": "Загрузка в фоне", "story": f"Пользователи жалуются: видео на {size} МБ не загружается, если свернуть приложение. В логах устройства — вот что.",
            "prompt": "Как сделать правильно?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("mob_lc_fgs_push", "Mobile", "Жизненный цикл приложения", "choice", 2.3, 2.1)
def _(rng):
    svc = rng.choice(["SyncService", "TrackUploadService", "BackupService"])
    api, t = rng.choice([31, 33, 34]), _ts(rng, 3)
    lines = [
        _log(t(0, 12), "PushHandler", "INFO", "onMessageReceived: type=sync, priority=normal"),
        _log(t(0, 12), "app", "INFO", f"startForegroundService(Intent(.{svc}))"),
        _log(t(0, 12), "AndroidRuntime", "ERROR", f"FATAL EXCEPTION: main\nandroid.app.ForegroundServiceStartNotAllowedException: startForegroundService() "
                                                    f"not allowed due to mAllowStartForeground false: service ru.demo.app/.{svc}"),
        _log(t(5, 0), "crash-stats", "INFO", f"все краши — API {api}+, процесс в фоне в момент пуша"),
    ]
    opts, key = _choice(rng, "С Android 12 фоновое приложение не может запускать foreground-сервис: работу по пушу — через WorkManager (expedited), FGS — только из видимого состояния", [
        "Добавить в манифест разрешение FOREGROUND_SERVICE: без него сервис не стартует из пуша",
        "Заменить startForegroundService на startService: обычный сервис из фона запускать можно",
        "Повторять startForegroundService с паузой, пока система не разрешит запуск сервиса",
    ])
    return {"scene_title": "Синхронизация по пушу", "story": f"После обновления targetSdk пуш синхронизации роняет приложение, если оно свёрнуто. {svc} запускается прямо из обработчика пуша.",
            "prompt": "Что сделать?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("mob_lc_process_death", "Mobile", "Жизненный цикл приложения", "choice", 2.3, 2.6)
def _(rng):
    holder, field, frag, title, where = rng.choice([("SessionHolder", "session", "CheckoutFragment", "оплаты", "экран входа"),
                                                    ("CartHolder", "cart", "DeliveryFragment", "выбора доставки", "экран каталога"),
                                                    ("ProfileHolder", "profile", "EditProfileFragment", "редактирования профиля", "главный экран")])
    pid, mins, t = rng.randint(10000, 29999), rng.randint(20, 90), _ts(rng, 16)
    lines = [
        _log(t(0, 3), "app", "INFO", f"{frag} resumed; пользователь уходит в другое приложение"),
        _log(t(2, 51), "ActivityManager", "INFO", f"Killing {pid}:ru.demo.app/u0a211 (adj 905): cached #{rng.randint(12, 30)}"),
        _log(t(18, 40), "ActivityManager", "INFO", f"Start proc {pid + rng.randint(40, 900)}:ru.demo.app/u0a211 for activity ru.demo.app/.MainActivity"),
        _log(t(18, 41), "FragmentManager", "DEBUG", f"restored back stack top={frag}; SavedStateHandle keys=[orderId, step]"),
        _log(t(18, 41), "AndroidRuntime", "ERROR", f"FATAL EXCEPTION: main\nkotlin.UninitializedPropertyAccessException: lateinit property {field} has not been initialized\n"
                                                    f"  at ru.demo.app.{holder}.get{field.capitalize()}"),
        _log(t(19, 0), "qa", "INFO", f"«Don't keep activities» и поворот экрана — без падений; краши у вернувшихся через {mins}+ мин"),
    ]
    opts, key = _choice(rng, f"Процесс убит в фоне и восстановлен сразу на экране {title}: стек и SavedStateHandle вернулись, а синглтон {holder} пуст — он должен подниматься из хранилища сам", [
        f"Это эффект «Don't keep activities»: Activity пересоздаётся без ViewModel — держать {field} в ViewModel экрана {title}, а не в синглтоне",
        f"При восстановлении Activity.onCreate вызывается раньше Application.onCreate, и {holder} ещё не готов: перенести его инициализацию в ContentProvider",
        "Глубокий экран после возврата восстанавливать не нужно: поставить clearTaskOnLaunch, чтобы приложение всегда открывалось с главного",
    ])
    return {"scene_title": "Падение при возврате", "story": f"Краши с экрана {title}: пользователь надолго уходит в другое приложение, возвращается — падение. {holder} — синглтон, его заполняет {where}.",
            "prompt": "В чём причина и что исправить?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Ревью кода ---


@family("mob_rv_force_unwrap", "Mobile", "Ревью кода", "mark", 2.1, -1.4)
def _(rng):
    param, ent = rng.choice([("order", "Order"), ("promo", "Promo"), ("ticket", "Ticket")])
    lines = ["func handle(deepLink url: URL) {"]
    if rng.random() < 0.5:
        lines.append("    analytics.track(\"deeplink_opened\")")
    lines.append("    let components = URLComponents(url: url, resolvingAgainstBaseURL: false)")
    lines.append(f"    let id = components!.queryItems!.first {{ $0.name == \"{param}\" }}!.value!")
    key = len(lines)
    lines += [f"    router.open{ent}(id: id)", "}"]
    return {"scene_title": "Диплинк из рассылки", "story": f"После рассылки со ссылкой без параметра {param} пришла волна крашей при открытии приложения по ссылке.",
            "prompt": "Нажмите на строку, из-за которой приложение падает.",
            "panel": {"type": "code", "lang": "swift", "lines": lines, "caption": f"PR #{rng.randint(300, 999)} · «диплинки на {ent.lower()}»"}, "key": key}


@family("mob_rv_setstate_mounted", "Mobile", "Ревью кода", "mark", 2.2, 0.9)
def _(rng):
    page, typ, field, fn = rng.choice([("OrdersPage", "List<Order>", "orders", "fetchOrders"), ("ProfilePage", "Profile", "profile", "fetchProfile"),
                                       ("WalletPage", "Balance", "balance", "fetchBalance")])
    lines = [f"class _{page}State extends State<{page}> {{", f"  {typ}? _{field};", "", "  @override", "  void initState() {", "    super.initState();", "    _load();", "  }", ""]
    if rng.random() < 0.5:
        lines.append("  // загрузка при открытии экрана")
    lines += ["  Future<void> _load() async {", f"    final data = await api.{fn}();", f"    setState(() => _{field} = data);"]
    key = len(lines)
    lines += ["  }", "}"]
    return {"scene_title": "Ошибка после ухода", "story": f"В отчётах об ошибках: «setState() called after dispose(): _{page}State». Пользователи уходят с экрана, не дождавшись загрузки.",
            "prompt": "Нажмите на строку, которую нужно исправить.", "panel": {"type": "code", "lang": "dart", "lines": lines}, "key": [key - 1, key]}


@family("mob_rv_collect_lifecycle", "Mobile", "Ревью кода", "mark", 2.3, 2.2)
def _(rng):
    flow, v, view, call, what = rng.choice([("courierPosition", "pos", "map", "showCourier", "геолокация"),
                                            ("heartRate", "bpm", "pulseView", "render", "датчик пульса"),
                                            ("nearbyBeacons", "list", "beaconList", "submit", "сканирование Bluetooth")])
    lines = ["override fun onCreate(savedInstanceState: Bundle?) {", "    super.onCreate(savedInstanceState)", "    setContentView(binding.root)"]
    if rng.random() < 0.5:
        lines.append("    binding.toolbar.setNavigationOnClickListener { finish() }")
    lines.append("    lifecycleScope.launch {")
    key = len(lines)
    lines += [f"        viewModel.{flow}.collect {{ {v} ->", f"            binding.{view}.{call}({v})", "        }", "    }", "}"]
    return {"scene_title": "Батарея садится", "story": f"После релиза жалобы на расход батареи: {what} работает, даже когда приложение свёрнуто. Поток в ViewModel активен, пока его кто-то собирает.",
            "prompt": "Нажмите на строку с причиной.", "panel": {"type": "code", "lang": "kotlin", "lines": lines, "caption": f"PR #{rng.randint(300, 999)}"},
            "key": [key, key + 1]}


@family("mob_rv_actor_reentrancy", "Mobile", "Ревью кода", "mark", 2.3, 2.4)
def _(rng):
    actor, field, typ, call, ep = rng.choice([("SessionStore", "session", "Session", "api.refresh(session?.refreshToken)", "/auth/refresh"),
                                              ("FlagsStore", "flags", "FeatureFlags", "api.fetchFlags()", "/v1/flags"),
                                              ("ConfigStore", "config", "RemoteConfig", "api.fetchConfig()", "/v1/config")])
    lines = [f"actor {actor} {{", f"    private var {field}: {typ}?"]
    if rng.random() < 0.5:
        lines.append(f"    private let log = Logger(subsystem: \"app\", category: \"{field}\")")
    lines += ["", f"    func current() async throws -> {typ} {{", f"        if let v = {field}, !v.isExpired {{ return v }}", f"        let fresh = try await {call}"]
    key = len(lines)
    lines += [f"        {field} = fresh", "        return fresh", "    }", "}"]
    return {"scene_title": "Актор не спас", "story": f"{actor} переписали на actor, чтобы убрать гонки при старте. Но бэкенд всё равно видит по {rng.randint(3, 6)} одинаковых запроса {ep} "
                                                    "от одного устройства за секунду: экраны одновременно вызывают current().",
            "prompt": "Нажмите на строку, из-за которой актор пропускает дублирующие запросы.",
            "panel": {"type": "code", "lang": "swift", "lines": lines, "caption": f"PR #{rng.randint(300, 999)} · «{actor} → actor»"}, "key": key}


# --- Сеть и офлайн ---


@family("mob_net_offline_cache", "Mobile", "Сеть и офлайн", "choice", 2.0, -1.5)
def _(rng):
    screen = rng.choice(["ленту новостей", "список заказов", "расписание занятий"])
    place = rng.choice(["в самолёте", "в метро", "за городом без связи"])
    opts, key = _choice(rng, "Показать последние сохранённые данные из локального кэша с пометкой «нет сети» и обновить их, когда связь вернётся", [
        "Показать системную ошибку и закрыть экран: устаревшие данные без сети вреднее пустого экрана, пользователь сам вернётся, когда связь появится",
        "Увеличить таймаут запроса до пяти минут, чтобы дождаться появления сети",
        "Повторять запрос без паузы, пока он не пройдёт, и держать спиннер на экране",
    ])
    return {"scene_title": "Без связи", "story": f"Пользователь {place} открыл {screen} и видит бесконечный спиннер, хотя час назад всё загружалось.",
            "prompt": "Как должно вести себя приложение?", "panel": None, "options": opts, "key": key}


@family("mob_net_cleartext", "Mobile", "Сеть и офлайн", "choice", 2.2, 0.1)
def _(rng):
    host = rng.choice(["api.shop-demo.ru", "media.demo-cdn.ru", "pay.wallet-demo.ru"])
    ver, t = _ver(rng), _ts(rng, 9)
    if rng.random() < 0.5:
        err = _log(t(2, 15), "OkHttp", "ERROR", f"java.net.UnknownServiceException: CLEARTEXT communication to {host} not permitted by network security policy")
    else:
        err = _log(t(2, 15), "CFNetwork", "ERROR", "App Transport Security has blocked a cleartext HTTP (http://) resource load since it is insecure. "
                                                    "Use HTTPS instead or add Exception Domains to your app's Info.plist.")
    lines = [
        _log(t(0, 1), "build", "INFO", f"release {ver}: BASE_URL=http://{host}/v{rng.randint(1, 3)}"),
        _log(t(2, 14), "app", "INFO", "feed: GET /items"),
        err,
        _log(t(2, 15), "app", "WARN", "feed: request failed, showing empty state"),
    ]
    opts, key = _choice(rng, "Сборка ходит на сервер по HTTP, а система по умолчанию блокирует незашифрованный трафик: перевести BASE_URL на HTTPS", [
        "Разрешить незашифрованный трафик для всех доменов (usesCleartextTraffic / NSAllowsArbitraryLoads) — так быстрее всего вернуть работу всем",
        f"DNS на устройствах не резолвит {host}: проверить настройки сети и VPN у пользователей",
        f"Сертификат сервера {host} истёк, и приложение отвергает соединение: обновить сертификат",
    ])
    return {"scene_title": "Пустые экраны", "story": f"Release-сборка {ver} не загружает ни одного экрана, а до бэкенда запросы вообще не доходят.",
            "prompt": "В чём причина и что сделать?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("mob_net_refresh_race", "Mobile", "Сеть и офлайн", "choice", 2.4, 2.3)
def _(rng):
    eps = rng.sample(["/v1/profile", "/v1/orders", "/v1/notifications", "/v1/balance", "/v1/feed"], 3)
    r1, t = rng.randint(1000, 9999), _ts(rng, 8)
    lines = [*(_log(t(0, 2), "http", "INFO", f"GET {e} → 401 token_expired") for e in eps),
             _log(t(0, 3), "auth", "INFO", f"POST /auth/refresh (refresh=…{r1}) → 200, new pair issued"),
             _log(t(0, 3), "auth", "WARN", f"POST /auth/refresh (refresh=…{r1}) → 401 refresh_token_reused, token family revoked"),
             _log(t(0, 3), "auth", "WARN", f"POST /auth/refresh (refresh=…{r1}) → 401 refresh_token_reused"),
             _log(t(0, 4), "app", "ERROR", "session revoked → logout, open LoginScreen")]
    opts, key = _choice(rng, "Один refresh на всех: первый 401 запускает обновление, остальные запросы ждут его и повторяются с новым токеном", [
        "Увеличить срок жизни access-токена до 30 дней, чтобы обновление случалось реже и не мешало",
        "Перенести refresh-токен в Keychain или EncryptedSharedPreferences: сейчас его перезаписывает фоновый процесс, и сервер видит старое значение",
        "При первом 401 сразу разлогинивать пользователя: это безопаснее, чем повторять запросы",
    ])
    return {"scene_title": "Выкинуло на вход", "story": "Утром после релиза часть пользователей внезапно оказывается на экране входа. Сервер выдаёт одноразовые refresh-токены (ротация).",
            "prompt": "Как исправить клиент?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("mob_net_sync_conflict", "Mobile", "Сеть и офлайн", "choice", 2.4, 2.9)
def _(rng):
    what, f1, f2 = rng.choice([("заметку", "заголовок", "текст"), ("карточку задачи", "статус", "описание"), ("список покупок", "название", "позиции")])
    h, skew, doc = rng.randint(9, 16), rng.randint(16, 40), rng.randint(100, 999)

    def hm(m: int) -> str:
        return f"{m // 60:02d}:{m % 60:02d}"

    lines = [
        _log(hm(h * 60 - 10) + ":00", "tablet", "INFO", f"офлайн: изменено поле «{f2}», updatedAt={hm(h * 60 - 10 + skew)} (по часам планшета)"),
        _log(hm(h * 60 + 5) + ":12", "sync", "INFO", f"phone: PUT /docs/{doc} (весь документ, изменено «{f1}»), updatedAt={hm(h * 60 + 5)} → 200"),
        _log(hm(h * 60 + 70) + ":40", "sync", "INFO", f"tablet: PUT /docs/{doc} (весь документ), updatedAt={hm(h * 60 - 10 + skew)} → 200, newer wins"),
        _log(hm(h * 60 + 71) + ":03", "support", "WARN", f"doc {doc}: «{f1}» снова старый — правка с телефона пропала"),
        _log(hm(h * 60 + 72) + ":30", "device", "INFO", f"часы планшета спешат на {skew} мин"),
    ]
    opts, key = _choice(rng, f"Слать изменённые поля с базовой ревизией: сервер видит правку поверх старой версии и сливает «{f1}» с телефона и «{f2}» с планшета", [
        "Ставить updatedAt на сервере в момент приёма запроса: тогда спешащие часы устройств перестанут влиять на то, какая из записей победит",
        f"Поправлять время клиента по заголовку Date ответа сервера перед записью updatedAt: планшет спешит на {skew} мин, отсюда и неверный порядок",
        "Брать на сервере блокировку документа на время редактирования, чтобы второе устройство не меняло его, пока первое не закончит",
    ])
    return {"scene_title": "Пропавшая правка", "story": f"Пользователь правит одну и ту же {what} на телефоне и на планшете, планшет часть времени без сети. Синхронизация — last-write-wins по updatedAt.",
            "prompt": "Как исправить, чтобы не терялась ни одна из правок?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Производительность ---


@family("mob_perf_listview", "Mobile", "Производительность", "mark", 2.1, -0.9)
def _(rng):
    title, coll, tile = rng.choice([("Каталог", "products", "ProductCard"), ("Отзывы", "reviews", "ReviewTile"), ("Афиша", "events", "EventCard")])
    n, s = rng.choice([2000, 5000, 8000]), rng.choice([3, 4, 6])
    lines = ["@override", "Widget build(BuildContext context) {"]
    if rng.random() < 0.5:
        lines.append("  final theme = Theme.of(context);")
    lines.append("  return ListView(")
    key = len(lines)
    lines += [f"    children: {coll}.map((x) => {tile}(item: x)).toList(),", "  );", "}"]
    return {"scene_title": "Долгое открытие", "story": f"Экран «{title}» открывается {s} секунды: в списке {n} элементов, каждый — карточка с картинкой.",
            "prompt": "Нажмите на строку с причиной.", "panel": {"type": "code", "lang": "dart", "lines": lines}, "key": [key, key + 1]}


@family("mob_perf_cold_start", "Mobile", "Производительность", "choice", 2.3, 1.3)
def _(rng):
    major, minor0, rel = rng.randint(3, 6), rng.randint(10, 30), rng.randint(4, 6)
    k, d = rng.randint(2, 4), rng.randint(3, 6)
    x = [f"{major}.{minor0 + i}" for i in range(8)]
    start = [rng.randint(780, 980) if i < rel else rng.randint(2200, 2800) for i in range(8)]
    size0 = rng.randint(60, 120)
    size = [size0 + i + (d if i >= rel else 0) for i in range(8)]
    panel = {"type": "chart", "x": x, "marker": {"i": rel, "label": f"релиз {x[rel]}"}, "series": [
        {"name": "холодный старт p90, мс", "axis": "left", "max": 3000, "data": start},
        {"name": "размер приложения, МБ", "axis": "right", "max": 200, "data": size},
    ]}
    opts, key = _choice(rng, "Новые SDK инициализируются синхронно при запуске: некритичные отложить и проверить трассировкой старта", [
        "Векторные иконки: их растеризация занимает секунды при каждом холодном старте",
        f"Рост размера приложения на {d} МБ: при каждом запуске система дольше читает и проверяет пакет с диска, а код грузится целиком до первого кадра",
        "Новый онбординг: его экраны и анимации создаются при каждом холодном старте",
    ])
    return {"scene_title": "Медленный старт", "story": f"В {x[rel]}: новый онбординг (только при первом запуске), иконки в векторе и ещё {k} SDK (аналитика, A/B, чат), они инициализируются при старте приложения.",
            "prompt": "Что вероятнее всего замедлило холодный старт?", "panel": panel, "options": opts, "key": key}


@family("mob_perf_recompose", "Mobile", "Производительность", "choice", 2.3, 1.8)
def _(rng):
    screen, typ = rng.choice([("Акции", "PromoItem"), ("Товары дня", "Product"), ("Подборки", "Collection")])
    m = rng.randint(2, 3)
    x = [f"{2 * i} с" for i in range(8)]
    rec = [rng.randint(30, 60) if i < m else rng.randint(1800, 2400) for i in range(8)]
    jank = [rng.randint(1, 4) if i < m else rng.randint(25, 40) for i in range(8)]
    panel = {"type": "chart", "x": x, "marker": {"i": m, "label": "запущен таймер"}, "series": [
        {"name": "рекомпозиций строк в секунду", "axis": "left", "max": 2500, "data": rec},
        {"name": "кадров дольше 16 мс, %", "axis": "right", "max": 50, "data": jank},
    ]}
    opts, key = _choice(rng, f"Параметр строки нестабилен для Compose (List и {typ} из модуля без компилятора Compose): сделать UI-модель @Immutable и задать key у items", [
        "Таймер тикает слишком часто: если обновлять его раз в пять секунд, лента перестанет дёргаться",
        "Картинки строк декодируются на главном потоке: перевести их загрузку в фоновый поток",
        "LazyColumn не подходит для длинных лент: заменить его на Column с verticalScroll",
    ])
    return {"scene_title": "Таймер акции", "story": f"После таймера акции в шапке лента «{screen}» дёргается. Layout Inspector: строки перерисовываются на каждый тик, хотя их данные не менялись. Строки получают List<{typ}> из модуля domain.",
            "prompt": "В чём причина?", "panel": panel, "options": opts, "key": key}


@family("mob_perf_prefs_anr", "Mobile", "Производительность", "choice", 2.3, 2.75)
def _(rng):
    screen = rng.choice(["FeedActivity", "CatalogActivity", "ChatListActivity"])
    ver, kb, share, t = _ver(rng), rng.randint(300, 900), rng.randint(85, 96), _ts(rng, 19)
    lines = [
        _log(t(0, 1), "release", "INFO", f"{ver}: кэш списка (≈{kb} КБ JSON) сохраняется в SharedPreferences через apply() при каждой остановке прокрутки"),
        _log(t(3, 12), "ActivityManager", "ERROR", f"ANR in ru.demo.app (ru.demo.app/.{screen})\nReason: Input dispatching timed out (5000 ms)"),
        _log(t(3, 12), "traces", "INFO", "\"main\" prio=5 WAITING\n  at java.util.concurrent.CountDownLatch.await\n  at android.app.SharedPreferencesImpl$EditorImpl$1.run\n"
                                         "  at android.app.QueuedWork.waitToFinish\n  at android.app.ActivityThread.handleStopActivity"),
        _log(t(5, 0), "anr-stats", "INFO", f"{share}% ANR — бюджетные устройства с eMMC; StrictMode: commit() и чтений файлов на главном потоке нет"),
    ]
    opts, key = _choice(rng, "apply() пишет в фоне, но при onStop ActivityThread ждёт незаконченные записи: большой кэш вынести из prefs в файл или БД и писать реже", [
        "Где-то в коде остался синхронный commit(): найти запись в prefs на главном потоке и заменить её на apply()",
        f"Разбор JSON на {kb} КБ при возврате на {screen} нагружает главный поток: перенести парсинг кэша в Dispatchers.Default, а на экране показывать заглушку",
        "Бюджетным устройствам не хватает памяти, и сборка мусора на каждом кадре прокрутки даёт ANR: снизить аллокации",
    ])
    return {"scene_title": "ANR при сворачивании", "story": f"После {ver} ANR выросли втрое: зависание на секунды, когда пользователь сворачивает {screen}. На флагманах почти не воспроизводится.",
            "prompt": "В чём причина и что сделать?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Алгоритмы ---


@family("mob_alg_dedup", "Mobile", "Алгоритмы", "choice", 2.1, -1.6)
def _(rng):
    field, by = rng.choice([("phone", "номеру"), ("email", "почте")])
    n = rng.choice([5, 10, 20])
    lines = ["fun dedupe(contacts: List<Contact>): List<Contact> {", "    val result = mutableListOf<Contact>()", "    for (c in contacts) {",
             f"        if (result.none {{ it.{field} == c.{field} }}) result.add(c)", "    }", "    return result", "}"]
    opts, key = _choice(rng, f"Запоминать уже встреченные значения {field} в HashSet: проверка за O(1), всего O(n)", [
        "Сортировать result после каждого добавления, чтобы поиск шёл быстрее",
        "Заменить mutableListOf на ArrayList с заранее заданной ёмкостью",
        "Запустить функцию в Dispatchers.Default: на фоновом потоке перебор не мешает интерфейсу, и сам импорт пройдёт быстрее",
    ])
    return {"scene_title": "Импорт контактов", "story": f"Импорт {n} тыс. контактов из телефонной книги «висит» минуту: дубли по {by} убираются функцией ниже.",
            "prompt": "Как ускорить?", "panel": {"type": "code", "lang": "kotlin", "lines": lines}, "options": opts, "key": key}


@family("mob_alg_binsearch", "Mobile", "Алгоритмы", "mark", 2.2, 0.4)
def _(rng):
    fn, arr, thing = rng.choice([("insertIndex", "times", "сообщение в чате"), ("slotAfter", "starts", "слот доставки"), ("placeEvent", "moments", "событие в ленте")])
    lines = [f"fun {fn}({arr}: List<Long>, t: Long): Int {{"]
    if rng.random() < 0.5:
        lines.append("    require(t >= 0)")
    lines += ["    var lo = 0", f"    var hi = {arr}.size - 1"]
    key = len(lines)
    lines += ["    while (lo < hi) {", "        val mid = (lo + hi) ushr 1", f"        if ({arr}[mid] <= t) lo = mid + 1 else hi = mid", "    }", "    return lo", "}"]
    return {"scene_title": "Не на своём месте", "story": f"Функция ищет, куда вставить {thing} со временем t в отсортированный список: после всех, у кого время ≤ t. Если t позже всех, элемент почему-то встаёт перед последним, а не в конец.",
            "prompt": "Нажмите на строку с ошибкой.", "panel": {"type": "code", "lang": "kotlin", "lines": lines}, "key": key}


@family("mob_alg_lru", "Mobile", "Алгоритмы", "choice", 2.0, 0.8)
def _(rng):
    mb, what = rng.choice([32, 64, 128]), rng.choice(["миниатюр каталога", "обложек плейлистов", "аватаров в чате"])
    opts, key = _choice(rng, "Хеш-таблица плюс двусвязный список по порядку доступа (LRU): get и put за O(1)", [
        "Список, отсортированный по времени доступа, который пересортировывается при каждом get",
        "Очередь FIFO по времени добавления: при переполнении удалять самое давно добавленное",
        "Хеш-таблица без порядка: при переполнении удалять случайный ключ, это O(1)",
    ])
    return {"scene_title": "Кэш картинок", "story": f"Кэш {what} ограничен {mb} МБ. При переполнении нужно выкидывать то, что дольше всех не показывали; get и put вызываются на каждом кадре прокрутки.",
            "prompt": "Какую структуру выбрать?", "panel": None, "options": opts, "key": key}
