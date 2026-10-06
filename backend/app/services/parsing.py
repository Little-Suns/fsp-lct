"""Разбор свободного текста: потребность работодателя и резюме кандидата.

Сначала локальная LLM (JSON по справочнику); каждое поле проверяется по catalog, а что не прошло проверку
или не пришло — добирают правила. Суммы всегда берутся из регулярок, если они нашли хоть что-то: числа
правила читают точнее модели. Персональные признаки (пол, возраст, вуз, фото, национальность) не извлекаются
и вырезаются из текста до разбора — подбору они не нужны и запрещены к использованию.

Из резюме дополнительно достаются контакты (имя, почта, Telegram) — только чтобы предзаполнить форму самого
кандидата; в подбор и в модель они не попадают. Роли, софт-скиллы и места работы — для профиля и PDF-профиля,
в ранжировании и грейде не участвуют.
"""

import math
import re
from datetime import datetime

from app import catalog
from app.services import llm

_W = "a-zа-яё0-9_"
_B = rf"(?<![{_W}])"  # левая граница слова для кириллицы и латиницы


def _skill_patterns() -> list[tuple[re.Pattern, str]]:
    pairs = {(syn, canon) for canon, syns in catalog.SKILLS.items() for syn in [*syns, canon.lower()]}
    out = []
    for syn, canon in sorted(pairs, key=lambda p: (-len(p[0]), p[0])):
        tail = "[а-яё]{0,3}" if re.search("[а-яё]", syn) else ""  # «питоне», «кафкой», «постгресом»
        out.append((re.compile(rf"{_B}{re.escape(syn)}{tail}(?![{_W}])"), canon))
    return out


_SKILL_RX = _skill_patterns()
_CANON = {k.lower(): k for k in catalog.SKILLS} | {s: k for k, syns in catalog.SKILLS.items() for s in syns}


def canon_skill(s: str) -> str | None:
    """«postgres» → «PostgreSQL»; не из справочника → None."""
    return _CANON.get(str(s).strip().lower())


def canon_skills(items) -> list[str]:
    out = [canon_skill(s) for s in items if isinstance(s, str)] if isinstance(items, list) else []  # от модели может прийти не список
    return list(dict.fromkeys(s for s in out if s))


def extract_skills(text: str, skip: frozenset[str] = frozenset()) -> list[str]:
    """Навыки из справочника в порядке первого упоминания. Длинные синонимы первыми и вырезаются,
    чтобы «node.js» не дал ещё и «js»."""
    s = text.lower()
    found: dict[str, int] = {}
    for rx, canon in _SKILL_RX:
        for m in rx.finditer(s):
            if m.group(0) in skip:
                continue
            found[canon] = min(found.get(canon, m.start()), m.start())
            s = s[: m.start()] + " " * (m.end() - m.start()) + s[m.end() :]
    return sorted(found, key=found.get)


# ---------- персональные признаки ----------

_PERSONAL = [
    ("возраст", r"(?:до|от|не старше|не моложе|старше|моложе)\s*\d{2}\s*(?:лет|года|год)|возраст\w*"),
    ("пол", rf"{_B}(?:мужчин\w*|женщин\w*|девушк\w*|парн(?:я|ей|и|ем)?(?![{_W}])|мужск\w* пол\w*|женск\w* пол\w*)"),
    ("вуз", rf"{_B}(?:выпускник\w*|окончивш\w*|высш\w* образован\w*|мгу|мфти|вшэ|итмо|бауманк\w*|мгту)(?![{_W}])"),
    ("фото", rf"{_B}фото\w*"),
    ("национальность", rf"{_B}(?:славян\w*|национальн\w*)"),
]


def _strip_personal(text: str) -> tuple[str, list[str]]:
    ignored = []
    for kind, rx in _PERSONAL:
        text, n = re.subn(rx, " ", text, flags=re.IGNORECASE)
        if n:
            ignored.append(kind)
    return text, ignored


# ---------- категория ----------

