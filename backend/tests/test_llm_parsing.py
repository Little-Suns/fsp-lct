"""Клиент LLM (httpx замокан) и разбор текста: при недоступной модели всё работает на правилах, ответ модели
проверяется по справочнику, а персональные признаки вырезаются до разбора. БД не нужна."""

import json
import time
from datetime import datetime

import httpx
import pytest

from app import catalog, config
from app.services import llm, parsing
from app.services.parsing import parse_cv, parse_need

URL = "http://llm.test/v1"


@pytest.fixture
def model(monkeypatch):
    """Подменяет httpx.post: ответ задаётся через model.reply (dict | Exception | httpx.Response | обработчик)."""
    monkeypatch.setattr(config, "LLM_PROVIDER", "openai_compatible")
    monkeypatch.setattr(config, "LLM_BASE_URL", URL + "/")
    monkeypatch.setattr(config, "LLM_API_KEY", "")
    monkeypatch.setattr(config, "LLM_MODEL", "test-chat")
    monkeypatch.setattr(config, "EMBED_MODEL", "test-embed")
    monkeypatch.setattr(config, "LLM_CA_BUNDLE", "")
    monkeypatch.setattr(llm, "_down_until", 0.0)
    monkeypatch.setattr(llm, "_token", ("", 0.0))

    class Fake:
        reply: object = None
        calls: list = []

        def __call__(self, url, json=None, timeout=None, headers=None, data=None, verify=None):
            self.calls.append((url, json, timeout))
            self.kw.append({"headers": headers or {}, "data": data, "verify": verify})
            if callable(self.reply):  # обработчик: (url, json, headers, data) → httpx.Response
                return self.reply(url, json, headers or {}, data)
            if isinstance(self.reply, Exception):
                raise self.reply
            if isinstance(self.reply, httpx.Response):
                return self.reply
            return httpx.Response(200, json=self.reply, request=httpx.Request("POST", url))

    fake = Fake()
    fake.calls, fake.kw = [], []
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
    assert model.kw[0]["headers"] == {} and model.kw[0]["verify"] is True  # без ключа — без Authorization; TLS проверяется


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


def test_embeddings_off_and_providers_off(model, monkeypatch):
    monkeypatch.setattr(config, "EMBED_MODEL", "")  # эмбеддинги выключены — подбор по навыкам, без запроса
    assert llm.embed(["a"]) is None and model.calls == []
    for p in ("none", "qwerty"):  # none — правила; неизвестный провайдер тоже ничего не шлёт
        monkeypatch.setattr(config, "LLM_PROVIDER", p)
        assert llm.chat_json("s", "u") is None
    assert model.calls == []


def test_openai_compatible_bearer_key_and_fenced_json(model, monkeypatch):
    monkeypatch.setattr(config, "LLM_API_KEY", "k-123")
    model.reply = _chat('Вот ответ:\n```json\n{"spec": "QA"}\n```')
    assert llm.chat_json("s", "u") == {"spec": "QA"}
    assert model.kw[0]["headers"] == {"Authorization": "Bearer k-123"}
    model.reply = _chat("```json {не json} ```")
    assert llm.chat_json("s", "u") is None
    model.reply = {"choices": [{"message": {"content": None}}]}
    assert llm.chat_json("s", "u") is None


def test_ca_bundle_adds_roots_without_disabling_tls(model, monkeypatch):
    import ssl

    import certifi

    monkeypatch.setattr(config, "LLM_CA_BUNDLE", certifi.where())  # любой валидный PEM вместо Russian Trusted Root CA
    model.reply = _chat({"ok": 1})
    assert llm.chat_json("s", "u") == {"ok": 1}
    ctx = model.kw[0]["verify"]
    assert isinstance(ctx, ssl.SSLContext) and ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname


