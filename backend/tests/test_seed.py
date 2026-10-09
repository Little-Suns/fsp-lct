"""Генератор синтетики (CLI целиком, маленький прогон), эталонная релевантность gold.py и отчёт валидации на нём.
Своя БД (fsp_gen): генератор делает --reset, демо-база fsp не трогается."""

import os
import sys
from datetime import timedelta
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fsp:fsp@localhost:5432/fsp_gen")
os.environ["LLM_BASE_URL"] = ""

import pytest
from sqlalchemy import delete, func, select

from app import catalog, config
from app.db import SessionLocal, engine
from app.models import Candidate, Company, Invitation, Item, Message, Need, User
from app.routers.employer import inn_valid
from app.services import validation as V
from app.services.chat import may_talk, peers_linked
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
    # роли и софт-скиллы у синтетики — из справочников и у заметной части кандидатов
    gen = [c for c in synth if c.is_synthetic]
    assert all(set(c.roles) <= set(catalog.ROLES) and set(c.soft_skills) <= set(catalog.SOFT_SKILLS) and len(c.soft_skills) <= 4 for c in gen)
    assert sum(bool(c.roles) for c in gen) >= len(gen) // 5 and sum(bool(c.soft_skills) for c in gen) >= len(gen) // 2
    # часть синтетики без теста: ни грейда по тесту, ни θ, ни перцентиля, ни подтверждённых навыков — категория по заявленному
    untested = [c for c in gen if c.theta is None]
    assert untested and len(untested) < len(gen) // 3
    assert all(c.grade is None and c.percentile is None and c.tested_at is None and not c.competencies and not c.skills_confirmed
               and c.grade_claimed in catalog.GRADES for c in untested)
    assert all(c.percentile is not None for c in gen if c.theta is not None)
    k, lo = (db.scalar(select(Candidate).where(Candidate.public_id == pid)) for pid in ("K-2077", "L-3141"))
    assert k.theta is None and k.grade is None and k.grade_claimed == "Middle" and k.consent_publish and k.skills_claimed
    assert (lo.grade, lo.grade_claimed) == ("Middle", "Senior")
    # вилка в каждом приглашении обязательна и не перевёрнута
    for inv in db.scalars(select(Invitation)):
        assert inv.salary_from and inv.salary_to and inv.salary_from <= inv.salary_to and inv.expires_at > inv.sent_at
    # демо-диалоги чата: только при живой связи и прочитаны (бейдж непрочитанного на стенде начинается с нуля)
    msgs = db.scalars(select(Message)).all()
    assert len({(m.company_id, m.candidate_id) for m in msgs}) == 2 and all(m.read_at for m in msgs)
    for m in msgs:  # связь есть и кандидат не закрыл доступ — диалог откроется у обеих сторон
        assert peers_linked(db, "employer", m.company_id, [m.candidate_id]) == {m.candidate_id}
        assert may_talk(db.get(Candidate, m.candidate_id), db.get(Company, m.company_id))
    # повторный запуск без --reset не портит засеянную базу
    argv = sys.argv
    sys.argv = ["seed.generate", "--candidates", "5", "--needs", "1"]
    try:
        with pytest.raises(SystemExit, match="уже засеяна"):
            generate.main()
        n, items = db.scalar(select(func.count()).select_from(Candidate)), db.scalar(select(func.count()).select_from(Item))
        db.execute(delete(Item).where(Item.family == "be_inc_pool"))  # засев оборвался до банка — автозасев его докладывает
        db.commit()
        sys.argv = ["seed.generate", "--if-empty", "--candidates", "5", "--needs", "1"]  # автозасев стенда при каждом старте
        generate.main()
        assert db.scalar(select(func.count()).select_from(Candidate)) == n
        assert db.scalar(select(func.count()).select_from(Item)) == items
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


def test_refresh_demo(seeded):
    """--refresh-demo: стенд засеян давно — истёкшие без ответа демо-приглашения снова открыты, ответы на стенде не трогаются."""
    db = seeded

    def pair(co, pid):
        return db.scalar(select(Invitation).join(Company, Invitation.company_id == Company.id)
                         .join(Candidate, Invitation.candidate_id == Candidate.id).where(Company.name == co, Candidate.public_id == pid))

    lad, kip, j = pair("Ладога Пэй", "A-1042"), pair("Кипрей Логистик", "A-1042"), pair("Ладога Пэй", "J-4410")
    assert (lad.status, kip.status, j.status) == ("sent", "sent", "seen")
    # засеяно 2026-10-05, стенд стартует через 10 дней: Ладога истекла лениво (статус sent), J-4410 — уже expired, Кипрей принят
    later = generate.anchor(generate.DEMO_TODAY + timedelta(days=10))
    j.status, kip.status, kip.responded_at = "expired", "accepted", later
    db.commit()
    argv = sys.argv
    sys.argv = ["seed.generate", "--refresh-demo", "--today", str(generate.DEMO_TODAY + timedelta(days=10))]
    try:
        generate.main()
        for inv in (lad, kip, j):
            db.refresh(inv)
        assert (lad.status, lad.sent_at, lad.expires_at - lad.sent_at) == ("sent", later - timedelta(minutes=5), timedelta(days=6, minutes=5))
        assert lad.seen_at is None and lad.responded_at is None
        assert (j.status, j.sent_at, j.expires_at) == ("seen", later - timedelta(days=2), later + timedelta(days=5))
        assert j.seen_at == j.sent_at + timedelta(days=0.3)
        assert kip.status == "accepted"  # ответ на стенде — не откатывается
        generate.set_clock(later.date())
        with SessionLocal() as s:  # ещё открытые не трогаются: повторный запуск ничего не меняет
            assert generate.refresh_demo(s) == 0
        # кандидат, которого компания сейчас не видит (закрыл профиль), приглашение снова не получает
        j.status, j.expires_at, j.candidate.status = "expired", later, "off"
        db.commit()
        with SessionLocal() as s:
            assert generate.refresh_demo(s) == 0
        db.refresh(j)
        assert j.status == "expired"
        # у кандидата полная ёмкость (чужие открытые приглашения) — тоже не освежается
        j.candidate.status = "open"
        others = db.scalars(select(Company).where(Company.name.not_in(["Ладога Пэй"])).limit(catalog.CANDIDATE_CAP)).all()
        db.add_all(Invitation(company_id=co.id, candidate_id=j.candidate_id, role="Backend", salary_from=200000, salary_to=250000,
                              format="Удалённо", sent_at=later, expires_at=later + timedelta(days=3)) for co in others)
        db.commit()
        with SessionLocal() as s:
            assert generate.refresh_demo(s) == 0
        db.execute(delete(Invitation).where(Invitation.candidate_id == j.candidate_id, Invitation.role == "Backend", Invitation.sent_at == later))
        db.commit()
        with SessionLocal() as s:  # ёмкость освободилась — освежается
            assert generate.refresh_demo(s) == 1
    finally:
        sys.argv = argv
        generate.set_clock(None)
