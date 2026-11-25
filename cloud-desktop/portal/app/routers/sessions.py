"""Керування робочими столами і перевірка доступу для Nginx-проксі."""
from __future__ import annotations

import base64
import re

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import config
from ..db import get_db
from ..deps import current_user, user_from_request
from ..drivers import get_driver
from ..models import ROLE_STUDENT, S_CREATING, S_RUNNING, DesktopSession, Template, User
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


@router.get("/api/sessions/{session_id}")
def get_one(session_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    sess = sync_one(db, get_session_for(db, user, session_id))
    data = session_out(sess)
    data["ready"] = bool(sess.status == S_RUNNING and sess.container_id and get_driver().is_ready(sess.container_id))
    data["viewer_url"] = viewer_url(sess)
    data["is_owner"] = sess.user_id == user.id
    return data


def viewer_url(sess: DesktopSession) -> str:
    # Клієнт KasmVNC (форк noVNC) будує адресу WebSocket з параметра path від кореня сайту.
    return f"/desktop/{sess.id}/?autoconnect=1&resize=remote&reconnect=1&path=desktop/{sess.id}/websockify"


@router.post("/api/sessions/{session_id}/heartbeat")
def heartbeat(session_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Вкладка зі столом повідомляє, що студент працює (для автовимкнення при простої)."""
    sess = get_session_for(db, user, session_id)
    if sess.user_id == user.id:
        touch(db, sess, min_interval=10)
    return {"status": sess.status}


@router.post("/api/sessions/{session_id}/pause")
def pause(session_id: int, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return session_out(pause_session(db, user, get_session_for(db, user, session_id), request))


@router.post("/api/sessions/{session_id}/resume")
def resume(session_id: int, request: Request, background: BackgroundTasks,
           user: User = Depends(current_user), db: Session = Depends(get_db)):
    sess = get_session_for(db, user, session_id)
    if sess.status == "paused":
        return session_out(resume_session(db, user, sess, request))
    # Зупинений або з помилкою — запускаємо знову від імені власника столу.
    sess, needs_provision = start_session(db, sess.user, sess.template, request)
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
DESKTOP_URI = re.compile(r"^/desktop/(\d+)(/|$)")


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
    sess = db.get(DesktopSession, int(match.group(1)))
    if sess is None or not can_manage_student(user, sess.user):
        raise HTTPException(status.HTTP_403_FORBIDDEN)
    if sess.status != S_RUNNING or not sess.port:
        raise HTTPException(status.HTTP_409_CONFLICT if sess.status == S_CREATING else status.HTTP_403_FORBIDDEN)
    if sess.user_id == user.id:
        touch(db, sess)
    elif user.role != ROLE_STUDENT and request.headers.get("x-original-uri", "").find("websockify") != -1:
        # Викладач/адмін підключився до чужого столу — це фіксуємо в журналі.
        audit(db, "session_connect_helper", user, f"до столу {sess.user.username} ({sess.template.name})", request)
        db.commit()
    credentials = base64.b64encode(f"{config.desktop_user}:{sess.vnc_password}".encode()).decode()
    response.headers["X-Desktop-Upstream"] = f"{sess.host}:{sess.port}"
    response.headers["X-Desktop-Auth"] = f"Basic {credentials}"
    return {"ok": True}
