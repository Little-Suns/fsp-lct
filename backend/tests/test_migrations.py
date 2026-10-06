"""Миграции Alembic: с пустой базы до моделей без расхождений (модель поменяли без ревизии — тест падает),
база от create_all помечается baseline, откат до base и обратно, чужая ревизия и чужие таблицы. Своя БД (fsp_migr)."""

import os
import re
from datetime import UTC, datetime

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://fsp:fsp@localhost:5432/fsp_migr")

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import JSON, Boolean, DateTime, Float, Integer, MetaData, String, Table, inspect, text

from app import models  # noqa: F401
from app.db import ALEMBIC_INI, BASELINE, BASELINE_TABLES, Base, engine, init_db, migrate, reset_schema

SCRIPT = ScriptDirectory.from_config(Config(str(ALEMBIC_INI)))


@pytest.fixture(autouse=True)
def empty_db():
    if "fsp_migr" not in str(engine.url):
        pytest.skip("тест сносит схему — нужен отдельный DATABASE_URL (fsp_migr)")
    with engine.begin() as c:
        c.execute(text("DROP SCHEMA public CASCADE"))
        c.execute(text("CREATE SCHEMA public"))


def _versions() -> set[str]:
    with engine.connect() as c:
        return set(c.scalars(text("SELECT version_num FROM alembic_version")))


def _diff() -> list:
    with engine.connect() as c:
        ctx = MigrationContext.configure(c, opts={"compare_type": True, "compare_server_default": True})
        return compare_metadata(ctx, Base.metadata)


def test_revision_ids():
    # NNNN_slug, не длиннее alembic_version.version_num (varchar 32); baseline — корень
    for rev in SCRIPT.walk_revisions():
        assert re.fullmatch(r"\d{4}_[a-z0-9_]+", rev.revision) and len(rev.revision) <= 32, rev.revision
    assert list(SCRIPT.get_bases()) == [BASELINE]


def _cfg(conn) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes["connection"] = conn
    return cfg


def test_baseline_tables():
    # список в app.db (по нему распознаётся база от create_all) совпадает с тем, что создаёт ревизия baseline
    with engine.begin() as c:
        command.upgrade(_cfg(c), BASELINE)
    assert set(inspect(engine).get_table_names()) == BASELINE_TABLES | {"alembic_version"}


def test_upgrade_from_empty_matches_models():
    migrate()
    assert _versions() == set(SCRIPT.get_heads())
    assert _diff() == []  # иначе: модель изменили без ревизии — uv run alembic revision --autogenerate
    migrate()  # повторный запуск — no-op
    assert _versions() == set(SCRIPT.get_heads())


def _defs(schema: str) -> set[tuple[str, str, str]]:
    # индексы и ограничения как их видит Postgres (с предикатами WHERE и ondelete), без имени схемы
    with engine.connect() as c:
        rows = c.execute(text(
            "SELECT tablename, indexname, indexdef FROM pg_indexes WHERE schemaname = :s "
            "UNION ALL SELECT r.relname, o.conname, pg_get_constraintdef(o.oid) FROM pg_constraint o "
            "JOIN pg_class r ON r.oid = o.conrelid JOIN pg_namespace n ON n.oid = r.relnamespace WHERE n.nspname = :s"
        ), {"s": schema})
        return {(t, n, d.replace(f"{schema}.", "")) for t, n, d in rows if t != "alembic_version"}


def test_indexes_and_constraints_match_create_all():
    # autogenerate не сравнивает postgresql_where и не всегда — ondelete: сверяем определения с create_all
    migrate()
    with engine.begin() as c:
        c.execute(text("CREATE SCHEMA probe"))
        Base.metadata.create_all(c.execution_options(schema_translate_map={None: "probe"}))
    try:
        assert _defs("public") == _defs("probe")
    finally:
        with engine.begin() as c:
            c.execute(text("DROP SCHEMA probe CASCADE"))


def _legacy_main_db() -> None:
    """База, созданная create_all схемы main до Alembic: это ровно baseline (сверено pg_dump), но без alembic_version.
    create_all текущих моделей сюда не годится — в них уже колонки следующих ревизий."""
    with engine.begin() as c:
        command.upgrade(_cfg(c), BASELINE)
        c.execute(text("DROP TABLE alembic_version"))


def test_legacy_create_all_db_is_stamped():
    _legacy_main_db()
    with engine.begin() as c:
        c.execute(text("INSERT INTO retired_public_ids VALUES ('A-0001')"))
    init_db()  # таблицы есть, alembic_version нет → stamp baseline, upgrade heads, сверка
    assert _versions() == set(SCRIPT.get_heads())
    with engine.connect() as c:  # данные не тронуты
        assert c.scalar(text("SELECT public_id FROM retired_public_ids")) == "A-0001"
    assert _diff() == []


def test_0002_candidate_profile_on_existing_candidates():
    # ALTER на базе с кандидатами: NOT NULL-колонки получают пустые списки и включённый «Опыт» в PDF
    with engine.begin() as c:
        command.upgrade(_cfg(c), BASELINE)
    cand = Table("candidates", MetaData(), autoload_with=engine)
    filler = {String: "x", Integer: 0, Float: 0.0, Boolean: False, JSON: [], DateTime: datetime.now(UTC)}
    row = {col.name: next(v for t, v in filler.items() if isinstance(col.type, t)) for col in cand.columns
           if not col.nullable and col.server_default is None and not col.primary_key}
    with engine.begin() as c:
        c.execute(cand.insert().values(**row))
    migrate()
    with engine.connect() as c:
        got = c.execute(text("SELECT roles::text, soft_skills::text, pdf_experience FROM candidates")).one()
    assert tuple(got) == ("[]", "[]", True) and _diff() == []


