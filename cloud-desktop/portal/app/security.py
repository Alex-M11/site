"""Хешування паролів (PBKDF2-SHA256) і JWT-токени."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from datetime import timedelta

import jwt

from .config import config

ALGO = "pbkdf2_sha256"


def hash_password(password: str, iterations: int | None = None) -> str:
    iterations = iterations or config.pbkdf2_iterations
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return "$".join([ALGO, str(iterations), base64.b64encode(salt).decode(), base64.b64encode(digest).decode()])


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iterations, salt_b64, digest_b64 = stored.split("$")
        if algo != ALGO:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt_b64), int(iterations))
        return hmac.compare_digest(digest, base64.b64decode(digest_b64))
    except (ValueError, TypeError):
        return False


def validate_password_strength(password: str) -> str | None:
    if len(password) < 8:
        return "Пароль має містити щонайменше 8 символів"
    if password.isdigit() or password.isalpha():
        return "Пароль має містити і літери, і цифри"
    return None


def create_token(user, method: str = "password") -> tuple[str, str, int]:
    """JWT для користувача. Повертає (токен, jti, час закінчення unix). method: password | oidc."""
    now = int(time.time())
    jti = secrets.token_hex(16)
    exp = now + config.token_ttl_minutes * 60
    payload = {"sub": str(user.id), "role": user.role, "ver": user.token_version or 0,
               "iat": now, "exp": exp, "jti": jti, "amr": method}
    return jwt.encode(payload, config.secret_key, algorithm="HS256"), jti, exp


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, config.secret_key, algorithms=["HS256"],
                          options={"require": ["sub", "exp", "jti"]})
    except jwt.PyJWTError:
        return None


_TEMP_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # без схожих l/1/O/0


def temp_password(length: int = 10) -> str:
    """Тимчасовий пароль, який легко продиктувати; завжди має і літери, і цифри."""
    while True:
        pw = "".join(secrets.choice(_TEMP_ALPHABET) for _ in range(length))
        if validate_password_strength(pw) is None and any(c.isdigit() for c in pw):
            return pw


# --- захист від перебору паролів -----------------------------------------------------
# Рахуємо невдалі спроби за журналом дій у БД, тому ліміт працює і з кількома процесами порталу.
MAX_FAILS_PER_USER_IP = 5      # з однієї адреси на один логін за вікно
MAX_FAILS_PER_USER = 20        # на один логін з будь-яких адрес (розподілений перебір)
FAIL_WINDOW = timedelta(minutes=5)


def login_blocked(db, username: str, ip: str) -> bool:
    from sqlalchemy import func, select

    from .models import AuditLog, utcnow
    since = utcnow() - FAIL_WINDOW
    last_ok = db.scalar(select(func.max(AuditLog.created_at)).where(
        AuditLog.username == username, AuditLog.action == "login", AuditLog.ip == ip))
    since_ip = max(since, last_ok) if last_ok else since
    per_ip = db.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.username == username, AuditLog.action == "login_failed",
        AuditLog.ip == ip, AuditLog.created_at > since_ip)) or 0
    if per_ip >= MAX_FAILS_PER_USER_IP:
        return True
    total = db.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.username == username, AuditLog.action == "login_failed", AuditLog.created_at > since)) or 0
    return total >= MAX_FAILS_PER_USER
