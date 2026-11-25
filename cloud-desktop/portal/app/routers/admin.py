"""Панель адміністратора: акаунти, групи, ліміти, навантаження, журнал."""
from __future__ import annotations

import csv
import io
import os
import shutil
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import config
from ..db import get_db
from ..deps import require_admin
from ..drivers import get_driver
from ..models import (
    ACTIVE_STATES, ROLE_STUDENT, ROLE_TEACHER, ROLES, AuditLog, DesktopSession, Group, User, utcnow,
)
from ..security import hash_password, validate_password_strength
from ..serializers import dt, group_out, session_out, user_out
from ..sessions_service import delete_session, stop_session
from ..settings_store import all_settings, set_setting
from ..storage import USERNAME_RE, dir_size, home_dir

router = APIRouter(prefix="/api/admin", tags=["admin"])


class UserIn(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    full_name: str = Field(default="", max_length=128)
    email: str = Field(default="", max_length=128)
    role: str = ROLE_STUDENT
    group_id: int | None = None
    teaching_ids: list[int] = Field(default_factory=list)
    password: str | None = Field(default=None, max_length=256)
    is_active: bool = True
    quota_mb: int | None = Field(default=None, ge=0)


class GroupIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    description: str = Field(default="", max_length=255)


class ImportIn(BaseModel):
    csv: str = Field(max_length=2_000_000)


# --- користувачі ---------------------------------------------------------------
def _apply_user(db: Session, u: User, data: UserIn, creating: bool) -> None:
    username = data.username.strip().lower()
    if not USERNAME_RE.match(username):
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            "Логін: латинські малі літери, цифри, крапка, дефіс або _, від 2 символів")
    if data.role not in ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Невідома роль")
    if data.group_id is not None and db.get(Group, data.group_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Групу не знайдено")
    if creating or data.password:
        if not data.password:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Вкажіть пароль")
        problem = validate_password_strength(data.password)
        if problem:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)
        u.password_hash = hash_password(data.password)
    u.username, u.full_name, u.email = username, data.full_name.strip(), data.email.strip()
    u.role, u.is_active = data.role, data.is_active
    u.group_id = data.group_id if data.role == ROLE_STUDENT else None
    u.quota_mb = data.quota_mb or None
    teaching = db.scalars(select(Group).where(Group.id.in_(data.teaching_ids))).all() \
        if data.role == ROLE_TEACHER and data.teaching_ids else []
    u.teaching = list(teaching)