_SPEC_RX = {
    "Backend": r"бэк|бек|backend|back-end|серверн",
    "Frontend": r"фронт|frontend|front-end|верстальщ",
    "Mobile": r"мобильн|mobile|ios|android|андроид|flutter",
    "ML / DS": rf"ml(?![{_W}])|машинн\w* обучен|data scien|дата.?сайент|nlp(?![{_W}])|компьютерн\w* зрени|computer vision",
    "Data Eng / Analytics": rf"data engineer|дата.?инженер|инженер\w* данных|аналитик|analyst|bi(?![{_W}])|dwh(?![{_W}])|etl(?![{_W}])",
    "DevOps / SRE": rf"devops|девопс|sre(?![{_W}])|инфраструктур",
    "QA": rf"qa(?![{_W}])|тестировщ|автотест|тестирован",
    "Security": r"безопасн|security|пентест|pentest|appsec|ctf",
}
_SPEC_BY_SKILL = {
    "Backend": {"Python", "Go", "Java", "Kotlin", "Node.js", "C#", "Django", "FastAPI", "gRPC"},
    "Frontend": {"React", "Vue", "Angular", "TypeScript", "JavaScript"},
    "Mobile": {"Swift", "Flutter"},
    "ML / DS": {"PyTorch", "scikit-learn", "LLM", "Computer Vision"},
    "Data Eng / Analytics": {"Spark", "Airflow", "ClickHouse"},
    "DevOps / SRE": {"Terraform", "Prometheus"},
    "QA": {"Selenium"},
    "Security": {"Pentest"},
}
# трек: (регулярка по тексту, навыки-подсказки)
_TRACK_HINTS = {
    "Python": (r"python|питон", ["Python"]),
    "Go": (rf"golang|go(?![{_W}])", ["Go"]),
    "Java / Kotlin": (r"java|kotlin|котлин|джава", ["Java", "Kotlin"]),
    "Node.js": (r"node", ["Node.js"]),
    "C# / .NET": (r"c#|\.net|dotnet", ["C#"]),
    "React": (r"react|реакт", ["React"]),
    "Vue": (r"vue", ["Vue"]),
    "Angular": (r"angular", ["Angular"]),
    "iOS": (r"ios|swift", ["Swift"]),
    "Android": (r"android|андроид|kotlin", ["Kotlin"]),
    "Flutter": (r"flutter|dart", ["Flutter"]),
    "Classic ML": (r"классическ|scikit|sklearn|бустинг|catboost", ["scikit-learn"]),
    "CV": (rf"cv(?![{_W}])|компьютерн\w* зрени|computer vision", ["Computer Vision"]),
    "NLP / LLM": (rf"nlp|llm|rag(?![{_W}])", ["LLM"]),
    "Data Engineering": (r"инженер\w* данных|data engineer|дата.?инженер|etl|dwh", ["Spark", "Airflow"]),
    "BI / Analytics": (rf"bi(?![{_W}])|аналит|дашборд", []),
    "Kubernetes": (r"kubernetes|k8s|кубер", ["Kubernetes"]),
    "Cloud": (r"cloud|облак|aws", ["Terraform"]),
    "Manual": (r"ручн|manual", []),
    "Automation": (r"автотест|automation|автоматиз", ["Selenium"]),
    "AppSec": (r"appsec|безопасн\w* разработ", []),
    "Pentest": (r"pentest|пентест", ["Pentest"]),
}


def _first(rx: str, s: str) -> int:
    m = re.search(rf"{_B}(?:{rx})", s)
    return m.start() if m else math.inf


def _spec(s: str, skills: list[str]) -> str | None:
    pos = {spec: _first(rx, s) for spec, rx in _SPEC_RX.items()}
    best = min(pos, key=pos.get)
    if pos[best] < math.inf:
        return best
    votes = {spec: sum(1 for k in skills if k in ks) for spec, ks in _SPEC_BY_SKILL.items()}
    best = max(votes, key=votes.get)
    return best if votes[best] else None


