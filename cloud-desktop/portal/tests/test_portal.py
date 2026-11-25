"""Наскрізні тести порталу з fake-драйвером (без Docker)."""
from datetime import timedelta

from conftest import H


def tpl_id(c, name):
    return next(t["id"] for t in c.get("/api/templates").json() if t["name"] == name)


# --- вхід і безпека --------------------------------------------------------------
def test_login_logout_and_me(client):
    assert client.get("/api/auth/me").status_code == 401
    r = client.post("/api/auth/login", json={"username": "Student1", "password": "Student123"}, headers=H)
    assert r.status_code == 200
    assert "cd_token" in r.cookies
    me = client.get("/api/auth/me").json()
    assert me["username"] == "student1" and me["group"] == "КН-21"
    client.post("/api/auth/logout", headers=H)
    client.cookies.clear()
    assert client.get("/api/auth/me").status_code == 401


def test_wrong_password_and_rate_limit(client):
    for _ in range(5):
        r = client.post("/api/auth/login", json={"username": "student1", "password": "bad"}, headers=H)
        assert r.status_code == 401
    r = client.post("/api/auth/login", json={"username": "student1", "password": "Student123"}, headers=H)
    assert r.status_code == 429


def test_csrf_header_required(login):
    c = login("student1", "Student123")
    r = c.post("/api/sessions", json={"template_id": 1})
    assert r.status_code == 403


def test_passwords_are_hashed(client):
    from sqlalchemy import select

    from app.db import db_session
    from app.models import User
    with db_session() as db:
        u = db.scalar(select(User).where(User.username == "student1"))
        assert u.password_hash.startswith("pbkdf2_sha256$") and "Student123" not in u.password_hash


def test_bearer_token_works(client):
    token = client.post("/api/auth/login", json={"username": "teacher", "password": "Teacher123"}, headers=H).json()["token"]
    client.cookies.clear()
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.json()["role"] == "teacher"


# --- каталог і ролі ----------------------------------------------------------------
def test_student_sees_only_group_templates(login):
    kn = {t["name"] for t in login("student1", "Student123").get("/api/templates").json()}
    kb = {t["name"] for t in login("student3", "Student123").get("/api/templates").json()}
    assert "Kali Linux — Мережі" not in kn and "Програмування" in kn
    assert "Kali Linux — Мережі" in kb and "Програмування" not in kb


def test_student_cannot_use_admin_or_teacher_api(login):
    c = login("student1", "Student123")
    assert c.get("/api/admin/users").status_code == 403
    assert c.get("/api/teacher/sessions").status_code == 403
    assert c.post("/api/templates", json={"name": "x", "image": "y"}, headers=H).status_code == 403


def test_student_cannot_start_foreign_template(login):
    kali = tpl_id(login("student3", "Student123"), "Kali Linux — Мережі")
    r = login("student1", "Student123").post("/api/sessions", json={"template_id": kali}, headers=H)
    assert r.status_code == 403


# --- життєвий цикл столу ----------------------------------------------------------------
def test_session_lifecycle(login, driver):
    c = login("student1", "Student123")
    tid = tpl_id(c, "SQL")
    s = c.post("/api/sessions", json={"template_id": tid}, headers=H).json()
    sid = s["id"]
    info = c.get(f"/api/sessions/{sid}").json()
    assert info["status"] == "running" and info["ready"] and info["is_owner"]
    cid = next(iter(driver.containers))
    spec = driver.containers[cid]["spec"]
    assert spec.memory_mb == 2048 and spec.cpu == 1
    assert spec.files_host_path.endswith("/home/student1")
    assert spec.vnc_password and spec.vnc_password not in str(info)

    # повторний запуск повертає той самий стіл
    assert c.post("/api/sessions", json={"template_id": tid}, headers=H).json()["id"] == sid
    assert len(driver.containers) == 1

    assert c.post(f"/api/sessions/{sid}/pause", headers=H).json()["status"] == "paused"
    assert driver.containers[cid]["status"] == "paused"
    assert c.post(f"/api/sessions/{sid}/resume", headers=H).json()["status"] == "running"
    assert c.post(f"/api/sessions/{sid}/stop", headers=H).json()["status"] == "stopped"
    assert driver.containers[cid]["status"] == "stopped"
    assert c.post(f"/api/sessions/{sid}/resume", headers=H).json()["status"] == "running"
    assert driver.containers[cid]["status"] == "running"

    # скидання: старий контейнер видалено, створено новий
    c.post(f"/api/sessions/{sid}/reset", headers=H)
    assert cid not in driver.containers and len(driver.containers) == 1
    assert c.get(f"/api/sessions/{sid}").json()["status"] == "running"

    assert c.delete(f"/api/sessions/{sid}", headers=H).status_code == 200
    assert driver.containers == {}
    assert c.get("/api/sessions").json() == []


