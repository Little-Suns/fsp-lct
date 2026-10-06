"""Клиент LLM (httpx замокан) и разбор текста: при недоступной модели всё работает на правилах, ответ модели
проверяется по справочнику, а персональные признаки вырезаются до разбора. БД не нужна."""

import json
from datetime import datetime

import httpx
import pytest

from app import catalog, config
from app.services import llm, parsing
from app.services.parsing import parse_cv, parse_need

URL = "http://llm.test/v1"


@pytest.fixture
def model(monkeypatch):
    """Подменяет httpx.post: ответ задаётся через model.reply (dict | Exception | httpx.Response)."""
    monkeypatch.setattr(config, "LLM_BASE_URL", URL + "/")
    monkeypatch.setattr(llm, "_down_until", 0.0)

    class Fake:
        reply: object = None
        calls: list = []

        def __call__(self, url, json=None, timeout=None):
            self.calls.append((url, json, timeout))
            if isinstance(self.reply, Exception):
                raise self.reply
            if isinstance(self.reply, httpx.Response):
                return self.reply
            return httpx.Response(200, json=self.reply, request=httpx.Request("POST", url))

    fake = Fake()
    fake.calls = []
    monkeypatch.setattr(llm.httpx, "post", fake)
    return fake


def _chat(content) -> dict:
    return {"choices": [{"message": {"content": content if isinstance(content, str) else json.dumps(content)}}]}


# ---------- llm.py ----------


