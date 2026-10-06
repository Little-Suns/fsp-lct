from collections.abc import Iterator
from pathlib import Path

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)

ALEMBIC_INI = Path(__file__).resolve().parent.parent / "alembic.ini"
BASELINE = "0001_baseline"  # схема, которую до Alembic создавал create_all
BASELINE_TABLES = {  # таблицы baseline: база без alembic_version помечается им, только если они все на месте
    "audit_log", "consent_events", "events", "items", "login_challenges", "retired_public_ids", "users", "candidates",
    "companies", "achievements", "external_accounts", "needs", "quest_sessions", "vacancies", "applications", "lotteries",
    "tasks", "invitations", "task_submissions",
}
MIGRATE_LOCK = 0x46535001  # ключ advisory-блокировки: несколько процессов не накатывают миграции одновременно


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db


def init_db() -> None:
    """Старт приложения: накатить все миграции, потом убедиться, что схема совпадает с моделями."""
    from app import models  # noqa: F401 — check_schema сверяет со всеми таблицами

    migrate()
    check_schema()


def migrate(bind: Engine = engine) -> None:
    """alembic upgrade heads (все головы: у параллельных веток свои ревизии поверх baseline).

    База, созданная create_all до Alembic (таблицы есть, alembic_version нет), сначала помечается baseline.
    Всё — одной транзакцией под advisory-блокировкой: DDL в Postgres транзакционный, при ошибке ничего не меняется.
    """
    from alembic import command
    from alembic.config import Config
    from alembic.util import CommandError
    from sqlalchemy import inspect

    from app import models  # noqa: F401

    with bind.begin() as conn:
        conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": MIGRATE_LOCK})
        cfg = Config(str(ALEMBIC_INI))
        cfg.attributes["connection"] = conn
        have = set(inspect(conn).get_table_names())
        if "alembic_version" not in have and have & BASELINE_TABLES:
            if lost := BASELINE_TABLES - have:  # недосозданная база: пометить baseline — навсегда потерять эти таблицы
                raise RuntimeError(
                    "База создана без Alembic и неполная, нет таблиц: " + ", ".join(sorted(lost))
                    + ". Пересоздайте её: python -m seed.generate --reset (или docker compose down -v)."
                )
            command.stamp(cfg, BASELINE)
        try:
            command.upgrade(cfg, "heads")
        except CommandError as e:
            raise RuntimeError(
                f"Миграции БД не применились: {e}. Если в базе ревизия, которой нет в коде, база осталась от другой ветки — "
                "переключитесь на неё или пересоздайте базу: python -m seed.generate --reset (или docker compose down -v)."
            ) from e


def reset_schema(bind: Engine = engine) -> None:
    """Пустая схема public и все миграции заново. В отличие от drop_all, сносит и чужие таблицы
    (от других веток) вместе с alembic_version — иначе повторный засев падает на висящих внешних ключах."""
    with bind.begin() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    migrate(bind)


def check_schema() -> None:
    """Страховка после миграций: модель поменяли без ревизии Alembic — падаем сразу и объясняем, что делать,
    а не валим запросы позже и непонятно. Сверяются таблицы и колонки; полную сверку держит tests/test_migrations.py.
    """
    from sqlalchemy import inspect

    insp = inspect(engine)
    tables = set(insp.get_table_names())
    missing = []
    for t in Base.metadata.sorted_tables:
        if t.name not in tables:
            missing.append(t.name)
            continue
        have = {c["name"] for c in insp.get_columns(t.name)}
        missing += [f"{t.name}.{col.name}" for col in t.columns if col.name not in have]
    if missing:
        raise RuntimeError(
            "Схема БД не совпадает с моделями, нет таблиц или колонок: " + ", ".join(missing)
            + ". Модель изменили без ревизии Alembic? Добавьте её: cd backend && uv run alembic revision --autogenerate"
            " --rev-id NNNN_slug -m '…'. Если база от другой ветки — python -m seed.generate --reset."
        )
