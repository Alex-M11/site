"""Викладач біля столу студента: режим перегляду, керування, попередження студенту."""
import base64

from conftest import H


def start(c, name="SQL"):
    tid = next(t["id"] for t in c.get("/api/templates").json() if t["name"] == name)
    return c.post("/api/sessions", json={"template_id": tid}, headers=H).json()["id"]


def vnc_user(resp):
    return base64.b64decode(resp.headers["x-desktop-auth"].split()[1]).decode().split(":")[0]


def test_view_only_uses_viewer_account_and_student_sees_banner(login):
    s = login("student1", "Student123")
    sid = start(s)
    t = login("teacher", "Teacher123")

    info = t.get(f"/api/sessions/{sid}").json()
    assert not info["is_owner"]
    assert info["view_only_url"].startswith(f"/desktop/{sid}-view/") and "view_only=1" in info["view_only_url"]
    assert "resize=scale" in info["viewer_url"]          # викладач не змінює роздільність студенту
    assert "resize=remote" in s.get(f"/api/sessions/{sid}").json()["viewer_url"]

    assert s.get(f"/api/sessions/{sid}").json()["helper"] is None
    r = t.get("/api/proxy/auth", headers={"X-Original-URI": f"/desktop/{sid}-view/websockify"})
    assert r.status_code == 200 and vnc_user(r) == "kasm_viewer"
    helper = s.post(f"/api/sessions/{sid}/heartbeat", headers=H).json()["helper"]
    assert helper["mode"] == "view" and "Іваненко" in helper["name"]

    r = t.get("/api/proxy/auth", headers={"X-Original-URI": f"/desktop/{sid}/websockify"})
    assert vnc_user(r) == "kasm_user"
    assert s.get(f"/api/sessions/{sid}").json()["helper"]["mode"] == "control"
    log = login("admin", "Admin12345").get("/api/admin/audit?action=session_connect_helper").json()
    assert "керування" in log[0]["details"] and "перегляд" in log[1]["details"]


def test_owner_view_path_gets_viewer_and_other_student_denied(login):
    s = login("student1", "Student123")
    sid = start(s)
    r = s.get("/api/proxy/auth", headers={"X-Original-URI": f"/desktop/{sid}-view/"})
    assert vnc_user(r) == "kasm_viewer"
    assert login("student2", "Student123").get(
        "/api/proxy/auth", headers={"X-Original-URI": f"/desktop/{sid}-view/"}).status_code == 403


def test_teacher_resume_is_logged_as_teacher(login):
    s = login("student1", "Student123")
    sid = start(s)
    s.post(f"/api/sessions/{sid}/stop", headers=H)
    t = login("teacher", "Teacher123")
    assert t.post(f"/api/sessions/{sid}/resume", headers=H).json()["status"] == "running"
    entry = login("admin", "Admin12345").get("/api/admin/audit?action=session_start").json()[0]
    assert entry["username"] == "teacher" and "student1" in entry["details"]