def _track(s: str, spec: str, skills: list[str]) -> str:
    tracks = catalog.TRACKS[spec]
    pos = {t: _first(_TRACK_HINTS[t][0], s) if t in _TRACK_HINTS else math.inf for t in tracks}
    best = min(pos, key=pos.get)
    if pos[best] < math.inf:
        return best
    # в тексте названия трека нет — по навыкам (найдены через синонимы), в порядке упоминания
    for k in skills:
        for t in tracks:
            if k in _TRACK_HINTS.get(t, ("", []))[1]:
                return t
    return tracks[0]


_GRADE_RX = {
    "Intern": r"интерн|стаж[её]р|intern",
    "Junior": r"джун|junior|младш",
    "Middle": r"мидл|миддл|middle",
    "Senior": r"с[еи]нь[её]р|с[еи]ньор|senior|старш",
    "Lead": rf"тимлид|техлид|лид(?![{_W}])|lead",
}


def _grade(s: str) -> str | None:
    pos = {g: _first(rx, s) for g, rx in _GRADE_RX.items()}
    best = min(pos, key=pos.get)
    return best if pos[best] < math.inf else None


def _format(s: str) -> str | None:
    if _first(r"гибрид|hybrid", s) < math.inf:
        return "Гибрид"
    pos = {"Удалённо": _first(r"удал[её]н|remote|из дома", s), "Офис": _first(r"офис|office", s)}
    best = min(pos, key=pos.get)
    return best if pos[best] < math.inf else None


_CITIES = {
    "Москва": r"москв|мск(?![а-яё])",
    "Санкт-Петербург": r"петербург|спб(?![а-яё])|питер(?![а-яё]?он)",
    "Новосибирск": r"новосиб",
    "Екатеринбург": r"екатеринбург|екб(?![а-яё])",
    "Казань": r"казан",
    "Нижний Новгород": r"нижн\w* новгород",
    "Краснодар": r"краснодар",
    "Самара": r"самар",
    "Ростов-на-Дону": r"ростов",
    "Иннополис": r"иннополис",
}


def _city(s: str) -> str | None:
    pos = {c: _first(rx, s) for c, rx in _CITIES.items()}
    best = min(pos, key=pos.get)
    return best if pos[best] < math.inf else None


# ---------- зарплата ----------

_NUM = r"(\d{1,3}(?:[  ]\d{3})+|\d+(?:[.,]\d+)?)\s*(млн|тыс\w*\.?|т\.?\s?р\.?|к(?![а-яё])|k(?![a-z]))?"
_SAL_MIN, _SAL_MAX = 20_000, 3_000_000


def _money(num: str, unit: str | None) -> int | None:
    v = float(re.sub(r"[  ]", "", num).replace(",", "."))
    if unit and unit.startswith("млн"):
        v *= 1_000_000
    elif unit or v < 1000:  # «до 300» в ИТ-вакансии — тысячи рублей
        v *= 1000
    v = int(round(v / 1000) * 1000)
    return v if _SAL_MIN <= v <= _SAL_MAX else None


def _salary(s: str) -> tuple[int | None, int | None]:
    """«от 250 до 300», «250–300к», «до 300 на руки», «от 250», «300к». Одиночное число — потолок бюджета."""
    s = re.sub(r"\d+\s*(?:лет|года|год)\b", " ", s)  # стаж — не деньги
    m = re.search(rf"(?:от\s*)?{_NUM}\s*(?:-|–|—|до)\s*{_NUM}", s)
    if m and (a := _money(m[1], m[2] or m[4])) and (b := _money(m[3], m[4])):
        return min(a, b), max(a, b)
    lo = hi = None
    for m in re.finditer(rf"{_B}до\s*{_NUM}", s):
        if hi := _money(m[1], m[2]):
            break
    for m in re.finditer(rf"{_B}от\s*{_NUM}", s):
        if lo := _money(m[1], m[2]):
            break
    if lo is None and hi is None:
        for m in re.finditer(rf"{_NUM}\s*(?:₽|руб)?", s):
            if (m[2] or re.match(r".*(?:₽|руб)", m[0]) or len(re.sub(r"\D", "", m[1])) >= 5) and (hi := _money(m[1], m[2])):
                break
    return lo, hi