@pytest.fixture
def yandex(model, monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "yandexgpt")
    monkeypatch.setattr(config, "LLM_BASE_URL", "https://llm.api.cloud.yandex.net/v1")
    monkeypatch.setattr(config, "LLM_MODEL", "yandexgpt-lite/latest")
    monkeypatch.setattr(config, "EMBED_MODEL", "text-search-doc/latest")
    monkeypatch.setattr(config, "LLM_API_KEY", "AQVN-secret")
    monkeypatch.setattr(config, "YANDEX_FOLDER_ID", "b1gfolder")
    return model


def test_yandexgpt(yandex, monkeypatch):
    yandex.reply = _chat({"spec": "Backend"})
    assert llm.chat_json("s", "u") == {"spec": "Backend"}
    url, body, _ = yandex.calls[0]
    assert url == "https://llm.api.cloud.yandex.net/v1/chat/completions" and body["model"] == "gpt://b1gfolder/yandexgpt-lite/latest"
    assert yandex.kw[0]["headers"] == {"Authorization": "Api-Key AQVN-secret", "x-folder-id": "b1gfolder", "x-data-logging-enabled": "false"}
    yandex.reply = {"data": [{"index": 0, "embedding": [0.5]}]}
    assert llm.embed(["a"]) == [[0.5]] and yandex.calls[1][1]["model"] == "emb://b1gfolder/text-search-doc/latest"
    monkeypatch.setattr(config, "LLM_MODEL", "gpt://other/yandexgpt/rc")  # полный URI не трогаем
    yandex.reply = _chat({})
    llm.chat_json("s", "u")
    assert yandex.calls[2][1]["model"] == "gpt://other/yandexgpt/rc"
    monkeypatch.setattr(config, "YANDEX_FOLDER_ID", "")  # без каталога (или ключа) — выключено, правила
    n = len(yandex.calls)
    assert llm.chat_json("s", "u") is None and len(yandex.calls) == n


OAUTH = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"


@pytest.fixture
def giga(model, monkeypatch):
    """GigaChat: OAuth-токен по ключу авторизации, затем chat/completions с Bearer. Сеть замокана."""
    monkeypatch.setattr(config, "LLM_PROVIDER", "gigachat")
    monkeypatch.setattr(config, "LLM_BASE_URL", "https://gigachat.devices.sberbank.ru/api/v1")
    monkeypatch.setattr(config, "GIGACHAT_AUTH_KEY", "Y2xpZW50OnNlY3JldA==")
    monkeypatch.setattr(config, "GIGACHAT_SCOPE", "GIGACHAT_API_PERS")
    monkeypatch.setattr(config, "GIGACHAT_OAUTH_URL", OAUTH)
    state = {"n": 0, "expires": (time.time() + 1800) * 1000, "reject": set(), "oauth": 200}

    def handler(url, body, headers, data):
        req = httpx.Request("POST", url)
        if url == OAUTH:
            state["n"] += 1
            if state["oauth"] != 200:
                return httpx.Response(state["oauth"], json={"message": "bad key"}, request=req)
            return httpx.Response(200, json={"access_token": f"tok{state['n']}", "expires_at": state["expires"]}, request=req)
        if headers.get("Authorization") in state["reject"]:
            return httpx.Response(401, json={"message": "token expired"}, request=req)
        if url.endswith("/embeddings"):
            return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0]}]}, request=req)
        return httpx.Response(200, json=_chat({"auth": headers.get("Authorization")}), request=req)

    model.reply = handler
    model.state = state
    return model


def test_gigachat_token_fetch_and_reuse(giga):
    assert llm.chat_json("s", "u") == {"auth": "Bearer tok1"}
    url, _, _ = giga.calls[0]
    kw = giga.kw[0]
    assert url == OAUTH and kw["data"] == {"scope": "GIGACHAT_API_PERS"}
    assert kw["headers"]["Authorization"] == "Basic Y2xpZW50OnNlY3JldA==" and len(kw["headers"]["RqUID"]) == 36
    body = giga.calls[1][1]
    assert "response_format" not in body and body["temperature"] > 0 and body["model"] == "test-chat"
    assert llm.embed(["a"]) == [[1.0]]
    assert giga.state["n"] == 1  # токен живёт 30 минут — повторно не запрашиваем


