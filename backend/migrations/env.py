"""Окружение Alembic. База — DATABASE_URL из app.config, целевая схема — app.db.Base.metadata (все модели).

Из кода (app.db.migrate) соединение приходит готовым в config.attributes["connection"] — миграции идут
в его транзакции под advisory-блокировкой. Из CLI (uv run alembic …) — своё соединение по DATABASE_URL.
"""

from logging.config import fileConfig

from alembic import context

from app import models  # noqa: F401 — регистрирует все таблицы в Base.metadata
from app.db import Base, engine

config = context.config
target_metadata = Base.metadata


def run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True,
                      compare_server_default=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Офлайн-режим (--sql) не поддерживается: миграции применяются к живой базе")

conn = config.attributes.get("connection")
if conn is not None:
    run(conn)
else:
    # логи настраиваем только для CLI: fileConfig при старте приложения перетёр бы логгеры uvicorn
    if config.config_file_name:
        fileConfig(config.config_file_name, disable_existing_loggers=False)
    with engine.connect() as c:
        run(c)
