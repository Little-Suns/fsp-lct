from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import DATABASE_URL

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db


def init_db() -> None:
    # ponytail: create_all вместо миграций; Alembic, когда схема начнёт меняться на живых данных
    from app import models  # noqa: F401

    Base.metadata.create_all(engine)
    check_schema()


def check_schema() -> None:
    """create_all не добавляет колонки в существующие таблицы — старая схема валит запросы позже и непонятно.

    Падаем сразу и объясняем, что делать.
    """
    from sqlalchemy import inspect

    insp = inspect(engine)
    missing = []
    for t in Base.metadata.sorted_tables:
        have = {c["name"] for c in insp.get_columns(t.name)}
        missing += [f"{t.name}.{col.name}" for col in t.columns if col.name not in have]
    if missing:
        raise RuntimeError(
            "Схема БД устарела, нет колонок: " + ", ".join(missing)
            + ". Пересоздайте базу: docker compose down -v (или python -m seed.generate --reset)."
        )
