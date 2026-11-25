"""Моделі бази даних: акаунти, групи, шаблони, сесії, завдання, здані роботи, журнал."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON, BigInteger, Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Table, Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    """Поточний час UTC без tz (MySQL DATETIME не зберігає зону)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


ROLE_STUDENT = "student"
ROLE_TEACHER = "teacher"
ROLE_ADMIN = "admin"
ROLES = (ROLE_STUDENT, ROLE_TEACHER, ROLE_ADMIN)

# Стани сесії робочого столу
S_CREATING = "creating"
S_RUNNING = "running"
S_PAUSED = "paused"
S_STOPPED = "stopped"
S_ERROR = "error"
ACTIVE_STATES = (S_CREATING, S_RUNNING, S_PAUSED)  # займають пам'ять сервера


teacher_groups = Table(
    "teacher_groups", Base.metadata,
    Column("teacher_id", ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
)

template_groups = Table(
    "template_groups", Base.metadata,
    Column("template_id", ForeignKey("templates.id", ondelete="CASCADE"), primary_key=True),
    Column("group_id", ForeignKey("groups.id", ondelete="CASCADE"), primary_key=True),
)


class Group(Base):
    __tablename__ = "groups"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True)
    description: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    students: Mapped[list[User]] = relationship(back_populates="group", foreign_keys="User.group_id")
    teachers: Mapped[list[User]] = relationship(secondary=teacher_groups, back_populates="teaching")
    templates: Mapped[list[Template]] = relationship(secondary=template_groups, back_populates="groups")


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(128), default="")
    email: Mapped[str] = mapped_column(String(128), default="")
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), default=ROLE_STUDENT)
    group_id: Mapped[int | None] = mapped_column(ForeignKey("groups.id", ondelete="SET NULL"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    quota_mb: Mapped[int | None] = mapped_column(Integer, nullable=True)  # None → значення за замовчуванням
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Збільшується при зміні пароля/ролі/вимкненні — усі раніше видані токени стають недійсними.
    token_version: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Пароль видав адміністратор або викладач — після входу його треба змінити.
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default="0")
    # Останнє виміряне використання «Моїх файлів» (фонове завдання).
    disk_used_bytes: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    disk_checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    group: Mapped[Group | None] = relationship(back_populates="students", foreign_keys=[group_id])
    teaching: Mapped[list[Group]] = relationship(secondary=teacher_groups, back_populates="teachers")


class Template(Base):
    """Шаблон середовища, який готує викладач (напр. «Мережі», «SQL»)."""
    __tablename__ = "templates"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128))
    subject: Mapped[str] = mapped_column(String(128), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    os_family: Mapped[str] = mapped_column(String(32), default="ubuntu")
    image: Mapped[str] = mapped_column(String(255))
    cpu: Mapped[float] = mapped_column(Float, default=1.0)
    memory_mb: Mapped[int] = mapped_column(Integer, default=2048)
    shm_mb: Mapped[int] = mapped_column(Integer, default=512)
    # Додаткові змінні оточення (напр. стартова URL браузера).
    env: Mapped[dict] = mapped_column(JSON, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    created_by: Mapped[User | None] = relationship()
    groups: Mapped[list[Group]] = relationship(secondary=template_groups, back_populates="templates")


class DesktopSession(Base):
    """Робочий стіл студента: один контейнер на пару (користувач, шаблон)."""
    __tablename__ = "desktop_sessions"
    __table_args__ = (UniqueConstraint("user_id", "template_id", name="uq_session_user_template"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("templates.id", ondelete="CASCADE"))
    container_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    container_name: Mapped[str] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(16), default=S_CREATING, index=True)
    host: Mapped[str | None] = mapped_column(String(64), nullable=True)
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    vnc_password: Mapped[str] = mapped_column(String(64))
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_activity: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Хто з викладачів зараз дивиться/керує столом (студент бачить попередження).
    helper_name: Mapped[str] = mapped_column(String(128), default="", server_default="")
    helper_mode: Mapped[str] = mapped_column(String(8), default="", server_default="")
    helper_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    user: Mapped[User] = relationship()
    template: Mapped[Template] = relationship()


class Assignment(Base):
    __tablename__ = "assignments"
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    group_id: Mapped[int] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"))
    template_id: Mapped[int | None] = mapped_column(ForeignKey("templates.id", ondelete="SET NULL"), nullable=True)
    teacher_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    # Автоперевірка: скрипт bash виконується в ізольованому контейнері, здані файли — у /work.
    check_script: Mapped[str | None] = mapped_column(Text, nullable=True, default="")
    check_image: Mapped[str] = mapped_column(String(255), default="", server_default="")
    check_timeout: Mapped[int] = mapped_column(Integer, default=60, server_default="60")
    show_check_to_student: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")

    group: Mapped[Group] = relationship()
    template: Mapped[Template | None] = relationship()
    teacher: Mapped[User | None] = relationship()


class Submission(Base):
    __tablename__ = "submissions"
    __table_args__ = (UniqueConstraint("assignment_id", "student_id", name="uq_submission"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    assignment_id: Mapped[int] = mapped_column(ForeignKey("assignments.id", ondelete="CASCADE"), index=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    comment: Mapped[str] = mapped_column(Text, default="")
    files: Mapped[list] = mapped_column(JSON, default=list)
    submitted_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    grade: Mapped[str] = mapped_column(String(32), default="")
    feedback: Mapped[str] = mapped_column(Text, default="")
    graded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    check_status: Mapped[str] = mapped_column(String(16), default="", server_default="")  # pending/passed/failed/error
    check_output: Mapped[str | None] = mapped_column(Text, nullable=True, default="")
    checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    assignment: Mapped[Assignment] = relationship()
    student: Mapped[User] = relationship()


class AuditLog(Base):
    """Журнал дій: хто, коли і з яким середовищем працював."""
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_user_action_time", "username", "action", "created_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    action: Mapped[str] = mapped_column(String(48), index=True)
    details: Mapped[str] = mapped_column(Text, default="")
    ip: Mapped[str] = mapped_column(String(64), default="")


class RevokedToken(Base):
    """Токени, які відкликано (вихід із системи). Записи видаляються після закінчення терміну дії."""
    __tablename__ = "revoked_tokens"
    jti: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text)
