"""Mobile, сюжет «Релиз на прогулке» (приложение для собачников): сценарные семейства с логами, графиками и кодом (Swift, Kotlin, Dart).
По три семейства на компетенцию сверх простого шаблона из items.py; b — по полосам сложности.
У каждого семейства три варианта механики (items._variant), правильные ответы других вариантов — среди дистракторов."""

from app.services.items import _log, _options, _variant, family


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
    line = rng.randint(30, 90)
    v = _variant(rng, 3)
    if v == 0:
        mid = [_log(t(0, 5), "git", "INFO", "refactor: rename outlets in Main.storyboard"), _log(t(9, 47), "app", "INFO", f"{vc}.viewDidLoad()"),
               _log(t(9, 47), "app", "ERROR", f"Fatal error: Unexpectedly found nil while implicitly unwrapping an Optional value\n  {vc}.swift:{line}  {outlet}.isHidden = false")]
        story = "Тестировщик открывает экран — приложение сразу падает. Перед сборкой был небольшой рефакторинг."
    elif v == 1:
        mid = [_log(t(9, 40), "app", "INFO", f"{vc}: pull-to-refresh → items.removeAll(), загрузка в фоне"),
               _log(t(9, 41), "app", "ERROR", f"Fatal error: Index out of range\n  {vc}.swift:{line}  tableView(_:cellForRowAt:) → items[indexPath.row]")]
        story = "Тестировщик тянет список вниз, чтобы обновить, и одновременно прокручивает — приложение падает."
    else:
        mid = [_log(t(9, 46), "app", "ERROR", "SecItemCopyMatching failed: -34018 (errSecMissingEntitlement), keychain-access-groups"),
               _log(t(9, 47), "app", "ERROR", f"Fatal error: Unexpectedly found nil while unwrapping an Optional value\n  {vc}.swift:{line}  let token = keychain.token!")]
        story = "Тестировщик открывает экран — приложение сразу падает. В локальной сборке из Xcode всё работает, падает только сборка из TestFlight."
    lines = sorted([_log(t(1, 12), "xcodebuild", "INFO", f"Archive {ver} ({rng.randint(400, 900)}) succeeded"), *mid,
                    _log(t(9, 47), "crash", "ERROR", "EXC_BREAKPOINT (SIGTRAP), Thread 0 Crashed: com.apple.main-thread")], key=lambda x: x["t"])
    opts, key = _options(rng, [f"После переименования связь @IBOutlet {outlet} со storyboard потеряна, outlet остался nil",
                               "Массив данных очищается раньше, чем таблица узнаёт об этом: менять данные и обновлять таблицу вместе на главном потоке",
                               "У сборки из TestFlight нет entitlement на группу Keychain (-34018): поправить capabilities и профиль подписи"], v,
                         ["Экран создаётся не на главном потоке, и UIKit падает на первом обращении к view",
                          f"Системе не хватило памяти: в сборке {ver} экран тяжелее, и его view выгружается ещё до вызова viewDidLoad"])
    return {"scene_title": "Краш в TestFlight", "story": f"Сборка {ver} для TestFlight. {story}", "prompt": "В чём причина?",
            "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("mob_dbg_r8_reflection", "Mobile", "Отладка", "choice", 2.3, 1.1)
def _(rng):
    dto, field, screen = rng.choice([("OrderDto", "deliveryAddress", "Заказ"), ("ProfileDto", "displayName", "Профиль"), ("TariffDto", "monthlyPrice", "Тарифы")])
    ver, t = _ver(rng), _ts(rng, 11)
    slug = dto.removesuffix("Dto").lower()
    v = _variant(rng, 3)
    if v == 0:
        lines = [_log(t(0, 2), "ci", "INFO", f"assembleRelease {ver}: isMinifyEnabled=true (R8)"),
                 _log(t(4, 30), "qa", "INFO", f"debug {ver}: {dto}({field}=\"…\") — экран «{screen}» OK"),
                 _log(t(6, 11), "app", "WARN", f"release {ver}: parsed {dto}(a=null, b=null, c=0)"),
                 _log(t(6, 11), "AndroidRuntime", "ERROR", f"java.lang.NullPointerException: Parameter specified as non-null is null: method {slug}Binder.bind, parameter {field}")]
        story = f"Release-сборка {ver}: экран «{screen}» пустой и падает. Debug-сборка с тем же сервером и тем же аккаунтом работает."
    elif v == 1:
        lines = [_log(t(0, 2), "ci", "INFO", f"assembleRelease {ver}: BASE_URL=https://api-v1-legacy.demo.ru (buildTypes.release)"),
                 _log(t(0, 2), "ci", "INFO", f"assembleDebug {ver}: BASE_URL=https://api.demo.ru"),
                 _log(t(6, 11), "app", "WARN", f"release {ver}: GET /{slug} → 200, ответ без поля {field} (схема v1)"),
                 _log(t(6, 11), "AndroidRuntime", "ERROR", f"java.lang.NullPointerException: Parameter specified as non-null is null: parameter {field}")]
        story = f"Release-сборка {ver}: экран «{screen}» пустой и падает. Debug-сборка с тем же аккаунтом работает."
    else:
        lines = [_log(t(0, 2), "ci", "INFO", f"release {ver}: amount = String.format(\"%.2f\", value)"),
                 _log(t(6, 11), "app", "WARN", f"POST /{slug} body: {{\"amount\": \"1234,50\"}} → 400 invalid number (Locale ru-RU)"),
                 _log(t(6, 12), "app", "INFO", f"POST /{slug} body: {{\"amount\": \"1234.50\"}} → 200 (Locale en-US)")]
        story = f"Сборка {ver}: на экране «{screen}» отправка падает с ошибкой сервера, но только у пользователей с русским языком системы."
    opts, key = _options(rng, ["R8 переименовал поля DTO, а Gson ищет поля по именам через рефлексию: нужны @SerializedName или keep-правила",
                               "Release-конфигурация ходит на старый сервер с другим контрактом: исправить BASE_URL для release",
                               "Число для API форматируется по локали устройства: для сервера форматировать с Locale.ROOT"], v,
                         ["В release-сборке отключено логирование, поэтому значения полей выглядят пустыми",
                          "Kotlin data class в release-сборке не поддерживает null: поля нужно сделать var"])
    return {"scene_title": "Работает не везде", "story": story, "prompt": "Что вероятнее всего?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("mob_dbg_tx_too_large", "Mobile", "Отладка", "choice", 2.3, 1.9)
def _(rng):
    screen = rng.choice(["CatalogActivity", "GalleryActivity", "ChatActivity"])
    n, size, t = rng.randint(800, 3000), rng.randint(1_050_000, 1_900_000), _ts(rng, 14)
    v = _variant(rng, 3)
    if v == 0:
        lines = [_log(t(0, 3), "ActivityTaskManager", "INFO", f"Displayed ru.demo.app/.{screen}"),
                 _log(t(3, 40), "app", "DEBUG", f"onSaveInstanceState: putParcelableArrayList(\"items\", size={n})"),
                 _log(t(3, 40), "ActivityTaskManager", "INFO", f"{screen}: paused → stopped (Home pressed)"),
                 _log(t(3, 41), "AndroidRuntime", "ERROR", f"FATAL EXCEPTION: main\njava.lang.RuntimeException: android.os.TransactionTooLargeException: data parcel size {size} bytes")]
        story = f"Краши приходят у хозяев, которые свернули приложение на экране {screen} после долгой прокрутки. На коротких списках не воспроизводится."
    elif v == 1:
        lines = [_log(t(0, 3), "app", "INFO", f"{screen}: загрузка деталей, по ответу — показать DetailsFragment"),
                 _log(t(0, 4), "ActivityTaskManager", "INFO", f"{screen}: paused → stopped (Home pressed), onSaveInstanceState"),
                 _log(t(0, 6), "AndroidRuntime", "ERROR", "FATAL EXCEPTION: main\njava.lang.IllegalStateException: Can not perform this action after onSaveInstanceState\n"
                                                         "  at FragmentManager.checkStateLoss (supportFragmentManager.beginTransaction().commit())")]
        story = f"Краши приходят у хозяев, которые свернули приложение на экране {screen}, не дождавшись загрузки деталей."
    else:
        lines = [_log(t(0, 3), "app", "INFO", f"{screen}: каждый элемент списка читает Cursor из локальной базы"),
                 _log(t(3, 40), "SQLiteCursor", "WARN", f"Window is full: requested allocation 2048 bytes, free space 512 bytes, window size 2097152 bytes (open cursors: {n})"),
                 _log(t(3, 41), "AndroidRuntime", "ERROR", "FATAL EXCEPTION: main\nandroid.database.CursorWindowAllocationException: Cursor window allocation of 2048 kb failed")]
        story = f"Краши приходят у хозяев, которые долго листают {screen}. На коротких списках не воспроизводится."
    opts, key = _options(rng, [f"Весь список ({n} шт.) кладётся в saved state, а Bundle через Binder ограничен ~1 МБ: сохранять id и позицию",
                               "Транзакция фрагмента после onSaveInstanceState: показывать результат, только когда экран снова в STARTED",
                               "Курсоры не закрываются и исчерпывают окна: закрывать их (use { }) сразу после чтения"], v,
                         [f"Утечка памяти в {screen}: в onStop очищать адаптер и вызывать System.gc(), чтобы освободить место",
                          "Процесс убивает система из-за нехватки памяти, это поведение ОС, и в коде его не исправить"])
    return {"scene_title": "Отчёты о крашах", "story": story, "prompt": "В чём причина и как исправить?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Жизненный цикл приложения ---


@family("mob_lc_remember", "Mobile", "Жизненный цикл приложения", "mark", 2.1, -1.1)
def _(rng):
    fn, var, init, label, op, btn, step = rng.choice([("QuantityPicker", "count", "1", "Количество", "count++", "Ещё", 1),
                                                      ("TipSelector", "tip", "10", "Чаевые, %", "tip += 5", "+5 %", 5),
                                                      ("SeatCounter", "seats", "1", "Мест", "seats++", "Добавить", 1)])
    v = _variant(rng, 3)
    if v == 0:
        lang, lines = "kotlin", ["@Composable", f"fun {fn}() {{"]
        if rng.random() < 0.5:
            lines.append("    val haptics = LocalHapticFeedback.current")
        lines.append(f"    var {var} by remember {{ mutableStateOf({init}) }}")
        key = len(lines)
        lines += ["    Column {", f"        Text(\"{label}: ${var}\")", f"        Button(onClick = {{ {op} }}) {{ Text(\"{btn}\") }}", "    }", "}"]
        story = f"Пока Рей тянул вас к кусту, вы выбрали значение «{label}» и повернули телефон — значение сбросилось к {init}."
    elif v == 1:
        lang, lines = "kotlin", ["@Composable", f"fun {fn}Screen() {{", f"    val vm = {fn}ViewModel()"]
        key = len(lines)
        lines += [f"    val {var} by vm.{var}.collectAsState()", "    Column {", f"        Text(\"{label}: ${var}\")",
                  f"        Button(onClick = {{ vm.inc() }}) {{ Text(\"{btn}\") }}", "    }", "}"]
        story = f"Значение «{label}» хранится во ViewModel, но сбрасывается к {init} при повороте и даже при любом обновлении экрана."
    else:
        lang, lines = "swift", [f"struct {fn}View: View {{", f"    @ObservedObject var model = {fn}Model()"]
        key = len(lines)
        lines += ["    var body: some View {", "        VStack {", f"            Text(\"{label}: \\(model.{var})\")",
                  f"            Button(\"{btn}\") {{ model.{var} += {step} }}", "        }", "    }", "}"]
        story = f"Значение «{label}» сбрасывается к {init} каждый раз, когда обновляется родительский экран."
    return {"scene_title": "Значение сбрасывается", "story": story, "prompt": "Нажмите на строку, которую нужно изменить, чтобы значение не сбрасывалось.",
            "panel": {"type": "code", "lang": lang, "lines": lines}, "key": key}


@family("mob_lc_bg_upload", "Mobile", "Жизненный цикл приложения", "choice", 2.2, 1.0)
def _(rng):
    size, n, t = rng.randint(80, 600), rng.randint(100, 999), _ts(rng, 13)
    v = _variant(rng, 3)
    if v == 0:
        lines = [_log(t(0, 4), "app", "INFO", f"upload started: video_{n}.mov ({size} MB), URLSessionConfiguration.default"),
                 _log(t(0, 31), "UIApplication", "INFO", "applicationDidEnterBackground"),
                 _log(t(0, 31), "app", "INFO", "beginBackgroundTask(withName: \"upload\") granted"),
                 _log(t(1, 2), "UIApplication", "WARN", "Background task \"upload\" expired, ending"),
                 _log(t(1, 2), "CFNetwork", "ERROR", "Task <…>.<1> finished with error [-999] cancelled")]
        story = f"Хозяева жалуются, и вы сами проверили на ролике с Реем: видео на {size} МБ не загружается, если свернуть приложение."
    elif v == 1:
        lines = [_log(t(0, 4), "push", "INFO", "silent push (content-available: 1) sent: new messages sync"),
                 _log(t(0, 4), "apns", "INFO", "device state: app terminated by user (swipe up in app switcher)"),
                 _log(t(0, 5), "push", "WARN", "background notification not delivered to app"),
                 _log(t(2, 0), "app", "INFO", "launch by user → sync started only now")]
        story = "Пользователи жалуются: сообщения подгружаются только после открытия приложения, хотя сервер шлёт тихий пуш на синхронизацию."
    else:
        lines = [_log(t(0, 4), "app", "INFO", "tracking started: CLLocationManager, authorization: whenInUse"),
                 _log(t(0, 31), "UIApplication", "INFO", "applicationDidEnterBackground"),
                 _log(t(0, 32), "CoreLocation", "INFO", "location updates paused (no background mode, whenInUse)"),
                 _log(t(5, 0), "server", "WARN", "трек курьера прерывается на всё время, пока приложение свёрнуто")]
        story = "Курьеры, которые возят корм, жалуются: трек доставки прерывается, когда они сворачивают приложение и открывают навигатор."
    opts, key = _options(rng, ["Перенести загрузку в URLSession с background-конфигурацией: файл передаёт система, даже если приложение выгружено",
                               "Тихий пуш не будит приложение, закрытое пользователем: синхронизировать при запуске и не полагаться только на пуш",
                               "Нужен фоновый режим location и allowsBackgroundLocationUpdates = true: иначе обновления в фоне останавливаются"], v,
                         ["Вызывать beginBackgroundTask заново каждые 25 секунд: система каждый раз продлит время работы в фоне",
                          "Включить фоновый режим аудио и проигрывать тишину, чтобы приложение не засыпало"])
    return {"scene_title": "Работа в фоне", "story": f"{story} Ниже — логи устройства.", "prompt": "Как сделать правильно?",
            "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("mob_lc_fgs_push", "Mobile", "Жизненный цикл приложения", "choice", 2.3, 2.1)
def _(rng):
    svc = rng.choice(["SyncService", "TrackUploadService", "BackupService"])
    api, t = 31, _ts(rng, 3)
    v = _variant(rng, 3)
    if v == 0:
        lines = [_log(t(0, 12), "PushHandler", "INFO", "onMessageReceived: type=sync, priority=normal"),
                 _log(t(0, 12), "app", "INFO", f"startForegroundService(Intent(.{svc}))"),
                 _log(t(0, 12), "AndroidRuntime", "ERROR", f"FATAL EXCEPTION: main\nandroid.app.ForegroundServiceStartNotAllowedException: startForegroundService() "
                                                         f"not allowed due to mAllowStartForeground false: service ru.demo.app/.{svc}"),
                 _log(t(5, 0), "crash-stats", "INFO", f"все краши — API {api}+, процесс в фоне в момент пуша")]
        story = f"После обновления targetSdk пуш синхронизации роняет приложение, если оно свёрнуто. {svc} запускается прямо из обработчика пуша."
    elif v == 1:
        lines = [_log(t(0, 12), "app", "INFO", f"user tapped «Начать запись трека» → startForegroundService(.{svc})"),
                 _log(t(0, 12), "AndroidRuntime", "ERROR", "FATAL EXCEPTION: main\nandroid.app.MissingForegroundServiceTypeException: "
                                                         "Starting FGS without a type callerApp=ru.demo.app targetSDK=34"),
                 _log(t(5, 0), "crash-stats", "INFO", "все краши — Android 14, приложение на экране в момент нажатия")]
        story = f"После обновления targetSdk до 34 {svc} падает сразу при старте, хотя пользователь запускает его кнопкой на экране."
    else:
        lines = [_log(t(0, 12), "app", "INFO", "setExactAndAllowWhileIdle(… напоминание о приёме лекарства …)"),
                 _log(t(0, 12), "AndroidRuntime", "ERROR", "FATAL EXCEPTION: main\njava.lang.SecurityException: Caller ru.demo.app needs to hold "
                                                         "'android.permission.SCHEDULE_EXACT_ALARM' to set exact alarms."),
                 _log(t(5, 0), "crash-stats", "INFO", "все краши — Android 14, новые установки")]
        story = "После обновления targetSdk приложение падает при создании точного напоминания о лекарстве для питомца, но только у новых пользователей."
    opts, key = _options(rng, ["С Android 12 из фона нельзя запускать foreground-сервис: работу по пушу ставить в WorkManager как expedited",
                               "С Android 14 у foreground-сервиса обязателен тип в манифесте и соответствующее разрешение FOREGROUND_SERVICE_*",
                               "Точные будильники требуют разрешения: проверять canScheduleExactAlarms() и просить его или ставить неточный"], v,
                         ["Заменить startForegroundService на startService: обычный сервис можно запускать откуда угодно",
                          "Повторять вызов с паузой, пока система не разрешит"])
    return {"scene_title": "Новый targetSdk", "story": story, "prompt": "Что сделать?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("mob_lc_process_death", "Mobile", "Жизненный цикл приложения", "choice", 2.3, 2.6)
def _(rng):
    holder, field, frag, title, where, keys = rng.choice([
        ("SessionHolder", "session", "CheckoutFragment", "оплаты", "экран входа", "orderId, step"),
        ("CartHolder", "cart", "DeliveryFragment", "выбора доставки", "экран каталога", "addressId, slot"),
        ("ProfileHolder", "profile", "EditProfileFragment", "редактирования профиля", "главный экран", "draftName, avatarUri")])
    pid, mins, t = rng.randint(10000, 29999), rng.randint(15, 18), _ts(rng, 16)  # минуты ≤ 59
    v = _variant(rng, 3)
    crash = _log(t(mins, 41), "AndroidRuntime", "ERROR", f"FATAL EXCEPTION: main\nkotlin.UninitializedPropertyAccessException: lateinit property {field} has not been initialized\n"
                                                       f"  at ru.demo.app.{holder}.get{field.capitalize()}")
    if v == 0:
        lines = [_log(t(0, 3), "app", "INFO", f"{frag} resumed; пользователь уходит в другое приложение"),
                 _log(t(2, 51), "ActivityManager", "INFO", f"Killing {pid}:ru.demo.app/u0a211 (adj 905): cached #{rng.randint(12, 30)}"),
                 _log(t(mins, 40), "ActivityManager", "INFO", f"Start proc {pid + rng.randint(40, 900)}:ru.demo.app/u0a211 for activity ru.demo.app/.MainActivity"),
                 _log(t(mins, 41), "FragmentManager", "DEBUG", f"restored back stack top={frag}; SavedStateHandle keys=[{keys}]"), crash,
                 _log(t(mins + 1, 0), "qa", "INFO", "«Don't keep activities» и поворот экрана — без падений; краши только у тех, кто возвращается через 15 минут и позже")]
        story = f"Краши с экрана {title}: пользователь надолго уходит в другое приложение, возвращается — падение. {holder} — синглтон, его заполняет {where}."
    elif v == 1:
        lines = [_log(t(0, 3), "app", "INFO", f"{frag}: введено в форму, данные лежат в полях ViewModel"),
                 _log(t(2, 51), "ActivityManager", "INFO", f"Killing {pid}:ru.demo.app/u0a211 (adj 905): cached #{rng.randint(12, 30)}"),
                 _log(t(mins, 41), "FragmentManager", "DEBUG", f"restored back stack top={frag}; SavedStateHandle keys=[]"),
                 _log(t(mins, 42), "app", "INFO", f"{frag}: форма пустая"),
                 _log(t(mins + 1, 0), "qa", "INFO", "поворот экрана — данные на месте; теряются только после долгого ухода в другое приложение")]
        story = f"Пользователи жалуются: заполнили форму {title}, надолго ушли в другое приложение, вернулись — форма пустая. Падений нет."
    else:
        lines = [_log(t(0, 3), "app", "INFO", f"open deep link ru.demo.app://{frag.removesuffix('Fragment').lower()} (из письма), процесса нет — холодный старт"),
                 _log(t(0, 4), "Navigation", "DEBUG", f"start destination skipped → {frag}"), _log(t(0, 4), "AndroidRuntime", "ERROR", crash["msg"]),
                 _log(t(1, 0), "qa", "INFO", f"если сначала открыть приложение с иконки, а потом ссылку — падения нет; {holder} заполняет {where}")]
        story = f"Краши с экрана {title}: пользователи открывают его по ссылке из письма, когда приложение не запущено."
    opts, key = _options(rng, [f"Процесс убит системой в фоне: стек экранов и SavedStateHandle восстановились, а синглтон {holder} пуст — он должен подниматься из хранилища сам",
                               "ViewModel не переживает смерть процесса: введённое нужно класть в SavedStateHandle, а не только в поля ViewModel",
                               f"Ссылка открывает экран напрямую, минуя {where}, который заполняет {holder}: данные должны загружаться там, где они нужны"], v,
                         [f"Это эффект «Don't keep activities»: Activity пересоздаётся без ViewModel — держать {field} в ViewModel, а не в синглтоне {holder}",
                          f"При восстановлении Activity.onCreate вызывается раньше Application.onCreate, и {holder} ещё не готов: перенести инициализацию в ContentProvider",
                          "Глубокий экран восстанавливать не нужно: поставить clearTaskOnLaunch, чтобы приложение всегда открывалось с главного экрана"])
    return {"scene_title": "Возврат на экран", "story": story, "prompt": "В чём причина и что исправить?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Ревью кода ---


@family("mob_rv_force_unwrap", "Mobile", "Ревью кода", "mark", 2.1, -1.4)
def _(rng):
    param, ent, ru = rng.choice([("order", "Order", "заказов"), ("promo", "Promo", "промокодов"), ("ticket", "Ticket", "билетов")])
    v = _variant(rng, 3)
    if v == 0:
        lines = ["func handle(deepLink url: URL) {"]
        if rng.random() < 0.5:
            lines.append("    analytics.track(\"deeplink_opened\")")
        lines.append("    let components = URLComponents(url: url, resolvingAgainstBaseURL: false)")
        lines.append(f"    let id = components!.queryItems!.first {{ $0.name == \"{param}\" }}!.value!")
        key = len(lines)
        lines += [f"    router.open{ent}(id: id)", "}"]
        story, caption = f"После рассылки собачникам со ссылкой без параметра {param} пришла волна крашей при открытии приложения по ссылке.", f"диплинки {ru}"
    elif v == 1:
        lines = [f"func show{ent}s(_ items: [{ent}]) {{"]
        if rng.random() < 0.5:
            lines.append("    analytics.track(\"list_opened\")")
        lines.append("    let first = items[0]")
        key = len(lines)
        lines += ["    header.configure(with: first)", "    table.reload(items)", "}"]
        story, caption = f"У новых пользователей без {ru} приложение падает сразу при открытии списка.", f"шапка списка {ru}"
    else:
        lines = [f"enum {ent}Status: String, Decodable {{ case new, paid, cancelled }}", "", f"func parse(_ data: Data) -> [{ent}] {{"]
        if rng.random() < 0.5:
            lines.append("    let decoder = JSONDecoder()")
        lines.append(f"    return try! JSONDecoder().decode([{ent}].self, from: data)")
        key = [1, len(lines)]  # enum без запасного случая роняет декодирование, try! превращает ошибку в краш
        lines.append("}")
        story, caption = f"После обновления бэкенда приложение падает на экране {ru}: сервер добавил новый статус partially_refunded.", f"разбор {ru}"
    return {"scene_title": "Волна крашей", "story": story, "prompt": "Нажмите на строку, из-за которой приложение падает.",
            "panel": {"type": "code", "lang": "swift", "lines": lines, "caption": f"PR #{rng.randint(300, 999)} · «{caption}»"}, "key": key}


@family("mob_rv_setstate_mounted", "Mobile", "Ревью кода", "mark", 2.2, 0.9)
def _(rng):
    page, typ, field, fn = rng.choice([("OrdersPage", "List<Order>", "orders", "fetchOrders"), ("ProfilePage", "Profile", "profile", "fetchProfile"),
                                       ("WalletPage", "Balance", "balance", "fetchBalance")])
    v = _variant(rng, 3)
    lines = [f"class _{page}State extends State<{page}> {{", f"  {typ}? _{field};"]
    if v == 1:
        lines.append("  late final StreamSubscription _sub;")
    lines += ["", "  @override", "  void initState() {", "    super.initState();"]
    if v == 1:
        lines.append(f"    _sub = api.watch{field.capitalize()}().listen((data) => setState(() => _{field} = data));")
        key = len(lines)
        lines += ["  }", "}"]
        story = "После ухода с экрана в логах продолжают идти обновления данных, а память приложения растёт с каждым открытием экрана."
        prompt = "Нажмите на строку, которую нужно дополнить очисткой в dispose."
    else:
        lines += ["    _load();", "  }", ""]
        if rng.random() < 0.5:
            lines.append("  // загрузка при открытии экрана")
        if v == 0:
            lines += ["  Future<void> _load() async {", f"    final data = await api.{fn}();", f"    setState(() => _{field} = data);"]
            key = [len(lines) - 1, len(lines)]
            lines += ["  }", "}"]
            story = f"В отчётах об ошибках: «setState() called after dispose(): _{page}State». Пользователи уходят с экрана, не дождавшись загрузки."
        else:
            lines += ["  Future<void> _save() async {", "    if (!mounted) return;", f"    await api.save{field.capitalize()}(_{field}!);", "    Navigator.of(context).pop();"]
            key = [len(lines) - 2, len(lines)]
            lines += ["  }", "}"]
            story = "Иногда после сохранения закрывается не тот экран, а в отчётах — «Looking up a deactivated widget's ancestor is unsafe»."
        prompt = "Нажмите на строку, которую нужно исправить."
    return {"scene_title": "Ревью Flutter-экрана", "story": story, "prompt": prompt, "panel": {"type": "code", "lang": "dart", "lines": lines}, "key": key}


@family("mob_rv_collect_lifecycle", "Mobile", "Ревью кода", "mark", 2.3, 2.2)
def _(rng):
    flow, v_, view, call, what = rng.choice([("courierPosition", "pos", "map", "showCourier", "геолокация"),
                                             ("heartRate", "bpm", "pulseView", "render", "датчик пульса"),
                                             ("nearbyBeacons", "list", "beaconList", "submit", "сканирование Bluetooth")])
    v = _variant(rng, 3)
    if v == 0:
        lines = ["override fun onCreate(savedInstanceState: Bundle?) {", "    super.onCreate(savedInstanceState)", "    setContentView(binding.root)"]
        if rng.random() < 0.5:
            lines.append("    binding.toolbar.setNavigationOnClickListener { finish() }")
        lines.append("    lifecycleScope.launch {")
        key = [len(lines), len(lines) + 1]
        lines += [f"        viewModel.{flow}.collect {{ {v_} ->", f"            binding.{view}.{call}({v_})", "        }", "    }", "}"]
        story = f"После релиза хозяева жалуются на расход батареи: {what} работает, даже когда приложение свёрнуто. Поток в ViewModel активен, пока его кто-то собирает."
    elif v == 1:
        lines = ["class TrackViewModel(private val repo: TrackRepository) : ViewModel() {", "    fun start() {", "        GlobalScope.launch {"]
        key = len(lines)
        lines += [f"            repo.{flow}().collect {{ {v_} -> repo.save({v_}) }}", "        }", "    }", "}"]
        story = f"После закрытия экрана {what} продолжает работать и писать в базу, пока процесс жив; каждое открытие экрана добавляет ещё один поток."
    else:
        lines = ["binding.saveButton.setOnClickListener {", "    val result = runBlocking {"]
        key = len(lines)
        lines += ["        repo.saveSettings(viewModel.settings)", "    }", "    showToast(result.message)", "}"]
        story = "При нажатии «Сохранить» интерфейс замирает на несколько секунд, на слабых телефонах — до ANR."
    return {"scene_title": "Ревью корутин", "story": story, "prompt": "Нажмите на строку с причиной.",
            "panel": {"type": "code", "lang": "kotlin", "lines": lines, "caption": f"PR #{rng.randint(300, 999)}"}, "key": key}


@family("mob_rv_actor_reentrancy", "Mobile", "Ревью кода", "mark", 2.3, 2.4)
def _(rng):
    actor, field, typ, call, ep = rng.choice([("SessionStore", "session", "Session", "api.refresh(session?.refreshToken)", "/auth/refresh"),
                                              ("FlagsStore", "flags", "FeatureFlags", "api.fetchFlags()", "/v1/flags"),
                                              ("ConfigStore", "config", "RemoteConfig", "api.fetchConfig()", "/v1/config")])
    v = _variant(rng, 3)
    if v == 0:
        lines = [f"actor {actor} {{", f"    private var {field}: {typ}?"]
        if rng.random() < 0.5:
            lines.append(f"    private let log = Logger(subsystem: \"app\", category: \"{field}\")")
        lines += ["", f"    func current() async throws -> {typ} {{", f"        if let v = {field}, !v.isExpired {{ return v }}", f"        let fresh = try await {call}"]
        key = len(lines)
        lines += [f"        {field} = fresh", "        return fresh", "    }", "}"]
        story = (f"{actor} переписали на actor, чтобы убрать гонки при старте. Но бэкенд всё равно видит по {rng.randint(3, 4)} одинаковых запроса {ep} "
                 "от одного устройства за секунду: экраны одновременно вызывают current().")
        prompt = "Нажмите на строку, из-за которой актор пропускает дублирующие запросы."
    elif v == 1:
        lines = [f"final class {typ}ViewModel: ObservableObject {{", f"    @Published var {field}: {typ}?"]
        key = 1
        lines += ["", "    func load() async {", f"        {field} = try? await {call}"]
        key = [key, len(lines)]
        lines += ["    }", "}"]
        story = "В консоли Xcode фиолетовые предупреждения «Publishing changes from background threads is not allowed», экран иногда не обновляется."
        prompt = "Нажмите на строку, которую нужно исправить."
    else:
        lines = [f"struct {typ}Screen: View {{", f"    @StateObject var model = {typ}ViewModel()", "    var body: some View {", "        List(model.items) { Row($0) }",
                 "            .onAppear {", "                Task { await model.load() }"]
        key = [len(lines) - 1, len(lines)]
        lines += ["            }", "    }", "}"]
        story = f"При каждом возврате на экран уходит новый запрос {ep}, старые не отменяются, и иногда устаревший ответ приходит последним и перетирает свежий."
        prompt = "Нажмите на строку, из-за которой загрузки не отменяются."
    return {"scene_title": "Ревью async-кода", "story": story, "prompt": prompt,
            "panel": {"type": "code", "lang": "swift", "lines": lines, "caption": f"PR #{rng.randint(300, 999)} · «{actor}»"}, "key": key}


# --- Сеть и офлайн ---


@family("mob_net_offline_cache", "Mobile", "Сеть и офлайн", "choice", 2.0, -1.5)
def _(rng):
    screen, screen_nom = rng.choice([("ленту новостей", "лента новостей"), ("список заказов", "список заказов"), ("расписание занятий", "расписание занятий")])
    place = rng.choice(["в самолёте", "в метро", "за городом без связи"])
    v = _variant(rng, 3)
    story = [f"Пользователь {place} открыл {screen} и видит бесконечный спиннер, хотя час назад всё загружалось.",
             f"В кафе, куда пускают с собаками, телефон подключён к Wi-Fi, но интернет там только после входа на страницу провайдера. Приложение уверено, что сеть есть, и {screen_nom} висит на загрузке.",
             "Пользователи жалуются на расход батареи: приложение каждые 10 секунд спрашивает сервер, нет ли новых сообщений."][v]
    opts, key = _options(rng, ["Показать последние сохранённые данные из локального кэша с пометкой «нет сети» и обновить их, когда связь вернётся",
                               "Проверять доступность реальным запросом к своему серверу, а не только по флагу «подключено к сети»",
                               "Пуш-уведомления или одно долгоживущее соединение вместо частого опроса сервера"], v,
                         ["Показать системную ошибку и закрыть экран: пользователь сам вернётся, когда связь появится",
                          "Увеличить таймаут запроса до пяти минут, чтобы дождаться ответа"])
    return {"scene_title": "Связь и батарея", "story": story, "prompt": "Как должно вести себя приложение?", "panel": None, "options": opts, "key": key}


@family("mob_net_cleartext", "Mobile", "Сеть и офлайн", "choice", 2.2, 0.1)
def _(rng):
    host = rng.choice(["api.shop-demo.ru", "media.demo-cdn.ru", "pay.wallet-demo.ru"])
    ver, t = _ver(rng), _ts(rng, 9)
    v = _variant(rng, 3)
    if v == 0:
        err = (_log(t(2, 15), "OkHttp", "ERROR", f"java.net.UnknownServiceException: CLEARTEXT communication to {host} not permitted by network security policy")
               if rng.random() < 0.5 else
               _log(t(2, 15), "CFNetwork", "ERROR", "App Transport Security has blocked a cleartext HTTP (http://) resource load since it is insecure."))
        lines = [_log(t(0, 1), "build", "INFO", f"release {ver}: BASE_URL=http://{host}/v{rng.randint(1, 3)}"), _log(t(2, 14), "app", "INFO", "feed: GET /items"), err]
        story = f"Release-сборка {ver} не загружает ни одного экрана, а до бэкенда запросы вообще не доходят."
    elif v == 1:
        lines = [_log(t(0, 1), "ops", "INFO", f"{host}: сертификат перевыпущен вчера, новый ключ"),
                 _log(t(2, 14), "app", "INFO", "feed: GET /items"),
                 _log(t(2, 15), "OkHttp", "ERROR", f"javax.net.ssl.SSLPeerUnverifiedException: Certificate pinning failure!\n  Pinned certificates for {host}: sha256/AAAA…= (один пин)")]
        story = f"С утра все версии приложения не загружают ни одного экрана; в браузере {host} открывается нормально."
    else:
        lines = [_log(t(0, 1), "ops", "INFO", f"{host}: на балансировщике оставлен только TLS 1.3"),
                 _log(t(2, 15), "OkHttp", "ERROR", "javax.net.ssl.SSLHandshakeException: SSL handshake aborted: Failure in SSL library, usually a protocol error"),
                 _log(t(3, 0), "crash-stats", "INFO", "ошибка только на Android 7–9, на новых версиях всё работает")]
        story = "После обновления настроек сервера часть пользователей не может загрузить ни одного экрана."
    lines.insert(len(lines) - (v == 2), _log(t(2, 16), "app", "WARN", "feed: request failed, showing empty state"))
    opts, key = _options(rng, ["Сборка ходит на сервер по HTTP, а система по умолчанию блокирует незашифрованный трафик: перевести BASE_URL на HTTPS",
                               "Пин не совпал с новым ключом сервера: пиннить ключ с запасным пином и выпускать обновление заранее",
                               "Старые Android не умеют TLS 1.3: вернуть на сервере TLS 1.2 с совместимыми наборами шифров"], v,
                         ["Разрешить незашифрованный трафик и отключить проверку сертификатов для всех доменов — так быстрее всего вернуть работу",
                          f"DNS на устройствах не резолвит {host}: проверить настройки сети и VPN у пользователей"])
    return {"scene_title": "Пустые экраны", "story": story, "prompt": "В чём причина и что сделать?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("mob_net_refresh_race", "Mobile", "Сеть и офлайн", "choice", 2.4, 2.3)
def _(rng):
    eps = rng.sample(["/v1/profile", "/v1/orders", "/v1/notifications", "/v1/balance", "/v1/feed"], 3)
    r1, t = rng.randint(1000, 9999), _ts(rng, 8)
    v = _variant(rng, 3)
    if v == 0:
        lines = [*(_log(t(0, 2), "http", "INFO", f"GET {e} → 401 token_expired") for e in eps),
                 _log(t(0, 3), "auth", "INFO", f"POST /auth/refresh (refresh=…{r1}) → 200, new pair issued"),
                 _log(t(0, 3), "auth", "WARN", f"POST /auth/refresh (refresh=…{r1}) → 401 refresh_token_reused, token family revoked"),
                 _log(t(0, 4), "app", "ERROR", "session revoked → logout, open LoginScreen")]
        story = "После релиза часть пользователей внезапно оказывается на экране входа. Сервер выдаёт одноразовые refresh-токены (ротация)."
    elif v == 1:
        lines = [_log(t(0, 1), "app", "INFO", f"main app: refresh → saved refresh=…{r1 + 1}"),
                 _log(t(0, 2), "notification-ext", "INFO", f"push extension: refresh with …{r1} (прочитан при старте) → 200, saved refresh=…{r1 + 7}"),
                 _log(t(0, 5), "app", "WARN", f"POST /auth/refresh (refresh=…{r1 + 1}) → 401 refresh_token_reused, token family revoked"),
                 _log(t(0, 5), "app", "ERROR", "session revoked → logout")]
        story = "Пользователей выкидывает на вход после того, как пришёл пуш. Сервер выдаёт одноразовые refresh-токены, расширение уведомлений тоже ходит в API."
    else:
        lines = [_log(t(0, 1), "device", "INFO", "system time: 2026-10-07 08:11 (сервер: 2026-10-07 10:46)"),
                 _log(t(0, 2), "app", "INFO", "access token exp=2026-10-07 11:00 → client check: valid for 2h49m, sending"),
                 _log(t(0, 2), "http", "INFO", f"GET {eps[0]} → 401 token_expired"),
                 _log(t(0, 3), "app", "WARN", "client check says valid → no refresh, retry with same token → 401 → logout")]
        story = "Некоторых пользователей постоянно выкидывает на вход; у всех них неправильно выставлены часы в телефоне."
    opts, key = _options(rng, ["Один общий refresh: параллельные запросы с 401 ждут уже начатое обновление, а не запускают каждый своё",
                               "Токены обновлять в одном месте под общей блокировкой для приложения и расширений (общее хранилище App Group)",
                               "Не решать по часам устройства, истёк ли токен: на 401 обновлять токен, а время сверять с сервером"], v,
                         ["Увеличить срок жизни access-токена до 30 дней, чтобы обновление случалось реже",
                          "При первом 401 сразу разлогинивать пользователя: это безопаснее, чем повторять запросы"])
    return {"scene_title": "Выкинуло на вход", "story": story, "prompt": "Как исправить клиент?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("mob_net_sync_conflict", "Mobile", "Сеть и офлайн", "choice", 2.4, 2.9)
def _(rng):
    what, noun, f1, f2 = rng.choice([("одну и ту же заметку", "заметку", "заголовок", "текст"), ("одну и ту же карточку задачи", "карточку задачи", "статус", "описание"),
                                     ("один и тот же список покупок", "список покупок", "название", "позиции")])
    h, skew, doc = rng.randint(9, 16), rng.randint(16, 40), rng.randint(100, 999)

    def hm(m: int) -> str:
        return f"{m // 60:02d}:{m % 60:02d}"

    v = _variant(rng, 3)
    if v == 0:
        lines = [_log(hm(h * 60 - 10) + ":00", "tablet", "INFO", f"офлайн: изменено поле «{f2}», updatedAt={hm(h * 60 - 10 + skew)} (по часам планшета)"),
                 _log(hm(h * 60 + 5) + ":12", "sync", "INFO", f"phone: PUT /docs/{doc} (весь документ, изменено «{f1}»), updatedAt={hm(h * 60 + 5)} → 200"),
                 _log(hm(h * 60 + 70) + ":40", "sync", "INFO", f"tablet: PUT /docs/{doc} (весь документ), updatedAt={hm(h * 60 - 10 + skew)} → 200, newer wins"),
                 _log(hm(h * 60 + 71) + ":03", "support", "WARN", f"doc {doc}: «{f1}» снова старый — правка с телефона пропала"),
                 _log(hm(h * 60 + 72) + ":30", "device", "INFO", f"часы планшета спешат на {skew} мин")]
        story = f"Пользователь правит {what} на телефоне и на планшете, планшет часть времени без сети. Синхронизация — last-write-wins по updatedAt."
    elif v == 1:
        lines = [_log(hm(h * 60) + ":00", "phone", "INFO", "офлайн: создан документ, локальный id=tmp-1"),
                 _log(hm(h * 60 + 20) + ":00", "sync", "INFO", "POST /docs → timeout (ответ потерян, сервер создал doc 9131)"),
                 _log(hm(h * 60 + 20) + ":30", "sync", "INFO", "retry POST /docs → 201 doc 9132"),
                 _log(hm(h * 60 + 21) + ":00", "support", "WARN", "у пользователя два одинаковых документа")]
        story = f"Пользователь создаёт {noun} в метро; когда связь появляется, иногда на сервере оказываются две копии."
    else:
        lines = [_log(hm(h * 60) + ":00", "phone", "INFO", f"удалён doc {doc} → DELETE /docs/{doc} → 204"),
                 _log(hm(h * 60 + 40) + ":00", "tablet", "INFO", "офлайн-копия списка: все документы, включая удалённый"),
                 _log(hm(h * 60 + 41) + ":00", "sync", "INFO", f"tablet: PUT /docs (весь список, {doc} в нём есть) → 200"),
                 _log(hm(h * 60 + 42) + ":00", "support", "WARN", f"doc {doc} снова в списке у пользователя")]
        story = f"Пользователь удаляет {noun} на телефоне, а через час удалённое возвращается: планшет синхронизирует свою офлайн-копию."
    opts, key = _options(rng, [f"Слать только изменённые поля с базовой ревизией: сервер видит правку поверх старой версии и сливает «{f1}» с телефона и «{f2}» с планшета",
                               "Создавать запись с идентификатором, сгенерированным на клиенте, и делать вставку идемпотентной по нему",
                               "Хранить удаление как запись-надгробие с версией, а не просто отсутствие документа в списке"], v,
                         ["Ставить updatedAt на сервере в момент приёма запроса: тогда часы устройств перестанут влиять на то, какая запись победит",
                          "Брать на сервере блокировку документа на время редактирования, чтобы второе устройство не меняло его"])
    return {"scene_title": "Синхронизация", "story": story, "prompt": "Как исправить синхронизацию?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Производительность ---


@family("mob_perf_listview", "Mobile", "Производительность", "mark", 2.1, -0.9)
def _(rng):
    title, coll, tile = rng.choice([("Каталог", "products", "ProductCard"), ("Отзывы", "reviews", "ReviewTile"), ("Афиша", "events", "EventCard")])
    n, s = rng.choice([2000, 5000, 8000]), rng.choice(["3 секунды", "4 секунды", "6 секунд"])
    v = _variant(rng, 3)
    lines = ["@override", "Widget build(BuildContext context) {"]
    if rng.random() < 0.5:
        lines.append("  final theme = Theme.of(context);")
    if v == 0:
        lines.append("  return ListView(")
        key = [len(lines), len(lines) + 1]
        lines += [f"    children: {coll}.map((x) => {tile}(item: x)).toList(),", "  );", "}"]
        story = f"Экран «{title}» открывается {s}: в списке {n} элементов, каждый — карточка с картинкой."
    elif v == 1:
        lines.append(f"  final sorted = [...{coll}]..sort((a, b) => a.rank.compareTo(b.rank));")
        key = len(lines)
        lines += ["  return ListView.builder(", "    itemCount: sorted.length,", f"    itemBuilder: (_, i) => {tile}(item: sorted[i]),", "  );", "}"]
        story = f"Экран «{title}» с {n} элементами дёргается при каждом обновлении таймера в шапке: build вызывается раз в секунду."
    else:
        lines += ["  return ListView.builder(", f"    itemCount: {coll}.length,", "    itemBuilder: (_, i) => Opacity(", "      opacity: _fade.value,"]
        key = [len(lines) - 1, len(lines)]
        lines += [f"      child: {tile}(item: {coll}[i]),", "    ),", "  );", "}"]
        story = f"На экране «{title}» карточки плавно проявляются, и во время анимации прокрутка падает до 20 кадров в секунду."
    return {"scene_title": "Тормозит список", "story": story, "prompt": "Нажмите на строку с причиной.", "panel": {"type": "code", "lang": "dart", "lines": lines}, "key": key}


@family("mob_perf_cold_start", "Mobile", "Производительность", "choice", 2.3, 1.3)
def _(rng):
    major, minor0, rel = rng.randint(3, 6), rng.randint(10, 30), rng.randint(4, 6)
    k = rng.randint(2, 4)
    x = [f"{major}.{minor0 + i}" for i in range(8)]
    start = [rng.randint(780, 980) if i < rel else rng.randint(2200, 2800) for i in range(8)]
    v = _variant(rng, 3)
    name = ["инициализация SDK до первого кадра, мс", "ожидание удалённого конфига до первого кадра, мс", "миграция локальной базы при запуске, мс"][v]
    part = [rng.randint(50, 120) if i < rel else rng.randint(1300, 1800) for i in range(8)]
    panel = {"type": "chart", "x": x, "marker": {"i": rel, "label": f"релиз {x[rel]}"}, "series": [
        {"name": "холодный старт p90, мс", "axis": "left", "max": 3000, "data": start}, {"name": name, "axis": "right", "max": 2000, "data": part}]}
    opts, key = _options(rng, ["Новые SDK инициализируются синхронно при запуске: некритичные отложить и проверить трассировкой старта",
                               "Первый экран ждёт свежий удалённый конфиг: показывать закэшированный и обновлять его в фоне",
                               "Миграция базы выполняется синхронно при старте: делать её в фоне с прогрессом или разбить на шаги"], v,
                         ["Векторные иконки: их растеризация занимает секунды при каждом холодном старте",
                          "Новый онбординг: его экраны и анимации создаются при каждом холодном старте"])
    return {"scene_title": "Медленный старт", "story": f"Рей уже тянет поводок к следующей поляне, а приложение открывается заметно дольше обычного: холодный старт подскочил в {x[rel]}. В этом релизе — новый онбординг (только при первом запуске), "
                                                     f"векторные иконки, ещё {k} SDK, загрузка удалённого конфига с A/B-флагами и новая схема локальной базы.",
            "prompt": "Что вероятнее всего замедлило холодный старт?", "panel": panel, "options": opts, "key": key}


@family("mob_perf_recompose", "Mobile", "Производительность", "choice", 2.3, 1.8)
def _(rng):
    screen, typ = rng.choice([("Акции", "PromoItem"), ("Товары дня", "Product"), ("Подборки", "Collection")])
    m = rng.randint(2, 3)
    x = [f"{2 * i} с" for i in range(8)]
    v = _variant(rng, 3)
    if v == 0:
        series = [{"name": "рекомпозиций строк в секунду", "axis": "left", "max": 2500, "data": [rng.randint(30, 60) if i < m else rng.randint(1800, 2400) for i in range(8)]}]
        story = (f"После переноса моделей в модуль domain лента «{screen}» дёргается, пока в шапке тикает таймер акции. Layout Inspector: экран, как и раньше, "
                 f"перекомпонуется на каждый тик, но теперь вместе с ним — все строки, хотя их данные не менялись. Строки получают List<{typ}> из модуля domain.")
    elif v == 1:
        series = [{"name": "рекомпозиций экрана целиком в секунду", "axis": "left", "max": 100, "data": [rng.randint(0, 2) if i < m else rng.randint(55, 65) for i in range(8)]}]
        story = (f"С тех пор как в шапке появился таймер акции, лента «{screen}» дёргается. Layout Inspector: на каждый тик перекомпонуется весь экран — "
                 "значение таймера читается в корневой функции экрана и передаётся вниз параметром.")
    else:
        series = [{"name": "средняя перерисовка пикселя, раз", "axis": "left", "max": 6, "data": [rng.randint(1, 2) if i < m else rng.randint(4, 5) for i in range(8)]}]
        story = f"После редизайна лента «{screen}» дёргается на бюджетных телефонах. Рекомпозиций немного; каждая карточка — фон, подложка, градиент и тень поверх фона экрана."
    series.append({"name": "кадров дольше 16 мс, %", "axis": "right", "max": 50, "data": [rng.randint(1, 4) if i < m else rng.randint(25, 40) for i in range(8)]})
    panel = {"type": "chart", "x": x, "marker": {"i": m, "label": "запущен таймер" if v != 2 else "новая карточка"}, "series": series}
    opts, key = _options(rng, [f"List<{typ}> из модуля без компилятора Compose нестабилен: сделать UI-модель @Immutable и задать key у items",
                               "Читать тикающее значение как можно ниже — внутри самого таймера (лямбдой), а не в корне экрана",
                               "Слишком много слоёв рисуется поверх друг друга: убрать лишние фоны и подложки"], v,
                         ["Таймер тикает слишком часто: обновлять его раз в пять секунд, тогда лента перестанет дёргаться",
                          "LazyColumn не подходит для длинных лент: заменить его на Column с verticalScroll"])
    return {"scene_title": "Лента дёргается", "story": story, "prompt": "В чём причина?", "panel": panel, "options": opts, "key": key}


@family("mob_perf_prefs_anr", "Mobile", "Производительность", "choice", 2.3, 2.75)
def _(rng):
    screen = rng.choice(["FeedActivity", "CatalogActivity", "ChatListActivity"])
    ver, kb, share, t = _ver(rng), rng.randint(300, 900), rng.randint(85, 96), _ts(rng, 19)
    v = _variant(rng, 3)
    if v == 0:
        lines = [_log(t(0, 1), "release", "INFO", f"{ver}: кэш списка (≈{kb} КБ JSON) сохраняется в SharedPreferences через apply() при каждой остановке прокрутки"),
                 _log(t(3, 12), "ActivityManager", "ERROR", f"ANR in ru.demo.app (ru.demo.app/.{screen})\nReason: Input dispatching timed out (5000 ms)"),
                 _log(t(3, 12), "traces", "INFO", "\"main\" prio=5 WAITING\n  at java.util.concurrent.CountDownLatch.await\n  at android.app.SharedPreferencesImpl$EditorImpl$1.run\n"
                                                  "  at android.app.QueuedWork.waitToFinish\n  at android.app.ActivityThread.handleStopActivity"),
                 _log(t(5, 0), "anr-stats", "INFO", f"{share}% ANR — бюджетные устройства с eMMC; StrictMode: commit() и чтений файлов на главном потоке нет")]
        story = f"После {ver} ANR выросли втрое: зависание на секунды, когда пользователь сворачивает {screen}. На флагманах почти не воспроизводится."
    elif v == 1:
        lines = [_log(t(0, 1), "release", "INFO", f"{ver}: аватары контактов в {screen} берутся из ContactsContract по каждому элементу"),
                 _log(t(3, 12), "ActivityManager", "ERROR", f"ANR in ru.demo.app (ru.demo.app/.{screen})\nReason: Input dispatching timed out (5000 ms)"),
                 _log(t(3, 12), "traces", "INFO", "\"main\" prio=5 NATIVE\n  at android.os.BinderProxy.transact\n  at android.content.ContentResolver.query\n"
                                                  f"  at ru.demo.app.ContactAvatar.load\n  at ru.demo.app.{screen}Adapter.onBindViewHolder")]
        story = f"После {ver} ANR выросли втрое: зависание при прокрутке {screen} у пользователей с большой телефонной книгой."
    else:
        lines = [_log(t(0, 1), "release", "INFO", f"{ver}: ConnectivityReceiver при смене сети пересчитывает и сохраняет офлайн-кэш (≈{kb} КБ)"),
                 _log(t(3, 12), "ActivityManager", "ERROR", "ANR in ru.demo.app\nReason: Broadcast of Intent { act=android.net.conn.CONNECTIVITY_CHANGE } timed out (10000 ms)"),
                 _log(t(3, 12), "traces", "INFO", "\"main\" prio=5 RUNNABLE\n  at ru.demo.app.OfflineCache.rebuild\n  at ru.demo.app.ConnectivityReceiver.onReceive")]
        story = f"После {ver} ANR выросли втрое: зависания случаются при входе в метро и выходе из него."
    opts, key = _options(rng, ["apply() пишет в фоне, но при onStop ActivityThread ждёт незаконченные записи: большой кэш вынести из prefs в файл или БД и писать реже",
                               "Синхронный запрос к ContentProvider на главном потоке в адаптере: грузить аватары в фоне и кэшировать",
                               "onReceive выполняется на главном потоке и ограничен по времени: тяжёлую работу передать в WorkManager"], v,
                         ["Где-то в коде остался синхронный commit(): найти запись в prefs на главном потоке и заменить её на apply()",
                          "Бюджетным устройствам не хватает памяти, и сборка мусора на каждом кадре даёт ANR: снизить аллокации"])
    return {"scene_title": "ANR", "story": story, "prompt": "В чём причина и что сделать?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Алгоритмы ---


@family("mob_alg_dedup", "Mobile", "Алгоритмы", "choice", 2.1, -1.6)
def _(rng):
    field, by = rng.choice([("phone", "номеру"), ("email", "почте")])
    n = rng.choice([5, 10, 20])
    v = _variant(rng, 3)
    if v == 0:
        lines = ["fun dedupe(contacts: List<Contact>): List<Contact> {", "    val result = mutableListOf<Contact>()", "    for (c in contacts) {",
                 f"        if (result.none {{ it.{field} == c.{field} }}) result.add(c)", "    }", "    return result", "}"]
        story = f"Импорт {n} тыс. контактов из телефонной книги «висит» минуту: дубли по {by} убираются функцией ниже."
    elif v == 1:
        lines = ["fun dedupe(contacts: List<Contact>): List<Contact> =", "    contacts.distinctBy { it.phone }", "",
                 "// в книге: «+7 912 345-67-89», «8 (912) 345 67 89», «79123456789»"]
        story = "Импорт контактов работает быстро, но дубли по номеру остаются: один человек виден трижды."
    else:
        lines = ["fun sorted(contacts: List<Contact>): List<Contact> =", "    contacts.sortedBy { it.name }", "", "// на экране: «Елена», «Яна», «Ёлка», «юрист» — в таком порядке"]
        story = "Список контактов отсортирован, но порядок странный: «Ё» оказывается после «Я», а имена со строчной буквы — в самом конце."
    opts, key = _options(rng, [f"Запоминать уже встреченные значения {field} в HashSet: проверка за O(1), всего O(n)",
                               "Сначала привести номера к единому формату (E.164), потом убирать дубли",
                               "Сравнивать строки с учётом языка (Collator для ru), а не по кодам символов"], v,
                         ["Сортировать result после каждого добавления, чтобы поиск шёл быстрее", "Заменить mutableListOf на ArrayList с заранее заданной ёмкостью"])
    return {"scene_title": "Контакты", "story": story, "prompt": "Как исправить?", "panel": {"type": "code", "lang": "kotlin", "lines": lines}, "options": opts, "key": key}


@family("mob_alg_binsearch", "Mobile", "Алгоритмы", "mark", 2.2, 0.4)
def _(rng):
    fn, arr, thing = rng.choice([("insertIndex", "times", "сообщение в чате"), ("slotAfter", "starts", "слот доставки"), ("placeEvent", "moments", "событие в ленте")])
    v = _variant(rng, 3)
    lines = [f"fun {fn}({arr}: List<Long>, t: Long): Int {{"]
    if rng.random() < 0.5:
        lines.append("    require(t >= 0)")
    lines += ["    var lo = 0", f"    var hi = {arr}.size - 1" if v == 0 else f"    var hi = {arr}.size"]
    if v == 0:
        key = len(lines)
    lines.append("    while (lo <= hi) {" if v == 1 else "    while (lo < hi) {")
    if v == 1:
        key = len(lines)
    lines.append("        val mid = (lo + hi) ushr 1")
    lines.append(f"        if ({arr}[mid] < t) lo = mid + 1 else hi = mid" if v == 2 else f"        if ({arr}[mid] <= t) lo = mid + 1 else hi = mid")
    if v == 2:
        key = len(lines)
    lines += ["    }", "    return lo", "}"]
    story = ["Если t позже всех, элемент почему-то встаёт перед последним, а не в конец.",
             "Иногда функция не возвращается: приложение зависает на вставке.",
             "Элементы с таким же временем, как уже существующие, встают перед ними, а должны — после."][v]
    return {"scene_title": "Не на своём месте", "story": f"Функция ищет, куда вставить {thing} со временем t в отсортированный список: после всех, у кого время ≤ t. {story}",
            "prompt": "Нажмите на строку с ошибкой.", "panel": {"type": "code", "lang": "kotlin", "lines": lines}, "key": key}


@family("mob_alg_lru", "Mobile", "Алгоритмы", "choice", 2.0, 0.8)
def _(rng):
    mb, what = rng.choice([32, 64, 128]), rng.choice(["миниатюр каталога", "обложек плейлистов", "аватаров в чате"])
    v = _variant(rng, 3)
    story = [f"Кэш {what} ограничен {mb} МБ. При переполнении нужно выкидывать то, что дольше всех не показывали; get и put вызываются на каждом кадре прокрутки.",
             f"Приложение хранит {rng.randint(2, 9) * 100} запланированных напоминаний и постоянно добавляет новые; нужно быстро узнавать ближайшее по времени.",
             "В редакторе фото питомцев нужны «Отменить» и «Повторить» для любых правок; новая правка после отмены сбрасывает возможность повторить."][v]
    opts, key = _options(rng, ["Хеш-таблица плюс двусвязный список по порядку доступа (LRU): get и put за O(1)",
                               "Двоичная куча по времени: ближайшее — за O(1), добавление и удаление — за O(log n)",
                               "Два стека: отменённые правки переходят в стек «повторить», новая правка его очищает"], v,
                         ["Список, отсортированный по времени, который пересортировывается при каждом обращении",
                          "Хеш-таблица без порядка: при необходимости удалять случайный ключ, это O(1)"])
    return {"scene_title": "Структура данных", "story": story, "prompt": "Какую структуру выбрать?", "panel": None, "options": opts, "key": key}
