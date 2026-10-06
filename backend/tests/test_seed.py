"""Генератор синтетики (CLI целиком, маленький прогон), эталонная релевантность gold.py и отчёт валидации на нём.
Своя БД (fsp_gen): генератор делает --reset, демо-база fsp не трогается."""

import os
import sys
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fsp:fsp@localhost:5432/fsp_gen")
os.environ["LLM_BASE_URL"] = ""

import pytest
from sqlalchemy import func, select

from app import catalog, config
from app.db import SessionLocal, engine
from app.models import Candidate, Company, Invitation, Item, Message, Need, User
from app.routers.employer import inn_valid
from app.services import validation as V
from app.services.chat import peers_linked
from seed import generate, gold

config.LLM_BASE_URL = ""
pytestmark = pytest.mark.slow
N_CAND, N_NEEDS = 60, 8


@pytest.fixture(scope="module")
def seeded():
    if "fsp_gen" not in str(engine.url):
        pytest.skip("генератор делает --reset — нужен отдельный DATABASE_URL (fsp_gen)")
    argv = sys.argv
    sys.argv = ["seed.generate", "--reset", "--candidates", str(N_CAND), "--needs", str(N_NEEDS), "--seed", "7"]
    try:
        generate.main()
    finally:
        sys.argv = argv
    with SessionLocal() as db:
        yield db


def test_generate_cli(seeded, capsys):
    db = seeded
    synth = db.scalars(select(Candidate).where(Candidate.public_id != "A-1042")).all()
    assert len(synth) >= N_CAND
    orlov = db.scalar(select(Candidate).where(Candidate.public_id == "A-1042"))
    assert orlov.name == "Дмитрий Орлов" and orlov.truth["skills_true"] and orlov.consent_publish
    assert db.scalar(select(User).where(User.email == "m.kovaleva@ladoga-pay.example")).role == "employer"
    assert db.scalar(select(func.count()).select_from(Need)) >= N_NEEDS
    assert db.scalar(select(func.count()).select_from(Item)) > 0  # банк заданий засеян
    # данные только синтетические: почты на example-доменах, у всех кандидатов — согласие с датой и версией
    for c in synth:
        assert c.email.rsplit("@", 1)[1] in ("example.ru", "example.com", "example.org"), c.email
        assert c.consent_152 and c.consent_152_at and c.consent_version == catalog.CONSENT_VERSION
        assert c.truth and {"theta_true", "skills_true"} <= c.truth.keys()
    for co in db.scalars(select(Company)):
        assert inn_valid(co.inn), co.inn
    # вилка в каждом приглашении обязательна и не перевёрнута
    for inv in db.scalars(select(Invitation)):
        assert inv.salary_from and inv.salary_to and inv.salary_from <= inv.salary_to and inv.expires_at > inv.sent_at
    # демо-диалоги чата: только при живой связи и прочитаны (бейдж непрочитанного на стенде начинается с нуля)
    msgs = db.scalars(select(Message)).all()
    assert len({(m.company_id, m.candidate_id) for m in msgs}) == 2 and all(m.read_at for m in msgs)
    for m in msgs:
        assert peers_linked(db, "employer", m.company_id, [m.candidate_id]) == {m.candidate_id}
    # повторный запуск без --reset не портит засеянную базу
    argv = sys.argv
    sys.argv = ["seed.generate", "--candidates", "5", "--needs", "1"]
    try:
        with pytest.raises(SystemExit, match="уже засеяна"):
            generate.main()
    finally:
        sys.argv = argv


def test_gold_on_seed(seeded):
    db = seeded
    needs = db.scalars(select(Need)).all()
    cands = db.scalars(select(Candidate)).all()
    scores = [gold.relevance(c, n) for n in needs for c in cands]
    assert set(scores) <= {0, 1, 2, 3} and 3 in scores and 0 in scores
    # правда приоритетнее заявленного: навыки из резюме без skills_true релевантности не дают
    lad = next(n for n in needs if n.must == ["Python", "PostgreSQL", "Kafka"])
    c = next(c for c in cands if c.spec == "Backend" and set(lad.must) <= set(c.truth["skills_true"]))
    fake = SimpleNamespace(**{k: getattr(c, k) for k in ("spec", "track", "grade", "min_salary", "formats", "city", "skills_confirmed")},
                           truth={**c.truth, "skills_true": ["Python"]})
    assert gold.relevance(fake, lad) == 0


def test_gold_rules():
    need = SimpleNamespace(spec="Backend", track=None, grade="Middle", must=["Python"], nice=[], salary_to=None, format=None, city=None)
    # ORM-подобный объект без truth — берутся наблюдаемые поля
    c = SimpleNamespace(spec="Backend", track="Go", grade=None, grade_claimed="Middle", skills_confirmed=["Python"], truth=None,
                        min_salary=None, formats=None, city=None)
    assert gold.relevance(c, need) == 3  # трек не указан в потребности, формат и вилка не заданы
    assert gold.relevance(c, SimpleNamespace(**{**vars(need), "track": "Python"})) == 0
    assert gold.relevance(c, SimpleNamespace(**{**vars(need), "grade": "Lead"})) == 0
    # dict без truth — сам себе правда
    d = {"spec": "Backend", "track": "Python", "grade": "Senior", "skills": ["Python", "Kafka"], "min_salary": 400000, "formats": ["Офис"], "city": "Казань"}
    n2 = {"spec": "Backend", "track": "Python", "grade": "Middle", "must": ["Python"], "nice": ["Kafka", "Go"], "salary_to": 300000,
          "format": "Офис", "city": "Москва"}
    assert gold.relevance(d, n2) == 1  # 3 дефекта: нет Go, дороже вилки, другой город
    assert gold.format_ok(["Удалённо"], "Казань", "Удалённо", "Москва") and not gold.format_ok([], None, "Офис", None)


def test_validation_report_on_seed(seeded, tmp_path, monkeypatch, capsys):
    """CLI валидации на маленьком засеве: отчёт печатается, JSON сохраняется."""
    monkeypatch.setattr(V, "OUT", tmp_path / "validation.json")
    monkeypatch.setattr(sys, "argv", ["validation", "--k", "5", "--seed", "3"])
    V.main()
    out = capsys.readouterr().out
    assert "Валидация ФСП Карьеры" in out and "precision@5" in out and "Стабильность" in out
    assert (tmp_path / "validation.json").exists()