def test_0004_reweights_existing_achievements():
    # старые веса с иерархией уровней → результативность без уровня; рейтинг CF не трогается
    with engine.begin() as c:
        command.upgrade(_cfg(c), "0003_merge_chat_profile")
        c.execute(text("INSERT INTO users (id, email, role, created_at) VALUES (1, 'u@example.ru', 'candidate', now())"))
        cand = Table("candidates", MetaData(), autoload_with=c)
        filler = {String: "x", Integer: 0, Float: 0.0, Boolean: False, JSON: [], DateTime: datetime.now(UTC)}
        row = {col.name: next(v for t, v in filler.items() if isinstance(col.type, t)) for col in cand.columns
               if not col.nullable and col.server_default is None and not col.primary_key}
        cid = c.execute(cand.insert().values(**row).returning(cand.c.id)).scalar()
        c.execute(text("INSERT INTO events (id, source, external_id, title, level, participants, tags) VALUES "
                       "(1, 'fsp', 'reg', 'Этап', 'regional', 100, '[]'), (2, 'codeforces', '7', 'Round', 'national', NULL, '[]'),"
                       "(3, 'ctftime', '9', 'CTF', 'international', 900, '[]')"))
        rows = [  # (id, event_id, source, place, verified, data, старый вес)
            (1, 1, "fsp", 1, True, '{"kind": "protocol"}', 0.5), (2, 1, "fsp", 8, True, '{"kind": "protocol"}', 0.25),
            (3, 1, "fsp", None, True, '{"kind": "protocol"}', 0.075), (4, 2, "codeforces", 12, True, '{"kind": "contest"}', 0.2),
            (5, None, "codeforces", None, True, '{"kind": "rating"}', 0.396), (6, 3, "ctftime", 2, False, '{"kind": "ctf"}', 0.425),
            (7, 3, "ctftime", 90, True, '{"kind": "ctf"}', 0.5), (8, 3, "ctftime", 91, False, '{"kind": "ctf"}', 0.125),
        ]
        for aid, eid, src, place, ver, data, w in rows:
            c.execute(text("INSERT INTO achievements (id, candidate_id, event_id, source, title, place, weight, verified, data, created_at) "
                           "VALUES (:id, :c, :e, :s, 't', :p, :w, :v, CAST(:d AS json), now())"),
                      {"id": aid, "c": cid, "e": eid, "s": src, "p": place, "w": w, "v": ver, "d": data})
    migrate()
    with engine.connect() as c:
        got = dict((i, (r, w)) for i, r, w in c.execute(text("SELECT id, result, weight FROM achievements")))
    assert got == {1: ("winner", 0.8), 2: ("finalist", 0.35), 3: ("participant", 0.05), 4: ("finalist", 0.35),
                   5: (None, 0.396), 6: ("prize", 0.3), 7: ("finalist", 0.35), 8: ("participant", 0.025)}
    assert _diff() == []


def test_chat_table_already_created_on_branch():
    # база ветки чата до Alembic: messages создана create_all — 0002_chat_messages её не пересоздаёт
    _legacy_main_db()
    Base.metadata.tables["messages"].create(engine)
    init_db()
    assert _versions() == set(SCRIPT.get_heads()) and _diff() == []


def test_legacy_main_db_gets_chat_table():
    # база схемы main до Alembic (без messages): stamp baseline, затем 0002_chat_messages создаёт таблицу чата
    _legacy_main_db()
    init_db()
    assert "messages" in inspect(engine).get_table_names() and _diff() == []


def test_partial_legacy_db_refused():
    # create_all прервался: таблицы частично есть, alembic_version нет → не помечаем baseline, просим пересоздать
    Base.metadata.tables["users"].create(engine)
    with pytest.raises(RuntimeError, match="неполная.*candidates"):
        migrate()
    assert "alembic_version" not in inspect(engine).get_table_names()


def test_downgrade_base_and_back():
    migrate()
    with engine.begin() as c:
        command.downgrade(_cfg(c), "base")
    assert set(inspect(engine).get_table_names()) == {"alembic_version"}
    migrate()
    assert _versions() == set(SCRIPT.get_heads()) and _diff() == []


def test_foreign_revision_fails_clearly():
    migrate()
    with engine.begin() as c:
        c.execute(text("UPDATE alembic_version SET version_num = '9999_other_branch'"))
    with pytest.raises(RuntimeError, match="другой ветки"):
        migrate()


def test_reset_drops_foreign_tables():
    # таблица другой ветки с внешним ключом на нашу: drop_all на ней падал, reset_schema сносит всё
    migrate()
    with engine.begin() as c:
        c.execute(text("CREATE TABLE notes_other_branch (id serial PRIMARY KEY, user_id int REFERENCES users(id))"))
    reset_schema()
    assert "notes_other_branch" not in inspect(engine).get_table_names()
    assert _versions() == set(SCRIPT.get_heads()) and _diff() == []
