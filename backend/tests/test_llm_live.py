"""Живой смоук LLM: только с LIVE_LLM=1, по умолчанию пропускается (в CI модели нет). Провайдер — из окружения,
по умолчанию локальная Ollama с mistral:7b:

    cd backend && LIVE_LLM=1 LLM_PROVIDER=ollama uv run pytest -q -s tests/test_llm_live.py

Проверяет, что ответы модели разбираются в JSON и проходят проверку по справочнику, а если модель отдаёт мусор
или не успевает — разбор всё равно возвращает результат правил. Печатает время и долю ответов модели. БД не нужна.
"""

import os
import time

import pytest

if os.environ.get("LIVE_LLM") != "1":
    pytest.skip("живой смоук LLM — только с LIVE_LLM=1", allow_module_level=True)

from app import catalog, config  # noqa: E402
from app.models import Candidate, Need  # noqa: E402
from app.services import llm, matching  # noqa: E402
from app.services.parsing import parse_cv, parse_need  # noqa: E402

if config.LLM_PROVIDER == "none":
    config.LLM_PROVIDER, config.LLM_BASE_URL, config.LLM_MODEL = "ollama", "http://localhost:11434/v1", "mistral:7b"

NEEDS = [
    "Ищем бэкендера на Python в команду платежей. Нужен опыт с PostgreSQL и Kafka, хорошо бы Kubernetes. Уровень — мидл, до 300 на руки. "
    "Гибрид, Москва. Контакт: Ольга Белова, hr@ladoga.example",
    "Нужен Go-разработчик, синьор, от 350 до 450к, удалёнка. gRPC, ClickHouse желательно.",
    "Фронтендер на React + TypeScript, джун, 150к, офис СПб.",
    "Data engineer: Spark, Airflow, ClickHouse. Middle+, до 320 тыс., Казань или удалённо.",
    "Сеньор DevOps: k8s, terraform желательно. 250-320 тыс, офис.",
]
CVS = [
    "Кузнецова Мария Андреевна\nSenior Backend Developer\n+7 (916) 555-12-34 · m.kuz@example.ru · @mkuz_dev\n"
    "2019 — н.в. ООО «Ромашка», ведущий разработчик. Python, FastAPI, PostgreSQL, Kafka.\n2016 — 2019 Банк, разработчик Java.",
    "Dmitry Orlov, Backend Engineer. dorlov@example.com. Опыт работы 4 года. Python, asyncio, Postgres, Kafka, Docker.",
    "Анна Петрова\nt.me/anna_dev\nТимлид фронтенда, React, TypeScript, Redux. Менторила джунов. Опыт 6 лет.",
    "Стажёр-аналитик данных. SQL, Python, pandas, Airflow. Курсы по ML.",
    "QA-инженер: автотесты на Selenium и Python, ручное тестирование API. Опыт 3 года.",
]


def _run(fn, items):
    t, by_llm = [], 0
    for x in items:
        t0 = time.monotonic()
        out = fn(x)
        t.append(time.monotonic() - t0)
        by_llm += out["parsed_by"] == "llm"
        assert out["parsed_by"] in ("llm", "rules")
    return by_llm, t


def _report(name, by_llm, t, n):
    print(f"\n{name}: ответ модели {by_llm}/{n}, время ср. {sum(t) / len(t):.1f} с, макс. {max(t):.1f} с ({config.LLM_PROVIDER} · {config.LLM_MODEL})")


def test_live_parse_need():
    llm._down_until = 0.0
    by_llm, t = _run(parse_need, NEEDS)
    _report("parse_need", by_llm, t, len(NEEDS))
    n = parse_need(NEEDS[0])
    assert n["spec"] in catalog.SPECS and n["grade"] in catalog.GRADES and n["salary_to"] == 300000  # суммы — правила


def test_live_parse_cv():
    llm._down_until = 0.0
    by_llm, t = _run(parse_cv, CVS)
    _report("parse_cv", by_llm, t, len(CVS))
    cv = parse_cv(CVS[0])
    assert set(cv["skills"]) <= set(catalog.SKILLS) and cv["contacts"]["email"] == "m.kuz@example.ru"


def test_live_rerank_top30():
    llm._down_until = 0.0
    matching._llm_cache.clear()
    need = Need(spec="Backend", track="Python", grade="Middle", must=["Python", "PostgreSQL", "Kafka"], nice=["Kubernetes"])
    skills = ["Python", "PostgreSQL", "Kafka", "Docker", "Kubernetes", "Redis", "Django", "FastAPI"]
    cands = [Candidate(public_id=f"A-{1000 + i}", grade=catalog.GRADES[1 + i % 3], track="Python", theta=-1 + i * 0.1,
                       skills_confirmed=skills[: 1 + i % 4], skills_claimed=skills[: 2 + i % 6]) for i in range(30)]
    t0 = time.monotonic()
    scores = matching._llm_scores(need, cands)
    dt = time.monotonic() - t0
    got = len(scores or {})
    print(f"\nреранк топ-30: оценок {got}/30, время {dt:.1f} с ({config.LLM_PROVIDER} · {config.LLM_MODEL})")
    assert scores is None or all(0 <= v <= 1 for v in scores.values())  # None — подбор остаётся на правилах
