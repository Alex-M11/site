import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.update({
    "CD_DATABASE_URL": "sqlite:///:memory:",
    "CD_DRIVER": "fake",
    "CD_PBKDF2_ITERATIONS": "1000",
    "CD_DEMO_SEED": "1",
    "CD_ADMIN_PASSWORD": "Admin12345",
    "CD_SECRET_KEY": "test-secret-key-that-is-long-enough-for-hs256",
    "CD_BACKGROUND_TASKS": "0",
})

H = {"X-Requested-With": "cloud-desktop"}


@pytest.fixture()
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CD_STORAGE_ROOT", str(tmp_path / "storage"))
    from app import config as config_mod
    config_mod.reload_config()
    from app import db
    from app.drivers import set_driver
    from app.security import login_limiter
    set_driver(None)
    login_limiter._attempts.clear()
    if db.engine is not None:
        db.Base.metadata.drop_all(db.engine)
    yield


@pytest.fixture()
def client(app_env):
    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def login(client):
    from fastapi.testclient import TestClient

    from app.main import app

    clients = []

    def _login(username, password):
        c = TestClient(app)
        r = c.post("/api/auth/login", json={"username": username, "password": password}, headers=H)
        assert r.status_code == 200, r.text
        clients.append(c)
        return c
    yield _login
    for c in clients:
        c.close()


@pytest.fixture()
def driver():
    from app.drivers import get_driver
    return get_driver()
