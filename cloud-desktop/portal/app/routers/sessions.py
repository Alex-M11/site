"""Керування робочими столами і перевірка доступу для Nginx-проксі."""
from __future__ import annotations

import base64
import re
from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import config
from ..db import get_db
from ..deps import current_user, must_change_now, user_from_request
from ..drivers import get_driver
from ..models import S_CREATING, S_RUNNING, DesktopSession, Template, User, utcnow
from ..serializers import session_out
from ..sessions_service import (
    can_manage_student, delete_session, get_session_for, pause_session, provision, reset_session, resume_session,
    start_session, stop_session, sync_one, touch,
)

router = APIRouter(tags=["sessions"])


class StartIn(BaseModel):
    template_id: int


@router.get("/api/sessions")
def my_sessions(user: User = Depends(current_user), db: Session = Depends(get_db)):
    q = select(DesktopSession).where(DesktopSession.user_id == user.id).order_by(DesktopSession.last_activity.desc())
    return [session_out(s) for s in db.scalars(q)]


@router.post("/api/sessions")
def start(data: StartIn, request: Request, background: BackgroundTasks,
          user: User = Depends(current_user), db: Session = Depends(get_db)):
    template = db.get(Template, data.template_id)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Середовище не знайдено")
    sess, needs_provision = start_session(db, user, template, request)
    if needs_provision:
        background.add_task(provision, sess.id)
    return session_out(sess)


HELPER_VISIBLE = timedelta(seconds=150)


@router.get("/api/sessions/{session_id}")
def get_one(session_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    sess = sync_one(db, get_session_for(db, user, session_id))
    data = session_out(sess)
    data["ready"] = bool(sess.status == S_RUNNING and sess.container_id and get_driver().is_ready(
        sess.container_id, (config.desktop_user, sess.vnc_password)))
    is_owner = sess.user_id == user.id
    data["viewer_url"] = viewer_url(sess, view_only=False, owner=is_owner)
    data["view_only_url"] = viewer_url(sess, view_only=True, owner=is_owner)
    data["is_owner"] = is_owner
    data["helper"] = helper_info(sess)
    return data


def viewer_url(sess: DesktopSession, view_only: bool = False, owner: bool = True) -> str:
    # Клієнт KasmVNC (форк noVNC) будує адресу WebSocket з параметра path від кореня сайту.
    prefix = f"desktop/{sess.id}{'-view' if view_only else ''}"
    extra = "&view_only=1" if view_only else ""
    # Лише власник підганяє роздільну здатність столу під своє вікно; викладач масштабує картинку в себе,
    # інакше в студента «стрибав» би екран.
    resize = "remote" if owner and not view_only else "scale"
    return f"/{prefix}/?autoconnect=1&resize={resize}&reconnect=1{extra}&path={prefix}/websockify"


def helper_info(sess: DesktopSession) -> dict | None:
    """Хто з викладачів зараз біля столу — студент має це бачити."""
    if sess.helper_seen_at and utcnow() - sess.helper_seen_at < HELPER_VISIBLE and sess.helper_name:
        return {"name": sess.helper_name, "mode": sess.helper_mode or "view"}
    return None


def mark_helper(sess: DesktopSession, user: User, mode: str) -> None:
    sess.helper_name = user.full_name or user.username
    sess.helper_mode = mode
    sess.helper_seen_at = utcnow()


class HeartbeatIn(BaseModel):
    mode: str = "control"   # для викладача: view | control


@router.post("/api/sessions/{session_id}/heartbeat")
def heartbeat(session_id: int, data: HeartbeatIn | None = None, user: User = Depends(current_user),
              db: Session = Depends(get_db)):
    """Вкладка зі столом повідомляє, що людина працює (автовимкнення при простої, попередження студенту)."""
    sess = get_session_for(db, user, session_id)
    if sess.user_id == user.id:
        touch(db, sess, min_interval=10)
    elif sess.status == S_RUNNING:
        mark_helper(sess, user, "control" if data and data.mode == "control" else "view")
        db.commit()
    return {"status": sess.status, "helper": helper_info(sess) if sess.user_id == user.id else None}


@router.post("/api/sessions/{session_id}/pause")
def pause(session_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return session_out(pause_session(db, user, get_session_for(db, user, session_id), request))


@router.post("/api/sessions/{session_id}/resume")
def resume(session_id: int, request: Request, background: BackgroundTasks,
           user: User = Depends(current_user), db: Session = Depends(get_db)):
    sess = get_session_for(db, user, session_id)
    if sess.status == "paused":
        return session_out(resume_session(db, user, sess, request))
    # Зупинений або з помилкою — запускаємо знову: ліміти й права рахуються для власника столу.
    sess, needs_provision = start_session(db, sess.user, sess.template, request, actor=user)
    if needs_provision:
        background.add_task(provision, sess.id)
    return session_out(sess)


@router.post("/api/sessions/{session_id}/stop")
def stop(session_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return session_out(stop_session(db, user, get_session_for(db, user, session_id), request))


@router.post("/api/sessions/{session_id}/reset")
def reset(session_id: int, request: Request, background: BackgroundTasks,
          user: User = Depends(current_user), db: Session = Depends(get_db)):
    sess = reset_session(db, user, get_session_for(db, user, session_id), request)
    background.add_task(provision, sess.id)
    return session_out(sess)


@router.delete("/api/sessions/{session_id}")
def delete(session_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    delete_session(db, user, get_session_for(db, user, session_id), request)
    return {"ok": True}


# --- auth_request для Nginx ------------------------------------------------------------
DESKTOP_URI = re.compile(r"^/desktop/(\d+)(-view)?(/|$)")


@router.get("/api/proxy/auth", include_in_schema=False)
def proxy_auth(request: Request, response: Response, db: Session = Depends(get_db)):
    """Nginx викликає цей endpoint перед кожним запитом до /desktop/<id>/.

    200 → у заголовках адреса контейнера і Basic-авторизація KasmVNC (пароль ніколи не потрапляє в браузер).
    401/403 → Nginx відмовляє у доступі.
    """
    match = DESKTOP_URI.match(request.headers.get("x-original-uri", ""))
    if not match:
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    user = user_from_request(request, db)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED)
    if must_change_now(request, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    sess = db.get(DesktopSession, int(match.group(1)))
    if sess is None or not can_manage_student(user, sess.user):
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    if sess.status != S_RUNNING or not sess.port:
        raise HTTPException(status.HTTP_409_CONFLICT if sess.status == S_CREATING else status.HTTP_403_FORBIDDEN)
    view_only = match.group(2) is not None
    if sess.user_id == user.id:
        touch(db, sess)
    elif "websockify" in request.headers.get("x-original-uri", ""):
        # Викладач/адмін підключився до чужого столу — фіксуємо в журналі, студент бачить попередження.
        mode = "view" if view_only else "control"
        mark_helper(sess, user, mode)
        audit(db, "session_connect_helper", user,
              f"до столу {sess.user.username} ({sess.template.name}), "
              f"{'перегляд' if view_only else 'керування'}", request)
        db.commit()
    # kasm_viewer — вбудований в образи Kasm користувач лише для перегляду (той самий пароль).
    vnc_user = config.desktop_viewer if view_only else config.desktop_user
    credentials = base64.b64encode(f"{vnc_user}:{sess.vnc_password}".encode()).decode()
    response.headers["X-Desktop-Upstream"] = f"{sess.host}:{sess.port}"
    response.headers["X-Desktop-Auth"] = f"Basic {credentials}"
    return {"ok": True}
