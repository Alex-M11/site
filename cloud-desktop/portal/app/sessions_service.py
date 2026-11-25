"""Логіка робочих столів: запуск, пауза, зупинка, скидання, автовимкнення при простої."""
from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .audit import audit
from .config import config
from .db import db_session
from .drivers import DesktopSpec, DriverError, get_driver
from .models import (
    ACTIVE_STATES, ROLE_ADMIN, ROLE_STUDENT, ROLE_TEACHER, S_CREATING, S_ERROR, S_PAUSED, S_RUNNING,
    S_STOPPED, DesktopSession, Template, User, utcnow,
)
from .settings_store import get_setting
from .storage import host_home_dir

log = logging.getLogger("cloud_desktop.sessions")

CREATING_TIMEOUT = timedelta(minutes=20)  # великі образи можуть довго завантажуватися


# --- права доступу ---------------------------------------------------------------
def teacher_group_ids(user: User) -> set[int]:
    return {g.id for g in user.teaching}


def can_use_template(user: User, template: Template) -> bool:
    if not template.is_active:
        return user.role == ROLE_ADMIN
    if user.role in (ROLE_ADMIN, ROLE_TEACHER):
        return True
    return user.group_id is not None and any(g.id == user.group_id for g in template.groups)


def visible_templates(db: Session, user: User) -> list[Template]:
    templates = db.scalars(select(Template).order_by(Template.subject, Template.name)).all()
    return [t for t in templates if can_use_template(user, t) and (t.is_active or user.role == ROLE_ADMIN)]


def can_manage_student(user: User, student: User) -> bool:
    """Адміністратор — усіх; викладач — студентів своїх груп; студент — лише себе."""
    if user.role == ROLE_ADMIN or user.id == student.id:
        return True
    return user.role == ROLE_TEACHER and student.role == ROLE_STUDENT \
        and student.group_id is not None and student.group_id in teacher_group_ids(user)


def get_session_for(db: Session, user: User, session_id: int) -> DesktopSession:
    sess = db.get(DesktopSession, session_id)
    if sess is None or not can_manage_student(user, sess.user):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Сесію не знайдено")
    return sess


# --- ліміти ----------------------------------------------------------------------
def active_count(db: Session, user_id: int | None = None) -> int:
    q = select(func.count()).select_from(DesktopSession).where(DesktopSession.status.in_(ACTIVE_STATES))
    if user_id is not None:
        q = q.where(DesktopSession.user_id == user_id)
    return db.scalar(q) or 0


def check_capacity(db: Session, user: User) -> None:
    if active_count(db, user.id) >= get_setting(db, "max_sessions_per_user"):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                            "Досягнуто ліміту одночасних столів. Зупиніть інший стіл і спробуйте знову.")
    if active_count(db) >= get_setting(db, "max_active_sessions"):
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            "Сервер зараз повністю завантажений. Спробуйте за кілька хвилин.")


# --- життєвий цикл ---------------------------------------------------------------
def _spec(sess: DesktopSession) -> DesktopSpec:
    t = sess.template
    return DesktopSpec(
        name=sess.container_name,
        image=t.image,
        cpu=t.cpu,
        memory_mb=t.memory_mb,
        shm_mb=t.shm_mb,
        vnc_password=sess.vnc_password,
        files_host_path=host_home_dir(sess.user.username),
        files_container_path=config.container_files_path,
        env={str(k): str(v) for k, v in (t.env or {}).items()},
        labels={"cloud-desktop.user": sess.user.username, "cloud-desktop.template": str(t.id),
                "cloud-desktop.session": str(sess.id)},
    )


def _new_container_name(user: User, template: Template) -> str:
    return f"cd-{user.username}-t{template.id}-{secrets.token_hex(3)}".replace(".", "-")


def _refresh_endpoint(sess: DesktopSession) -> None:
    ep = get_driver().endpoint(sess.container_id)
    sess.host, sess.port = ep.host, ep.port


def provision(session_id: int) -> None:
    """Створити контейнер (виконується у фоні: завантаження образу може бути довгим)."""
    with db_session() as db:
        sess = db.get(DesktopSession, session_id)
        if sess is None or sess.status != S_CREATING:
            return
        driver = get_driver()
        try:
            if sess.container_id:
                driver.remove(sess.container_id)
            sess.container_id = driver.create(_spec(sess))
            _refresh_endpoint(sess)
            sess.status = S_RUNNING
            sess.error = ""
            sess.started_at = sess.last_activity = utcnow()
        except (DriverError, OSError) as exc:
            log.exception("Не вдалося створити стіл %s", session_id)
            sess.status = S_ERROR
            sess.error = str(exc)
            audit(db, "session_error", sess.user, f"{sess.template.name}: {exc}")
        db.commit()


def start_session(db: Session, user: User, template: Template, request=None) -> tuple[DesktopSession, bool]:
    """Запустити стіл або повернутися до вже відкритого. Повертає (сесія, чи потрібне створення контейнера)."""
    if not can_use_template(user, template):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Це середовище недоступне для вашої групи")
    sess = db.scalar(select(DesktopSession).where(
        DesktopSession.user_id == user.id, DesktopSession.template_id == template.id))
    driver = get_driver()

    if sess is not None and sess.status in (S_RUNNING, S_CREATING):
        sess.last_activity = utcnow()
        db.commit()
        return sess, False
    if sess is not None and sess.status == S_PAUSED:
        return resume_session(db, user, sess, request), False

    check_capacity(db, user)
    needs_provision = True
    if sess is None:
        sess = DesktopSession(user_id=user.id, template_id=template.id,
                              container_name=_new_container_name(user, template),
                              vnc_password=secrets.token_urlsafe(18), status=S_CREATING)
        db.add(sess)
        db.flush()
    elif sess.container_id and driver.status(sess.container_id) != "missing" and sess.status == S_STOPPED:
        try:
            driver.start(sess.container_id)
            _refresh_endpoint(sess)
            sess.status = S_RUNNING
            sess.started_at = utcnow()
            sess.error = ""
            needs_provision = False
        except DriverError as exc:
            log.warning("Не вдалося запустити існуючий контейнер, створюю новий: %s", exc)
    if needs_provision:
        sess.status = S_CREATING
        sess.error = ""
        sess.container_name = _new_container_name(user, template)
    sess.last_activity = utcnow()
    audit(db, "session_start", user, f"{template.name} (сесія {sess.id})", request)
    db.commit()
    return sess, needs_provision