def test_gigachat_token_refresh_on_expiry_and_401(giga):
    giga.state["expires"] = (time.time() + 30) * 1000  # истекает меньше чем через минуту → обновим заранее
    assert llm.chat_json("s", "u") == {"auth": "Bearer tok1"}
    giga.state["expires"] = (time.time() + 1800) * 1000
    assert llm.chat_json("s", "u") == {"auth": "Bearer tok2"}
    giga.state["reject"].add("Bearer tok2")  # отозван раньше срока → один повтор с новым токеном
    assert llm.chat_json("s", "u") == {"auth": "Bearer tok3"} and llm._down_until == 0.0


def test_gigachat_401_does_not_refetch_token_refreshed_by_neighbour(giga):
    llm._token = ("fresh", time.time() + 1800)  # соседний поток уже обновил токен
    assert llm._gigachat_token(stale="old") == "fresh" and giga.state["n"] == 0


def test_bad_ca_bundle_falls_back_to_rules(model, monkeypatch):
    monkeypatch.setattr(config, "LLM_CA_BUNDLE", "/nonexistent/russian_trusted_root_ca.pem")  # не смонтировали сертификат
    assert llm.chat_json("s", "u") is None and llm._down_until > 0  # не 500, а правила


def test_unknown_provider_warns_at_import(monkeypatch, caplog):
    import importlib

    monkeypatch.setattr(config, "LLM_PROVIDER", "yandex")
    with caplog.at_level("WARNING"):
        importlib.reload(llm)
    assert "не поддерживается" in caplog.text
    monkeypatch.undo()
    importlib.reload(llm)


def test_gigachat_oauth_failure_falls_back(giga):
    giga.state["oauth"] = 401
    assert llm.chat_json("s", "u") is None and llm._down_until > 0
    assert llm._token == ("", 0.0)


def test_gigachat_oauth_garbage_falls_back(giga):
    giga.reply = lambda url, *a: httpx.Response(200, json={"no_token": 1}, request=httpx.Request("POST", url))
    assert llm.chat_json("s", "u") is None and llm._down_until > 0


def test_gigachat_disabled_without_key(giga, monkeypatch):
    monkeypatch.setattr(config, "GIGACHAT_AUTH_KEY", "")
    assert llm.chat_json("s", "u") is None and giga.calls == []


@pytest.mark.parametrize(
    "env, want",
    [
        ({}, ("none", "", "", "")),
        ({"LLM_PROVIDER": "ollama"}, ("ollama", "http://localhost:11434/v1", "mistral:7b", "bge-m3")),
        ({"LLM_PROVIDER": "Ollama", "OLLAMA_URL": "http://host.docker.internal:11434/v1", "LLM_BASE_URL": "", "EMBED_MODEL": "none"},
         ("ollama", "http://host.docker.internal:11434/v1", "mistral:7b", "")),
        ({"LLM_PROVIDER": "yandexgpt"}, ("yandexgpt", "https://llm.api.cloud.yandex.net/v1", "yandexgpt-lite/latest", "text-search-doc/latest")),
        ({"LLM_PROVIDER": "gigachat", "LLM_MODEL": "GigaChat-2-Max"}, ("gigachat", "https://gigachat.devices.sberbank.ru/api/v1", "GigaChat-2-Max", "Embeddings")),
        ({"LLM_PROVIDER": "openai_compatible", "LLM_BASE_URL": "http://vllm:8000/v1"}, ("openai_compatible", "http://vllm:8000/v1", "", "")),
    ],
)
def test_config_presets(env, want):
    """Пресеты читаются при импорте config — проверяем в отдельном процессе с чистым окружением."""
    import os
    import subprocess
    import sys

    base = {k: v for k, v in os.environ.items() if not k.startswith(("LLM_", "EMBED_", "OLLAMA_", "YANDEX_", "GIGACHAT_"))}
    code = "from app import config as c; print(repr((c.LLM_PROVIDER, c.LLM_BASE_URL, c.LLM_MODEL, c.EMBED_MODEL)))"
    out = subprocess.run([sys.executable, "-c", code], env={**base, **env}, capture_output=True, text=True, check=True,
                         cwd=os.path.dirname(os.path.dirname(__file__)))
    assert out.stdout.strip() == repr(want)


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
    empty = {"roles": [], "soft_skills": [], "contacts": {"name": None, "email": None, "tg": None}, "experience": [], "parsed_by": "rules",
             "grade_hint": None}
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
        ("Name: Anna Petrova developer\nabout.me/anna_dev", {"name": "Anna Petrova", "email": None, "tg": None}),
        ("Резюме\nCompany name: Yandex Cloud", {"name": None, "email": None, "tg": None}),
        ("Резюме: Иван Петров\nTelegram integration, tg-бот", {"name": "Иван Петров", "email": None, "tg": None}),  # подпись не в начале строки
    ],
)
def test_cv_contacts(no_llm, text, contacts):
    assert parse_cv(text)["contacts"] == contacts