def test_session_limits(login, client):
    admin = login("admin", "Admin12345")
    admin.put("/api/admin/settings", json={"max_sessions_per_user": 1, "max_active_sessions": 2}, headers=H)
    s1 = login("student1", "Student123")
    s2 = login("student2", "Student123")
    s3 = login("student3", "Student123")
    assert s1.post("/api/sessions", json={"template_id": tpl_id(s1, "SQL")}, headers=H).status_code == 200
    r = s1.post("/api/sessions", json={"template_id": tpl_id(s1, "Ubuntu 22.04")}, headers=H)
    assert r.status_code == 429
    assert s2.post("/api/sessions", json={"template_id": tpl_id(s2, "SQL")}, headers=H).status_code == 200
    r = s3.post("/api/sessions", json={"template_id": tpl_id(s3, "SQL")}, headers=H)
    assert r.status_code == 503 and "завантажений" in r.json()["detail"]


def test_driver_error_marks_session(login, driver):
    c = login("student1", "Student123")
    driver.fail_next_create = True
    sid = c.post("/api/sessions", json={"template_id": tpl_id(c, "SQL")}, headers=H).json()["id"]
    info = c.get(f"/api/sessions/{sid}").json()
    assert info["status"] == "error" and "Імітована" in info["error"]
    # повторний запуск після помилки працює
    assert c.post(f"/api/sessions/{sid}/resume", headers=H).status_code == 200
    assert c.get(f"/api/sessions/{sid}").json()["status"] == "running"


def test_idle_auto_stop_and_sync(login, driver):
    from app.db import db_session
    from app.models import DesktopSession, utcnow
    from app.sessions_service import maintenance

    c = login("student1", "Student123")
    sid = c.post("/api/sessions", json={"template_id": tpl_id(c, "SQL")}, headers=H).json()["id"]
    sid2 = c.post("/api/sessions", json={"template_id": tpl_id(c, "Ubuntu 22.04")}, headers=H).json()["id"]
    with db_session() as db:
        s = db.get(DesktopSession, sid)
        s.last_activity = utcnow() - timedelta(hours=2)
        db.commit()
        cid2 = db.get(DesktopSession, sid2).container_id
    driver.remove(cid2)  # контейнер зник поза порталом
    with db_session() as db:
        result = maintenance(db)
    assert result["idle_stopped"] == 1 and result["synced"] == 1
    assert c.get(f"/api/sessions/{sid}").json()["status"] == "stopped"
    assert c.get(f"/api/sessions/{sid2}").json()["status"] == "stopped"
    # після зупинки через простій стіл знову запускається
    assert c.post(f"/api/sessions/{sid2}/resume", headers=H).status_code == 200
    assert c.get(f"/api/sessions/{sid2}").json()["status"] == "running"


def test_heartbeat_updates_activity(login):
    from app.db import db_session
    from app.models import DesktopSession, utcnow

    c = login("student1", "Student123")
    sid = c.post("/api/sessions", json={"template_id": tpl_id(c, "SQL")}, headers=H).json()["id"]
    old = utcnow() - timedelta(minutes=20)
    with db_session() as db:
        db.get(DesktopSession, sid).last_activity = old
        db.commit()
    c.post(f"/api/sessions/{sid}/heartbeat", headers=H)
    with db_session() as db:
        assert db.get(DesktopSession, sid).last_activity > old