@router.get("/users")
def users(q: str = "", role: str = "", group_id: int | None = None,
          admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    stmt = select(User).order_by(User.role, User.username)
    if q:
        like = f"%{q.lower()}%"
        stmt = stmt.where(func.lower(User.username).like(like) | func.lower(User.full_name).like(like))
    if role:
        stmt = stmt.where(User.role == role)
    if group_id:
        stmt = stmt.where(User.group_id == group_id)
    return [user_out(u, full=True) for u in db.scalars(stmt)]


@router.post("/users", status_code=201)
def create_user(data: UserIn, request: Request, admin: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    u = User()
    _apply_user(db, u, data, creating=True)
    db.add(u)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Користувач з таким логіном уже існує") from exc
    audit(db, "user_create", admin, f"{u.username} ({u.role})", request)
    db.commit()
    return user_out(u, full=True)


@router.put("/users/{user_id}")
def update_user(user_id: int, data: UserIn, request: Request, admin: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Користувача не знайдено")
    if u.id == admin.id and (data.role != admin.role or not data.is_active):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Не можна зняти права або вимкнути власний акаунт")
    _apply_user(db, u, data, creating=False)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Користувач з таким логіном уже існує") from exc
    audit(db, "user_update", admin, u.username, request)
    db.commit()
    return user_out(u, full=True)


@router.delete("/users/{user_id}")
def delete_user(user_id: int, request: Request, admin: User = Depends(require_admin),
                db: Session = Depends(get_db)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Користувача не знайдено")
    if u.id == admin.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Не можна видалити власний акаунт")
    for sess in db.scalars(select(DesktopSession).where(DesktopSession.user_id == u.id)).all():
        delete_session(db, admin, sess, request)
    audit(db, "user_delete", admin, u.username, request)
    db.delete(u)
    db.commit()
    # Файли студента не видаляємо автоматично — адміністратор робить це вручну після архівації.
    return {"ok": True}


@router.post("/users/import")
def import_users(data: ImportIn, request: Request, admin: User = Depends(require_admin),
                 db: Session = Depends(get_db)):
    """CSV: username,full_name,password,role,group (рядок заголовка обов'язковий). Групи створюються автоматично."""
    reader = csv.DictReader(io.StringIO(data.csv.strip()))
    required = {"username", "password"}
    if not reader.fieldnames or not required.issubset({f.strip() for f in reader.fieldnames}):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Потрібні колонки: username,full_name,password,role,group")
    created, errors = 0, []
    groups = {g.name: g for g in db.scalars(select(Group))}
    for line, row in enumerate(reader, start=2):
        row = {k.strip(): (v or "").strip() for k, v in row.items() if k}
        username = row.get("username", "").lower()
        try:
            if db.scalar(select(User).where(User.username == username)):
                raise ValueError("логін уже існує")
            gname = row.get("group", "")
            group = None
            if gname:
                group = groups.get(gname)
                if group is None:
                    group = groups[gname] = Group(name=gname)
                    db.add(group)
                    db.flush()
            payload = UserIn(username=username, full_name=row.get("full_name", ""), password=row.get("password"),
                             role=row.get("role") or ROLE_STUDENT, email=row.get("email", ""),
                             group_id=group.id if group else None)
            u = User()
            _apply_user(db, u, payload, creating=True)
            db.add(u)
            db.flush()
            created += 1
        except (ValueError, HTTPException) as exc:
            errors.append(f"рядок {line} ({username or '?'}): {getattr(exc, 'detail', exc)}")
    audit(db, "user_import", admin, f"створено {created}, помилок {len(errors)}", request)
    db.commit()
    return {"created": created, "errors": errors}


# --- групи ----------------------------------------------------------------------
@router.get("/groups")
def groups(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return [group_out(g) for g in db.scalars(select(Group).order_by(Group.name))]


@router.post("/groups", status_code=201)
def create_group(data: GroupIn, request: Request, admin: User = Depends(require_admin),
                 db: Session = Depends(get_db)):
    g = Group(name=data.name.strip(), description=data.description.strip())
    db.add(g)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Група з такою назвою вже існує") from exc
    audit(db, "group_create", admin, g.name, request)
    db.commit()
    return group_out(g)


@router.put("/groups/{group_id}")
def update_group(group_id: int, data: GroupIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    g = db.get(Group, group_id)
    if g is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Групу не знайдено")
    g.name, g.description = data.name.strip(), data.description.strip()
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Група з такою назвою вже існує") from exc
    return group_out(g)


@router.delete("/groups/{group_id}")
def delete_group(group_id: int, request: Request, admin: User = Depends(require_admin),
                 db: Session = Depends(get_db)):
    g = db.get(Group, group_id)
    if g is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Групу не знайдено")
    if g.students:
        raise HTTPException(status.HTTP_409_CONFLICT, "У групі є студенти — спершу перенесіть або видаліть їх")
    audit(db, "group_delete", admin, g.name, request)
    db.delete(g)
    db.commit()
    return {"ok": True}


# --- налаштування й ліміти ----------------------------------------------------------
@router.get("/settings")
def get_settings(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return all_settings(db)


@router.put("/settings")
def put_settings(data: dict, request: Request, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    try:
        for key, value in data.items():
            set_setting(db, key, value)
    except KeyError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Невідоме налаштування: {exc}") from exc
    except (ValueError, TypeError) as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    audit(db, "settings_update", admin, ", ".join(sorted(data)), request)
    db.commit()
    return all_settings(db)


# --- навантаження сервера ----------------------------------------------------------------
def _meminfo() -> dict:
    info: dict[str, int] = {}
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                key, value = line.split(":", 1)
                info[key] = int(value.split()[0]) * 1024
    except OSError:
        return {}
    return {"total": info.get("MemTotal"), "available": info.get("MemAvailable")}


def server_stats(db: Session) -> dict:
    by_status = dict(db.execute(select(DesktopSession.status, func.count()).group_by(DesktopSession.status)).all())
    disk = shutil.disk_usage(config.storage_root) if config.storage_root.exists() else None
    load = os.getloadavg() if hasattr(os, "getloadavg") else (0, 0, 0)
    since = utcnow() - timedelta(hours=24)
    return {
        "cpu_count": os.cpu_count(),
        "load": [round(x, 2) for x in load],
        "memory": _meminfo(),
        "disk": {"total": disk.total, "used": disk.used, "free": disk.free} if disk else None,
        "sessions": by_status,
        "active_sessions": sum(v for k, v in by_status.items() if k in ACTIVE_STATES),
        "users": db.scalar(select(func.count()).select_from(User)),
        "logins_24h": db.scalar(select(func.count()).select_from(AuditLog)
                                .where(AuditLog.action == "login", AuditLog.created_at >= since)),
        "driver": get_driver().name,
    }


@router.get("/stats")
def stats(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    return server_stats(db)


@router.get("/storage")
def storage_usage(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    """Скільки місця займає кожен користувач (може бути повільно на великих дисках)."""
    rows = []
    for u in db.scalars(select(User).order_by(User.username)):
        rows.append({"username": u.username, "full_name": u.full_name,
                     "used": dir_size(home_dir(u.username, create=False)) if (
                         config.storage_root / "home" / u.username).exists() else 0,
                     "quota_mb": u.quota_mb})
    return sorted(rows, key=lambda r: r["used"], reverse=True)


@router.get("/sessions")
def all_sessions(admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    q = select(DesktopSession).order_by(DesktopSession.last_activity.desc())
    return [session_out(s) for s in db.scalars(q)]


@router.post("/sessions/{session_id}/stop")
def force_stop(session_id: int, request: Request, admin: User = Depends(require_admin),
               db: Session = Depends(get_db)):
    sess = db.get(DesktopSession, session_id)
    if sess is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сесію не знайдено")
    return session_out(stop_session(db, admin, sess, request, reason="session_force_stop"))


# --- журнал дій ----------------------------------------------------------------------------
@router.get("/audit")
def audit_log(limit: int = Query(200, le=2000), offset: int = 0, action: str = "", username: str = "",
              admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    q = select(AuditLog).order_by(AuditLog.id.desc())
    if action:
        q = q.where(AuditLog.action == action)
    if username:
        q = q.where(AuditLog.username == username.lower())
    rows = db.scalars(q.limit(limit).offset(offset))
    return [{"id": r.id, "created_at": dt(r.created_at), "username": r.username, "action": r.action,
             "details": r.details, "ip": r.ip} for r in rows]