def test_cv_contacts_linear_on_long_text(no_llm):
    """Слитная строка без пробелов (мусор из PDF) не должна давать квадратичный поиск почты."""
    t0 = time.monotonic()
    assert parsing._contacts("x" * 200_000 + " me@ex.ru")["email"] == "me@ex.ru"
    assert parsing._contacts("@" + "a" * 200_000)["tg"] is None
    assert parsing.cv_experience("dec" * 100_000 + "март" * 50_000) == []  # месяцы без границы слова не перебираются
    assert parsing._years("1" * 100_000 + " лет опыта") is None  # цепочка цифр — не стаж и не квадратично
    assert time.monotonic() - t0 < 5


def test_cv_no_false_roles_soft(no_llm):
    """Слова из обязанностей и стека — не роли и не софт-скиллы: их иначе увидит работодатель «со слов кандидата»."""
    cv = parse_cv("Responsibilities: microservice architecture, inter-service communication, open source libraries. Зона ответственности — платежи.")
    assert cv["roles"] == [] and cv["soft_skills"] == []
    cv = parse_cv("Architect. Contributed to Django. Ответственный, коммуникативный.")
    assert cv["roles"] == ["Архитектор"] and cv["soft_skills"] == ["Ответственность", "Коммуникация"]  # «contributed to Django» — работа, не open source
    assert parse_cv("Contributed to open source: aiohttp.")["roles"] == ["Контрибьютор open source"]


def test_cv_experience_sections():
    text = ("Образование\n2010 — 2015 Технический институт\nКарьера\n2016 — 2019 Банк, Scrum Master\n"
            "2019 —\n2021 Mastercard, разработчик\n" + "\n".join(f"{y} — {y + 1} Компания {y}" for y in range(2000, 2015)))
    jobs = parsing.cv_experience(text)
    assert jobs[:2] == [{"from": 2016, "to": 2019, "title": "Банк, Scrum Master"}, {"from": 2019, "to": 2021, "title": "Mastercard, разработчик"}]
    assert len(jobs) == 17 and len(parse_cv(text)["experience"]) == 12  # в стаж — все периоды, в ответ — первые 12
    assert parsing.cv_experience("2005 — 2015 Школа № 57\n2016 — 2018 Фирма, разработчик —\nОбразование\n2012 — 2016 Курс") == [
        {"from": 2016, "to": 2018, "title": "Фирма, разработчик"}]  # школа — учёба; тире в конце строки не съедает заголовок
    assert parsing._years(text.lower()) == 20  # 2000–2015 и 2016–2021, разрыв в год не считается


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
    # не списки от модели не роняют разбор: остаётся найденное правилами
    model.reply = _chat({"skills": True, "roles": 5, "soft_skills": "Лидерство"})
    cv = parse_cv("Python. Тимлид.")
    assert cv["skills"] == ["Python"] and cv["roles"] == ["Тимлид"] and cv["soft_skills"] == []


