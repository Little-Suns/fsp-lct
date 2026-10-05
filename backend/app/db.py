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