# --- проксі Nginx ----------------------------------------------------------------------
def test_proxy_auth(login, client):
    owner = login("student1", "Student123")
    sid = owner.post("/api/sessions", json={"template_id": tpl_id(owner, "SQL")}, headers=H).json()["id"]
    uri = {"X-Original-URI": f"/desktop/{sid}/websockify"}

    r = owner.get("/api/proxy/auth", headers=uri)
    assert r.status_code == 200
    assert r.headers["x-desktop-upstream"].startswith("127.0.0.1:")
    assert r.headers["x-desktop-auth"].startswith("Basic ")

    assert login("student2", "Student123").get("/api/proxy/auth", headers=uri).status_code == 403
    assert client.get("/api/proxy/auth", headers=uri).status_code == 401
    assert owner.get("/api/proxy/auth", headers={"X-Original-URI": "/etc/passwd"}).status_code == 403

    # викладач групи може підключитися, і це потрапляє в журнал
    assert login("teacher", "Teacher123").get("/api/proxy/auth", headers=uri).status_code == 200
    admin = login("admin", "Admin12345")
    log = admin.get("/api/admin/audit?action=session_connect_helper").json()
    assert log and log[0]["username"] == "teacher"

    owner.post(f"/api/sessions/{sid}/stop", headers=H)
    assert owner.get("/api/proxy/auth", headers=uri).status_code == 403


def test_teacher_cannot_touch_other_groups(login):
    from app.db import db_session
    from app.models import Group, User
    from sqlalchemy import select

    s3 = login("student3", "Student123")  # КБ-22
    sid = s3.post("/api/sessions", json={"template_id": tpl_id(s3, "SQL")}, headers=H).json()["id"]
    with db_session() as db:  # знімаємо з викладача групу КБ-22
        t = db.scalar(select(User).where(User.username == "teacher"))
        t.teaching = [db.scalar(select(Group).where(Group.name == "КН-21"))]
        db.commit()
    teacher = login("teacher", "Teacher123")
    assert teacher.get(f"/api/sessions/{sid}").status_code == 404
    assert teacher.post(f"/api/sessions/{sid}/stop", headers=H).status_code == 404
    assert all(s["user"]["username"] != "student3" for s in teacher.get("/api/teacher/sessions").json())


# --- файли ------------------------------------------------------------------------------------
def test_files_upload_list_download_delete(login):
    c = login("student1", "Student123")
    assert c.post("/api/files/mkdir", json={"path": "", "name": "lab1"}, headers=H).status_code == 200
    r = c.post("/api/files/upload", data={"path": "lab1"}, files={"file": ("query.sql", b"SELECT 1;")}, headers=H)
    assert r.status_code == 200
    listing = c.get("/api/files?path=lab1").json()
    assert listing["items"][0]["name"] == "query.sql" and listing["used"] == 9
    assert c.get("/api/files/download?path=lab1/query.sql").content == b"SELECT 1;"
    assert c.delete("/api/files?path=lab1/query.sql", headers=H).status_code == 200
    assert c.get("/api/files?path=lab1").json()["items"] == []


def test_files_path_traversal_blocked(login, tmp_path):
    c = login("student1", "Student123")
    login("student2", "Student123").post("/api/files/upload", data={"path": ""},
                                         files={"file": ("secret.txt", b"x")}, headers=H)
    assert c.get("/api/files/download?path=../student2/secret.txt").status_code == 400
    assert c.get("/api/files?path=../../").status_code == 400
    assert c.delete("/api/files?path=..", headers=H).status_code == 400
    r = c.post("/api/files/upload", data={"path": ""}, files={"file": ("../evil.txt", b"x")}, headers=H)
    assert r.status_code == 200  # ім'я очищено до evil.txt усередині власної папки
    assert any(i["name"] == "evil.txt" for i in c.get("/api/files").json()["items"])


def test_symlink_not_followed(login):
    from app.storage import home_dir
    c = login("student1", "Student123")
    login("student2", "Student123").post("/api/files/upload", data={"path": ""},
                                         files={"file": ("secret.txt", b"top secret")}, headers=H)
    home = home_dir("student1")
    (home / "link").symlink_to(home.parent / "student2" / "secret.txt")
    (home / "dir").mkdir()
    (home / "dir" / "link").symlink_to(home.parent / "student2" / "secret.txt")
    assert c.get("/api/files/download?path=link").status_code == 400
    aid = c.get("/api/assignments").json()[0]["id"]
    assert c.post(f"/api/assignments/{aid}/submit", json={"files": ["link"]}, headers=H).status_code == 400
    sub = c.post(f"/api/assignments/{aid}/submit", json={"files": ["dir"]}, headers=H).json()
    import zipfile
    from app.storage import submission_dir
    with zipfile.ZipFile(submission_dir(aid, "student1") / sub["files"][0]) as zf:
        assert zf.namelist() == []


