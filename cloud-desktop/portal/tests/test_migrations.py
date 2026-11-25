"""Міграції: схема після `upgrade head` збігається з моделями; стара БД без журналу міграцій оновлюється."""
import sqlalchemy as sa
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app import models  # noqa: F401
from app.db import Base
from app.migrate import upgrade


def test_migrations_match_models(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    upgrade(engine)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], diff


def test_legacy_database_is_stamped_and_upgraded(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    # Імітуємо БД першої версії: таблиця users без нових колонок і без alembic_version.
    with engine.begin() as conn:
        from alembic.operations import Operations
        ctx = MigrationContext.configure(conn)
        import importlib.util
        from app.migrate import MIGRATIONS
        spec = importlib.util.spec_from_file_location("m0001", MIGRATIONS / "versions" / "0001_initial_schema.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        with Operations.context(ctx):
            mod.upgrade()
        conn.execute(sa.text("INSERT INTO users (username, full_name, email, password_hash, role, is_active, created_at)"
                             " VALUES ('old', '', '', 'x', 'student', 1, '2026-01-01')"))
    upgrade(engine)
    with engine.connect() as conn:
        cols = {c["name"] for c in sa.inspect(conn).get_columns("users")}
        assert {"token_version", "must_change_password"} <= cols
        assert conn.execute(sa.text("SELECT token_version FROM users WHERE username='old'")).scalar() == 0
        assert conn.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == "0002"
