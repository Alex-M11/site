"""Завдання, здача робіт студентами і перевірка викладачем."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import current_user, require_teacher
from ..models import ROLE_ADMIN, ROLE_STUDENT, Assignment, Group, Submission, Template, User, utcnow
from ..serializers import assignment_out, submission_out
from ..sessions_service import teacher_group_ids
from ..storage import StorageError, copy_submission, safe_path, submission_dir

router = APIRouter(prefix="/api/assignments", tags=["assignments"])


class AssignmentIn(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=10000)
    group_id: int
    template_id: int | None = None
    due_at: datetime | None = None


class SubmitIn(BaseModel):
    files: list[str] = Field(min_length=1, max_length=50)
    comment: str = Field(default="", max_length=5000)


class GradeIn(BaseModel):
    grade: str = Field(default="", max_length=32)
    feedback: str = Field(default="", max_length=5000)


def _naive_utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def _teacher_can(user: User, group_id: int) -> bool:
    return user.role == ROLE_ADMIN or group_id in teacher_group_ids(user)


def _get_assignment(db: Session, user: User, assignment_id: int) -> Assignment:
    a = db.get(Assignment, assignment_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Завдання не знайдено")
    if user.role == ROLE_STUDENT:
        if a.group_id != user.group_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Завдання не знайдено")
    elif not _teacher_can(user, a.group_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Це завдання іншої групи")
    return a


@router.get("")
def list_assignments(user: User = Depends(current_user), db: Session = Depends(get_db)):
    if user.role == ROLE_STUDENT:
        if user.group_id is None:
            return []
        items = db.scalars(select(Assignment).where(Assignment.group_id == user.group_id)
                           .order_by(Assignment.due_at.is_(None), Assignment.due_at, Assignment.id.desc())).all()
        subs = {s.assignment_id: s for s in db.scalars(
            select(Submission).where(Submission.student_id == user.id))}
        return [assignment_out(a, subs.get(a.id)) for a in items]
    q = select(Assignment).order_by(Assignment.created_at.desc())
    if user.role != ROLE_ADMIN:
        q = q.where(Assignment.group_id.in_(teacher_group_ids(user) or {-1}))
    result = []
    for a in db.scalars(q):
        subs = db.scalars(select(Submission).where(Submission.assignment_id == a.id)).all()
        result.append(assignment_out(a, stats={
            "students": len(a.group.students), "submitted": len(subs),
            "graded": sum(1 for s in subs if s.grade)}))
    return result


def _validate(db: Session, user: User, data: AssignmentIn) -> None:
    if db.get(Group, data.group_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Групу не знайдено")
    if not _teacher_can(user, data.group_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Можна створювати завдання лише для своїх груп")
    if data.template_id is not None and db.get(Template, data.template_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Шаблон не знайдено")


@router.post("", status_code=201)
def create(data: AssignmentIn, request: Request, user: User = Depends(require_teacher),
           db: Session = Depends(get_db)):
    _validate(db, user, data)
    a = Assignment(title=data.title.strip(), description=data.description, group_id=data.group_id,
                   template_id=data.template_id, teacher_id=user.id, due_at=_naive_utc(data.due_at))
    db.add(a)
    db.flush()
    audit(db, "assignment_create", user, a.title, request)
    db.commit()
    return assignment_out(a, stats={"students": len(a.group.students), "submitted": 0, "graded": 0})


@router.put("/{assignment_id}")
def update(assignment_id: int, data: AssignmentIn, user: User = Depends(require_teacher),
           db: Session = Depends(get_db)):
    a = _get_assignment(db, user, assignment_id)
    _validate(db, user, data)
    a.title, a.description, a.group_id = data.title.strip(), data.description, data.group_id
    a.template_id, a.due_at = data.template_id, _naive_utc(data.due_at)
    db.commit()
    return assignment_out(a, stats={})


@router.delete("/{assignment_id}")
def delete(assignment_id: int, request: Request, user: User = Depends(require_teacher),
           db: Session = Depends(get_db)):
    a = _get_assignment(db, user, assignment_id)
    audit(db, "assignment_delete", user, a.title, request)
    db.delete(a)
    db.commit()
    return {"ok": True}


@router.post("/{assignment_id}/submit")
def submit(assignment_id: int, data: SubmitIn, request: Request, user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    if user.role != ROLE_STUDENT:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Здавати роботи можуть лише студенти")
    a = _get_assignment(db, user, assignment_id)
    try:
        names = copy_submission(user.username, a.id, data.files)
    except StorageError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    sub = db.scalar(select(Submission).where(Submission.assignment_id == a.id, Submission.student_id == user.id))
    if sub is None:
        sub = Submission(assignment_id=a.id, student_id=user.id)
        db.add(sub)
    sub.files, sub.comment, sub.submitted_at = names, data.comment, utcnow()
    sub.grade, sub.feedback, sub.graded_at = "", "", None  # повторна здача — нова перевірка
    audit(db, "submission", user, f"{a.title}: {', '.join(names)}", request)
    db.commit()
    db.refresh(sub)
    return submission_out(sub)


@router.get("/{assignment_id}/submissions")
def submissions(assignment_id: int, user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    a = _get_assignment(db, user, assignment_id)
    subs = {s.student_id: s for s in db.scalars(select(Submission).where(Submission.assignment_id == a.id))}
    rows = []
    for student in sorted(a.group.students, key=lambda s: s.full_name or s.username):
        s = subs.get(student.id)
        rows.append({"student": {"id": student.id, "username": student.username, "full_name": student.full_name},
                     "submission": submission_out(s) if s else None})
    return {"assignment": assignment_out(a, stats={}), "rows": rows}


def _get_submission(db: Session, user: User, submission_id: int) -> Submission:
    sub = db.get(Submission, submission_id)
    if sub is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Роботу не знайдено")
    if user.role == ROLE_STUDENT:
        if sub.student_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Роботу не знайдено")
    elif not _teacher_can(user, sub.assignment.group_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостатньо прав")
    return sub


@router.get("/submissions/{submission_id}/files/{name}")
def submission_file(submission_id: int, name: str, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    sub = _get_submission(db, user, submission_id)
    if name not in (sub.files or []):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не знайдено")
    try:
        path = safe_path(submission_dir(sub.assignment_id, sub.student.username), name)
    except StorageError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не знайдено")
    return FileResponse(path, filename=name)


@router.put("/submissions/{submission_id}/grade")
def grade(submission_id: int, data: GradeIn, request: Request, user: User = Depends(require_teacher),
          db: Session = Depends(get_db)):
    sub = _get_submission(db, user, submission_id)
    sub.grade, sub.feedback, sub.graded_at = data.grade.strip(), data.feedback, utcnow()
    audit(db, "submission_grade", user, f"{sub.assignment.title}: {sub.student.username} → {sub.grade}", request)
    db.commit()
    return submission_out(sub)