def fill_fork(spec: str, grade: str, city: str | None, lo: int | None, hi: int | None) -> tuple[int, int, str | None]:
    """Достраивает вилку по рынку. «до X» → от = min(медиана, X/1,25), не ниже p25: ширина ≤ 25 % (лимит 40 %)
    и нижняя граница не выше медианы. Для Backend · Middle · Москва и «до 300» даёт 240 000, как в макете."""
    m = catalog.market(spec, grade, city)
    r5 = lambda v: int(round(v / 5000) * 5000)
    if lo and hi:
        return lo, hi, None
    if hi:
        lo = max(m["p25"], min(m["p50"], r5(hi / 1.25)))
        lo = min(lo, hi)
        return lo, hi, f"«до {hi // 1000}» → нижнюю границу предложили по рынку: {lo:,} ₽ (медиана {m['p50']:,} ₽)".replace(",", " ")
    if lo:
        hi = max(m["p50"], r5(lo * 1.25))
        return lo, hi, f"«от {lo // 1000}» → верхнюю границу предложили по рынку: {hi:,} ₽".replace(",", " ")
    return m["p50"], m["p75"], "Вилка не указана → предложили по рынку: от медианы до 75-го перцентиля"


# ---------- потребность ----------

_NICE_RX = r"хорошо бы|желательн\w*|будет плюсом|плюсом будет|как плюс|приветству\w*|nice to have|было бы (?:здорово|неплохо|хорошо|круто)|опционально|не обязательн\w*|необязательн\w*"


def _rules_need(text: str) -> dict:
    s = text.lower()
    must, nice = [], []
    for sent in re.split(r"[.;!?](?=\s|$)|\n", s):
        m = re.search(_NICE_RX, sent)
        if not m:
            must += extract_skills(sent)
        elif tail := extract_skills(sent[m.end() :]):  # «хорошо бы Kubernetes, Terraform»
            must += extract_skills(sent[: m.start()])
            nice += tail
        else:  # «terraform желательно» — желательна часть до запятой
            a = sent.rfind(",", 0, m.start()) + 1
            must += extract_skills(sent[:a])
            nice += extract_skills(sent[a:])
    must = list(dict.fromkeys(must))
    nice = [k for k in dict.fromkeys(nice) if k not in must]
    spec = _spec(s, must + nice) or "Backend"
    lo, hi = _salary(s)
    return {
        "spec": spec,
        "track": _track(s, spec, must + nice),
        "grade": _grade(s),
        "must": must,
        "nice": nice,
        "salary_from": lo,
        "salary_to": hi,
        "format": _format(s),
        "city": _city(s),
    }


_NEED_SYSTEM = (
    "Ты разбираешь текст потребности работодателя в ИТ-специалисте. Верни JSON: "
    '{"spec": str, "track": str, "grade": str, "must": [str], "nice": [str], "salary_from": int|null, '
    '"salary_to": int|null, "format": str|null, "city": str|null}. '
    f"spec — одно из {catalog.SPECS}; track — из {catalog.TRACKS}; grade — из {catalog.GRADES}; "
    f"format — из {catalog.FORMATS}; навыки — только из справочника {sorted(catalog.SKILLS)}. "
    "must — обязательные навыки, nice — желательные («хорошо бы», «плюсом»). Зарплата в рублях на руки в месяц: "
    "«до 300» → salary_to=300000, нижнюю границу не выдумывай. Пол, возраст, вуз, внешность, национальность "
    "не извлекай и не учитывай."
)


def _valid_money(v) -> int | None:
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    v = v * 1000 if v < 1000 else v
    return int(v) if _SAL_MIN <= v <= _SAL_MAX else None


