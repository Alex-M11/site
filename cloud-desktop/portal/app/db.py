"""Підключення до бази даних (MySQL у продакшені, SQLite для розробки й тестів)."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


engine: Engine | None = None
SessionLocal = sessionmaker(autoflush=False, expire_on_commit=False)


def init_engine(url: str) -> Engine:
    global engine
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        path = url.split("///", 1)[-1]
        if path and path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        else:
            kwargs["poolclass"] = StaticPool  # одна спільна БД у пам'яті (тести)
    else:
        kwargs["pool_recycle"] = 3600
    engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _fk_on(dbapi_conn, _record):  # pragma: no cover - тривіально
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    SessionLocal.configure(bind=engine)
    return engine


def create_schema() -> None:
    """Створити або оновити схему через міграції Alembic."""
    from . import models  # noqa: F401  (реєстрація моделей)
    from .migrate import upgrade
    assert engine is not None
    upgrade(engine)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def db_session() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
