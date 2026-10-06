"""Синтетические данные: демо-персонажи из макета + ~1500 кандидатов, ~60 компаний, 250 потребностей, приглашения.

Запуск: uv run python -m seed.generate [--reset] [--candidates 1500] [--needs 250] [--seed 42]

Сначала структура, потом текст (сессия, §8): специализация/трек/истинный θ → наблюдаемый θ ± SE → грейд,
навыки (истинные ⊇ подтверждённые тестом; заявленные ⊇ подтверждённых, у ~10% — завышены), достижения,
Codeforces, зарплата по рынку, формат, город; резюме и тексты потребностей — из шаблонов с шумом
(синонимы из catalog.SKILLS, опечатки). Скрытая правда — в Candidate.truth, для seed/gold.py.
Детерминировано по --seed (время — относительно «сейчас»).
"""

import argparse
import inspect
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np
from sqlalchemy import func, select

from app import catalog as C
from app.db import Base, SessionLocal, engine
from app.integrations.scoring import place_weight
from app.models import (Achievement, Application, Candidate, Company, ConsentEvent, Event, ExternalAccount, Invitation, Need, Task,
                        TaskSubmission, User, Vacancy)

NOW = datetime.now(UTC)
# неделя квоты — с понедельника 00:00 МСК, как в employer.quota; в UTC с вс 21:00 до пн 00:00 неделя была бы прошлой
_NOW_MSK = NOW.astimezone(ZoneInfo("Europe/Moscow"))
WEEK_START = (_NOW_MSK - timedelta(days=_NOW_MSK.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
DAY = timedelta(days=1)

# ───────────────────────── справочники генератора ─────────────────────────

SPEC_P = {"Backend": .30, "Frontend": .17, "Mobile": .08, "ML / DS": .10, "Data Eng / Analytics": .09,
          "DevOps / SRE": .09, "QA": .11, "Security": .06}
TRACK_P = {"Backend": [.35, .2, .2, .15, .1]}  # остальные специализации — равномерно
GRADE_P = [.08, .25, .37, .22, .08]
THETA_BAND = {"Intern": (-2.2, -0.5), "Junior": (-0.5, 0.5), "Middle": (0.5, 1.5), "Senior": (1.5, 2.3), "Lead": (2.3, 3.0)}
YEARS = {"Intern": (0, 1), "Junior": (0.5, 2), "Middle": (2, 5), "Senior": (4, 9), "Lead": (6, 14)}
# роли из резюме: вероятность по заявленному грейду (лидерские — с Senior); Исследователь — у ML / DS
ROLE_P = {
    "Intern": {"Контрибьютор open source": .05, "Капитан команды": .05},
    "Junior": {"Контрибьютор open source": .08, "Капитан команды": .08, "Спикер": .03},
    "Middle": {"Ментор": .2, "Капитан команды": .1, "Контрибьютор open source": .1, "Спикер": .08, "Преподаватель": .04},
    "Senior": {"Ментор": .45, "Техлид": .3, "Архитектор": .15, "Спикер": .15, "Контрибьютор open source": .12, "Преподаватель": .06},
    "Lead": {"Тимлид": .7, "Ментор": .55, "Техлид": .35, "Архитектор": .25, "Руководитель проекта": .2, "Спикер": .2},
}

CORE = {  # трек → навыки, которые есть у каждого в треке и подтверждаются модулем теста
    "Python": ["Python"], "Go": ["Go"], "Java / Kotlin": ["Java", "Kotlin"], "Node.js": ["Node.js", "TypeScript"],
    "C# / .NET": ["C#"], "React": ["React", "TypeScript"], "Vue": ["Vue", "JavaScript"], "Angular": ["Angular", "TypeScript"],
    "iOS": ["Swift"], "Android": ["Kotlin"], "Flutter": ["Flutter"],
    "Classic ML": ["Python", "scikit-learn"], "CV": ["Python", "PyTorch", "Computer Vision"], "NLP / LLM": ["Python", "PyTorch", "LLM"],
    "Data Engineering": ["Python", "SQL", "Airflow"], "BI / Analytics": ["SQL", "ClickHouse"],
    "Kubernetes": ["Kubernetes", "Docker", "Linux"], "Cloud": ["Terraform", "Docker", "Linux"],
    "Manual": ["SQL"], "Automation": ["Python", "Selenium"], "AppSec": ["Python", "Pentest"], "Pentest": ["Pentest", "Linux"],
}
EXTRA = {  # специализация → дополнительные навыки (часть есть, часть нет)
    "Backend": ["PostgreSQL", "MySQL", "MongoDB", "Redis", "Kafka", "RabbitMQ", "Docker", "Kubernetes", "gRPC", "ClickHouse", "Linux"],
    "Frontend": ["JavaScript", "TypeScript", "Docker", "Node.js"],
    "Mobile": ["Kotlin", "Java", "Swift", "Flutter", "Docker"],
    "ML / DS": ["SQL", "Docker", "Spark", "Airflow", "ClickHouse", "PostgreSQL", "LLM", "scikit-learn", "PyTorch"],
    "Data Eng / Analytics": ["PostgreSQL", "Kafka", "ClickHouse", "Docker", "Spark", "Python", "Airflow"],
    "DevOps / SRE": ["Prometheus", "Kubernetes", "Docker", "Terraform", "Python", "Go", "Kafka", "PostgreSQL"],
    "QA": ["Selenium", "Python", "SQL", "Docker", "Java", "JavaScript", "PostgreSQL"],
    "Security": ["Linux", "Docker", "Python", "Go", "Kubernetes", "PostgreSQL"],
}
POPULAR = {"PostgreSQL": 5, "SQL": 3, "Docker": 3, "TypeScript": 3, "Kafka": 2.5, "Redis": 2.5, "Linux": 2}
TRACK_EXTRA = {"Python": ["asyncio", "FastAPI", "Django"], "Node.js": ["JavaScript"], "Android": ["Java"]}

# 41 регион: Москва 38 %, Санкт-Петербург 14 %, остальное — регионы с убывающими весами
REGIONS = ["Новосибирск", "Екатеринбург", "Казань", "Нижний Новгород", "Челябинск", "Самара", "Омск", "Ростов-на-Дону",
           "Уфа", "Красноярск", "Воронеж", "Пермь", "Волгоград", "Краснодар", "Саратов", "Тюмень", "Ижевск", "Барнаул",
           "Иркутск", "Ульяновск", "Хабаровск", "Ярославль", "Владивосток", "Махачкала", "Томск", "Оренбург", "Кемерово",
           "Рязань", "Пенза", "Липецк", "Калининград", "Тула", "Киров", "Чебоксары", "Белгород", "Курск", "Тверь",
           "Архангельск", "Мурманск"]
CITIES = ["Москва", "Санкт-Петербург", *REGIONS]
_rw = 1 / np.arange(1, len(REGIONS) + 1) ** 0.7
CITY_P = np.array([.38, .14, *(_rw / _rw.sum() * .48)])

FORMAT_SETS = [["Удалённо"], ["Гибрид"], ["Офис"], ["Гибрид", "Удалённо"], ["Офис", "Гибрид"], ["Офис", "Гибрид", "Удалённо"]]
FORMAT_P = [.25, .12, .06, .30, .15, .12]

MALE = ["Александр", "Дмитрий", "Максим", "Иван", "Артём", "Никита", "Михаил", "Даниил", "Егор", "Андрей", "Илья",
        "Алексей", "Роман", "Сергей", "Кирилл", "Владимир", "Павел", "Тимур", "Глеб", "Матвей", "Денис", "Евгений",
        "Константин", "Ярослав", "Арсений", "Руслан", "Олег", "Вадим"]
FEMALE = ["Анастасия", "Мария", "Анна", "Дарья", "Екатерина", "Полина", "Алина", "Ксения", "Виктория", "Елизавета",
          "Софья", "Валерия", "Ольга", "Наталья", "Юлия", "Вероника", "Арина", "Татьяна", "Диана", "Камила"]
SURNAMES = ("Иванов Смирнов Кузнецов Попов Васильев Петров Соколов Михайлов Новиков Фёдоров Морозов Волков Алексеев "
            "Лебедев Семёнов Егоров Павлов Козлов Степанов Николаев Захаров Зайцев Соловьёв Борисов Яковлев Григорьев "
            "Романов Воробьёв Сергеев Кузьмин Фролов Александров Дмитриев Королёв Гусев Киселёв Ильин Максимов Поляков "
            "Сорокин Виноградов Белов Медведев Антонов Тарасов Жуков Баранов Филиппов Комаров Давыдов Беляев Герасимов "
            "Богданов Осипов Сидоров Матвеев Титов Марков Миронов Крылов Куликов Карпов Власов Мельников Денисов Гаврилов "
            "Тихонов Казаков Афанасьев Данилов Савельев Тимофеев Фомин Чернов Абрамов Мартынов Ефимов Федотов Щербаков "
            "Назаров Калинин Исаев Быков Маслов Родионов Коновалов Лазарев Воронин Климов Филатов Пономарёв Голубев "
            "Кудрявцев Прохоров Наумов Потапов Журавлёв Трофимов Леонов Соболев Ермаков Колесников Гончаров Никитин "
            "Ахметов Хабибуллин Гарипов Шевченко Бондаренко Ткаченко Ким Цой Алиев Садыков Юсупов Белоусов Островский "
            "Вишневский Левицкий").split()
_TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
               "a b v g d e e zh z i y k l m n o p r s t u f kh ts ch sh sch - y - e yu ya".split()))


