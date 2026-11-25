"""Контроль місця: «Мої файли» понад квоту і розрослий контейнер."""
from conftest import H


def tpl_id(c, name):
    return next(t["id"] for t in c.get("/api/templates").json() if t["name"] == name)


def fill(username, mb):
    from app.storage import home_dir
    (home_dir(username) / "big.bin").write_bytes(b"0" * (mb * 1024 * 1024))


def run_maintenance():
    from app.db import db_session
    from app.models import User
    from app.sessions_service import maintenance
    with db_session() as db:
        for u in db.query(User):   # змусити переміряти зараз
            u.disk_checked_at = None
        db.commit()
        return maintenance(db)


def test_over_quota_blocks_start_and_hard_limit_stops_desktop(login):
    admin = login("admin", "Admin12345")
    admin.put("/api/admin/settings", json={"default_quota_mb": 100, "quota_hard_percent": 120}, headers=H)
    s = login("student1", "Student123")
    sid = s.post("/api/sessions", json={"template_id": tpl_id(s, "SQL")}, headers=H).json()["id"]

    fill("student1", 110)                  # понад квоту, але нижче жорсткої межі (120 МБ)
    assert run_maintenance()["disk_stopped"] == 0
    assert s.get(f"/api/sessions/{sid}").json()["status"] == "running"
    me = s.get("/api/auth/me").json()
    assert me["quota"]["level"] == "over"
    r = s.post("/api/sessions", json={"template_id": tpl_id(s, "Ubuntu 22.04")}, headers=H)
    assert r.status_code == 507 and "Мої файли" in r.json()["detail"]

    fill("student1", 130)                  # понад жорстку межу — стіл зупиняється
    assert run_maintenance()["disk_stopped"] == 1
    info = s.get(f"/api/sessions/{sid}").json()
    assert info["status"] == "stopped" and "перевищила квоту" in info["error"]
    assert s.post(f"/api/sessions/{sid}/resume", headers=H).status_code == 507

    s.delete("/api/files?path=big.bin", headers=H)
    assert s.post(f"/api/sessions/{sid}/resume", headers=H).json()["status"] == "running"
    assert s.get("/api/auth/me").json()["quota"]["level"] == "ok"


def test_container_disk_limit_forces_fresh_desktop(login, driver):
    admin = login("admin", "Admin12345")
    admin.put("/api/admin/settings", json={"max_container_disk_mb": 512}, headers=H)
    s = login("student1", "Student123")
    sid = s.post("/api/sessions", json={"template_id": tpl_id(s, "SQL")}, headers=H).json()["id"]
    cid = next(iter(driver.containers))
    driver.containers[cid]["disk"] = 600 * 1024 * 1024
    assert run_maintenance()["disk_stopped"] == 1
    info = s.get(f"/api/sessions/{sid}").json()
    assert info["status"] == "error" and "заново" in info["error"]
    assert s.post(f"/api/sessions/{sid}/resume", headers=H).status_code == 200
    assert cid not in driver.containers           # старий розрослий контейнер видалено
    assert s.get(f"/api/sessions/{sid}").json()["status"] == "running"
