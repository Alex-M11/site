"""Автоматичне оновлення схеми БД при старті порталу (Alembic)."""
from __future__ import annotations

import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect
from sqlalchemy.engine import Engine

log = logging.getLogger("cloud_desktop.migrate")
MIGRATIONS = Path(__file__).parent / "migrations"
# Схема першої версії порталу (до появи міграцій) відповідає ревізії 0001.
LEGACY_REVISION = "0001"


def alembic_config(connection=None) -> Config:
    cfg = Config(str(MIGRATIONS / "alembic.ini"))
    cfg.set_main_option("script_location", str(MIGRATIONS))
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def upgrade(engine: Engine) -> None:
    with engine.begin() as conn:
        tables = set(inspect(conn).get_table_names())
        cfg = alembic_config(conn)
        if "users" in tables and "alembic_version" not in tables:
            log.warning("БД створена до появи міграцій — позначаю її як ревізію %s", LEGACY_REVISION)
            command.stamp(cfg, LEGACY_REVISION)
        command.upgrade(cfg, "head")