def pause_session(db: Session, actor: User, sess: DesktopSession, request=None) -> DesktopSession:
    if sess.status != S_RUNNING:
        raise HTTPException(status.HTTP_409_CONFLICT, "Призупинити можна лише запущений стіл")
    _driver_call(get_driver().pause, sess)
    sess.status = S_PAUSED
    audit(db, "session_pause", actor, _describe(sess), request)
    db.commit()
    return sess


def resume_session(db: Session, actor: User, sess: DesktopSession, request=None) -> DesktopSession:
    if sess.status != S_PAUSED:
        raise HTTPException(status.HTTP_409_CONFLICT, "Стіл не на паузі")
    _driver_call(get_driver().unpause, sess)
    sess.status = S_RUNNING
    sess.last_activity = utcnow()
    audit(db, "session_resume", actor, _describe(sess), request)
    db.commit()
    return sess


def stop_session(db: Session, actor: User | None, sess: DesktopSession, request=None,
                 reason: str = "session_stop") -> DesktopSession:
    if sess.status in (S_STOPPED, S_ERROR):
        return sess
    if sess.container_id:
        try:
            get_driver().stop(sess.container_id)
        except DriverError as exc:
            log.warning("Помилка зупинки %s: %s", sess.container_name, exc)
    sess.status = S_STOPPED
    sess.host = sess.port = None
    audit(db, reason, actor, _describe(sess), request, username=None if actor else "system")
    db.commit()
    return sess


def reset_session(db: Session, actor: User, sess: DesktopSession, request=None) -> DesktopSession:
    """Скинути стіл до початкового стану: новий контейнер з образу, «Мої файли» лишаються."""
    if sess.status not in ACTIVE_STATES:
        check_capacity(db, sess.user)
    if sess.container_id:
        get_driver().remove(sess.container_id)
    sess.container_id = None
    sess.container_name = _new_container_name(sess.user, sess.template)
    sess.vnc_password = secrets.token_urlsafe(18)
    sess.status = S_CREATING
    sess.host = sess.port = None
    sess.error = ""
    sess.last_activity = utcnow()
    audit(db, "session_reset", actor, _describe(sess), request)
    db.commit()
    return sess


def delete_session(db: Session, actor: User, sess: DesktopSession, request=None) -> None:
    if sess.container_id:
        get_driver().remove(sess.container_id)
    audit(db, "session_delete", actor, _describe(sess), request)
    db.delete(sess)
    db.commit()


def sync_one(db: Session, sess: DesktopSession) -> DesktopSession:
    """Звірити стан одного столу з Docker (напр. контейнер несподівано завершився)."""
    if sess.status in (S_RUNNING, S_PAUSED) and sess.container_id:
        real = get_driver().status(sess.container_id)
        if real in ("stopped", "missing"):
            sess.status = S_STOPPED
            sess.host = sess.port = None
            sess.error = "Робочий стіл несподівано завершив роботу. Запустіть його знову або натисніть «Скинути»."
            if real == "missing":
                sess.container_id = None
            db.commit()
    return sess


def touch(db: Session, sess: DesktopSession, min_interval: int = 30) -> None:
    now = utcnow()
    if (now - sess.last_activity).total_seconds() >= min_interval:
        sess.last_activity = now
        db.commit()


def _driver_call(fn, sess: DesktopSession) -> None:
    if not sess.container_id:
        raise HTTPException(status.HTTP_409_CONFLICT, "Контейнер ще не створено")
    try:
        fn(sess.container_id)
    except DriverError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc


def _describe(sess: DesktopSession) -> str:
    return f"{sess.template.name} (сесія {sess.id}, студент {sess.user.username})"


# --- фонове обслуговування -------------------------------------------------------
def maintenance(db: Session) -> dict:
    """Автовимкнення при простої й узгодження стану БД із Docker. Викликається раз на хвилину."""
    now = utcnow()
    idle_cutoff = now - timedelta(minutes=get_setting(db, "idle_timeout_minutes"))
    driver = get_driver()
    result = {"idle_stopped": 0, "synced": 0, "failed": 0}
    sessions = db.scalars(select(DesktopSession).where(DesktopSession.status.in_(ACTIVE_STATES))).all()
    for sess in sessions:
        if sess.status == S_CREATING:
            if now - sess.last_activity > CREATING_TIMEOUT:
                sess.status = S_ERROR
                sess.error = "Перевищено час створення столу"
                result["failed"] += 1
            continue
        real = driver.status(sess.container_id) if sess.container_id else "missing"
        if real in ("stopped", "missing"):
            sess.status = S_STOPPED
            sess.host = sess.port = None
            if real == "missing":
                sess.container_id = None
            result["synced"] += 1
        elif sess.last_activity < idle_cutoff:
            stop_session(db, None, sess, reason="session_idle_stop")
            result["idle_stopped"] += 1
        elif real != sess.status:
            sess.status = real
            result["synced"] += 1
    db.commit()
    return result