def translit(s: str) -> str:
    return "".join(_TR.get(ch, ch) for ch in s.lower()).replace("-", "")


def feminine(surname: str) -> str:
    if surname.endswith(("ов", "ев", "ёв", "ин")):
        return surname + "а"
    if surname.endswith("ий"):
        return surname[:-2] + "ая"
    return surname


SPEC_TITLE = {"Backend": "Backend-разработчик", "Frontend": "Frontend-разработчик", "Mobile": "Мобильный разработчик",
              "ML / DS": "ML-инженер", "Data Eng / Analytics": "Инженер данных", "DevOps / SRE": "DevOps-инженер",
              "QA": "QA-инженер", "Security": "Специалист по ИБ"}
SPEC_WORD = {"Backend": ["бэкенд-разработчика", "backend-разработчика", "бэкендера"],
             "Frontend": ["фронтенд-разработчика", "фронтендера"], "Mobile": ["мобильного разработчика"],
             "ML / DS": ["ML-инженера", "data scientist'а"], "Data Eng / Analytics": ["дата-инженера", "аналитика данных"],
             "DevOps / SRE": ["DevOps-инженера", "SRE-инженера"], "QA": ["тестировщика", "QA-инженера"],
             "Security": ["специалиста по безопасности", "AppSec-инженера"]}
GRADE_WORD = {"Intern": "стажёр", "Junior": "джун", "Middle": "мидл", "Senior": "сеньор", "Lead": "лид"}
TEAMS = ["платежей", "логистики", "поиска", "рекомендаций", "биллинга", "личного кабинета", "антифрода", "аналитики",
         "внутренних сервисов", "интеграций", "мобильного банка", "маркетплейса"]
CV_LINES = ["Разрабатывал(а) сервисы на {a} и {b}.", "Отвечал(а) за интеграцию с {a}.", "Участвовал(а) в миграции на {a}.",
            "Писал(а) и поддерживал(а) код на {a}, настраивал(а) {b}.", "Оптимизировал(а) нагрузку, работал(а) с {a}.",
            "Вёл(а) код-ревью, помогал(а) младшим коллегам.", "Дежурил(а) по инцидентам, разбирал(а) логи и метрики.",
            "Делал(а) пет-проекты на {a}.", "Внедрял(а) {a} в команде из {n} человек."]
NEED_TPL = [
    "Ищем {sw} ({track}) в команду {team}. Нужен опыт с {must}. Хорошо бы {nice}. Уровень — {gw}, до {to_k} на руки. {fmt}, {city}.",
    "{company} ищет {sw} уровня {grade}. Обязательно: {must}. Будет плюсом: {nice}. Вилка {from_k}–{to_k} тыс. ₽. Формат: {fmt_l}, {city}.",
    "Открыта позиция: {spec} ({track}), {grade}. Стек: {must}. Плюсом будет {nice}. {from_k}–{to_k} тыс. ₽ на руки, {fmt_l}, {city}.",
    "Нужно усилить команду {team}: ищем {sw}, грейд {gw}. Must have — {must}; nice to have — {nice}. От {from_k} до {to_k} тыс. {fmt}.",
]
ADJACENT = {  # соседняя специализация с теми же словами в тексте — ловушка для подбора по ключевым словам
    "Data Eng / Analytics": ("Data Engineering", ["Python", "SQL", "Kafka"]),
    "DevOps / SRE": ("Kubernetes", ["Python", "Docker", "Kubernetes"]),
    "ML / DS": ("Classic ML", ["Python", "PostgreSQL", "scikit-learn"]),
    "QA": ("Automation", ["Python", "PostgreSQL", "Selenium"]),
}
INDUSTRIES = ["Финтех", "Ритейл", "Логистика", "Телеком", "Медтех", "Edtech", "Маркетплейс", "Геймдев", "Госсервисы",
              "Промышленность", "Страхование", "Банк", "Медиа", "Транспорт", "Энергетика", "Агротех", "Proptech", "B2B SaaS"]
CO_A = ["Северный", "Байкал", "Волга", "Ока", "Таймыр", "Алтай", "Ладья", "Сосна", "Кедр", "Озон", "Зенит", "Вектор",
        "Пульсар", "Орбита", "Меридиан", "Сапсан", "Берег", "Полюс", "Ясень", "Тундра"]
CO_B = ["Технологии", "Софт", "Диджитал", "Системс", "Лаб", "Данные", "Сервис", "Групп", "Платформа", "Код"]
COLORS = ["#402FFF", "#1B1C21", "#0E7C66", "#C2410C", "#7C3AED", "#0369A1", "#BE123C", "#4D7C0F", "#A16207", "#334155"]
EVENTS = [  # (source, external_id, title, level, participants, months_ago, tags)
    ("fsp", "cup-2025-prod", "Финал Кубка России по спортивному программированию 2025, продуктовое направление", "national", 600, 4, ["product"]),
    ("fsp", "cup-2024-prod", "Финал Кубка России по спортивному программированию 2024, продуктовое направление", "national", 520, 16, ["product"]),
    ("fsp", "champ-2024-prod", "Чемпионат России ФСП 2024, продуктовое направление", "national", 400, 12, ["product"]),
    ("fsp", "champ-2025-algo", "Чемпионат России ФСП 2025, алгоритмическое программирование", "national", 450, 2, ["algo"]),
    ("fsp", "champ-2025-sec", "Чемпионат России ФСП 2025, информационная безопасность", "national", 300, 3, ["security"]),
    *[("fsp", f"reg-{y}-{translit(c)}", f"Региональный этап ФСП {y}, {c}", "regional", 120, 6 + 12 * (2025 - y), ["product"])
      for y in (2024, 2025) for c in ["Москва", "Санкт-Петербург", "Казань", "Новосибирск", "Екатеринбург", "Нижний Новгород", "Самара", "Томск"]],
    ("hackathon", "dp-2024", "Хакатон «Цифровой прорыв» 2024", "national", 2500, 13, ["product"]),
    ("hackathon", "ldt-2025", "Хакатон «Лидеры цифровой трансформации» 2025", "national", 3000, 3, ["product"]),
    ("hackathon", "ml-cup-2025", "ML-хакатон по рекомендательным системам 2025", "national", 800, 5, ["ml"]),
    ("hackathon", "uni-kzn-2025", "Студенческий хакатон, Казань 2025", "local", 150, 7, ["product"]),
    ("hackathon", "uni-nsk-2024", "Студенческий хакатон, Новосибирск 2024", "local", 120, 14, ["product"]),
    ("hackathon", "mobile-2025", "Хакатон мобильной разработки 2025", "regional", 300, 6, ["mobile"]),
    ("hackathon", "icpc-ne-2024", "ICPC, полуфинал Северной Евразии 2024", "international", 300, 10, ["algo"]),
    ("ctftime", "ctf-fsp-2025", "CTF Кубка ФСП по информационной безопасности 2025", "national", 400, 5, ["security"]),
    ("ctftime", "ctf-uni-2024", "Университетский CTF 2024", "regional", 200, 11, ["security"]),
]
SPEC_TAGS = {"ML / DS": ["ml", "product", "algo"], "Mobile": ["mobile", "product"], "Security": ["security"],
             "Data Eng / Analytics": ["ml", "product"]}

assert all(s in C.SKILLS for v in (*CORE.values(), *EXTRA.values(), *TRACK_EXTRA.values()) for s in v)
assert set(CORE) == {t for ts in C.TRACKS.values() for t in ts} and len(CITIES) == 41


def inn_ok(inn: str) -> bool:
    w = [2, 4, 10, 3, 5, 9, 4, 6, 8]
    return sum(int(a) * b for a, b in zip(inn, w)) % 11 % 10 == int(inn[9])


def inn_make(prefix9: str) -> str:
    return next(prefix9 + str(d) for d in range(10) if inn_ok(prefix9 + str(d)))


def cf_rank(r: float) -> str:
    for lo, name in ((2400, "International Grandmaster"), (2300, "International Master"), (2100, "Master"),
                     (1900, "Candidate Master"), (1600, "Expert"), (1400, "Specialist"), (1200, "Pupil")):
        if r >= lo:
            return name
    return "Newbie"


