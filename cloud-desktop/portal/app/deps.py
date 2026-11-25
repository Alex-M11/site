"""Залежності FastAPI: поточний користувач і перевірка ролей."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .db import get_db
from .models import ROLE_ADMIN, ROLE_TEACHER, RevokedToken, User
from .security import decode_token

COOKIE_NAME = "cd_token"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "cloud-desktop"

# Поки користувач не змінив тимчасовий пароль, доступні лише ці адреси.
PASSWORD_CHANGE_ALLOWED = {"/api/auth/me", "/api/auth/password", "/api/auth/logout"}


def token_from_request(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(COOKIE_NAME)


def token_payload(request: Request) -> dict | None:
    token = token_from_request(request)
    return decode_token(token) if token else None


def user_from_request(request: Request, db: Session) -> User | None:
    """Користувач за токеном. Токен недійсний, якщо його відкликано (вихід) або змінилася
    версія токенів користувача (зміна пароля, ролі, вимкнення акаунта)."""
    payload = token_payload(request)
    if not payload:
        return None
    try:
        user = db.get(User, int(payload["sub"]))
    except (KeyError, ValueError):
        return None
    if user is None or not user.is_active:
        return None
    if int(payload.get("ver", 0)) != (user.token_version or 0):
        return None
    if db.get(RevokedToken, str(payload.get("jti", ""))) is not None:
        return None
    request.state.token = payload
    return user


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = user_from_request(request, db)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Потрібно увійти в систему")
    if must_change_now(request, user) and request.url.path not in PASSWORD_CHANGE_ALLOWED:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Спершу змініть тимчасовий пароль")
    return user


def must_change_now(request: Request, user: User) -> bool:
    """Тимчасовий пароль треба змінити — але не тим, хто увійшов через пошту коледжу (пароль їм не потрібен)."""
    payload = getattr(request.state, "token", None) or {}
    return bool(user.must_change_password) and payload.get("amr") != "oidc"


def require_roles(*roles: str) -> Callable[..., User]:
    def checker(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостатньо прав")
        return user
    return checker


require_teacher = require_roles(ROLE_TEACHER, ROLE_ADMIN)
require_admin = require_roles(ROLE_ADMIN)
