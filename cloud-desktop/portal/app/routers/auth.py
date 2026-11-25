"""Вхід (логін/пароль або пошта коледжу через OpenID Connect), вихід, зміна пароля."""
from __future__ import annotations

import secrets
from datetime import datetime, timezone
from urllib.parse import quote

import httpx

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import oidc
from ..audit import audit, client_ip
from ..config import config
from ..db import get_db
from ..deps import COOKIE_NAME, current_user, must_change_now
from ..models import ROLE_STUDENT, RevokedToken, User, utcnow
from ..security import (
    create_token, hash_password, login_blocked, validate_password_strength, verify_password,
)
from ..quota import state as quota_state
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
    username = data.username.strip().lower()[:64]
    if login_blocked(db, username, client_ip(request)):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Забагато спроб входу. Зачекайте 5 хвилин.")
    user = db.scalar(select(User).where(User.username == username))
    if user is None:
        _DUMMY_HASH = _DUMMY_HASH or hash_password("dummy-password")
        verify_password(data.password, _DUMMY_HASH)
    if user is None or not user.is_active or not verify_password(data.password, user.password_hash):
        audit(db, "login_failed", None, "", request, username=username)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Невірний логін або пароль")
    user.last_login = utcnow()
    audit(db, "login", user, "", request)
    db.commit()
    issue_cookie(response, user)
    # Токен не повертаємо в JSON: він живе лише в HttpOnly-cookie, недоступному для JavaScript.
    return {"user": user_out(user, full=True)}


def issue_cookie(response: Response, user: User, method: str = "password") -> None:
    token, _jti, _exp = create_token(user, method)
    response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax", secure=config.cookie_secure,
                        max_age=config.token_ttl_minutes * 60, path="/")


def revoke_current_token(db: Session, request: Request) -> None:
    payload = getattr(request.state, "token", None)
    if payload and payload.get("jti") and db.get(RevokedToken, payload["jti"]) is None:
        db.add(RevokedToken(jti=payload["jti"],
                            expires_at=datetime.fromtimestamp(payload["exp"], timezone.utc).replace(tzinfo=None)))


@router.post("/logout")
def logout(request: Request, response: Response, user: User = Depends(current_user),
           db: Session = Depends(get_db)):
    revoke_current_token(db, request)
    audit(db, "logout", user, "", request)
    db.commit()
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/me")
def me(request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    data = user_out(user, full=True)
    data["must_change_password"] = must_change_now(request, user)
    data["login_method"] = (getattr(request.state, "token", None) or {}).get("amr", "password")
    data["quota"] = quota_state(db, user)
    return data


# --- вхід через пошту коледжу (OpenID Connect) -------------------------------------------
OIDC_COOKIE = "cd_oidc"


def _redirect_uri(request: Request) -> str:
    base = config.public_url or str(request.base_url).rstrip("/")
    return f"{base}/api/auth/oidc/callback"


def _login_error(message: str) -> RedirectResponse:
    resp = RedirectResponse("/?login_error=" + quote(message), status_code=302)
    resp.delete_cookie(OIDC_COOKIE, path="/api/auth/oidc")
    return resp


@router.get("/oidc/config")
def oidc_config():
    return {"enabled": oidc.enabled(), "label": config.oidc_label}


@router.get("/oidc/login")
def oidc_login(request: Request):
    if not oidc.enabled():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Вхід через пошту не налаштовано")
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    verifier, challenge = oidc.pkce_pair()
    try:
        url = oidc.authorization_url(_redirect_uri(request), state, nonce, challenge)
    except httpx.HTTPError:
        return _login_error("Провайдер входу недоступний. Спробуйте пізніше або увійдіть з паролем.")
    resp = RedirectResponse(url, status_code=302)
    resp.set_cookie(OIDC_COOKIE, oidc.make_state_cookie(state, nonce, verifier), max_age=600, httponly=True,
                    samesite="lax", secure=config.cookie_secure, path="/api/auth/oidc")
    return resp


@router.get("/oidc/callback")
def oidc_callback(request: Request, code: str = "", state: str = "", error: str = "",
                  db: Session = Depends(get_db)):
    if error:
        return _login_error("Вхід скасовано.")
    try:
        saved = oidc.read_state_cookie(request.cookies.get(OIDC_COOKIE))
        if not code or not secrets.compare_digest(state, saved["state"]):
            raise oidc.OIDCError("Некоректна відповідь провайдера входу (state).")
        tokens = oidc.exchange_code(code, _redirect_uri(request), saved["pkce"])
        claims = oidc.verify_id_token(tokens.get("id_token", ""), saved["nonce"])
        email = oidc.email_from_claims(claims)
        user = db.scalar(select(User).where(func.lower(User.email) == email))
        if user is None and config.oidc_auto_create and config.oidc_allowed_domains:
            username = oidc.username_from_email(
                email, lambda n: db.scalar(select(User.id).where(User.username == n)) is not None)
            user = User(username=username, email=email, full_name=str(claims.get("name") or "")[:128],
                        role=ROLE_STUDENT, password_hash="!oidc")   # пароль не задано — вхід лише через пошту
            db.add(user)
            db.flush()
            audit(db, "user_create", None, f"{username} (перший вхід через пошту {email})", request,
                  username="system")
        if user is None:
            raise oidc.OIDCError(f"Акаунт для {email} не знайдено. Зверніться до адміністратора.")
        if not user.is_active:
            raise oidc.OIDCError("Акаунт вимкнено. Зверніться до адміністратора.")
    except oidc.OIDCError as exc:
        audit(db, "login_failed", None, f"OIDC: {exc}", request, username="oidc")
        db.commit()
        return _login_error(str(exc))
    except httpx.HTTPError:
        return _login_error("Провайдер входу недоступний. Спробуйте пізніше.")
    user.last_login = utcnow()
    audit(db, "login", user, f"через пошту {email}", request)
    db.commit()
    resp = RedirectResponse("/", status_code=302)
    resp.delete_cookie(OIDC_COOKIE, path="/api/auth/oidc")
    issue_cookie(resp, user, method="oidc")
    return resp


@router.post("/password")
def change_password(data: PasswordIn, request: Request, response: Response, user: User = Depends(current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(data.old_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Старий пароль невірний")
    problem = validate_password_strength(data.new_password)
    if problem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, problem)
    if data.new_password == data.old_password:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Новий пароль має відрізнятися від старого")
    user.password_hash = hash_password(data.new_password)
    user.must_change_password = False
    # Усі інші входи (інші браузери, загублений телефон) стають недійсними; поточний — оновлюємо.
    user.token_version = (user.token_version or 0) + 1
    audit(db, "password_change", user, "", request)
    db.commit()
    issue_cookie(response, user)
    return {"ok": True, "user": user_out(user, full=True)}