# ───────────────────────── генератор ─────────────────────────


class Gen:
    def __init__(self, seed: int):
        self.rng = np.random.default_rng(seed)
        self.ids: set[str] = set()
        self.handles: set[str] = set()
        self.emails: Counter = Counter()

    def pick(self, seq, p=None):
        return seq[self.rng.choice(len(seq), p=p)]

    def sample(self, seq, k):
        return [seq[i] for i in self.rng.choice(len(seq), size=min(k, len(seq)), replace=False)]

    def skills(self, seq, k):
        """Выборка навыков с учётом популярности (PostgreSQL у бэкендеров встречается чаще gRPC)."""
        w = np.array([POPULAR.get(x, 1.0) for x in seq])
        return [seq[i] for i in self.rng.choice(len(seq), size=min(k, len(seq)), replace=False, p=w / w.sum())]

    def public_id(self) -> str:
        while True:
            pid = f"{chr(65 + self.rng.integers(26))}-{self.rng.integers(10000):04d}"
            if pid not in self.ids:
                self.ids.add(pid)
                return pid

    def person(self, name: str | None = None):
        if name is None:
            male = self.rng.random() < 0.72
            first = self.pick(MALE if male else FEMALE)
            sur = self.pick(SURNAMES)
            name = f"{first} {sur if male else feminine(sur)}"
        first, sur = name.split()
        base = f"{translit(first)[0]}.{translit(sur)}"
        self.emails[base] += 1
        n = self.emails[base]
        email = f"{base}{n if n > 1 else ''}@{self.pick(['example.ru', 'example.com', 'example.org'])}"
        tg = f"@{translit(sur)}_{translit(first)[:3]}{self.rng.integers(10, 99)}"
        return name, email, tg

    def handle(self, name: str) -> str:
        first, sur = name.split()
        while True:
            h = f"{translit(sur)}{translit(first)[0]}{self.rng.integers(1, 999)}"
            if h not in self.handles:
                self.handles.add(h)
                return h

    def noisy(self, skill: str) -> str:
        return self.pick(C.SKILLS[skill]) if self.rng.random() < 0.45 else skill

    def typos(self, text: str, p: float = 0.04) -> str:
        words = text.split(" ")
        for i, w in enumerate(words):
            if len(w) > 4 and w.isalpha() and self.rng.random() < p:
                j = int(self.rng.integers(1, len(w) - 2))
                words[i] = w[:j] + w[j + 1] + w[j] + w[j + 2:]
        return " ".join(words)

    def comps(self, spec: str, theta: float, se: float) -> list[dict]:
        return [{"n": n, "t": round(float(theta + self.rng.normal(0, 0.35)), 2),
                 "se": round(float(np.clip(se + self.rng.normal(0, 0.05), 0.12, 0.45)), 2)} for n in C.COMPETENCIES[spec]]

    def cv(self, spec, track, grade, years, city, formats, skills) -> str:
        sk = list(skills)
        self.rng.shuffle(sk)
        lines = []
        for tpl in self.sample(CV_LINES, 3):
            a, b = self.pick(sk), self.pick(sk)
            lines.append(tpl.format(a=self.noisy(a), b=self.noisy(b), n=int(self.rng.integers(3, 12))))
        text = (f"{SPEC_TITLE[spec]} ({track}), {grade}. Опыт — {years:.0f} г.\n"
                f"Город: {city}. Формат: {', '.join(formats).lower()}.\n"
                f"Стек: {', '.join(self.noisy(s) for s in sk)}.\n" + " ".join(lines))
        return self.typos(text)

    # ── кандидат из структуры ──
    def candidate(self, spec=None, track=None, grade_true=None, inflated=None, city=None) -> Candidate:
        r = self.rng
        spec = spec or self.pick(list(SPEC_P), p=list(SPEC_P.values()))
        track = track or self.pick(C.TRACKS[spec], p=TRACK_P.get(spec))
        grade_true = grade_true or self.pick(C.GRADES, p=GRADE_P)
        inflated = bool(r.random() < 0.10) if inflated is None else inflated
        lo, hi = THETA_BAND[grade_true]
        theta_true = float(r.uniform(lo, hi))
        se = float(r.uniform(0.15, 0.35))
        theta = round(theta_true + float(r.normal(0, se)), 2)
        se = round(se, 2)
        grade = C.grade_from_theta(theta, se)
        gi = C.GRADES.index(grade_true)

        pool = [s for s in EXTRA[spec] + TRACK_EXTRA.get(track, []) if s not in CORE[track]]
        pool = list(dict.fromkeys(pool))
        k = min(len(pool), int(1 + gi + r.poisson(1)))
        skills_true = CORE[track] + self.skills(pool, k)
        confirmed = CORE[track] + [s for s in skills_true[len(CORE[track]):] if r.random() < 0.65]
        claimed = list(skills_true)
        grade_claimed = grade_true
        if inflated:  # «завышенное резюме при слабом тесте»: заявлено больше, чем есть
            rest = [s for s in pool if s not in skills_true] or [s for s in EXTRA["Backend"] if s not in skills_true]
            claimed += self.sample(rest, int(r.integers(2, 5)))
            grade_claimed = C.GRADES[min(gi + int(r.integers(1, 3)), 4)]

        city = city or self.pick(CITIES, p=CITY_P)
        formats = list(self.pick(FORMAT_SETS, p=FORMAT_P))
        salary_grade = grade_claimed if inflated else grade_true
        min_salary = int(round(C.market(spec, salary_grade, city)["p50"] * float(np.exp(r.normal(0, 0.15))) / 5000) * 5000)
        years = round(float(r.uniform(*YEARS[grade_claimed])), 1)
        tested = NOW - DAY * float(r.uniform(1, 300))
        name, email, tg = self.person()
        return Candidate(
            public_id=self.public_id(), name=name, email=email, tg=tg, **consent(tested - DAY * float(r.uniform(0, 3))),
            consent_publish=bool(r.random() < 0.95),
            consent_external=bool(r.random() < 0.4),  # у кого будут достижения/CF — станет True в achievements()/CF
            spec=spec, track=track, grade_claimed=grade_claimed, min_salary=min_salary, formats=formats, city=city,
            status="open" if r.random() < 0.9 else "off",
            cv_filename="resume.pdf", cv_text=self.cv(spec, track, grade_claimed, years, city, formats, claimed),
            years_exp=years, skills_claimed=claimed,
            grade=grade, theta=theta, se=se, competencies=self.comps(spec, theta, se), skills_confirmed=confirmed,
            tested_at=tested, next_upgrade_at=tested + DAY * C.UPGRADE_COOLDOWN_DAYS,
            review_passed=C.GRADES.index(grade) >= 3 and r.random() < 0.7,
            employer_confirmed=int(r.poisson(0.3)), is_synthetic=True,
            truth={"theta_true": round(theta_true, 3), "skills_true": skills_true, "inflated": inflated,
                   "spec": spec, "track": track, "grade_true": grade_true},
        )

    def achievements(self, cand: Candidate, events: list[Event], theta_true: float) -> None:
        tags = SPEC_TAGS.get(cand.spec, ["product", "algo"])
        pool = [e for e in events if set(e.tags) & set(tags)] or events
        for ev in self.sample(pool, int(self.rng.choice([1, 1, 1, 2, 2, 3]))):
            perf = theta_true + float(self.rng.normal(0, 0.8))
            n = ev.participants
            place = (int(self.rng.integers(1, 4)) if perf > 2.4 else int(self.rng.integers(4, max(5, n // 10))) if perf > 1.6
                     else int(self.rng.integers(n // 10, n // 2)) if perf > 0.6 else None)
            title = ev.title + (f", {place} место" if place and place <= 3 else ", финалист" if place else ", участник")
            cand.consent_external = True  # внешние данные — только с отдельным согласием
            cand.achievements.append(Achievement(
                event=ev, source=ev.source, title=title, place=place, team=f"Команда «{self.pick(CO_A)}»",
                role=self.pick(["backend", "frontend", "ML", "капитан", "аналитик", "mobile"]),
                weight=place_weight(place, n, ev.level), verified=bool(self.rng.random() < 0.85),
            ))

    def company(self, name=None, **kw) -> Company:
        r = self.rng
        name = name or f"{self.pick(CO_A)} {self.pick(CO_B)}"
        slug = translit(name).replace(" ", "-").replace("«", "").replace("»", "")
        rec, _, rtg = self.person()
        first, sur = rec.split()
        inn = inn_make(f"{self.pick(['77', '78', '16', '54', '66', '52', '50', '23'])}{r.integers(10**7):07d}")
        fields = dict(inn=inn, name=name, about=f"{self.pick(INDUSTRIES)}, {int(r.integers(30, 3000))} сотрудников",
                      color=self.pick(COLORS), site_domain=f"{slug}.example", recruiter_name=rec,
                      recruiter_email=f"{translit(first)[0]}.{translit(sur)}@{slug}.example", recruiter_tg=rtg,
                      verified=bool(r.random() < 0.85), quota_max=int(self.pick([10, 10, 10, 12])), is_synthetic=True)
        return Company(**{**fields, **kw})

    def need(self, company: Company, kind: str, city: str) -> Need:
        st = self.struct(company, kind, city)
        return Need(company=company, kind=kind, text=st.pop("text"), **st, is_synthetic=True)

    def struct(self, company: Company, kind: str, city: str) -> dict:
        """Структура потребности/вакансии + текст из шаблона с шумом."""
        r = self.rng
        spec = self.pick(list(SPEC_P), p=list(SPEC_P.values()))
        track = self.pick(C.TRACKS[spec], p=TRACK_P.get(spec))
        grade = self.pick(C.GRADES[1:], p=[.2, .45, .28, .07])
        extras = [s for s in dict.fromkeys(EXTRA[spec] + TRACK_EXTRA.get(track, [])) if s not in CORE[track]]
        must = CORE[track][:2] + self.skills(extras, int(r.integers(1, 3)))
        nice = self.sample([s for s in extras if s not in must], int(r.integers(1, 3)))
        if kind == "adjacent":
            spec = self.pick(list(ADJACENT))
            track, must = ADJACENT[spec]
            nice = self.sample([s for s in EXTRA[spec] if s not in must], 1)
        m = C.market(spec, grade, city)
        if kind == "fork_low":  # вилка ниже ожиданий — для большинства кандидатов категории
            frm = int(round(m["p25"] * r.uniform(0.65, 0.8) / 5000) * 5000)
        else:
            frm = int(round(r.uniform(m["p25"], m["p50"]) / 5000) * 5000)
        to = int(round(frm * (1 + r.uniform(0.12, C.FORK_MAX_WIDTH)) / 5000) * 5000)
        fmt = self.pick(C.FORMATS, p=[.2, .45, .35])
        text = self.pick(NEED_TPL).format(
            sw=self.pick(SPEC_WORD[spec]), track=track, team=self.pick(TEAMS), gw=GRADE_WORD[grade], grade=grade,
            spec=spec, company=company.name, must=", ".join(self.noisy(s) for s in must),
            nice=", ".join(self.noisy(s) for s in nice), from_k=frm // 1000, to_k=to // 1000,
            fmt=fmt, fmt_l=fmt.lower(), city=city)
        return dict(text=self.typos(text, 0.03), spec=spec, track=track, grade=grade, must=must, nice=nice,
                    salary_from=frm, salary_to=to, format=fmt, city=None if fmt == "Удалённо" else city)


def consent(at: datetime) -> dict:
    return {"consent_152": True, "consent_152_at": at, "consent_version": C.CONSENT_VERSION}


def invitation(company, cand, need, status, sent_at, *, role=None, frm=None, to=None, fmt=None, reason=None,
               synthetic=True, ttl=C.INVITE_TTL_DAYS, **kw) -> Invitation:
    need_role = f"{need.spec} ({need.track}), {need.grade}" if need else "Backend"
    inv = Invitation(company=company, candidate=cand, need=need, role=role or need_role,
                     salary_from=frm or need.salary_from, salary_to=to or need.salary_to,
                     format=fmt or (need.format if need else "Удалённо"), status=status, sent_at=sent_at,
                     expires_at=sent_at + DAY * ttl, decline_reason=reason, is_synthetic=synthetic, **kw)
    if status != "sent":
        inv.seen_at = sent_at + DAY * 0.3
    if status in ("accepted", "declined"):
        inv.responded_at = sent_at + DAY * 1.2
    return inv


# ───────────────────────── демо-персонажи макета ─────────────────────────

ORLOV_COMP = [  # COMP из макета, как есть
    {"n": "Диагностика инцидентов", "t": 1.35, "se": 0.22}, {"n": "Базы данных и транзакции", "t": 1.10, "se": 0.18},
    {"n": "Ревью кода", "t": 1.42, "se": 0.25}, {"n": "Проектирование API", "t": 0.85, "se": 0.30},
    {"n": "Конкурентность, asyncio", "t": 0.70, "se": 0.28}, {"n": "Алгоритмы", "t": 1.60, "se": 0.20},
]
# CANDS макета: id, pct, θ, SE, навыки, достижение ФСП (title, event_id, place), CF, зарплата, форматы, город, мес. назад, правда
CANDS = [
    ("C-0775", 71, 0.94, 0.21, ["Python", "PostgreSQL", "RabbitMQ", "FastAPI"], ("Призёр регионального этапа ФСП 2024", "reg-2024-moskva", 3),
     1650, 210000, ["Офис", "Гибрид"], "Москва", 5),
    ("B-2318", 85, 1.31, 0.16, ["Python", "PostgreSQL", "Kafka", "Kubernetes"], None, None, 280000, ["Удалённо"], "Казань", 1),
    ("D-3390", 69, 0.88, 0.24, ["Python", "Django", "PostgreSQL"], None, 1540, 250000, ["Удалённо"], "Новосибирск", 7),
    ("E-1187", 90, 1.44, 0.15, ["Python", "PostgreSQL", "Kafka", "Kubernetes", "Go"], ("Победитель чемпионата России ФСП 2024", "champ-2024-prod", 1),
     2105, 320000, ["Гибрид"], "Москва", 3),
]
COHORT = 30
PERSONA_LOAD = {"B-2318": 4, "D-3390": 2, "E-1187": 1}  # открытые приглашения от других компаний, как в макете
LADOGA_NEED = {
    "text": "Ищем бэкендера на Python в команду платежей. Нужен опыт с PostgreSQL и Kafka, хорошо бы Kubernetes. "
            "Уровень — мидл, до 300 на руки. Гибрид, Москва.",
    "spec": "Backend", "track": "Python", "grade": "Middle", "must": ["Python", "PostgreSQL", "Kafka"], "nice": ["Kubernetes"],
    "salary_from": 240000, "salary_to": 300000, "format": "Гибрид", "city": "Москва", "parsed_by": "rules",
}
LADOGA_INN = "7704123450"  # в задании 7704123456 — контрольная цифра неверна; ближайший валидный ИНН ЮЛ
assert inn_ok(LADOGA_INN)


def soft_profile(rng, grade: str, spec: str) -> tuple[list[str], list[str]]:
    """Роли и софт-скиллы синтетического кандидата (справочные, «со слов кандидата»): роли — по грейду,
    софт-скиллы — до 4 из справочника (у ~10 % — ни одного), лидерские роли тянут «Лидерство» / «Наставничество»."""
    p = {**ROLE_P[grade], **({"Исследователь": .2} if spec == "ML / DS" else {})}
    roles = [x for x in C.ROLES if x in p and rng.random() < p[x]]
    soft = [x for x in C.SOFT_SKILLS if rng.random() < .2]
    soft += ["Лидерство"] * bool({"Тимлид", "Техлид", "Капитан команды"} & set(roles)) + ["Наставничество"] * ("Ментор" in roles)
    return roles, [x for x in C.SOFT_SKILLS if x in soft][:4]


def persona(g: Gen, pid, pct, theta, se, skills, months, *, claimed=None, name=None, **kw) -> Candidate:
    g.ids.add(pid)
    n, e, tg = g.person(name)
    tested = kw.pop("tested_at", NOW - DAY * 30 * months)
    c = Candidate(public_id=pid, name=n, email=e, tg=tg, **consent(tested - DAY), consent_publish=True, spec="Backend", track="Python",
                  grade_claimed="Middle", grade=C.grade_from_theta(theta, se), theta=theta, se=se, percentile=pct,
                  competencies=kw.pop("competencies", None) or g.comps("Backend", theta, se),
                  skills_confirmed=skills, skills_claimed=claimed or skills, tested_at=tested,
                  next_upgrade_at=kw.pop("next_upgrade_at", tested + DAY * C.UPGRADE_COOLDOWN_DAYS),
                  status="open", years_exp=round(float(g.rng.uniform(2.5, 5)), 1), is_synthetic=False,
                  truth={"theta_true": theta, "skills_true": skills, "inflated": False, "spec": "Backend",
                         "track": "Python", "grade_true": "Middle"}, **kw)
    c.cv_text = g.cv("Backend", "Python", "Middle", c.years_exp, c.city, c.formats, c.skills_claimed)
    return c


def build(db, n_cand: int, n_needs: int, seed: int) -> dict:
    g = Gen(seed)
    r = g.rng
    events = [Event(source=s, external_id=x, title=t, level=lv, participants=n, date=NOW - DAY * 30 * m, tags=tg)
              for s, x, t, lv, n, m, tg in EVENTS]
    ev = {e.external_id: e for e in events}
    db.add_all(events)

    # ── демо: кандидат Дмитрий Орлов ──
    u_orlov = User(email="d.orlov@example.ru", role="candidate", fsp_id="FSP-1042")
    orlov = persona(g, "A-1042", 78, 1.12, 0.18, ["Python", "PostgreSQL", "Kafka", "asyncio"], 0,
                    claimed=["Python", "PostgreSQL", "Kafka", "asyncio", "Kubernetes", "Docker"],
                    name="Дмитрий Орлов", competencies=ORLOV_COMP, min_salary=230000, formats=["Гибрид", "Удалённо"],
                    city="Москва", tested_at=datetime(2026, 10, 5, 12, tzinfo=UTC),
                    next_upgrade_at=datetime(2027, 1, 3, 12, tzinfo=UTC), consent_external=True,
                    cv_filename="orlov_cv.pdf")
    orlov.email, orlov.tg = "d.orlov@example.ru", "@dorlov_dev"
    orlov.cv_text += ("\nОпыт работы\n2023 — н.в. Финтех «Волна Пэй», бэкенд-разработчик платёжного шлюза\n"
                      "2021 — 2023 Интернет-магазин «Полка», Python-разработчик\nМенторил стажёров, капитан команды на Кубке ФСП.")
    orlov.roles, orlov.soft_skills = ["Ментор", "Капитан команды"], ["Коммуникация", "Работа в команде", "Самостоятельность"]
    orlov.truth["skills_true"] = orlov.skills_confirmed + ["Docker"]  # Kubernetes заявлен, но не подтверждён тестом
    cup = ev["cup-2025-prod"]
    orlov.achievements.append(Achievement(event=cup, source="fsp", title=cup.title, place=12, team="Команда «Сапсан»",
                                          role="backend", weight=place_weight(12, cup.participants, cup.level), verified=True))
    orlov.accounts.append(ExternalAccount(provider="codeforces", handle="dorlov", verify_code="", verified_at=NOW - DAY * 60,
                                          rating=1912, rank="Candidate Master", fetched_at=NOW - DAY))
    g.handles.add("dorlov")
    personas = {"A-1042": orlov}
    for pid, pct, th, se, skills, fsp, cf, sal, fmts, city, months in CANDS:
        c = persona(g, pid, pct, th, se, skills, months, min_salary=sal, formats=fmts, city=city,
                    consent_external=cf is not None or fsp is not None)
        if fsp:
            title, eid, place = fsp
            c.achievements.append(Achievement(event=ev[eid], source="fsp", title=title, place=place, role="backend",
                                              weight=place_weight(place, ev[eid].participants, ev[eid].level), verified=True))
        if cf:
            c.accounts.append(ExternalAccount(provider="codeforces", handle=g.handle(c.name), verify_code="",
                                              verified_at=NOW - DAY * 90, rating=cf, rank=cf_rank(cf), fetched_at=NOW - DAY))
        personas[pid] = c
    # воронка «Ладога Пэй» из макета
    for pid, sal, kw in [("F-0911", 235000, {"name": "Анна Смирнова"}), ("G-2240", 300000, {}),
                         ("H-1503", 245000, {}), ("J-4410", 225000, {})]:
        th = round(float(r.uniform(0.85, 1.3)), 2)
        c = persona(g, pid, int(r.integers(60, 85)), th, 0.2, ["Python", "PostgreSQL", "Kafka"], int(r.integers(1, 6)),
                    min_salary=sal, formats=["Гибрид", "Удалённо"], city="Москва", **kw)
        personas[pid] = c
    personas["F-0911"].email = "a.smirnova@example.ru"

    # ── синтетические кандидаты ──
    cands = [g.candidate() for _ in range(n_cand - COHORT)]
    # когорта вокруг демо-потребности «Ладога Пэй»: Backend · Python, Москва, Kafka + PostgreSQL — чтобы у подбора и
    # лотереи на демо был живой пул (в общей массе Kafka, подтверждённая тестом, редкость)
    for _ in range(COHORT):
        c = g.candidate(spec="Backend", track="Python", grade_true=g.pick(["Middle", "Senior"], p=[.75, .25]),
                        inflated=False, city="Москва")
        for sk in ("PostgreSQL", "Kafka"):
            for lst in (c.truth["skills_true"], c.skills_confirmed, c.skills_claimed):
                if sk not in lst:
                    lst.append(sk)
        cands.append(c)
    # роли и софт-скиллы — свой генератор: основной поток случайных чисел не сдвигается, синтетика для валидации та же
    rs = np.random.default_rng(seed + 1)
    for c in cands:
        c.roles, c.soft_skills = soft_profile(rs, c.grade_claimed, c.spec)
    by_spec: dict[str, list[Candidate]] = {}
    for c in cands:
        by_spec.setdefault(c.spec, []).append(c)
    for group in by_spec.values():  # перцентиль θ внутри специализации
        ranks = np.argsort(np.argsort([c.theta for c in group]))
        for c, rk in zip(group, ranks):
            c.percentile = int(round(100 * (rk + 0.5) / len(group)))
    for c in cands:
        tt = c.truth["theta_true"]
        if r.random() < np.clip(0.25 + 0.08 * tt, 0.1, 0.6):
            g.achievements(c, events, tt)
    # Codeforces: ~20 % у Backend / ML / Data, рейтинг коррелирует с θ «Алгоритмов» (ρ ≈ 0.6)
    cf_c = [c for c in cands if r.random() < (0.2 if c.spec in ("Backend", "ML / DS", "Data Eng / Analytics") else 0.04)]
    alg = np.array([next(x["t"] for x in c.competencies if x["n"] in ("Алгоритмы", "Реверс", "Регресс", "План отката")) for c in cf_c])
    z = (alg - alg.mean()) / (alg.std() or 1)
    ratings = np.clip(1550 + 330 * (0.6 * z + 0.8 * r.normal(0, 1, len(cf_c))), 800, 3300).round()
    for c, rt in zip(cf_c, ratings):
        c.consent_external = True
        c.accounts.append(ExternalAccount(provider="codeforces", handle=g.handle(c.name), verify_code="",
                                          verified_at=NOW - DAY * float(r.uniform(5, 300)), rating=float(rt),
                                          rank=cf_rank(rt), fetched_at=NOW - DAY * float(r.uniform(0, 7))))

    # ── компании ──
    u_lad = User(email="m.kovaleva@ladoga-pay.example", role="employer")
    ladoga = Company(inn=LADOGA_INN, name="Ладога Пэй", about="Финтех, платёжный процессинг, 420 сотрудников",
                     color="#402FFF", site_domain="ladoga-pay.example", recruiter_name="Мария Ковалёва",
                     recruiter_email="m.kovaleva@ladoga-pay.example", recruiter_tg="@mkovaleva", verified=True, quota_max=10)
    db.add_all([u_orlov, u_lad])
    db.flush()  # нужны users.id: у Candidate/Company нет relationship на User
    orlov.user_id, ladoga.user_id = u_orlov.id, u_lad.id
    kiprey = g.company("Кипрей Логистик", color="#1B1C21", about="Логистика, B2B-сервисы, 150 сотрудников",
                       site_domain="kiprey-logistic.example", recruiter_name="Олег Тихонов",
                       recruiter_email="o.tikhonov@kiprey-logistic.example", recruiter_tg="@otikhonov",
                       verified=True, quota_max=10, is_synthetic=False)
    companies = [g.company() for _ in range(60)]
    seen_names = set()
    for c in companies:  # одинаковые названия → суффикс
        base, k = c.name, 1
        while c.name in seen_names:
            k += 1
            c.name = f"{base} {k}"
        seen_names.add(c.name)
        if k > 1:
            c.site_domain = c.site_domain.replace(".example", f"-{k}.example")
    seen_inn = {LADOGA_INN, kiprey.inn}
    for c in companies:
        while c.inn in seen_inn:
            c.inn = inn_make(f"77{r.integers(10**7):07d}")
        seen_inn.add(c.inn)
    for c in cands:  # ~3 % скрывают профиль от одной компании (например, текущего работодателя)
        if r.random() < 0.03:
            c.hidden_from = [g.pick(companies).inn]

    lad_need = Need(company=ladoga, kind="normal", text=LADOGA_NEED["text"], **{k: v for k, v in LADOGA_NEED.items() if k != "text"})
    kip_need = Need(company=kiprey, kind="normal", text="Маршрутизация доставок, интеграции с перевозчиками. Python, PostgreSQL, Redis.",
                    spec="Backend", track="Python", grade="Middle", must=["Python", "PostgreSQL"], nice=["Redis"],
                    salary_from=190000, salary_to=225000, format="Удалённо")
    kinds = Counter()
    needs = []
    hq = {id(c): g.pick(CITIES, p=CITY_P) for c in companies}
    for i in range(n_needs):
        kind = "adjacent" if i % 9 == 0 else "fork_low" if i % 9 == 1 else "normal"
        kinds[kind] += 1
        co = companies[i % len(companies)]
        needs.append(g.need(co, kind, hq[id(co)]))

    # ── приглашения ──
    invs: list[Invitation] = []
    keys: set = set()
    load: Counter = Counter()

    def add(inv: Invitation):
        key = (id(inv.company), id(inv.candidate), id(inv.need))
        if key in keys:
            return False
        keys.add(key)
        invs.append(inv)
        if inv.status in ("sent", "seen") and inv.expires_at > NOW:
            load[id(inv.candidate)] += 1
        return True

    L1 = dict(role="Backend-разработчик (Python), команда платежей", frm=240000, to=300000, fmt="Гибрид, Москва, 2 дня в офисе",
              task="Разбор инцидента с дублями платежей: ~45 минут, заменяет первый созвон",
              description="Сервис приёма платежей, 3 тыс. RPS в пике. Python 3.12, PostgreSQL, Kafka. Команда из 6 человек, релизы ежедневно.")
    add(invitation(ladoga, orlov, lad_need, "sent", NOW - timedelta(minutes=5), synthetic=False, **L1,
                   ttl=6 + 5 / 1440))  # «осталось 6 дней»
    add(invitation(kiprey, orlov, kip_need, "sent", NOW - DAY * 4, role="Python-разработчик, сервис маршрутизации",
                   frm=190000, to=225000, fmt="Удалённо", synthetic=False, description=kip_need.text))  # «осталось 3 дня»
    P = personas
    pay, af = "Backend (Python), платежи", "Backend (Python), антифрод"
    add(invitation(ladoga, P["F-0911"], lad_need, "accepted", NOW - DAY * 7, role=pay, frm=240000, to=300000, synthetic=False))
    add(invitation(ladoga, P["G-2240"], lad_need, "declined", NOW - DAY * 9, role=pay, frm=240000, to=290000, reason="salary", synthetic=False))
    add(invitation(ladoga, P["H-1503"], None, "expired", NOW - DAY * 17, role=af, frm=250000, to=310000, fmt="Гибрид", synthetic=False))
    add(invitation(ladoga, P["J-4410"], lad_need, "seen", NOW - DAY * 2, role=pay, frm=230000, to=290000, synthetic=False))

    pool_bp = [c for c in by_spec["Backend"] if c.track == "Python" and c.status == "open"]
    # история «Ладога Пэй»: принято 7 из 12 закрытых ≈ 58 %
    hist = ["accepted"] * 6 + ["declined"] * 2 + ["expired"]
    for status, c in zip(hist, g.sample(pool_bp, len(hist))):
        reason = "stack" if status == "declined" else None
        add(invitation(ladoga, c, lad_need, status, NOW - DAY * float(r.uniform(21, 70)), role=pay,
                       reason=reason, feedback="confirmed" if status == "accepted" and r.random() < .5 else None))
    # квота «Ладога Пэй»: 6 из 10 на этой неделе
    used = sum(1 for i in invs if i.company is ladoga and i.sent_at >= WEEK_START)
    lad_seen = {id(i.candidate) for i in invs if i.company is ladoga}
    fresh = [c for c in pool_bp if not load[id(c)] and id(c) not in lad_seen]
    for k, c in enumerate(g.sample(fresh, max(0, 6 - used)), 1):
        add(invitation(ladoga, c, lad_need, "sent", max(WEEK_START + timedelta(minutes=1), NOW - timedelta(minutes=7 * k)), role=pay))
    # нагрузка персонажей из макета (B-2318 — у потолка)
    for pid, n in PERSONA_LOAD.items():
        for co in g.sample(companies, n):
            add(invitation(co, P[pid], None, "sent", NOW - DAY * float(r.uniform(0, 5)), role="Backend (Python)",
                           frm=260000, to=330000, fmt="Удалённо"))

    # история синтетики: закрытые приглашения + немного открытых; почти у всех нагрузка 0–2, у ~15 — на потолке
    open_c = [c for c in cands if c.status == "open"]
    spec_open: dict[str, list[Candidate]] = {}
    for c in open_c:
        spec_open.setdefault(c.spec, []).append(c)
    for _ in range(int(n_cand * 0.45)):
        nd = g.pick(needs)
        c = g.pick(spec_open.get(nd.spec) or open_c)
        st = g.pick(["accepted", "declined", "expired"], p=[.42, .35, .23])
        reason = None
        if st == "declined":
            reason = "salary" if c.min_salary > nd.salary_to else g.pick(["stack", "format", "not_looking", "company"], p=[.35, .3, .2, .15])
        fb = g.pick([None, "confirmed", "not_confirmed", "hired"], p=[.5, .3, .08, .12]) if st == "accepted" else None
        add(invitation(nd.company, c, nd, st, NOW - DAY * float(r.uniform(8, 150)), reason=reason, feedback=fb))
    stars = sorted(open_c, key=lambda c: -c.theta)[:15]
    for c in stars:
        for _ in range(50):
            if load[id(c)] >= C.CANDIDATE_CAP:
                break
            nd = g.pick([n for n in needs if n.spec == c.spec] or needs)
            add(invitation(nd.company, c, nd, g.pick(["sent", "seen"]), NOW - DAY * float(r.uniform(0, 6.5))))
    for _ in range(int(n_cand * 0.13)):
        nd = g.pick(needs)
        c = g.pick(spec_open.get(nd.spec) or open_c)
        if load[id(c)] < 2:
            add(invitation(nd.company, c, nd, g.pick(["sent", "seen"], p=[.6, .4]), NOW - DAY * float(r.uniform(0, 6.5))))

    more = extras(db, g, ladoga, kiprey, lad_need, companies, hq, orlov, cands)
    for c in [*personas.values(), *cands]:  # версия текста — своя у каждой цели согласия
        c.consent_publish_version = C.CONSENT_VERSION if c.consent_publish else None
        c.consent_external_version = C.CONSENT_VERSION if c.consent_external else None
        for a in c.accounts:
            a.verify_attempts = 0
    db.add_all([ladoga, kiprey, *companies, lad_need, kip_need, *needs, *personas.values(), *cands, *invs, *more["all"]])
    db.flush()  # ConsentEvent.candidate_id без FK/relationship — нужны id
    events = []
    for c in [*personas.values(), *cands]:
        at, v = c.consent_152_at, C.CONSENT_VERSION
        events += [ConsentEvent(candidate_id=c.id, purpose="processing", granted=True, version=v, at=at),
                   ConsentEvent(candidate_id=c.id, purpose="publish", granted=c.consent_publish, version=v, at=at)]
        if c.consent_external:
            events.append(ConsentEvent(candidate_id=c.id, purpose="external", granted=True, version=v, at=at + DAY * 0.01))
    db.add_all(events)
    db.commit()
    return {**more, "cands": cands, "personas": personas, "needs": needs, "kinds": kinds, "invs": invs, "load": load,
            "companies": companies, "cf": (cf_c, ratings, alg), "ladoga": ladoga}


DEMO_VACANCIES = [  # (компания, title, spec, track, grade, must, nice, from, to, format, city, описание)
    ("ladoga", "Backend-разработчик (Python), команда платежей", "Backend", "Python", "Middle", ["Python", "PostgreSQL", "Kafka"],
     ["Kubernetes"], 240000, 300000, "Гибрид", "Москва",
     "Команда платежей «Ладога Пэй» отвечает за приём платежей: 3 тыс. RPS в пике, 40 млн операций в месяц.\n\n"
     "Задачи: развивать сервис авторизации платежей, переводить синхронные интеграции с банками на очереди Kafka, "
     "разбирать инциденты (дубли, зависшие статусы) и закрывать их причину, а не симптом.\n\n"
     "Стек: Python 3.12, asyncio, PostgreSQL 16 (партиционирование), Kafka, Kubernetes, Grafana.\n"
     "Команда: 6 человек, релизы ежедневно, дежурства раз в шесть недель, оплачиваются отдельно.\n\n"
     "Отбор: вместо первого созвона — разбор инцидента с дублями платежей (~45 минут), затем техническое интервью "
     "с тимлидом и встреча с командой. Решение — за неделю."),
    ("ladoga", "Frontend-разработчик (React), личный кабинет мерчанта", "Frontend", "React", "Middle", ["React", "TypeScript"],
     ["JavaScript", "Node.js"], 220000, 280000, "Гибрид", "Москва",
     "Личный кабинет, в котором 18 тыс. магазинов смотрят платежи, возвраты и выплаты.\n\n"
     "Задачи: таблицы на сотни тысяч строк без тормозов, фильтры и выгрузки, дизайн-система, доступность (WCAG AA).\n\n"
     "Стек: React 19, TypeScript, TanStack Query, Vite, Playwright.\n"
     "Отбор: задача на производительность таблицы (~40 минут) и интервью с командой."),
    ("ladoga", "ML-инженер, антифрод", "ML / DS", "Classic ML", "Senior", ["Python", "scikit-learn", "SQL"],
     ["ClickHouse", "Airflow"], 360000, 460000, "Гибрид", "Москва",
     "Антифрод для карточных и СБП-платежей: решение за 50 мс, ложные срабатывания стоят денег магазинам.\n\n"
     "Задачи: модели скоринга транзакций, мониторинг дрейфа данных, A/B-проверка правил, разбор спорных случаев с аналитиками.\n\n"
     "Стек: Python, CatBoost/scikit-learn, ClickHouse, Airflow, онлайн-фичи в Redis.\n"
     "Отбор: разбор деградации модели после релиза (подход, ~30 минут) и интервью."),
    ("kiprey", "Python-разработчик, сервис маршрутизации", "Backend", "Python", "Middle", ["Python", "PostgreSQL"], ["Redis"],
     190000, 225000, "Удалённо", None,
     "Маршрутизация доставок для 300 B2B-клиентов: строим маршруты, считаем окна доставки, интегрируемся с перевозчиками.\n\n"
     "Задачи: API расчёта маршрутов, интеграции с перевозчиками (REST, SOAP, файлы), кэширование и устойчивость к их сбоям.\n\n"
     "Стек: Python, FastAPI, PostgreSQL + PostGIS, Redis, RabbitMQ.\n"
     "Полностью удалённо, команда в трёх часовых поясах, созвоны только по делу."),
    ("kiprey", "DevOps-инженер (Kubernetes)", "DevOps / SRE", "Kubernetes", "Middle", ["Kubernetes", "Docker", "Linux"],
     ["Prometheus", "Terraform"], 230000, 290000, "Удалённо", None,
     "Платформа для 40 сервисов: два кластера Kubernetes, CI/CD, наблюдаемость.\n\n"
     "Задачи: миграции без простоя, план отката для каждого релиза, алерты, по которым можно действовать, а не шум.\n\n"
     "Стек: Kubernetes, Helm, Argo CD, Terraform, Prometheus, Grafana, Loki.\n"
     "Отбор: план отката неудачной миграции (подход, ~30 минут) и интервью."),
]
SHOWCASE = [  # (компания|None=синтетическая, title, spec, competency, kind, minutes, text)
    ("ladoga", "Идемпотентность платёжного API", "Backend", "Проектирование API", "approach", 30,
     "Клиент повторяет POST /payments при таймауте, и иногда списание проходит дважды. Предложите, как сделать "
     "создание платежа идемпотентным: ключ, хранение, поведение при гонке двух повторов, срок жизни ключа."),
    ("kiprey", "Кэш маршрутов при пиковой нагрузке", "Backend", "Конкурентность", "solve", 45,
     "Расчёт маршрута занимает 2 с, в пик 200 одинаковых запросов в секунду. Напишите обёртку кэша, при которой "
     "одновременные одинаковые запросы ждут один расчёт (без «эффекта толпы»)."),
    (None, "Тормозит таблица на 10 000 строк", "Frontend", "Производительность", "solve", 40,
     "Таблица платежей перерисовывается целиком при вводе в фильтр. Найдите причину в приложенном компоненте и исправьте."),
    (None, "Модель скоринга деградировала после релиза", "ML / DS", "Дрейф данных", "approach", 30,
     "После релиза мобильного приложения доля одобрений упала на 7 п. п. Опишите, как найти причину и что проверить первым."),
    (None, "План отката миграции БД", "DevOps / SRE", "План отката", "approach", 30,
     "Миграция добавляет NOT NULL колонку в таблицу на 200 млн строк. Опишите выкладку и откат без простоя."),
    (None, "Приёмка релиза мобильного банка", "QA", "Приёмка релиза", "solve", 40,
     "Даны список изменений и отчёт автотестов. Составьте чек-лист приёмки и решите: выпускать или нет."),
    (None, "Дубли в витрине заказов", "Data Eng / Analytics", "Качество данных", "solve", 45,
     "В витрине заказов 0,3 % дублей после перезапуска DAG. Найдите причину и сделайте загрузку идемпотентной."),
    (None, "Ревью эндпоинта выгрузки счетов", "Security", "Веб-уязвимости", "solve", 30,
     "Посмотрите обработчик GET /invoices/{id}/pdf и найдите уязвимости. Предложите исправление."),
]
NEED_TASKS = [
    ("Разбор инцидента с дублями платежей", "Диагностика инцидентов", "solve", 45,
     "Ночью часть платежей списалась дважды. Даны логи сервиса, график ретраев и схема таблиц. Найдите причину, "
     "предложите исправление и как не допустить повтора. Заменяет первый созвон."),
    ("Подход: перенос истории платежей в отдельное хранилище", "Базы данных и транзакции", "approach", 30,
     "Таблица платежей выросла до 2 ТБ, отчёты тормозят основную базу. Опишите план переноса истории без простоя."),
]
REVIEW_TEXT = {"strong": ["Чёткий план и аргументы, видно опыт.", "Нашёл корневую причину, решение аккуратное."],
               "ok": ["Решение рабочее, но пропущены крайние случаи.", "Направление верное, детали поверхностные."],
               "weak": ["Не учтены гонки и повторы.", "Ответ общий, без конкретики по задаче."]}


def extras(db, g: Gen, ladoga, kiprey, lad_need, companies, hq, orlov, cands) -> dict:
    """Вакансии, отклики, задания и решения; неподтверждённая демо-компания «Новый Стартап»."""
    r = g.rng
    demo = {"ladoga": ladoga, "kiprey": kiprey}
    vacancies = [Vacancy(company=demo[co], title=t, spec=sp, track=tr, grade=gr, must=mu, nice=ni, salary_from=f, salary_to=to,
                         format=fm, city=ci, description=d)
                 for co, t, sp, tr, gr, mu, ni, f, to, fm, ci, d in DEMO_VACANCIES]
    for i in range(120):
        co = companies[i % len(companies)]
        st = g.struct(co, "normal", hq[id(co)])
        text = st.pop("text")
        vacancies.append(Vacancy(company=co, title=f"{SPEC_TITLE[st['spec']]} ({st['track']}), {st['grade']}",
                                 description=f"{text}\n\nКоманда {g.pick(TEAMS)}, {int(r.integers(4, 15))} человек.",
                                 status="open" if r.random() < 0.9 else "closed", is_synthetic=True, **st))

    # отклики: кандидаты с открытым профилем и согласием на показ откликаются на вакансии своей специализации
    pool: dict[str, list[Candidate]] = {}
    for c in cands:
        if c.status == "open" and c.consent_publish:
            pool.setdefault(c.spec, []).append(c)
    apps, seen_pairs = [], set()
    for _ in range(350):
        v = g.pick(vacancies[len(DEMO_VACANCIES):])
        c = g.pick(pool.get(v.spec) or cands)
        if (id(v), id(c)) in seen_pairs:
            continue
        seen_pairs.add((id(v), id(c)))
        st = g.pick(["sent", "seen", "accepted", "declined"], p=[.3, .25, .2, .25])
        at = NOW - DAY * float(r.uniform(0, 40))
        reason = None
        if st == "declined":
            reason = "salary" if c.min_salary > v.salary_to else g.pick(["stack", "format", "company"])
        apps.append(Application(vacancy=v, candidate=c, status=st, decline_reason=reason, created_at=at, is_synthetic=True,
                                note=g.pick([None, "Интересна предметная область", "Готов к задаче вместо созвона"]),
                                seen_at=at + DAY * 0.5 if st != "sent" else None,
                                responded_at=at + DAY * 2 if st in ("accepted", "declined") else None))
    bp = [v for v in vacancies[len(DEMO_VACANCIES):] if v.spec == "Backend" and v.track == "Python" and v.status == "open"]
    for v, st in zip(bp[:2], ("seen", "sent")):  # свои отклики Орлова на этой неделе
        apps.append(Application(vacancy=v, candidate=orlov, status=st, note="Интересны высоконагруженные сервисы",
                                created_at=NOW - DAY * 0.5, seen_at=NOW - DAY * 0.2 if st == "seen" else None))

    # задания: витрина + два задания под потребность «Ладога Пэй»
    tasks = [Task(company=demo[co] if co else g.pick(companies), title=t, spec=sp, competency=cmp, kind=k, minutes=m, text=x,
                  public=True, is_synthetic=co is None) for co, t, sp, cmp, k, m, x in SHOWCASE]
    db.add(lad_need)
    db.flush()  # у Task нет relationship на Need — нужен need_id
    tasks += [Task(company=ladoga, need_id=lad_need.id, title=t, spec="Backend", competency=cmp, kind=k, minutes=m, text=x, public=False)
              for t, cmp, k, m, x in NEED_TASKS]
    subs = []
    for t in tasks[:len(SHOWCASE)]:
        for c in g.sample(pool.get(t.spec, []), int(r.integers(10, 26))):
            q = c.truth["theta_true"] + float(r.normal(0, 0.6))
            rv = None if r.random() < 0.2 else "strong" if q > 1.6 else "ok" if q > 0.6 else "weak"
            at = NOW - DAY * float(r.uniform(1, 60))
            subs.append(TaskSubmission(task=t, candidate=c, is_synthetic=True, created_at=at,
                                       answer=f"{'Решение' if t.kind == 'solve' else 'Подход'}: " + " ".join(
                                           g.sample(CV_LINES, 2)).format(a=g.pick(c.skills_confirmed), b=g.pick(c.skills_confirmed), n=5),
                                       review=rv, review_comment=g.pick(REVIEW_TEXT[rv]) if rv else None,
                                       reviewed_at=at + DAY * 2 if rv else None))
    subs.append(TaskSubmission(
        task=tasks[0], candidate=orlov, review="strong", created_at=NOW - DAY * 4, reviewed_at=NOW - DAY * 2,
        answer="Ключ идемпотентности от клиента (UUID) в заголовке; уникальный индекс (merchant_id, key) в PostgreSQL; "
               "первый запрос вставляет запись в статусе processing в той же транзакции, повтор получает сохранённый ответ "
               "или 409 при гонке; TTL ключа 24 ч; события в Kafka через outbox.",
        review_comment="Чёткий план: уникальный индекс, поведение при гонке, outbox. Обсудим детали на интервью."))

    # неподтверждённая демо-компания: работает с урезанной квотой, лотерея ей доступна
    u_new = User(email="newco.hr@gmail.com", role="employer")
    db.add(u_new)
    db.flush()
    newco = Company(user_id=u_new.id, inn=inn_make("773300112"), name="Новый Стартап", about="Edtech, MVP, 12 сотрудников",
                    color="#0E7C66", site_domain=None, recruiter_name="Алина Мельникова", recruiter_email="newco.hr@gmail.com",
                    recruiter_tg="@newco_hr", verified=False, quota_max=C.UNVERIFIED_QUOTA)
    new_need = Need(company=newco, kind="normal", spec="Backend", track="Python", grade="Junior", must=["Python"], nice=["Django"],
                    salary_from=120000, salary_to=160000, format="Удалённо",
                    text="Ищем джуна на Python для MVP образовательной платформы: Django, PostgreSQL. 120–160 тыс., удалённо.")
    return {"vacancies": vacancies, "apps": apps, "tasks": tasks, "subs": subs,
            "all": [*vacancies, *apps, *tasks, *subs, newco, new_need]}


def summary(db, res: dict, secs: float) -> None:
    cands = res["cands"]
    print(f"\nСинтетика: {len(cands)} кандидатов + {len(res['personas'])} демо, {len(res['companies'])} компаний + 2 демо, "
          f"{len(res['needs'])} потребностей + 2 демо, {len(res['invs'])} приглашений — {secs:.1f} с\n")
    tab = Counter((c.spec, c.grade) for c in cands)
    w = 22
    print("Специализация".ljust(w) + "".join(g[:6].rjust(8) for g in C.GRADES) + "Всего".rjust(8) + "Достиж.".rjust(9) + "CF".rjust(6))
    for s in C.SPECS:
        grp = [c for c in cands if c.spec == s]
        ach = sum(bool(c.achievements) for c in grp) / max(1, len(grp))
        cf = sum(bool(c.accounts) for c in grp) / max(1, len(grp))
        print(s.ljust(w) + "".join(str(tab[s, g]).rjust(8) for g in C.GRADES) + str(len(grp)).rjust(8)
              + f"{ach:8.0%}" + f"{cf:6.0%}")
    n = len(cands)
    cf_c, ratings, alg = res["cf"]
    rho = float(np.corrcoef(alg, ratings)[0, 1]) if len(cf_c) > 2 else float("nan")
    gt = sum(c.grade == c.truth["grade_true"] for c in cands) / n
    print(f"\nС достижениями: {sum(bool(c.achievements) for c in cands) / n:.0%} · с CF: {len(cf_c) / n:.0%} (ρ рейтинг~Алгоритмы = {rho:.2f})"
          f" · завышенные резюме: {sum(c.truth['inflated'] for c in cands) / n:.0%} · open: {sum(c.status == 'open' for c in cands) / n:.0%}")
    print(f"Грейд теста = истинному: {gt:.0%} (остальные — ниже из-за θ − SE) · городов: {len({c.city for c in cands})} · "
          f"Москва {sum(c.city == 'Москва' for c in cands) / n:.0%}")
    print(f"Потребности по типам: {dict(res['kinds'])}")
    print(f"Приглашения по статусам: {dict(Counter(i.status for i in res['invs']))}")
    lc = Counter(res["load"][id(c)] for c in cands)
    print(f"Нагрузка кандидатов (открытых приглашений): {dict(sorted(lc.items()))}")
    lad = res["ladoga"]
    li = [i for i in res["invs"] if i.company is lad]
    closed = [i for i in li if i.status in ("accepted", "declined", "expired")]
    print(f"«Ладога Пэй»: квота {sum(i.sent_at >= WEEK_START for i in li)} / {lad.quota_max} на этой неделе, "
          f"принято {sum(i.status == 'accepted' for i in closed) / len(closed):.0%} закрытых, ИНН {lad.inn}")
    print(f"Согласие на показ карточки (consent_publish): {sum(c.consent_publish for c in cands) / n:.0%} синтетики")
    print(f"Вакансии: {len(res['vacancies'])} (демо {sum(not v.is_synthetic for v in res['vacancies'])}) · отклики: "
          f"{dict(Counter(a.status for a in res['apps']))} · задания: {len(res['tasks'])} "
          f"(витрина {sum(t.public for t in res['tasks'])}) · решения: {dict(Counter(x.review for x in res['subs']))}")
    leak = db.scalar(select(func.count(Candidate.id.distinct())).where(
        ~Candidate.consent_external, Candidate.id.in_(select(Achievement.candidate_id).union(select(ExternalAccount.candidate_id)))))
    assert leak == 0, f"внешние данные без согласия: {leak}"
    assert not db.scalar(select(func.count()).select_from(Candidate).where(Candidate.consent_version != C.CONSENT_VERSION))
    assert not db.scalar(select(func.count()).select_from(ExternalAccount).where(ExternalAccount.verify_code != ""))
    cnt = lambda *w: db.scalar(select(func.count()).select_from(Candidate).where(*w))  # noqa: E731
    assert not cnt(Candidate.consent_publish, Candidate.consent_publish_version.is_distinct_from(C.CONSENT_VERSION))
    assert not cnt(Candidate.consent_external, Candidate.consent_external_version.is_distinct_from(C.CONSENT_VERSION))
    ce = dict(db.execute(select(ConsentEvent.purpose, func.count()).group_by(ConsentEvent.purpose)).all())
    print(f"Внешние данные без согласия: {leak} · consent_external: {sum(c.consent_external for c in cands) / n:.0%} · "
          f"журнал согласий: {ce}")
    print(f"Событий: {db.scalar(select(func.count()).select_from(Event))}, достижений: {db.scalar(select(func.count()).select_from(Achievement))}")


def main():
    ap = argparse.ArgumentParser(description="Синтетические данные ФСП Карьеры")
    ap.add_argument("--reset", action="store_true", help="drop_all + create_all перед генерацией")
    ap.add_argument("--candidates", type=int, default=1500)
    ap.add_argument("--needs", type=int, default=250)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    from app import models  # noqa: F401 — регистрирует таблицы

    if a.reset:
        print(f"--reset: пересоздаю таблицы в {engine.url.render_as_string(hide_password=True)}")
        Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    t0 = time.time()
    with SessionLocal() as db:
        if db.scalar(select(User).where(User.email == "d.orlov@example.ru")):
            raise SystemExit("База уже засеяна — запустите с --reset")
        res = build(db, a.candidates, a.needs, a.seed)
        secs = time.time() - t0
        try:
            from app.services.items import seed_items

            n = seed_items(db) if inspect.signature(seed_items).parameters else seed_items()
            print(f"Банк заданий: seed_items → {n}")
        except ImportError:
            print("Банк заданий: app.services.items.seed_items ещё нет — пропускаю")
        summary(db, res, secs)


if __name__ == "__main__":
    main()