def test_quota(login):
    admin = login("admin", "Admin12345")
    admin.put("/api/admin/settings", json={"default_quota_mb": 100}, headers=H)
    c = login("student1", "Student123")
    big = b"0" * (101 * 1024 * 1024)
    r = c.post("/api/files/upload", data={"path": ""}, files={"file": ("big.bin", big)}, headers=H)
    assert r.status_code == 400 and "ліміт" in r.json()["detail"]
    assert c.get("/api/files").json()["items"] == []


# --- завдання й здача робіт -------------------------------------------------------------------
def test_submission_flow(login):
    s = login("student1", "Student123")
    s.post("/api/files/upload", data={"path": ""}, files={"file": ("lab1.sql", b"SELECT * FROM students;")}, headers=H)
    assignments = s.get("/api/assignments").json()
    assert len(assignments) == 1 and assignments[0]["submission"] is None
    aid = assignments[0]["id"]
    r = s.post(f"/api/assignments/{aid}/submit", json={"files": ["lab1.sql"], "comment": "готово"}, headers=H)
    assert r.status_code == 200
    sub_id = r.json()["id"]

    # студент іншої групи не бачить завдання
    other = login("student3", "Student123")
    assert all(a["id"] != aid for a in other.get("/api/assignments").json())
    assert other.post(f"/api/assignments/{aid}/submit", json={"files": ["x"]}, headers=H).status_code == 404

    t = login("teacher", "Teacher123")
    rows = t.get(f"/api/assignments/{aid}/submissions").json()["rows"]
    assert {r["student"]["username"] for r in rows} == {"student1", "student2"}
    assert next(r for r in rows if r["student"]["username"] == "student1")["submission"]["files"] == ["lab1.sql"]
    f = t.get(f"/api/assignments/submissions/{sub_id}/files/lab1.sql")
    assert f.content == b"SELECT * FROM students;"
    t.put(f"/api/assignments/submissions/{sub_id}/grade", json={"grade": "11", "feedback": "Добре"}, headers=H)
    mine = s.get("/api/assignments").json()[0]["submission"]
    assert mine["grade"] == "11" and mine["feedback"] == "Добре"
    # чужу роботу студент не завантажить
    assert other.get(f"/api/assignments/submissions/{sub_id}/files/lab1.sql").status_code == 404


def test_teacher_creates_assignment_only_for_own_groups(login):
    admin = login("admin", "Admin12345")
    g = admin.post("/api/admin/groups", json={"name": "ІПЗ-23"}, headers=H).json()
    t = login("teacher", "Teacher123")
    groups = {x["name"]: x["id"] for x in t.get("/api/teacher/groups").json()}
    ok = t.post("/api/assignments", json={"title": "Лаба 2", "group_id": groups["КН-21"]}, headers=H)
    assert ok.status_code == 201
    assert t.post("/api/assignments", json={"title": "Лаба 2", "group_id": g["id"]}, headers=H).status_code == 403


# --- шаблони ---------------------------------------------------------------------------------
def test_teacher_template_crud_and_limits(login):
    t = login("teacher", "Teacher123")
    images = t.get("/api/templates/images").json()
    groups = {x["name"]: x["id"] for x in t.get("/api/teacher/groups").json()}
    body = {"name": "Мережі — лаба 3", "subject": "Мережі", "image": images[1]["image"], "cpu": 1, "memory_mb": 1024,
            "group_ids": [groups["КБ-22"]], "env": {"LAUNCH_URL": "https://example.edu"}}
    r = t.post("/api/templates", json=body, headers=H)
    assert r.status_code == 201 and r.json()["os_family"] == "kali"
    tid = r.json()["id"]
    assert any(x["id"] == tid for x in login("student3", "Student123").get("/api/templates").json())
    assert not any(x["id"] == tid for x in login("student1", "Student123").get("/api/templates").json())

    assert t.post("/api/templates", json={**body, "image": "evil/miner:latest"}, headers=H).status_code == 400
    assert t.post("/api/templates", json={**body, "memory_mb": 64000}, headers=H).status_code == 400
    assert t.post("/api/templates", json={**body, "env": {"VNC_PW": "x"}}, headers=H).status_code == 400

    body["is_active"] = False
    assert t.put(f"/api/templates/{tid}", json=body, headers=H).status_code == 200
    assert not any(x["id"] == tid for x in login("student3", "Student123").get("/api/templates").json())
    assert t.delete(f"/api/templates/{tid}", headers=H).status_code == 200


