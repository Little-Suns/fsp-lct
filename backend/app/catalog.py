"""Справочник: специализации, треки, грейды, навыки, рынок, правила. Значения взяты из макета (frontend/index.html)."""

SPECS = ["Backend", "Frontend", "Mobile", "ML / DS", "Data Eng / Analytics", "DevOps / SRE", "QA", "Security",
         "Analysis", "Management", "Design", "SysAdmin / Support"]

TRACKS = {
    "Backend": ["Python", "Go", "Java / Kotlin", "Node.js", "C# / .NET"],
    "Frontend": ["React", "Vue", "Angular"],
    "Mobile": ["iOS", "Android", "Flutter"],
    "ML / DS": ["Classic ML", "CV", "NLP / LLM"],
    "Data Eng / Analytics": ["Data Engineering", "BI / Analytics"],
    "DevOps / SRE": ["Kubernetes", "Cloud"],
    "QA": ["Manual", "Automation"],
    "Security": ["AppSec", "Pentest"],
    # нетехнические ИТ-роли: имена треков уникальны во всём справочнике (подсказки треков и синтетика ключуются по ним)
    "Analysis": ["System", "Business"],
    "Management": ["Project", "Product"],
    "Design": ["UX/UI", "Product Design"],
    "SysAdmin / Support": ["SysAdmin", "Support"],
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
    "Analysis": ["Выявление требований", "Моделирование процессов", "Интеграции и API", "Данные и SQL", "Спецификации", "Анализ изменений"],
    "Management": ["Планирование и сроки", "Риски", "Метрики продукта", "Приоритизация", "Стейкхолдеры", "Процессы команды"],
    "Design": ["Исследования", "Юзабилити", "Доступность", "Дизайн-системы", "Прототипирование", "Метрики и эксперименты"],
    "SysAdmin / Support": ["Диагностика инцидентов", "Сети", "Учётные записи и доступ", "Резервное копирование", "Серверы и ОС", "Работа с обращениями"],
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
    "BPMN": ["bpmn"],
    "UML": ["uml"],
    "REST": ["rest", "openapi", "swagger"],
    "Jira": ["jira", "джира"],
    "Confluence": ["confluence", "конфлюенс"],
    "Scrum": ["scrum", "скрам", "agile", "аджайл", "kanban", "канбан"],
    "A/B-тесты": ["a/b", "a/b-тесты", "ab-тесты", "аб-тесты"],
    "CustDev": ["custdev", "кастдев", "customer development"],
    "Figma": ["figma", "фигма"],
    "Windows Server": ["windows server", "active directory"],
    "Bash": ["bash"],
    "ITIL": ["itil", "service desk", "servicedesk"],
    "Zabbix": ["zabbix", "заббикс"],
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
    "Контрибьютор open source": ["контрибьют", "open[ -]?source[ -]contribut", "contribut\\w*\\s+to\\s+open[ -]?source", "мейнтейнер", "maintainer"],
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
SPEC_MULT = {"Backend": 1.0, "Frontend": 0.95, "Mobile": 1.0, "ML / DS": 1.08, "Data Eng / Analytics": 0.95, "DevOps / SRE": 1.05, "QA": 0.8, "Security": 1.05,
             "Analysis": 0.95, "Management": 1.05, "Design": 0.85, "SysAdmin / Support": 0.65}
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

# Отзыв кандидата о компании после принятия приглашения: кандидату репутация компании не показывается,
# отзывы только меняют квоту работодателя (services/reputation.py)
COMPANY_FEEDBACK = {
    "ok": "Всё честно, условия совпали",
    "no_contact": "Не вышли на связь",
    "mismatch": "Условия не совпали с приглашением",
    "fraud": "Вакансии не было: просили денег или данные",
}
COMPANY_FEEDBACK_BAD = ("no_contact", "mismatch", "fraud")
COMPANY_FEEDBACK_AFTER_DAYS = 7  # отзыв открывается через неделю после принятия: было время выйти на связь
FEEDBACK_WINDOW_DAYS = 30  # квота считается по отзывам за скользящие 30 дней — штраф снимается сам
FEEDBACK_BAD_MIN = 3  # плохих отзывов от разных кандидатов, ниже — один обиженный ничего не решает
FEEDBACK_BAD_SHARE = 0.5  # и не меньше половины всех отзывов окна: крупную компанию три отзыва не топят
FEEDBACK_PENALTY_QUOTA = 3  # квота при штрафе, без бонуса за принятые
FRAUD_BLOCK_MIN = 2  # «вакансии не было» от разных кандидатов → полный блок до ручной проверки
FEEDBACK_SUMMARY_MIN = 3  # сводку отзывов работодатель видит от трёх: по одному отзыву не вычислить автора
assert FEEDBACK_BAD_MIN >= FEEDBACK_SUMMARY_MIN  # плашка штрафа показывает сводку: при штрафе она должна быть открыта
APPLICATIONS_PER_WEEK = 10  # мягкий лимит откликов кандидата (Horton: меньше перегрузки работодателей)

# Данные ФСП из протоколов — факты для карточки, на вес достижения не влияют (дисциплины не ранжируются).
# Дисциплины вида спорта «спортивное программирование»: каноническое название → синонимы для импорта.
DISCIPLINES = {
    "продуктовое программирование": ("продуктовое", "product"),
    "алгоритмическое программирование": ("алгоритмическое", "algo", "algorithmic"),
    "программирование систем информационной безопасности": ("кибербезопасность", "информационная безопасность", "иб", "security"),
    "программирование беспилотных авиационных систем": ("программирование бас", "бас", "бпла", "uav"),
    "программирование робототехники": ("робототехника", "robotics"),
}
# Спортивные звания и разряды (ЕВСК) — от старшего к младшему; порядок нужен только, чтобы показать высший
SPORT_RANKS = ("ЗМС", "МС", "КМС", "1 разряд", "2 разряд", "3 разряд",
               "1 юношеский разряд", "2 юношеский разряд", "3 юношеский разряд")