def parse_need(text: str, *, use_llm: bool = True) -> dict:
    clean, ignored = _strip_personal(text)
    out = _rules_need(clean)
    parsed_by = "rules"
    got = llm.chat_json(_NEED_SYSTEM, clean) if use_llm else None
    if got:
        parsed_by = "llm"
        if got.get("spec") in catalog.SPECS:
            out["spec"] = got["spec"]
        out["track"] = got.get("track") if got.get("track") in catalog.TRACKS[out["spec"]] else _track(clean.lower(), out["spec"], out["must"] + out["nice"])
        if got.get("grade") in catalog.GRADES:
            out["grade"] = got["grade"]
        must = canon_skills(got.get("must"))
        if must:
            out["must"] = must
            out["nice"] = [k for k in canon_skills(got.get("nice")) if k not in must]
        if out["salary_from"] is None and out["salary_to"] is None:  # числа правила читают точнее
            out["salary_from"], out["salary_to"] = _valid_money(got.get("salary_from")), _valid_money(got.get("salary_to"))
        if got.get("format") in catalog.FORMATS:
            out["format"] = got["format"]
        if isinstance(got.get("city"), str) and 0 < len(got["city"]) <= 64 and not out["city"]:
            out["city"] = got["city"].strip()
    hints = []
    if not out["grade"]:
        out["grade"] = "Middle"
        hints.append("Грейд не указан → поставили Middle, поправьте при необходимости")
    out["salary_from"], out["salary_to"], h = fill_fork(out["spec"], out["grade"], out["city"], out["salary_from"], out["salary_to"])
    if h:
        hints.append(h)
    if ignored:
        hints.append("Персональные признаки не используются в подборе: " + ", ".join(ignored))
    return {**out, "parsed_by": parsed_by, "hints": hints, "ignored": ignored}


# ---------- резюме ----------

_CV_SYSTEM = (
    "Ты разбираешь резюме ИТ-специалиста. Верни JSON: "
    '{"skills": [str], "years_exp": number|null, "spec": str|null, "track": str|null, "roles": [str], "soft_skills": [str]}. '
    f"Навыки — только из справочника {sorted(catalog.SKILLS)}; spec — из {catalog.SPECS}; track — из {catalog.TRACKS}; "
    f"roles — роли, которые человек выполнял, только из {list(catalog.ROLES)}; soft_skills — только из {list(catalog.SOFT_SKILLS)}, "
    "и только если в тексте есть опора (факт или прямое упоминание). "
    "years_exp — суммарный коммерческий опыт в годах. ФИО, контакты, возраст, пол, вуз и фото не извлекай."
)
_YEARS_RX = [
    r"опыт\w*[^.\n\d]{0,40}?(\d+(?:[.,]\d)?)\s*\+?\s*(?:год|года|лет)",
    r"(\d+(?:[.,]\d)?)\s*\+?\s*(?:год\w*|лет)\s+(?:коммерческ\w*\s+)?опыт",
    r"(\d+(?:[.,]\d)?)\s*\+?\s*years? of experience",
]
# период работы: «2019 — 2021», «03.2019 – н.в.», «март 2019 — июнь 2021», «2021 – по настоящее время»
# месяц — с левой границей и ограниченной длиной, иначе на длинной слитной строке поиск квадратичный
_MONTH = r"(?:(?<![а-яёa-z])(?:янв|фев|мар|апр|ма[йя]|июн|июл|авг|сен|окт|ноя|дек|jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[а-яёa-z]{0,6}\.?\s{1,3}|\d{1,2}[./]\s{0,3})?"
_RANGE_RX = re.compile(
    rf"{_MONTH}((?:19|20)\d\d)\s*(?:г\.?\s*)?(?:-|–|—|по)\s*{_MONTH}((?:19|20)\d\d|н\.?\s?в\.?|(?:по\s+)?настоящ\w*(?:\s+время)?|сейчас|present|now|текущ\w*)",
    re.IGNORECASE,
)
_EDU_RX = rf"{_B}(?:университет|институт|академи|колледж|техникум|вуз|мгу|мгту|мфти|вшэ|итмо|спбгу|бакалавр|магистр|аспирант|факультет|(?:university|college|bachelor|master(?:'s| of))(?![a-z]))"
# заголовок раздела: учёба — периоды в нём не работа; любой другой известный раздел учёбу закрывает
_SECTION_RX = (r"(образование|education|курсы|сертификаты|certificates)|(опыт|experience|места работы|work|карьер|career|трудов|employment|"
               r"проекты|projects|навыки|skills|о себе|about|достижения|achievements)")


