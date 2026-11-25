"""Безпека входу: відкликання токенів, тимчасові паролі, ліміт спроб."""
from conftest import H


def test_logout_revokes_token(client):
    client.post("/api/auth/login", json={"username": "student1", "password": "Student123"}, headers=H)
    stolen = client.cookies["cd_token"]
    client.post("/api/auth/logout", headers=H)
    client.cookies.clear()
    # навіть якщо хтось скопіював cookie до виходу, він більше не діє
    assert client.get("/api/auth/me", headers={"Authorization": f"Bearer {stolen}"}).status_code == 401


def test_password_change_kills_other_sessions(login):
    phone = login("student1", "Student123")
    laptop = login("student1", "Student123")
    r = laptop.post("/api/auth/password", json={"old_password": "Student123", "new_password": "NewPass2026"}, headers=H)
    assert r.status_code == 200
    assert laptop.get("/api/auth/me").status_code == 200   # поточний вхід оновлено
    assert phone.get("/api/auth/me").status_code == 401    # інші — недійсні
    assert laptop.post("/api/auth/password", json={"old_password": "NewPass2026", "new_password": "NewPass2026"},
                       headers=H).status_code == 400


def test_admin_created_user_must_change_password(login):
    admin = login("admin", "Admin12345")
    admin.post("/api/admin/users", json={"username": "fresh", "password": "Given2026x"}, headers=H)
    u = login("fresh", "Given2026x")
    me = u.get("/api/auth/me").json()
    assert me["must_change_password"] is True
    assert u.get("/api/templates").status_code == 403          # усе інше закрито
    assert u.get("/api/proxy/auth", headers={"X-Original-URI": "/desktop/1/"}).status_code in (401, 403)
    u.post("/api/auth/password", json={"old_password": "Given2026x", "new_password": "Mine2026xx"}, headers=H)
    assert u.get("/api/templates").status_code == 200


def test_admin_deactivation_and_role_change_invalidate_tokens(login):
    admin = login("admin", "Admin12345")
    s = login("student2", "Student123")
    users = {u["username"]: u for u in admin.get("/api/admin/users").json()}
    body = {**users["student2"], "role": "student", "is_active": True, "password": None, "teaching_ids": []}
    admin.put(f"/api/admin/users/{body['id']}", json=body, headers=H)
    assert s.get("/api/auth/me").status_code == 200   # нічого важливого не змінилося
    admin.put(f"/api/admin/users/{body['id']}", json={**body, "is_active": False}, headers=H)
    assert s.get("/api/auth/me").status_code == 401
    admin.put(f"/api/admin/users/{body['id']}", json={**body, "is_active": True}, headers=H)
    assert s.get("/api/auth/me").status_code == 401   # старий токен не воскресає


def test_teacher_resets_student_password(login):
    t = login("teacher", "Teacher123")
    groups = t.get("/api/teacher/groups").json()
    sid = next(s["id"] for g in groups for s in g["students"] if s["username"] == "student1")
    old = login("student1", "Student123")
    res = t.post(f"/api/teacher/students/{sid}/reset-password", headers=H).json()
    assert old.get("/api/auth/me").status_code == 401
    new = login("student1", res["temporary_password"])
    assert new.get("/api/auth/me").json()["must_change_password"] is True
    # викладач не може скинути пароль адміністратору чи студенту чужої групи
    admin_id = next(u["id"] for u in login("admin", "Admin12345").get("/api/admin/users").json() if u["role"] == "admin")
    assert t.post(f"/api/teacher/students/{admin_id}/reset-password", headers=H).status_code == 404
    assert login("student3", "Student123").post(f"/api/teacher/students/{sid}/reset-password",
                                                headers=H).status_code == 403


def test_rate_limit_is_per_ip_and_resets_after_success(client):
    def attempt(pw, ip):
        return client.post("/api/auth/login", json={"username": "student1", "password": pw},
                           headers={**H, "X-Real-IP": ip}).status_code
    for _ in range(4):
        assert attempt("bad", "10.0.0.1") == 401
    assert attempt("Student123", "10.0.0.1") == 200          # успішний вхід обнуляє лічильник
    for _ in range(5):
        assert attempt("bad", "10.0.0.1") == 401
    assert attempt("Student123", "10.0.0.1") == 429
    assert attempt("Student123", "10.0.0.2") == 200          # інший комп'ютер не заблоковано


def test_rate_limit_global_per_user(client):
    for i in range(20):
        client.post("/api/auth/login", json={"username": "student2", "password": "bad"},
                    headers={**H, "X-Real-IP": f"10.1.0.{i}"})
    r = client.post("/api/auth/login", json={"username": "student2", "password": "Student123"},
                    headers={**H, "X-Real-IP": "10.1.1.1"})
    assert r.status_code == 429
