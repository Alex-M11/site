"""Перетворення моделей на JSON для API."""
from __future__ import annotations

from datetime import datetime

from .models import Assignment, DesktopSession, Group, Submission, Template, User


def dt(value: datetime | None) -> str | None:
    return value.isoformat() + "Z" if value else None


def user_out(u: User, full: bool = False) -> dict:
    data = {
        "id": u.id, "username": u.username, "full_name": u.full_name, "role": u.role,
        "group_id": u.group_id, "group": u.group.name if u.group else None,
    }
    if full:
        data.update({
            "email": u.email, "is_active": u.is_active, "quota_mb": u.quota_mb,
            "created_at": dt(u.created_at), "last_login": dt(u.last_login),
            "teaching": [{"id": g.id, "name": g.name} for g in u.teaching],
        })
    return data


def group_out(g: Group, with_members: bool = False) -> dict:
    data = {
        "id": g.id, "name": g.name, "description": g.description,
        "student_count": len(g.students),
        "teachers": [{"id": t.id, "username": t.username, "full_name": t.full_name} for t in g.teachers],
    }
    if with_members:
        data["students"] = [user_out(s) for s in sorted(g.students, key=lambda s: s.full_name or s.username)]
    return data


def template_out(t: Template) -> dict:
    return {
        "id": t.id, "name": t.name, "subject": t.subject, "description": t.description,
        "os_family": t.os_family, "image": t.image, "cpu": t.cpu, "memory_mb": t.memory_mb,
        "shm_mb": t.shm_mb, "env": t.env or {}, "is_active": t.is_active,
        "created_by": t.created_by.full_name or t.created_by.username if t.created_by else None,
        "created_by_id": t.created_by_id,
        "groups": [{"id": g.id, "name": g.name} for g in t.groups],
    }


def session_out(s: DesktopSession) -> dict:
    return {
        "id": s.id, "status": s.status, "error": s.error,
        "template": {"id": s.template.id, "name": s.template.name, "os_family": s.template.os_family,
                     "subject": s.template.subject},
        "user": {"id": s.user.id, "username": s.user.username, "full_name": s.user.full_name,
                 "group": s.user.group.name if s.user.group else None},
        "created_at": dt(s.created_at), "started_at": dt(s.started_at), "last_activity": dt(s.last_activity),
        "desktop_url": f"/desktop/{s.id}/",
    }


def assignment_out(a: Assignment, submission: Submission | None = None, stats: dict | None = None) -> dict:
    data = {
        "id": a.id, "title": a.title, "description": a.description,
        "group": {"id": a.group.id, "name": a.group.name},
        "template": {"id": a.template.id, "name": a.template.name} if a.template else None,
        "teacher": (a.teacher.full_name or a.teacher.username) if a.teacher else None,
        "due_at": dt(a.due_at), "created_at": dt(a.created_at),
    }
    if submission is not None:
        data["submission"] = submission_out(submission)
    elif stats is None:
        data["submission"] = None
    if stats is not None:
        data["stats"] = stats
    return data


def submission_out(s: Submission) -> dict:
    return {
        "id": s.id, "assignment_id": s.assignment_id,
        "student": {"id": s.student.id, "username": s.student.username, "full_name": s.student.full_name},
        "comment": s.comment, "files": s.files or [], "submitted_at": dt(s.submitted_at),
        "late": bool(s.assignment.due_at and s.submitted_at > s.assignment.due_at),
        "grade": s.grade, "feedback": s.feedback, "graded_at": dt(s.graded_at),
    }