# ---------- ПДн не уходят в модель ----------

CV_PII = """РЕЗЮМЕ
Кузнецова Мария Андреевна
Senior Backend Developer
Телефон: +7 (916) 555-12-34 | E-mail: m.kuznetsova@example.ru | Telegram: @mkuz_dev
GitHub: mkuznetsova · https://www.linkedin.com/in/m-kuznetsova · gitlab.com/mkuz · 8 903 777 88 99 · 9031112233
Адрес: г. Москва, ул. Тверская, д. 7, кв. 15
Дата рождения: 14.05.1993
Гражданство: РФ
Опыт работы
2019 — н.в. ООО «Ромашка», ведущий разработчик. Python, FastAPI, PostgreSQL, Kafka.
2016 — 2019 Банк, разработчик. Рекомендации: Смирнов Алексей, руководитель отдела.
О себе: Мария, ответственная; портфолио — mkuz.dev/projects"""
PII = ["Кузнецова", "Мария", "Андреевна", "Кузнецов", "916", "555-12-34", "m.kuznetsova", "example.ru", "mkuz", "linkedin", "gitlab",
       "903 777", "9031112233", "Тверская", "14.05.1993", "Гражданство", "Смирнов", "Алексей"]


def test_cv_pii_not_sent_to_model(model):
    model.reply = _chat({"skills": ["Python"], "years_exp": 7})
    cv = parse_cv(CV_PII)
    sent = json.dumps(model.calls[0][1], ensure_ascii=False)
    assert [p for p in PII if p.lower() in sent.lower()] == []
    # полезное для разбора остаётся: навыки, места работы, грейд в должности
    for keep in ("Python", "FastAPI", "PostgreSQL", "Kafka", "ООО «Ромашка», ведущий разработчик", "2016 — 2019", "Senior"):
        assert keep in sent, keep
    # контакты распознаны правилами локально — для предзаполнения формы самого кандидата
    assert cv["contacts"] == {"name": "Кузнецова Мария Андреевна", "email": "m.kuznetsova@example.ru", "tg": "@mkuz_dev"}


def test_need_pii_not_sent_to_model(model):
    model.reply = _chat({})
    parse_need("Ищем бэкендера на Python, мидл, до 300к.\nКонтакт: Ольга Сергеевна Белова, hr@ladoga.example, +7 999 000-11-22, t.me/olga_hr")
    sent = json.dumps(model.calls[0][1], ensure_ascii=False)
    assert not any(p in sent for p in ("Ольга", "Белова", "hr@", "ladoga", "000-11-22", "olga_hr")), sent
    assert "Python" in sent and "300к" in sent


