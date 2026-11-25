"""Автоперевірка робіт (у fake-режимі скрипт виконується локально; у docker — в ізольованому контейнері)."""
from unittest import mock

import pytest

from conftest import H

SCRIPT = """set -e
test -f lab1.sql || { echo "Немає файлу lab1.sql"; exit 1; }
grep -qi "select" lab1.sql && echo "OK: є SELECT"
"""


def teacher_assignment(t, **extra):
    a = next(x for x in t.get("/api/assignments").json() if x["group"]["name"] == "КН-21")
    body = {"title": a["title"], "description": a["description"], "group_id": a["group"]["id"],
            "template_id": a["template"]["id"] if a["template"] else None, "due_at": a["due_at"], **extra}
    r = t.put(f"/api/assignments/{a['id']}", json=body, headers=H)
    assert r.status_code == 200, r.text
    return r.json()


def upload(c, name, content):
    c.post("/api/files/upload", data={"path": ""}, files={"file": (name, content)}, headers=H)


def test_check_passes_and_fails(login):
    t = login("teacher", "Teacher123")
    a = teacher_assignment(t, check_script=SCRIPT)
    assert a["has_check"] and a["check_image"] == "python:3.12-slim"
    s = login("student1", "Student123")
    student_view = s.get("/api/assignments").json()[0]
    assert student_view["has_check"] and "check_script" not in student_view   # студент не бачить скрипт

    upload(s, "lab1.sql", b"SELECT * FROM students;")
    s.post(f"/api/assignments/{a['id']}/submit", json={"files": ["lab1.sql"]}, headers=H)
    sub = s.get("/api/assignments").json()[0]["submission"]
    assert sub["check_status"] == "passed" and "OK: є SELECT" in sub["check_output"]

    upload(s, "notes.txt", b"hello")
    s.post(f"/api/assignments/{a['id']}/submit", json={"files": ["notes.txt"]}, headers=H)
    sub = s.get("/api/assignments").json()[0]["submission"]
    assert sub["check_status"] == "failed" and "Немає файлу lab1.sql" in sub["check_output"]

    stats = next(x for x in t.get("/api/assignments").json() if x["id"] == a["id"])["stats"]
    assert stats["submitted"] == 1 and stats["passed"] == 0


def test_hidden_results_timeout_and_recheck(login):
    t = login("teacher", "Teacher123")
    a = teacher_assignment(t, check_script="sleep 10", check_timeout=5, show_check_to_student=False)
    s = login("student1", "Student123")
    upload(s, "lab1.sql", b"SELECT 1;")
    s.post(f"/api/assignments/{a['id']}/submit", json={"files": ["lab1.sql"]}, headers=H)
    mine = s.get("/api/assignments").json()[0]["submission"]
    assert mine["check_status"] == "hidden" and mine["check_output"] == ""
    row = next(r for r in t.get(f"/api/assignments/{a['id']}/submissions").json()["rows"] if r["submission"])
    assert row["submission"]["check_status"] == "failed" and "ліміт часу" in row["submission"]["check_output"]

    teacher_assignment(t, check_script="echo fixed", show_check_to_student=False)
    assert t.post(f"/api/assignments/{a['id']}/recheck", headers=H).json()["queued"] == 1
    row = next(r for r in t.get(f"/api/assignments/{a['id']}/submissions").json()["rows"] if r["submission"])
    assert row["submission"]["check_status"] == "passed"


def test_check_image_must_be_allowed(login):
    t = login("teacher", "Teacher123")
    a = next(x for x in t.get("/api/assignments").json() if x["group"]["name"] == "КН-21")
    r = t.put(f"/api/assignments/{a['id']}", json={"title": "x" * 3, "group_id": a["group"]["id"],
                                                     "check_script": "true", "check_image": "evil/miner"}, headers=H)
    assert r.status_code == 400


def test_docker_check_container_is_locked_down():
    docker = pytest.importorskip("docker")
    from app.drivers.base import CheckSpec
    from app.drivers.docker_driver import DockerDriver
    d = DockerDriver("cd_desktops", client=mock.MagicMock())
    kw = d.build_check_kwargs(CheckSpec(image="python:3.12-slim", script="true", work_host_path="/srv/x", timeout=30))
    assert kw["network_disabled"] and kw["read_only"] and kw["cap_drop"] == ["ALL"]
    assert kw["volumes"] == {"/srv/x": {"bind": "/work", "mode": "ro"}}
    assert kw["pids_limit"] <= 256 and kw["mem_limit"] == "512m" and kw["user"] == "1000:1000"
    del docker
