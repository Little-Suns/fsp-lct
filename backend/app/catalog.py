"""Справочник: специализации, треки, грейды, навыки, рынок, правила. Значения взяты из макета (frontend/index.html)."""

SPECS = ["Backend", "Frontend", "Mobile", "ML / DS", "Data Eng / Analytics", "DevOps / SRE", "QA", "Security"]

TRACKS = {
    "Backend": ["Python", "Go", "Java / Kotlin", "Node.js", "C# / .NET"],
    "Frontend": ["React", "Vue", "Angular"],
    "Mobile": ["iOS", "Android", "Flutter"],
    "ML / DS": ["Classic ML", "CV", "NLP / LLM"],
    "Data Eng / Analytics": ["Data Engineering", "BI / Analytics"],
    "DevOps / SRE": ["Kubernetes", "Cloud"],
    "QA": ["Manual", "Automation"],
    "Security": ["AppSec", "Pentest"],
}

GRADES = ["Intern", "Junior", "Middle", "Senior", "Lead"]
# пороги θ: грейд присваивается, если θ − SE ≥ порог (гистерезис против «дрожания» при пересдаче)
GRADE_TH = {"Intern": -9.0, "Junior": -0.5, "Middle": 0.5, "Senior": 1.5, "Lead": 2.3}
UPGRADE_COOLDOWN_DAYS = 90
REVIEW_REQUIRED_FROM = "Senior"  # «разбор решения» для Senior+

FORMATS = ["Офис", "Гибрид", "Удалённо"]
DECLINE_REASONS = {"salary": "Зарплата", "stack": "Стек", "format": "Формат", "not_looking": "Сейчас не ищу", "company": "Компания"}
FEEDBACK = {"confirmed": "грейд подтвердился", "not_confirmed": "не подтвердился", "hired": "наняли"}

# регуляторы рынка
CANDIDATE_CAP = 4  # открытых приглашений (sent|seen) у кандидата
INVITE_TTL_DAYS = 7
QUOTA_BASE = 10  # приглашений в неделю (сброс в понедельник)
QUOTA_BONUS = 12  # при доле принятых ≥ QUOTA_BONUS_AT
QUOTA_BONUS_AT = 0.5
FORK_MAX_WIDTH = 0.4  # (to − from) / from


def load_penalty(load: int) -> float:
    # каждое открытое приглашение −15 %; ёмкость заполнена → ×0,3 (кандидат почти выпадает из топа, но виден)
    return 0.3 if load >= CANDIDATE_CAP else 1 - 0.15 * load


# Компетенции по специализациям (для Backend — как в макете)
COMPETENCIES = {
    "Backend": ["Диагностика инцидентов", "Базы данных и транзакции", "Ревью кода", "Проектирование API", "Конкурентность", "Алгоритмы"],
    "Frontend": ["Отладка UI", "Производительность", "Ревью кода", "Архитектура клиента", "Доступность", "Алгоритмы"],
    "Mobile": ["Отладка", "Жизненный цикл приложения", "Ревью кода", "Сеть и офлайн", "Производительность", "Алгоритмы"],
    "ML / DS": ["Постановка задачи", "Валидация моделей", "Дрейф данных", "Feature engineering", "MLOps", "Алгоритмы"],
    "Data Eng / Analytics": ["SQL", "Моделирование данных", "Пайплайны", "Качество данных", "Визуализация", "Алгоритмы"],
    "DevOps / SRE": ["Диагностика инцидентов", "Сети", "Kubernetes", "CI/CD", "Наблюдаемость", "План отката"],
    "QA": ["Тест-дизайн", "Приёмка релиза", "Автотесты", "API-тестирование", "Баг-репорты", "Регресс"],
    "Security": ["Веб-уязвимости", "Ревью кода", "Сети", "Криптография", "Реагирование", "Реверс"],
}

# Навыки: канон → синонимы (нижний регистр). Используется при разборе резюме и потребностей.
SKILLS = {
    "Python": ["python", "питон", "пайтон", "py"],
    "Go": ["go", "golang", "голанг"],
    "Java": ["java", "джава"],
    "Kotlin": ["kotlin", "котлин"],
    "Node.js": ["node.js", "nodejs", "node", "нода"],
    "C#": ["c#", ".net", "dotnet", "шарп"],
    "TypeScript": ["typescript", "ts"],
    "JavaScript": ["javascript", "js"],
    "React": ["react", "реакт"],
    "Vue": ["vue", "vue.js"],
    "Angular": ["angular"],
    "Swift": ["swift", "ios"],
    "Flutter": ["flutter", "dart"],
    "PostgreSQL": ["postgresql", "postgres", "постгрес", "pg"],
    "MySQL": ["mysql"],
    "MongoDB": ["mongodb", "mongo"],
    "Redis": ["redis", "редис"],
    "ClickHouse": ["clickhouse", "кликхаус"],
    "Kafka": ["kafka", "кафка"],
    "RabbitMQ": ["rabbitmq", "rabbit", "кролик"],
    "Docker": ["docker", "докер"],
    "Kubernetes": ["kubernetes", "k8s", "кубернетес", "кубер"],
    "Terraform": ["terraform"],
    "Linux": ["linux", "линукс"],
    "asyncio": ["asyncio", "async", "асинхронщина"],
    "FastAPI": ["fastapi"],
    "Django": ["django", "джанго"],
    "gRPC": ["grpc"],
    "Spark": ["spark", "pyspark"],
    "Airflow": ["airflow"],
    "SQL": ["sql"],
    "PyTorch": ["pytorch", "torch"],
    "scikit-learn": ["scikit-learn", "sklearn"],
    "LLM": ["llm", "rag", "langchain"],
    "Computer Vision": ["computer vision", "cv", "opencv"],
    "Selenium": ["selenium", "playwright"],
    "Pentest": ["pentest", "пентест", "burp"],
    "Prometheus": ["prometheus", "grafana"],
}