@pytest.mark.parametrize(
    "text, gone, kept",
    [
        ("Иванов С. П., Python", ["Иванов"], ["Python"]),
        ("Меня зовут Пётр Сидоров. Kotlin", ["Пётр", "Сидоров"], ["Kotlin"]),
        ("Name: Ivan Petrov\nGo, gRPC", ["Ivan", "Petrov"], ["Go, gRPC"]),
        ("ФИО: Ли Ван\nk8s", ["Ли", "Ван"], ["k8s"]),
        ("phone - 89161234567, skype: ivan.p", ["89161234567", "ivan.p"], ["phone"]),
        # найдено ревью: ник без «@» и двоеточия, ФИО капсом, одиночное имя, «(at)», телефоны без «+», имя перед стеком
        ("Telegram ivan_petrov; тг: vanya; Instagram: @foo; пишите @ivan", ["ivan_petrov", "vanya", "foo", "@ivan"], []),
        ("ИВАН ПЕТРОВ\nPython Developer\nПетрова Мария — коллега", ["ИВАН", "ПЕТРОВ", "Петрова", "Мария"], ["Python Developer"]),
        ("Python.\nКонтакты: Иван\nО себе: Ивану интересен Go", ["Иван"], ["Python", "Go"]),
        ("ivan.petrov (at) gmail.com, ivan [at] mail [dot] ru, ivan at yandex dot ru", ["ivan", "gmail", "yandex"], []),
        ("916-123-45-67, 79161234567, (916) 123 45 67", ["916", "79161234567"], []),
        ("Сидоров Python Developer Москва", ["Сидоров"], ["Python Developer"]),
        ("Улица: ул. Ленина, д. 5\nЖиву: Невский проспект 10", ["Ленина", "Невский"], []),
        # не ПДн: квартал, Telegram-боты, установка, Java-аннотации на месте ника допустимы
        ("Во 2 кв. 2023 вывел продукт; Python\nTelegram-боты на aiogram, installation scripts", [], ["2 кв. 2023", "Python", "aiogram", "installation"]),
        # не ПДн: годы, суммы, периоды, индексы БД, IP-адрес, GitHub Actions, стек через «/»
        ("2019-2021, 150000-200000 руб, оптимизировал индексы, IP-адрес, GitHub Actions, github-actions, Node.js/TypeScript", [],
         ["2019-2021", "150000-200000", "индексы", "IP-адрес", "GitHub Actions", "github-actions", "Node.js/TypeScript"]),
    ],
)
def test_mask_pii(text, gone, kept):
    out = parsing.mask_pii(text)
    assert not [g for g in gone if g in out] and all(k in out for k in kept), out


# ---------- подсказка грейда ----------


@pytest.mark.parametrize(
    "text, grade, why",
    [
        (CV_FULL, "Senior", "в шапке резюме — «senior»"),  # «Senior Python Developer» в шапке
        ("Python\n2018 — н.в. Ozon, ведущий разработчик\n2015 — 2018 Банк, junior", "Senior", "в последней должности — «ведущий»"),
        ("Python\n2015 — 2018 Банк, junior\n2018 — н.в. Ozon, ведущий разработчик", "Senior", "в последней должности — «ведущий»"),
        ("Анна Петрова\nТимлид, менторила джунов.", "Lead", "«тимлид»"),
        ("Python. Руководил командой из 5 человек. Опыт 6 лет", "Lead", "руководство командой"),
        ("Python, Go. Менторил джунов и мидлов. Опыт 1,5 года", "Junior", "опыт 1,5 г."),  # чужие грейды — не про себя
        ("Go. Опыт 3 года", "Middle", "опыт 3 г."),
        ("Go. Опыт 7 лет", "Senior", "опыт 7 г."),
        ("Стажёр-аналитик. SQL", "Intern", "«стажёр»"),
        ("Резюме\nPython\nGo\nСейчас работаю как junior developer в стартапе. Опыт 4 года", "Middle", "в тексте резюме — «junior»; опыт 4 г."),
        ("Резюме\nPython\nGo\nIntern at Yandex 2015, потом senior. 7 лет опыта", "Senior", "«intern»; опыт 7 г."),  # стаж сильнее маркера в тексте
        ("Резюме\nPython\nGo\nСейчас работаю как junior developer в стартапе", "Junior", "в тексте резюме — «junior»"),
    ],
)
def test_grade_hint(no_llm, text, grade, why):
    h = parse_cv(text)["grade_hint"]
    assert h["grade"] == grade and why in h["why"], h


def test_grade_hint_absent_and_llm_years(model):
    model.reply = _chat({"years_exp": 0.5})
    assert parse_cv("Python")["grade_hint"] == {"grade": "Intern", "why": "опыт 0,5 г."}  # стаж от модели тоже идёт в подсказку
    model.reply = _chat({})
    assert parse_cv("просто текст")["grade_hint"] is None
