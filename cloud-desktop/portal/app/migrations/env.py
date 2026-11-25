"""Середовище Alembic. Міграції запускаються автоматично при старті порталу (app/migrate.py),
а вручну — так:  cd portal && alembic -c app/migrations/alembic.ini upgrade head"""
from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from app import models  # noqa: F401  (реєстрація таблиць)
from app.config import config as app_config
from app.db import Base

target_metadata = Base.metadata


def run_migrations_online() -> None:
    connection = context.config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    engine = create_engine(app_config.database_url)
    with engine.connect() as conn:
        _run(conn)


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",  # SQLite не вміє ALTER COLUMN
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


run_migrations_online()