def cv_experience(text: str) -> list[dict]:
    """Места работы по периодам: [{"from": 2019, "to": 2021 | None (по н. в.), "title": "Яндекс, бэкенд-разработчик"}].
    Название — текст после периода до следующего периода или конца предложения; если после пусто — перед периодом,
    затем следующая строка. Учёба (университет, бакалавр…) не считается работой."""
    text = re.sub(r"([-–—])[ \t]*\n\s*", r"\1 ", text)  # «2019 —⏎2021»: период разорван переносом
    lines = [ln.strip() for ln in text.splitlines()]
    out, edu = [], False
    for i, line in enumerate(lines):
        if len(line) < 40 and (sec := re.match(_SECTION_RX, line.lower())):  # заголовок раздела
            edu = bool(sec[1])
        ms = list(_RANGE_RX.finditer(line))
        for j, m in enumerate(ms):
            after = line[m.end() : ms[j + 1].start() if j + 1 < len(ms) else len(line)]
            before = line[ms[j - 1].end() if j else 0 : m.start()]
            title = ""
            for seg in (after, before, next((ln for ln in lines[i + 1 : i + 3] if ln and not _RANGE_RX.search(ln)), "") if j + 1 == len(ms) else ""):
                title = re.split(r"[;\n]|\.\s|\.$", seg.strip(" ,;:|·•—–-()\t"))[0].strip(" ,;:|·•—–-()")
                if title:
                    break
            if edu or re.search(_EDU_RX, f"{title} {after}".lower()):
                continue
            end = int(m[2]) if m[2][:1].isdigit() else None
            if end is not None and end < int(m[1]):
                continue
            out.append({"from": int(m[1]), "to": end, "title": re.sub(r"\s+", " ", title)[:120] or None})
    return out


def _years(s: str, experience: list[dict] | None = None) -> float | None:
    for rx in _YEARS_RX:
        if m := re.search(rx, s):
            return float(m[1].replace(",", "."))
    now = datetime.now().year
    spans = sorted((e["from"], e["to"] or now) for e in (experience if experience is not None else cv_experience(s)))
    total, end = 0, 0
    for a, b in spans:  # пересекающиеся периоды не суммируем дважды
        if b > end:
            total += b - max(a, end)
            end = b
    return float(min(total, 40)) if total else None


# ---------- резюме: контакты, роли, софт-скиллы ----------


def _dict_rx(d: dict[str, list[str]]) -> dict[str, re.Pattern]:
    return {k: re.compile(rf"{_B}(?:{'|'.join(v)})") for k, v in d.items()}


_ROLE_RX, _SOFT_RX = _dict_rx(catalog.ROLES), _dict_rx(catalog.SOFT_SKILLS)


def _by_dict(s: str, rxs: dict[str, re.Pattern]) -> list[str]:
    """Канонические значения справочника в порядке первого упоминания."""
    pos = {k: m.start() for k, rx in rxs.items() if (m := rx.search(s))}
    return sorted(pos, key=pos.get)


def canon_terms(items, allowed) -> list[str]:
    """Только значения справочника (роли, софт-скиллы), без дублей, в исходном порядке."""
    items = items if isinstance(items, list) else []  # от модели может прийти число или строка
    return list(dict.fromkeys(x for x in items if isinstance(x, str) and x in allowed))


