"""Frontend, «Неделя до релиза»: сценарные семейства с логами консоли, графиками метрик и кодом компонентов.
По 3 семейства на компетенцию сверх простых шаблонов items.py; a, b — экспертная оценка до калибровки."""

from app.services.items import _choice, _log, family

# --- Отладка UI ---


@family("fe_dbg_undefined", "Frontend", "Отладка UI", "choice", 2.2, -0.3)
def _(rng):
    comp, res = rng.choice([("ProductList", "products"), ("OrderTable", "orders"), ("ReviewFeed", "reviews"), ("CartItems", "cart")])
    s, ms = rng.randint(10, 50), rng.randint(240, 900)
    lines = [
        _log(f"10:{s:02d}:01.120", "vite", "INFO", f"page reload src/pages/{comp}.tsx"),
        _log(f"10:{s:02d}:01.204", "console", "ERROR", f"Uncaught TypeError: Cannot read properties of undefined (reading 'map')\n    at {comp} ({comp}.tsx:{rng.randint(14, 40)}:{rng.randint(12, 30)})"),
        _log(f"10:{s:02d}:01.205", "console", "WARN", f"The above error occurred in the <{comp}> component"),
        _log(f"10:{s:02d}:02.{ms:03d}", "network", "INFO", f"GET /api/{res} 200 ({ms + 900} ms), body: [{rng.randint(12, 80)} items]"),
    ]
    opts, key = _choice(rng, "Первый рендер идёт до ответа API: начальное состояние undefined, нужно задать [] или показывать загрузку", [
        f"API /api/{res} вернул не массив, а объект с полем {res}",
        "Vite не пересобрал модуль после изменения, нужен полный перезапуск dev-сервера",
        "У элементов списка нет key, поэтому React не может отрисовать map",
    ])
    return {"scene_title": "Белый экран", "story": f"Понедельник. Экран {comp} падает сразу при открытии. Состояние объявлено как useState(), данные грузятся в useEffect.",
            "prompt": "Почему компонент падает?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("fe_dbg_hydration", "Frontend", "Отладка UI", "choice", 2.3, 1.1)
def _(rng):
    city, off = rng.choice([("Москвы", 3), ("Екатеринбурга", 5), ("Новосибирска", 7), ("Владивостока", 10)])
    day, h, m = rng.randint(1, 28), rng.randint(0, 12), rng.randint(0, 59)
    srv, cli = f"{day:02d}.10.2026, {h:02d}:{m:02d}", f"{day:02d}.10.2026, {h + off:02d}:{m:02d}"
    comp = rng.choice(["DeliveryDate", "OrderCard", "SlotPicker"])
    lines = [
        _log("14:32:07", "browser", "WARN", f"Warning: Text content did not match. Server: \"{srv}\" Client: \"{cli}\"\n    at time\n    at {comp}"),
        _log("14:32:07", "browser", "ERROR", "Error: Hydration failed because the initial UI does not match what was rendered on the server."),
        _log("14:32:07", "browser", "WARN", "There was an error while hydrating. Switched to client rendering."),
        _log("14:32:08", "ssr", "INFO", f"GET /orders/{rng.randint(10000, 99999)} 200 render {rng.randint(40, 120)} ms (node, container ssr-{rng.randint(1, 4)})"),
    ]
    opts, key = _choice(rng, "Дата форматируется в часовом поясе процесса, а на сервере и в браузере он разный: передавать timeZone явно или форматировать на клиенте", [
        "CDN отдал закэшированный HTML от прошлой выкладки, поэтому время в разметке старое",
        "Сервер рендеринга и браузер используют разные версии React",
        f"У элементов списка в {comp} неуникальные key, и React перепутал узлы при гидрации",
    ])
    return {"scene_title": "Мерцающая дата", "story": f"Пользователи из {city} жалуются: время доставки на секунду показывается одно, потом меняется. В консоли — ошибка гидрации.",
            "prompt": "В чём причина?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("fe_dbg_race", "Frontend", "Отладка UI", "mark", 2.3, 1.9)
def _(rng):
    comp, res, q1, q2 = rng.choice([("ProductSearch", "products", "ноут", "ноутбук"), ("CitySearch", "cities", "Ново", "Новосибирск"),
                                    ("UserSearch", "users", "ива", "иванова")])
    lines = [f"function {comp}() {{", '  const [query, setQuery] = useState("");', "  const [items, setItems] = useState([]);"]
    if rng.random() < 0.5:
        lines.append("  const { t } = useTranslation();")
    lines += ["", "  useEffect(() => {", f"    fetch(`/api/{res}?q=${{encodeURIComponent(query)}}`)", "      .then((r) => r.json())",
              "      .then((data) => setItems(data));"]
    key = len(lines)
    lines += ["  }, [query]);", "", "  return <Results items={items} onSearch={setQuery} />;", "}"]
    return {"scene_title": "Чужие результаты", "story": f"Если быстро набрать «{q2}», под строкой поиска иногда остаются результаты для «{q1}». Сервер отвечает на запросы за разное время.",
            "prompt": "Нажмите на строку, из-за которой на экране остаются результаты устаревшего запроса.",
            "panel": {"type": "code", "lang": "tsx", "lines": lines}, "key": [key, key + 1]}


# --- Производительность ---


@family("fe_perf_lcp", "Frontend", "Производительность", "choice", 2.1, -1.3)
def _(rng):
    d0, rel = rng.randint(1, 20), rng.randint(3, 5)
    w, hgt, mb = rng.choice([(3840, 1600), (4000, 2000), (5120, 2160)]) + (rng.choice([4.2, 4.8, 5.6]),)
    x = [f"{d0 + i:02d}.10" for i in range(8)]
    lcp = [rng.randint(1800, 2300) if i < rel else rng.randint(5200, 6400) for i in range(8)]
    weight = [round(rng.uniform(1.2, 1.6), 1) if i < rel else round(mb + rng.uniform(1.2, 1.6), 1) for i in range(8)]
    panel = {"type": "chart", "x": x, "marker": {"i": rel, "label": "новый баннер"}, "series": [
        {"name": "LCP p75 главной, мс", "axis": "left", "max": 8000, "data": lcp},
        {"name": "вес главной, МБ", "axis": "right", "max": 10, "data": weight},
    ]}
    opts, key = _choice(rng, "Пережать баннер в AVIF/WebP под размер экрана (srcset)", [
        "Добавить баннеру loading=\"lazy\", чтобы он не мешал загрузке остальной страницы",
        "Перенести скрипты аналитики в конец body, тогда главная станет легче",
        "Включить HTTP/2 push для баннера, чтобы он приходил вместе с HTML",
    ])
    return {"scene_title": "Медленная главная", "story": f"Маркетинг заменил баннер на главной на PNG {w}×{hgt}. С этого дня LCP вырос почти втрое, остальной код не менялся.",
            "prompt": "Что сделать в первую очередь?", "panel": panel, "options": opts, "key": key}


@family("fe_perf_context", "Frontend", "Производительность", "choice", 2.2, 1.1)
def _(rng):
    prov, ctx, q, s = rng.choice([("FiltersProvider", "FiltersContext", "query", "sort"), ("CatalogProvider", "CatalogContext", "search", "category"),
                                  ("TableProvider", "TableContext", "filter", "columns")])
    n = rng.choice([2000, 3000, 5000])
    cap = q[0].upper() + q[1:]
    lines = [f"export function {prov}({{ children }}) {{", f'  const [{q}, set{cap}] = useState("");', f"  const [{s}, set{s.capitalize()}] = useState(null);"]
    if rng.random() < 0.5:
        lines.append("  const user = useCurrentUser();")
    lines += ["  return (", f"    <{ctx}.Provider value={{{{ {q}, set{cap}, {s}, set{s.capitalize()} }}}}>",
              "      {children}", f"    </{ctx}.Provider>", "  );", "}", "", f"// DataTable: const {{ {s} }} = useContext({ctx});"]
    opts, key = _choice(rng, f"Таблица читает весь контекст и перерисовывается от каждого символа: вынести {q} в отдельный контекст, value мемоизировать", [
        "Заменить useState на useReducer: React перестанет перерисовывать потребителей контекста",
        "Перенести Provider в корень приложения, тогда таблица не будет обновляться при вводе",
        "Это особенность dev-сборки: в production React не перерисовывает потребителей контекста",
    ])
    return {"scene_title": "Ввод тормозит", "story": f"Каждый символ в поле поиска перерисовывает все {n} строк DataTable, хотя таблица использует только {s}. Ввод заметно запаздывает.",
            "prompt": "Что исправить?", "panel": {"type": "code", "lang": "tsx", "lines": lines}, "options": opts, "key": key}


@family("fe_perf_inp", "Frontend", "Производительность", "choice", 2.3, 2.1)
def _(rng):
    d0, rel = rng.randint(1, 20), rng.randint(2, 4)
    ms, n = rng.randint(550, 900), rng.choice([30, 50, 80])
    x = [f"{d0 + i:02d}.10" for i in range(8)]
    inp = [rng.randint(110, 180) if i < rel else rng.randint(520, 760) for i in range(8)]
    longt = [rng.randint(2, 5) if i < rel else rng.randint(18, 30) for i in range(8)]
    panel = {"type": "chart", "x": x, "marker": {"i": rel, "label": "релиз фильтров"}, "series": [
        {"name": "INP p75 каталога, мс", "axis": "left", "max": 1000, "data": inp},
        {"name": "долгих задач за сессию", "axis": "right", "max": 40, "data": longt},
    ]}
    opts, key = _choice(rng, "Сначала отрисовать отклик на клик, а сортировку дробить с уступкой потоку или увести в Web Worker", [
        "Обернуть обработчик клика в requestAnimationFrame: работа уйдёт с главного потока",
        "Поставить debounce 300 мс на кнопку «Применить», чтобы не было лишних кликов",
        "Включить will-change: transform для таблицы, чтобы браузер рендерил её на GPU",
    ])
    return {"scene_title": "Отклик на клик", "story": f"После релиза фильтров вырос INP. В профиле: клик «Применить» запускает одну задачу на {ms} мс — синхронная фильтрация и сортировка {n} тыс. товаров, затем рендер.",
            "prompt": "Как вернуть отзывчивость?", "panel": panel, "options": opts, "key": key}


# --- Ревью кода ---


@family("fe_rv_xss", "Frontend", "Ревью кода", "mark", 2.2, -1.0)
def _(rng):
    comp, ent, who = rng.choice([("Comment", "comment", "комментариев"), ("Review", "review", "отзывов"), ("Message", "message", "сообщений в чате")])
    lines = [f"function {comp}({{ {ent} }}) {{", "  return (", f'    <article className="{ent}">', f"      <b>{{{ent}.author}}</b>"]
    if rng.random() < 0.5:
        lines.append(f"      <time>{{formatDate({ent}.createdAt)}}</time>")
    lines.append(f"      <div dangerouslySetInnerHTML={{{{ __html: {ent}.text }}}} />")
    key = len(lines)
    lines += [f"      <Likes count={{{ent}.likes}} />", "    </article>", "  );", "}"]
    return {"scene_title": "Переносы строк", "story": f"Стажёр сделал вывод {who} с сохранением форматирования. Текст пишут сами пользователи. Ревью за вами.",
            "prompt": "Нажмите на строку с уязвимостью.", "panel": {"type": "code", "lang": "tsx", "lines": lines, "caption": f"PR #{rng.randint(300, 899)} · «форматирование {who}»"},
            "key": key}


@family("fe_rv_stale_closure", "Frontend", "Ревью кода", "mark", 2.2, 0.9)
def _(rng):
    comp, label, start = rng.choice([("BookingTimer", "до конца брони", 600), ("OtpCountdown", "до повторной отправки кода", 60),
                                     ("PaymentTimer", "на оплату", 900)])
    lines = [f"function {comp}() {{", f"  const [seconds, setSeconds] = useState({start});"]
    if rng.random() < 0.5:
        lines.append("  const format = useDurationFormat();")
    lines += ["", "  useEffect(() => {", "    const id = setInterval(() => {", "      setSeconds(seconds - 1);"]
    key = len(lines)
    lines += ["    }, 1000);", "    return () => clearInterval(id);", "  }, []);", "", "  return <span>{seconds}</span>;", "}"]
    return {"scene_title": "Замерший таймер", "story": f"Таймер «{label}» показывает {start}, затем {start - 1} и замирает, хотя интервал продолжает срабатывать каждую секунду.",
            "prompt": "Нажмите на строку с причиной.", "panel": {"type": "code", "lang": "tsx", "lines": lines}, "key": [key, key + 3]}


@family("fe_rv_refresh", "Frontend", "Ревью кода", "mark", 2.3, 2.0)
def _(rng):
    cl, n = rng.choice(["api", "http", "client"]), rng.randint(4, 8)
    lines = [f"{cl}.interceptors.response.use(undefined, async (error) => {{", "  const original = error.config;"]
    if rng.random() < 0.5:
        lines.append("  // повторяем запрос один раз с новым токеном")
    lines += ["  if (error.response?.status !== 401 || original._retry) throw error;", "  original._retry = true;",
              "  const tokens = await auth.refresh(getRefreshToken());"]
    key = len(lines)
    lines += ["  saveTokens(tokens);", "  original.headers.Authorization = `Bearer ${tokens.access}`;", f"  return {cl}(original);", "});"]
    return {"scene_title": "Внезапный логаут", "story": f"Refresh-токен одноразовый: сервер выдаёт новый и отзывает старый. Когда access-токен истекает, дашборд с {n} параллельными запросами выкидывает пользователя на логин.",
            "prompt": "Нажмите на строку, из-за которой пользователя разлогинивает.",
            "panel": {"type": "code", "lang": "ts", "lines": lines, "caption": f"PR #{rng.randint(300, 899)} · «автообновление токена»"}, "key": key}


# --- Архитектура клиента ---


@family("fe_arch_drilling", "Frontend", "Архитектура клиента", "choice", 2.1, -1.1)
def _(rng):
    prop, what = rng.choice([("theme", "тема оформления"), ("locale", "язык интерфейса"), ("currency", "валюта цен")])
    tags = ["App", "Layout", "Sidebar", "Menu", "MenuItem", "Badge"][: rng.randint(5, 6)]
    lines = [f"{'  ' * i}<{t} {prop}={{{prop}}}{' />' if i == len(tags) - 1 else '>'}" for i, t in enumerate(tags)]
    opts, key = _choice(rng, f"Положить {prop} в контекст на верхнем уровне и читать там, где он нужен", [
        f"Записать {prop} в window и читать оттуда в любом компоненте",
        f"Сохранять {prop} в localStorage и читать в каждом компоненте при рендере",
        "Слить промежуточные компоненты в один, чтобы уровней стало меньше",
    ])
    return {"scene_title": "Пропсы насквозь", "story": f"Настройку «{what}» передают пропсами через {len(tags)} уровней. Половина компонентов её не использует, только передаёт дальше.",
            "prompt": "Как сделать проще?", "panel": {"type": "code", "lang": "tsx", "lines": lines}, "options": opts, "key": key}


@family("fe_arch_dedupe", "Frontend", "Архитектура клиента", "choice", 2.2, 0.2)
def _(rng):
    widgets = rng.sample(["Header", "Sidebar", "ProfileMenu", "Notifications", "CartBadge", "Greeting"], 4)
    s, t = rng.randint(10, 50), 100
    lines = []
    for i, w in enumerate(widgets):
        t += rng.randint(5, 40)
        lines.append(_log(f"Вт 11:{s:02d}:00.{t:03d}", "network", "INFO", f"GET /api/me 200 ({rng.randint(120, 300)} ms) initiator: {w}.tsx"))
    for w in rng.sample(widgets, 2):
        t += rng.randint(5, 40)
        lines.append(_log(f"Вт 11:{s:02d}:00.{t:03d}", "network", "INFO", f"GET /api/cart 200 ({rng.randint(150, 400)} ms) initiator: {w}.tsx"))
    lines.append(_log(f"Вт 11:{s:02d}:02.{rng.randint(100, 900):03d}", "lighthouse", "WARN", f"Time to Interactive {rng.randint(4, 7)}.{rng.randint(0, 9)} s"))
    opts, key = _choice(rng, "Общий слой серверного состояния с кэшем и дедупликацией запросов (TanStack Query, SWR или свой загрузчик)", [
        "Перенести запросы из useEffect в useLayoutEffect, чтобы они уходили раньше",
        "Хранить ответы API в localStorage без срока жизни и не запрашивать их снова",
        "Включить HTTP/2 на балансировщике: повторные запросы станут бесплатными",
    ])
    return {"scene_title": "Одни и те же запросы", "story": "Главная грузится медленно. В DevTools одни и те же запросы уходят по несколько раз: каждый виджет сам загружает данные в useEffect.",
            "prompt": "Как исправить архитектурно?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("fe_arch_federation", "Frontend", "Архитектура клиента", "choice", 2.3, 2.2)
def _(rng):
    mf, widget = rng.choice([("checkout", "CartWidget"), ("loyalty", "BonusWidget"), ("support", "ChatWidget")])
    host_v, mf_v = rng.choice([("18.2.0", "18.3.1"), ("18.3.1", "18.2.0")])
    lines = [
        _log("Ср 15:02:11", "host", "INFO", f"loaded remote {mf}@https://static.example.local/{mf}/remoteEntry.js"),
        _log("Ср 15:02:11", "build", "INFO", f"{mf} remoteEntry: bundled react@{mf_v}, react-dom@{mf_v} ({rng.randint(120, 160)} kB)"),
        _log("Ср 15:02:12", "browser", "WARN", "Warning: Invalid hook call. Hooks can only be called inside of the body of a function component.\n"
                                               "  3. You might have more than one copy of React in the same app"),
        _log("Ср 15:02:12", "browser", "ERROR", f"TypeError: Cannot read properties of null (reading 'useState')\n    at {widget} ({mf}/src/{widget}.tsx:{rng.randint(8, 30)})"),
        _log("Ср 15:02:12", "build", "INFO", f"host: react@{host_v}, ModuleFederationPlugin shared: {{}}"),
    ]
    opts, key = _choice(rng, f"В хосте и в {mf} объявить react и react-dom общими singleton-зависимостями с совместимым диапазоном версий", [
        f"Переписать {widget} на классовые компоненты: им хуки не нужны",
        "Включить React.StrictMode в хосте, чтобы найти побочные эффекты при рендере",
        f"Обновить в хосте только react-dom до {mf_v}, а react оставить прежним",
    ])
    return {"scene_title": "Чужой виджет", "story": f"Микрофронтенд {mf} соседней команды подключили к хосту через Module Federation. По отдельности оба работают, вместе {widget} падает.",
            "prompt": "Что исправить?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Доступность ---


@family("fe_a11y_label", "Frontend", "Доступность", "mark", 2.1, -1.4)
def _(rng):
    form, typ, ph = rng.choice([("входа", "password", "Пароль"), ("заказа", "tel", "Телефон"), ("оплаты", "text", "Промокод")])
    lines = ['<form class="checkout">', '  <label for="email">Почта</label>', '  <input id="email" type="email" autocomplete="email">']
    if rng.random() < 0.5:
        lines.append('  <p class="hint">Пришлём на неё чек</p>')
    lines.append(f'  <input type="{typ}" placeholder="{ph}">')
    key = len(lines)
    lines += ['  <button type="submit">Продолжить</button>', "</form>"]
    return {"scene_title": "Безымянное поле", "story": f"Тестировщик проверяет форму {form} со скринридером. На одном из полей тот читает только «поле ввода», и непонятно, что вводить.",
            "prompt": "Нажмите на строку, которую нужно исправить.", "panel": {"type": "code", "lang": "html", "lines": lines}, "key": key}


@family("fe_a11y_modal", "Frontend", "Доступность", "choice", 2.2, 1.0)
def _(rng):
    title = rng.choice(["Удалить адрес?", "Подтвердите заказ", "Выход из аккаунта"])
    lines = ["function openModal() {", '  overlay.hidden = false;', '  modal.style.display = "block";', "}", "",
             '<div class="overlay" hidden></div>', '<div class="modal">', f"  <h2>{title}</h2>",
             '  <button class="btn">Да</button>', '  <button class="btn ghost">Отмена</button>', "</div>"]
    opts, key = _choice(rng, "Открывать через <dialog>.showModal() или вручную: фокус в окно, ловушка фокуса, Esc и возврат фокуса на кнопку", [
        "Поднять z-index окна выше всех элементов страницы, тогда Tab не уйдёт под него",
        "Добавить окну role=\"alert\": скринридер сам переведёт туда фокус",
        "Сделать подложку непрозрачной, чтобы страница под окном не отвлекала",
    ])
    return {"scene_title": "Окно с клавиатуры", "story": f"Окно «{title}» открывается по кнопке. С клавиатуры фокус остаётся на странице под окном, Tab ходит по ссылкам за подложкой, Esc ничего не делает.",
            "prompt": "Как исправить?", "panel": {"type": "code", "lang": "js", "lines": lines}, "options": opts, "key": key}


@family("fe_a11y_live", "Frontend", "Доступность", "choice", 2.2, 1.9)
def _(rng):
    comp, msg = rng.choice([("PaymentForm", "Карта отклонена банком"), ("SignupForm", "Эта почта уже занята"), ("PromoForm", "Промокод истёк")])
    lines = [f"function {comp}() {{", "  const [error, setError] = useState(null);", "  // submit() вызывает setError(текст) при ошибке сервера", "  return (",
             "    <form onSubmit={submit}>", "      {/* … поля … */}", "      {error && (", '        <div role="status" aria-live="polite">{error}</div>', "      )}",
             "    </form>", "  );", "}"]
    opts, key = _choice(rng, "Live-регион должен быть в DOM до изменения: рендерить контейнер всегда и менять только текст в нём", [
        "Заменить polite на assertive: тогда объявление гарантировано в любом скринридере",
        "Добавить контейнеру tabindex=\"0\", чтобы скринридер его заметил",
        "Продублировать текст ошибки в aria-label всей формы",
    ])
    return {"scene_title": "Немая ошибка", "story": f"Ошибку «{msg}» видно на экране, но скринридер её не объявляет, хотя у контейнера стоит aria-live.",
            "prompt": "В чём причина и как исправить?", "panel": {"type": "code", "lang": "tsx", "lines": lines}, "options": opts, "key": key}


# --- Алгоритмы ---


@family("fe_alg_map", "Frontend", "Алгоритмы", "choice", 2.1, -1.2)
def _(rng):
    n, m = rng.randint(20, 90), rng.randint(5, 30)
    a, b, fk = rng.choice([("orders", "users", "userId"), ("tickets", "agents", "agentId"), ("payments", "merchants", "merchantId")])
    lines = [f"const rows = {a}.map((x) => ({{", "  ...x,", f"  owner: {b}.find((y) => y.id === x.{fk}),", "}));"]
    opts, key = _choice(rng, f"Один раз собрать Map по id из {b} и брать из неё: O(n + m)", [
        "Заменить find на filter(...)[0]: на больших массивах он быстрее",
        "Переписать map на цикл for: основная потеря — в вызовах функций",
        f"Отсортировать {a} по {fk}: тогда find сам станет бинарным поиском",
    ])
    return {"scene_title": "Склейка в браузере", "story": f"Таблица склеивает на клиенте {n} тыс. записей {a} и {m} тыс. записей {b}. Склейка идёт несколько секунд и вешает вкладку.",
            "prompt": "Как ускорить?", "panel": {"type": "code", "lang": "ts", "lines": lines}, "options": opts, "key": key}


@family("fe_alg_tree_path", "Frontend", "Алгоритмы", "choice", 2.1, 0.3)
def _(rng):
    n = rng.choice([8, 15, 40])
    root, child, leaf = rng.choice([("Электроника", "Ноутбуки", "Игровые"), ("Дом", "Кухня", "Посуда"), ("Спорт", "Велосипеды", "Шоссейные")])
    i1, i2, i3 = rng.randint(1, 9), rng.randint(10, 99), rng.randint(100, 999)
    lines = ["[", f'  {{ "id": {i1}, "parentId": null, "name": "{root}" }},', f'  {{ "id": {i3}, "parentId": {i2}, "name": "{leaf}" }},',
             f'  {{ "id": {i2}, "parentId": {i1}, "name": "{child}" }},', "  …", "]"]
    opts, key = _choice(rng, "Один раз построить Map id → категория и подниматься по parentId до корня: путь за O(глубины)", [
        "На каждом уровне заново фильтровать весь список по parentId: это O(log n)",
        "Отсортировать категории по name и искать родителя бинарным поиском",
        "Сериализовать список в строку и искать цепочку родителей регулярным выражением",
    ])
    return {"scene_title": "Хлебные крошки", "story": f"API отдаёт {n} тыс. категорий плоским списком с parentId, порядок произвольный. Для «хлебных крошек» на каждой странице нужен путь от корня до текущей категории.",
            "prompt": "Как считать путь?", "panel": {"type": "code", "lang": "json", "lines": lines}, "options": opts, "key": key}


@family("fe_alg_virtual", "Frontend", "Алгоритмы", "choice", 2.2, 1.3)
def _(rng):
    n, what = rng.choice([50, 120, 300]), rng.choice(["сообщений", "событий", "комментариев"])
    hs = [rng.choice([40, 64, 96, 128, 220]) for _ in range(6)]
    lines = [f"// {n} тыс. строк, высота каждой известна после измерения", f"const heights = [{', '.join(map(str, hs))}, …];",
             "const offsets = prefixSums(heights); // offsets[i] — верх строки i, массив возрастает", "", "function firstVisible(scrollTop: number): number {",
             "  // ?", "}"]
    opts, key = _choice(rng, "Бинарный поиск по offsets: O(log n) на кадр", [
        "Идти от первой строки, суммируя высоты: на кадр это O(1)",
        "Разделить scrollTop на среднюю высоту строки: результат точный",
        "Хеш-таблица offset → индекс: поиск по любому scrollTop за O(1)",
    ])
    return {"scene_title": "Виртуальный список", "story": f"Лента из {n} тыс. {what} с разной высотой строк. На каждом кадре прокрутки нужно найти первую видимую строку по scrollTop.",
            "prompt": "Как реализовать firstVisible?", "panel": {"type": "code", "lang": "ts", "lines": lines}, "options": opts, "key": key}