# --- адміністратор ---------------------------------------------------------------------------
def test_admin_users_groups_import(login):
    a = login("admin", "Admin12345")
    g = a.post("/api/admin/groups", json={"name": "ІПЗ-23"}, headers=H).json()
    r = a.post("/api/admin/users", json={"username": "new.student", "password": "short", "group_id": g["id"]}, headers=H)
    assert r.status_code == 400
    r = a.post("/api/admin/users", json={"username": "new.student", "password": "Secret123", "group_id": g["id"]}, headers=H)
    assert r.status_code == 201
    assert a.post("/api/admin/users", json={"username": "new.student", "password": "Secret123"}, headers=H).status_code == 409
    csv_text = "username,full_name,password,role,group\nivan.p,Петренко Іван,Start2026a,student,ІПЗ-24\nbad user,,x,student,\n"
    res = a.post("/api/admin/users/import", json={"csv": csv_text}, headers=H).json()
    assert res["created"] == 1 and len(res["errors"]) == 1
    login("ivan.p", "Start2026a")
    users = {u["username"]: u for u in a.get("/api/admin/users").json()}
    assert users["ivan.p"]["group"] == "ІПЗ-24"
    me = next(u for u in users.values() if u["username"] == "admin")
    assert a.delete(f"/api/admin/users/{me['id']}", headers=H).status_code == 400


def test_admin_settings_validation_and_stats(login):
    a = login("admin", "Admin12345")
    assert a.put("/api/admin/settings", json={"idle_timeout_minutes": 1}, headers=H).status_code == 400
    assert a.put("/api/admin/settings", json={"unknown": 1}, headers=H).status_code == 400
    assert a.put("/api/admin/settings", json={"idle_timeout_minutes": 45}, headers=H).json()["idle_timeout_minutes"] == 45
    stats = a.get("/api/admin/stats").json()
    assert stats["driver"] == "fake" and stats["users"] >= 5
    assert "cd_active_sessions" in a.get("/metrics").text


def test_audit_records_actions(login):
    s = login("student1", "Student123")
    sid = s.post("/api/sessions", json={"template_id": tpl_id(s, "SQL")}, headers=H).json()["id"]
    s.post(f"/api/sessions/{sid}/reset", headers=H)
    actions = [r["action"] for r in login("admin", "Admin12345").get("/api/admin/audit?username=student1").json()]
    assert {"login", "session_start", "session_reset"} <= set(actions)


def test_pages_served(client):
    assert "Хмарний робочий стіл" in client.get("/").text
    assert "desktop.js" in client.get("/session/1").text
    assert client.get("/healthz").json()["ok"]


def test_crashed_container_detected(login, driver):
    c = login("student1", "Student123")
    sid = c.post("/api/sessions", json={"template_id": tpl_id(c, "SQL")}, headers=H).json()["id"]
    cid = next(iter(driver.containers))
    driver.containers[cid]["status"] = "stopped"  # контейнер упав сам
    info = c.get(f"/api/sessions/{sid}").json()
    assert info["status"] == "stopped" and "несподівано" in info["error"]
    assert c.post(f"/api/sessions/{sid}/resume", headers=H).json()["status"] == "running"
    assert c.get(f"/api/sessions/{sid}").json()["error"] == ""


def test_admin_can_force_stop_and_teacher_sees_sessions(login):
    s = login("student1", "Student123")
    sid = s.post("/api/sessions", json={"template_id": tpl_id(s, "SQL")}, headers=H).json()["id"]
    t = login("teacher", "Teacher123")
    assert any(x["id"] == sid for x in t.get("/api/teacher/sessions").json())
    a = login("admin", "Admin12345")
    assert a.post(f"/api/admin/sessions/{sid}/stop", headers=H).json()["status"] == "stopped"
    assert "session_force_stop" in [r["action"] for r in a.get("/api/admin/audit").json()]
