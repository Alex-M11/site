"""Кабінет викладача: групи і столи студентів."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import require_teacher
from ..models import ROLE_ADMIN, ROLE_STUDENT, DesktopSession, Group, User
from ..security import hash_password, temp_password
from ..serializers import group_out, session_out
from ..sessions_service import can_manage_student, teacher_group_ids

router = APIRouter(prefix="/api/teacher", tags=["teacher"])


def _groups(db: Session, user: User) -> list[Group]:
    if user.role == ROLE_ADMIN:
        return list(db.scalars(select(Group).order_by(Group.name)))
    return sorted(user.teaching, key=lambda g: g.name)


@router.get("/groups")
def my_groups(user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    return [group_out(g, with_members=True) for g in _groups(db, user)]


@router.get("/sessions")
def student_sessions(user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    """Столи студентів моїх груп — щоб підключитися й допомогти."""
    q = select(DesktopSession).join(User, DesktopSession.user_id == User.id) \
        .order_by(DesktopSession.last_activity.desc())
    if user.role != ROLE_ADMIN:
        q = q.where(User.group_id.in_(teacher_group_ids(user) or {-1}))
    return [session_out(s) for s in db.scalars(q)]


@router.post("/students/{student_id}/reset-password")
def reset_student_password(student_id: int, request: Request, user: User = Depends(require_teacher),
                           db: Session = Depends(get_db)):
    """Студент забув пароль: видати тимчасовий, який треба змінити при вході."""
    student = db.get(User, student_id)
    if student is None or student.role != ROLE_STUDENT or not can_manage_student(user, student):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Студента не знайдено")
    password = temp_password()
    student.password_hash = hash_password(password)
    student.must_change_password = True
    student.token_version = (student.token_version or 0) + 1
    audit(db, "password_reset", user, f"студенту {student.username}", request)
    db.commit()
    return {"username": student.username, "temporary_password": password}