# начало — только на границе токена и длины частей ограничены: иначе на длинной слитной строке поиск квадратичный
_EMAIL_RX = r"(?<![a-z0-9._%+-])[a-z0-9._%+-]{1,64}@[a-z0-9-]{1,63}(?:\.[a-z0-9-]{1,63}){0,8}\.[a-z]{2,24}"
_TG_RX = r"(?:(?<![\w.])t(?:elegram)?\.me/|telegram[\s:\-]{0,5}@?|(?<![\w.])tg[\s:\-]{0,5}@?|(?<![\w.@/])@)([a-z][a-z0-9_]{4,31})(?![\w@]|\.\w)"
_NAME_WORD = r"(?:[А-ЯЁ][а-яё]+(?:-[А-ЯЁ][а-яё]+)?|[A-Z][a-z]+(?:-[A-Z][a-z]+)?)"
_NOT_NAME = {
    "резюме", "опыт", "работы", "работа", "город", "формат", "стек", "навыки", "контакты", "образование", "себе", "профиль",
    "разработчик", "программист", "инженер", "аналитик", "тестировщик", "специалист", "developer", "engineer", "resume",
    "curriculum", "vitae", "summary", "experience", "skills", "contacts", "about", "fullstack", "data", "team", "lead",
    *(g.lower() for g in catalog.GRADES), *(w.lower() for c in _CITIES for w in re.split(r"[\s-]", c)),
    *(w.lower() for k, syns in catalog.SKILLS.items() for w in [k, *syns]),
}


def _name(text: str) -> str | None:
    """ФИО: «ФИО: …» или первая строка-фрагмент из 2–3 слов с заглавной, где нет должности, навыка, города."""
    # подпись поля — в начале строки и без учёта регистра, само имя — с заглавных (иначе «Company name: Yandex Cloud»)
    m = re.search(rf"^[ \t]{{0,5}}(?i:фио|имя|full name|name)[ \t]{{0,5}}[:\-][ \t]{{0,5}}({_NAME_WORD}(?:[ \t]+{_NAME_WORD}){{1,2}})(?![\w-])", text, re.MULTILINE)
    chunks = [m[1]] if m else []
    for line in [ln for ln in text.splitlines() if ln.strip()][:5]:
        chunks += re.split(r"[.,;|•·(/]|\s[—–-]\s|\s{2,}", line.split(":")[0])  # «Компания: Яндекс Облако» — значение не имя
    for ch in (c.strip() for c in chunks):
        if (re.fullmatch(rf"{_NAME_WORD}(?:\s+{_NAME_WORD}){{1,2}}", ch) and not any(w.lower() in _NOT_NAME for w in re.split(r"[\s-]", ch))
                and _spec(ch.lower(), []) is None):
            return ch
    return None


def _contacts(text: str) -> dict:
    email = re.search(_EMAIL_RX, text, re.IGNORECASE)
    tg = re.search(_TG_RX, text, re.IGNORECASE)
    return {"name": _name(text), "email": email[0].lower() if email else None, "tg": "@" + tg[1] if tg else None}


def parse_cv(text: str, *, use_llm: bool = True) -> dict:
    """Резюме → навыки, стаж, категория (для подбора) + контакты, роли, софт-скиллы, места работы (для профиля).
    В модель уходит текст, но обратно от неё берутся только поля справочников — не ФИО и не контакты."""
    s = text.lower()
    skills = extract_skills(s, skip=frozenset({"cv"}))  # «CV» в резюме — заголовок, а не Computer Vision
    spec = _spec(s, skills)
    experience = cv_experience(text)
    out = {
        "skills": skills, "years_exp": _years(s, experience), "spec": spec, "track": _track(s, spec, skills) if spec else None,
        "roles": _by_dict(s, _ROLE_RX), "soft_skills": _by_dict(s, _SOFT_RX),
        "contacts": _contacts(text), "experience": experience[:12], "parsed_by": "rules",
    }
    got = llm.chat_json(_CV_SYSTEM, text[:8000]) if use_llm else None
    if got:
        out["parsed_by"] = "llm"
        out["skills"] = list(dict.fromkeys(canon_skills(got.get("skills")) + skills))
        y = got.get("years_exp")
        if isinstance(y, (int, float)) and 0 <= y <= 50:
            out["years_exp"] = float(y)
        if got.get("spec") in catalog.SPECS:
            out["spec"] = got["spec"]
        if out["spec"]:
            out["track"] = got.get("track") if got.get("track") in catalog.TRACKS[out["spec"]] else _track(s, out["spec"], out["skills"])
        out["roles"] = canon_terms(canon_terms(got.get("roles"), catalog.ROLES) + out["roles"], catalog.ROLES)
        out["soft_skills"] = canon_terms(canon_terms(got.get("soft_skills"), catalog.SOFT_SKILLS) + out["soft_skills"], catalog.SOFT_SKILLS)
    return out