# Роли и софт-скиллы из резюме: канон → основы слов (регулярки, совпадение с начала слова, нижний регистр).
# Заявлены кандидатом, тестом не проверяются: в карточке и PDF-профиле — справочно, в подборе и грейде не участвуют.
# ponytail: словарь основ без учёта отрицаний («не руководил»); с LLM разбор уточняет модель
ROLES = {
    "Тимлид": ["тимлид", "team ?lead", "руководител\\w* (?:команд|групп|отдел)", "руководил\\w* команд"],
    "Техлид": ["техлид", "tech ?lead", "технический лидер"],
    "Архитектор": ["архитектор", "architect(?!ur)"],
    "Ментор": ["ментор", "наставни", "mentor"],
    "Капитан команды": ["капитан", "captain"],
    "Руководитель проекта": ["руководител\\w* проект", "project manager", "менеджер\\w* проект", "product owner"],
    "Исследователь": ["исследовател", "researcher", "научн\\w* сотрудник"],
    "Преподаватель": ["преподава", "лектор", "teacher", "lecturer"],
    "Контрибьютор open source": ["контрибьют", "contribut(?:or|ed to|ing to)", "мейнтейнер", "maintainer"],
    "Спикер": ["спикер", "speaker", "доклад"],
}
SOFT_SKILLS = {
    "Коммуникация": ["коммуникаб", "коммуникативн", "навык\\w* коммуникац", "communication skills", "communicative", "переговор"],
    "Работа в команде": ["командн\\w* (?:игрок|работ)", "работ\\w* в команде", "team ?player", "teamwork", "кросс-?функциональн"],
    "Лидерство": ["лидерск", "лидерств", "leadership", "руководил", "возглавлял", "управлял\\w* команд"],
    "Наставничество": ["наставничеств", "менторств", "mentoring", "обучал\\w* (?:стаж|джун|новичк|сотрудник)", "онбординг"],
    "Самостоятельность": ["самостоятельн", "проактивн", "инициативн", "ownership", "self-?motivated"],
    "Ответственность": ["ответственн(?:ый|ая|а|ы|ость(?! за))(?![а-яё])", "responsible person", "accountab"],
    "Аналитическое мышление": ["аналитическ\\w* (?:мышлен|склад)", "системн\\w* мышлен", "analytical", "problem[ -]solving", "решени\\w* проблем"],
    "Обучаемость": ["обучаем", "быстро обуча", "быстро учусь", "fast learner"],
    "Тайм-менеджмент": ["тайм-?менеджмент", "time management", "управлени\\w* времен"],
    "Публичные выступления": ["публичн\\w* выступлен", "выступал", "public speaking", "доклад"],
}

# Рынок: перцентили зарплаты «на руки» (₽/мес) для Москвы по грейду; Backend · Middle — как в макете.
# ponytail: одна таблица по грейду + множители; реальные данные Хабр Карьеры — когда будут
MARKET_MOSCOW = {
    "Intern": (60000, 80000, 100000),
    "Junior": (110000, 140000, 175000),
    "Middle": (210000, 260000, 310000),
    "Senior": (320000, 390000, 460000),
    "Lead": (400000, 480000, 580000),
}
SPEC_MULT = {"Backend": 1.0, "Frontend": 0.95, "Mobile": 1.0, "ML / DS": 1.08, "Data Eng / Analytics": 0.95, "DevOps / SRE": 1.05, "QA": 0.8, "Security": 1.05}
CITY_MULT = {"Москва": 1.0, "Санкт-Петербург": 0.92}
CITY_MULT_DEFAULT = 0.78


def market(spec: str, grade: str, city: str | None = "Москва") -> dict:
    k = SPEC_MULT.get(spec, 1.0) * CITY_MULT.get(city or "Москва", CITY_MULT_DEFAULT)
    p25, p50, p75 = (round(v * k / 5000) * 5000 for v in MARKET_MOSCOW[grade])
    return {"p25": p25, "p50": p50, "p75": p75}


def grade_from_theta(theta: float, se: float) -> str:
    g = "Intern"
    for name in GRADES:
        if theta - se >= GRADE_TH[name]:
            g = name
    return g


# 152-ФЗ: версия текста согласия; при изменении текста согласие запрашивается заново
CONSENT_VERSION = "2026-10"
UNVERIFIED_QUOTA = 3  # неподтверждённая компания работает, но с урезанной квотой и плашкой для кандидата
APPLICATIONS_PER_WEEK = 10  # мягкий лимит откликов кандидата (Horton: меньше перегрузки работодателей)
