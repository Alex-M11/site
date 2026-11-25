"""Вхід, вихід, зміна пароля.

Вхід зроблено окремим модулем, щоб пізніше замінити логін/пароль на корпоративний вхід коледжу
(OAuth2/OpenID Connect через Google Workspace або Microsoft 365): треба лише видати той самий cookie.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit, client_ip
from ..config import config
from ..db import get_db
from ..deps import COOKIE_NAME, current_user
from ..models import User, utcnow
from ..security import (
    create_token, hash_password, login_limiter, validate_password_strength, verify_password,
)
from ..serializers import user_out

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Хеш для вирівнювання часу відповіді, коли користувача не існує.
_DUMMY_HASH: str | None = None


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class PasswordIn(BaseModel):
    old_password: str
    new_password: str = Field(max_length=256)


@router.post("/login")
def login(data: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)):
    global _DUMMY_HASH
    username = data.username.strip().lower()
    key = f"{username}|{client_ip(request)}"
    if login_limiter.is_blocked(key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Забагато спроб входу. Зачекайте 5 хвилин.")
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        _DUMMY_HASH = _DUMMY_HASH or hash_password("dummy-password")
        verify_password(data.password, _DUMMY_HASH)
    if user is None or not user.is_active or not verify_password(data.password, user.password_hash):
        login_limiter.fail(key)
        audit(db, "login_failed", None, "", request, username=username)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Невірний логін або пароль")
    login_limiter.reset(key)
    user.last_login = utcnow()
    audit(db, "login", user, "", request)
    db.commit()
    token = create_token(user.id, user.role)
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax", secure=config.cookie_secure,
                        max_age=config.token_ttl_minutes * 60, path="/")
    return {"user": user_out(user), "token": token}


@router.post("/logout")
def logout(request: Request, response: Response, user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    audit(db, "logout", user, "", request)
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(user: User = Depends(current_user)):
    return user_out(user, full=True)


@router.post("/password")
def change_password(data: PasswordIn, request: Request, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(data.old_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Старий пароль невірний")
    problem = validate_password_strength(data.new_password)
    if problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)
    user.password_hash = hash_password(data.new_password)
    audit(db, "password_change", user, "", request)
    db.commit()
    return {"ok": True}