def test_chat_json_success(model):
    model.reply = _chat({"spec": "Backend"})
    assert llm.chat_json("sys", "user") == {"spec": "Backend"}
    url, body, timeout = model.calls[0]
    assert url == URL + "/chat/completions" and timeout == config.LLM_TIMEOUT
    assert body["model"] == config.LLM_MODEL and body["temperature"] == 0 and body["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


@pytest.mark.parametrize("reply", [_chat("не json"), _chat([1, 2]), {"choices": []}, {"oops": 1}])
def test_chat_json_bad_answer_is_none_without_cooldown(model, reply):
    model.reply = reply
    assert llm.chat_json("s", "u") is None
    assert llm._down_until == 0.0  # модель ответила — просто плохой ответ, не отключаемся
    model.reply = _chat({"ok": True})
    assert llm.chat_json("s", "u") == {"ok": True}


@pytest.mark.parametrize(
    "reply",
    [
        httpx.ConnectError("нет соединения"),
        httpx.ReadTimeout("таймаут"),
        httpx.Response(500, text="boom", request=httpx.Request("POST", URL)),
        httpx.Response(200, content=b"<html>", request=httpx.Request("POST", URL)),  # r.json() → ValueError
    ],
)
def test_http_error_returns_none_and_cools_down(model, reply):
    model.reply = reply
    assert llm.chat_json("s", "u") is None
    assert llm._down_until > 0
    # минуту модель не дёргаем: следующий вызов сразу None, без запроса
    model.reply = _chat({"ok": True})
    n = len(model.calls)
    assert llm.chat_json("s", "u") is None and llm.embed(["x"]) is None
    assert len(model.calls) == n


def test_disabled_without_base_url(model, monkeypatch):
    monkeypatch.setattr(config, "LLM_BASE_URL", "")
    assert llm.chat_json("s", "u") is None and llm.embed(["x"]) is None
    assert model.calls == []


def test_embed(model):
    model.reply = {"data": [{"index": 1, "embedding": [0.2]}, {"index": 0, "embedding": [0.1]}]}
    assert llm.embed(["a", "b"]) == [[0.1], [0.2]]
    assert model.calls[0][0] == URL + "/embeddings" and model.calls[0][1] == {"model": config.EMBED_MODEL, "input": ["a", "b"]}
    for bad in ({"data": [{"index": 0}]}, {"data": None}, {}):
        model.reply = bad
        assert llm.embed(["a"]) is None


# ---------- parsing.py: правила (LLM недоступна) ----------


@pytest.fixture
def no_llm(monkeypatch):
    monkeypatch.setattr(config, "LLM_BASE_URL", "")


def test_need_rules_fallback_when_llm_down(model):
    """Модель лежит → parsed_by=rules и тот же результат, что у чистых правил."""
    model.reply = httpx.ConnectError("down")
    text = "Ищем бэкендера на Python. Нужен PostgreSQL и Kafka, хорошо бы Kubernetes. Мидл, до 300 на руки. Гибрид, Москва."
    n = parse_need(text)
    assert n["parsed_by"] == "rules" and n == parse_need(text, use_llm=False)
    assert (n["must"], n["nice"], n["salary_from"], n["salary_to"]) == (["Python", "PostgreSQL", "Kafka"], ["Kubernetes"], 240000, 300000)


@pytest.mark.parametrize(
    "text, expect",
    [
        # специализация по навыкам, когда слова «бэкенд» нет; грейд по умолчанию — Middle с подсказкой
        ("Нужен человек: Django, FastAPI, gRPC.", {"spec": "Backend", "track": "Python", "grade": "Middle", "must": ["Django", "FastAPI", "gRPC"]}),
        # трек без навыков — по словам
        ("Аналитик данных, BI, дашборды", {"spec": "Data Eng / Analytics", "track": "BI / Analytics", "must": []}),
        # совсем пусто → Backend, первый трек, вилка по рынку
        ("Нужен кто-то толковый", {"spec": "Backend", "track": "Python", "format": None, "city": None}),
        # стаж не путается с деньгами; диапазон «60-80к»
        ("QA инженер автотесты Selenium, стажёр, 5 лет опыта, 60-80к",
         {"spec": "QA", "track": "Automation", "grade": "Intern", "salary_from": 60000, "salary_to": 80000}),
        ("Тимлид Java, офис, Екатеринбург, 300k", {"track": "Java / Kotlin", "grade": "Lead", "format": "Офис", "city": "Екатеринбург", "salary_to": 300000}),
        ("Мобильный разработчик Flutter, удалёнка, СПб", {"spec": "Mobile", "track": "Flutter", "format": "Удалённо", "city": "Санкт-Петербург"}),
        ("Python. Kafka опционально", {"must": ["Python"], "nice": ["Kafka"]}),
    ],
)
def test_need_rules(no_llm, text, expect):
    n = parse_need(text)
    assert n["parsed_by"] == "rules"
    assert {k: n[k] for k in expect} == expect, n
    assert n["salary_from"] and n["salary_to"] and n["salary_from"] <= n["salary_to"]  # вилка всегда достроена


def test_need_hints_and_personal(no_llm):
    n = parse_need("Ищем разработчика React, от 250 тыс., удалённо. Выпускник МГУ, фото обязательно, славянской внешности.")
    assert (n["spec"], n["salary_from"], n["salary_to"]) == ("Frontend", 250000, 310000)
    assert n["ignored"] == ["вуз", "фото", "национальность"]
    assert any(h.startswith("«от 250»") for h in n["hints"]) and any("Персональные признаки" in h for h in n["hints"])
    n = parse_need("Нужен кто-то толковый")
    assert n["hints"] == ["Грейд не указан → поставили Middle, поправьте при необходимости",
                          "Вилка не указана → предложили по рынку: от медианы до 75-го перцентиля"]


@pytest.mark.parametrize(
    "s, expect",
    [
        ("от 250 до 300", (250000, 300000)),
        ("300–250 тыс", (250000, 300000)),
        ("1,2 млн - 1,5 млн", (1200000, 1500000)),
        ("зп 300 000 руб", (None, 300000)),
        ("от 180к", (180000, None)),
        ("до 5 млн", (None, None)),  # вне разумного диапазона
        ("до 10", (None, None)),  # 10 000 ₽ — меньше минимума
        ("опыт 5 лет", (None, None)),
        ("12345678", (None, None)),
    ],
)
def test_salary_rules(s, expect):
    assert parsing._salary(s) == expect


def test_fill_fork():
    assert parsing.fill_fork("Backend", "Middle", "Москва", 200000, 250000) == (200000, 250000, None)
    lo, hi, hint = parsing.fill_fork("Backend", "Middle", "Москва", None, 300000)
    assert (lo, hi) == (240000, 300000) and "медиана" in hint
    lo, hi, _ = parsing.fill_fork("Backend", "Lead", "Москва", None, 100000)
    assert lo == hi == 100000  # нижняя граница не выше верхней


def test_cv_rules(no_llm):
    empty = {"roles": [], "soft_skills": [], "contacts": {"name": None, "email": None, "tg": None}, "experience": [], "parsed_by": "rules"}
    cv = parse_cv("Резюме. Kotlin, Swift, разработка мобильных приложений")
    assert cv == {"skills": ["Kotlin", "Swift"], "years_exp": None, "spec": "Mobile", "track": "Android", **empty}
    assert parse_cv("просто текст") == {"skills": [], "years_exp": None, "spec": None, "track": None, **empty}
    assert parse_cv("CV. Python")["skills"] == ["Python"]  # «CV» — заголовок, а не Computer Vision
    assert parsing._years("2015 - 2018, 2017 — 2020") == 5  # пересечения не суммируются
    assert parsing._years("5 лет коммерческого опыта") == 5 and parsing._years("3.5 years of experience") == 3.5


CV_FULL = """РЕЗЮМЕ
Иванов Сергей Петрович
Senior Python Developer
Телефон: +7 (999) 123-45-67 | Email: S.Ivanov@Mail.ru | Telegram: @sivanov_dev
Опыт работы
Март 2019 — по настоящее время
ООО «Ромашка», ведущий разработчик. Руководил командой из 5 человек, выступал с докладами.
01.2016 – 02.2019 Яндекс, бэкенд-разработчик
2015 — 2014 опечатка в датах
Образование
2010 — 2015 Технический институт, специалист
О себе: ответственный, быстро обучаюсь, командный игрок. Python, Django, PostgreSQL, Kafka."""


def test_cv_extended_rules(no_llm):
    cv = parse_cv(CV_FULL)
    assert cv["contacts"] == {"name": "Иванов Сергей Петрович", "email": "s.ivanov@mail.ru", "tg": "@sivanov_dev"}
    assert cv["roles"] == ["Тимлид", "Спикер"]
    assert cv["soft_skills"] == ["Лидерство", "Публичные выступления", "Ответственность", "Обучаемость", "Работа в команде"]
    # период на отдельной строке → название со следующей; учёба и перевёрнутый период — не работа
    assert cv["experience"] == [{"from": 2019, "to": None, "title": "ООО «Ромашка», ведущий разработчик"},
                                {"from": 2016, "to": 2019, "title": "Яндекс, бэкенд-разработчик"}]
    assert cv["years_exp"] == datetime.now().year - 2016  # учёба в стаж не входит
    # одна строка, несколько периодов; название перед периодом; вуз по ключевому слову
    cv = parse_cv("Ozon, 2020 - present. 2012 — 2016 Университет ИТМО; 2016 — 2020 Яндекс")
    assert cv["experience"] == [{"from": 2020, "to": None, "title": "Ozon"}, {"from": 2016, "to": 2020, "title": "Яндекс"}]


@pytest.mark.parametrize(
    "text, contacts",
    [
        ("Dmitry Orlov, Backend Engineer. dorlov@gmail.com, tg: dorlov_dev.", {"name": "Dmitry Orlov", "email": "dorlov@gmail.com", "tg": "@dorlov_dev"}),
        ("Python Developer\nМосква\nmail@a.ru", {"name": None, "email": "mail@a.ru", "tg": None}),  # должность и город — не имя
        ("Резюме\nФИО: Анна-Мария Петрова-Водкина\nhttps://t.me/anna_m", {"name": "Анна-Мария Петрова-Водкина", "email": None, "tg": "@anna_m"}),
        ("Senior Backend Developer — Kafka Python", {"name": None, "email": None, "tg": None}),
        ("почта me@ex.ru; @mail.ru не ник; @ab — короткий", {"name": None, "email": "me@ex.ru", "tg": None}),
    ],
)
def test_cv_contacts(no_llm, text, contacts):
    assert parse_cv(text)["contacts"] == contacts


def test_canon_terms():
    assert parsing.canon_terms(["Тимлид", "Космонавт", 7, None, "Тимлид", "Ментор"], catalog.ROLES) == ["Тимлид", "Ментор"]
    assert parsing.canon_terms(None, catalog.SOFT_SKILLS) == []


def test_canon_skills():
    assert parsing.canon_skills(["postgres", "Питон", "неизвестно", 42, None, "python"]) == ["PostgreSQL", "Python"]
    assert parsing.canon_skill("  K8S ") == "Kubernetes" and parsing.canon_skill("cobol") is None


# ---------- parsing.py: ответ модели проверяется по справочнику ----------


def test_need_llm_answer_validated(model):
    model.reply = _chat({"spec": "Backend", "track": "Go", "grade": "Senior", "must": ["golang", "postgres", "COBOL"], "nice": ["k8s", "golang"],
                         "salary_from": "350", "salary_to": 450000, "format": "Удалённо", "city": "Казань"})
    n = parse_need("Нужен разработчик в платёжную команду. Мужчина до 35 лет.")
    assert n["parsed_by"] == "llm" and (n["spec"], n["track"], n["grade"]) == ("Backend", "Go", "Senior")
    assert n["must"] == ["Go", "PostgreSQL"] and n["nice"] == ["Kubernetes"]  # вне справочника отброшено, дубль убран
    assert (n["salary_from"], n["salary_to"]) == (350000, 450000)  # правила ничего не нашли → суммы модели
    assert (n["format"], n["city"]) == ("Удалённо", "Казань")
    assert {"возраст", "пол"} <= set(n["ignored"])
    assert "Мужчина" not in model.calls[0][1]["messages"][1]["content"]  # персональные признаки не уходят в модель


def test_need_llm_garbage_falls_back_to_rules(model):
    model.reply = _chat({"spec": "Космонавт", "track": "Луна", "grade": "Бог", "must": [], "salary_from": "много", "salary_to": 10**9,
                         "format": "Марс", "city": "x" * 100})
    text = "Ищем бэкендера на Python, мидл, до 300, гибрид, Москва. Kafka."
    n = parse_need(text)
    rules = parse_need(text, use_llm=False)
    assert n["parsed_by"] == "llm" and {k: v for k, v in n.items() if k != "parsed_by"} == {k: v for k, v in rules.items() if k != "parsed_by"}
    # суммы: правила главнее модели
    model.reply = _chat({"salary_from": 100000, "salary_to": 120000})
    assert parse_need(text)["salary_to"] == 300000
    # нет сумм ни у правил, ни у модели → рынок
    model.reply = _chat({"salary_from": None, "salary_to": "abc"})
    n = parse_need("Нужен бэкендер Python, мидл")
    assert n["salary_from"] and any("Вилка не указана" in h for h in n["hints"])


def test_cv_llm(model):
    model.reply = _chat({"skills": ["kafka", "python", "COBOL"], "years_exp": 4, "spec": "Backend", "track": "Fortran"})
    cv = parse_cv("Python разработчик. Docker.")
    assert cv["parsed_by"] == "llm" and cv["skills"] == ["Kafka", "Python", "Docker"] and cv["years_exp"] == 4.0
    assert (cv["spec"], cv["track"]) == ("Backend", "Python")  # трек модели вне справочника → правила
    model.reply = _chat({"skills": [], "years_exp": 99, "spec": "ML / DS", "track": "NLP / LLM"})
    cv = parse_cv("Опыт 2 года. PyTorch")
    assert cv["years_exp"] == 2.0 and (cv["spec"], cv["track"]) == ("ML / DS", "NLP / LLM")
    model.reply = _chat({"skills": ["x"], "years_exp": "много", "spec": None})
    cv = parse_cv("просто текст")
    assert cv["parsed_by"] == "llm" and cv["spec"] is None and cv["track"] is None and cv["years_exp"] is None
    # роли и софт-скиллы модели — только из справочника, плюс найденное правилами; контакты модель не даёт
    model.reply = _chat({"roles": ["Архитектор", "Космонавт"], "soft_skills": ["Лидерство", 5, "Харизма"], "name": "Пётр"})
    cv = parse_cv("Анна Петрова. Тимлид, коммуникабельна.")
    assert cv["roles"] == ["Архитектор", "Тимлид"] and cv["soft_skills"] == ["Лидерство", "Коммуникация"]
    assert cv["contacts"]["name"] == "Анна Петрова"
    assert "ФИО, контакты" in model.calls[-1][1]["messages"][0]["content"]