if __name__ == "__main__":
    n = parse_need(
        "Ищем бэкендера на Python в команду платежей. Нужен опыт с PostgreSQL и Kafka, хорошо бы Kubernetes. "
        "Уровень — мидл, до 300 на руки. Гибрид, Москва.",
        use_llm=False,
    )
    assert (n["spec"], n["track"], n["grade"]) == ("Backend", "Python", "Middle"), n
    assert n["must"] == ["Python", "PostgreSQL", "Kafka"] and n["nice"] == ["Kubernetes"], n
    assert (n["salary_from"], n["salary_to"]) == (240000, 300000), n
    assert (n["format"], n["city"]) == ("Гибрид", "Москва"), n
    n = parse_need("Нужен Go-разработчик, синьор, от 350 до 450к, удалёнка. Мужчина до 35 лет.", use_llm=False)
    assert (n["track"], n["grade"], n["salary_from"], n["salary_to"], n["format"]) == ("Go", "Senior", 350000, 450000, "Удалённо"), n
    assert "возраст" in n["ignored"] and "пол" in n["ignored"], n
    n = parse_need("Сеньор DevOps: k8s, terraform желательно. 250-320 тыс, Казань, офис", use_llm=False)
    assert (n["spec"], n["grade"], n["must"], n["nice"], n["salary_from"], n["city"]) == ("DevOps / SRE", "Senior", ["Kubernetes"], ["Terraform"], 250000, "Казань"), n
    n = parse_need("Фронтендер на React + TypeScript, джун, 150к, офис СПб", use_llm=False)
    assert (n["spec"], n["track"], n["grade"], n["salary_to"], n["city"]) == ("Frontend", "React", "Junior", 150000, "Санкт-Петербург"), n
    assert n["must"] == ["React", "TypeScript"], n
    cv = parse_cv("Дмитрий Орлов. CV. Опыт работы 4 года. Python, asyncio, Postgres, Kafka, Docker. Node.js немного.", use_llm=False)
    assert cv["years_exp"] == 4 and cv["spec"] == "Backend" and cv["track"] == "Python", cv
    assert cv["skills"] == ["Python", "asyncio", "PostgreSQL", "Kafka", "Docker", "Node.js"], cv
    cv = parse_cv("2019 — 2021 Яндекс; 2021 — н.в. Тинькофф", use_llm=False)
    assert cv["years_exp"] == datetime.now().year - 2019, cv
    assert cv["experience"] == [{"from": 2019, "to": 2021, "title": "Яндекс"}, {"from": 2021, "to": None, "title": "Тинькофф"}], cv
    cv = parse_cv("Анна Петрова\nanna.p@example.ru · t.me/anna_dev\nТимлид, менторила джунов. Коммуникабельна, ответственна.", use_llm=False)
    assert cv["contacts"] == {"name": "Анна Петрова", "email": "anna.p@example.ru", "tg": "@anna_dev"}, cv
    assert cv["roles"] == ["Тимлид", "Ментор"] and cv["soft_skills"] == ["Коммуникация", "Ответственность"], cv
    print("ok")
