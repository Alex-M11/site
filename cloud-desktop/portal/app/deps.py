"""Залежності FastAPI: поточний користувач і перевірка ролей."""
from __future__ import annotations

from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from .db import get_db
from .models import ROLE_ADMIN, ROLE_TEACHER, User
from .security import decode_token

COOKIE_NAME = "cd_token"
CSRF_HEADER = "x-requested-with"
CSRF_VALUE = "cloud-desktop"


def token_from_request(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.cookies.get(COOKIE_NAME)


def user_from_request(request: Request, db: Session) -> User | None:
    token = token_from_request(request)
    if not token:
        return None
    payload = decode_token(token)
    if not payload:
        return None
    try:
        user = db.get(User, int(payload["sub"]))
    except (KeyError, ValueError):
        return None
    if user is None or not user.is_active:
        return None
    return user


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user = user_from_request(request, db)
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Потрібно увійти в систему")
    return user


def require_roles(*roles: str) -> Callable[..., User]:
    def checker(user: User = Depends(current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостатньо прав")
        return user
    return checker


require_teacher = require_roles(ROLE_TEACHER, ROLE_ADMIN)
require_admin = require_roles(ROLE_ADMIN)
