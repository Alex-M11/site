"""Хешування паролів (PBKDF2-SHA256) і JWT-токени."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque
from datetime import timedelta
from threading import Lock

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


def create_token(user_id: int, role: str) -> str:
    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": int(time.time()),
        "exp": int(time.time()) + config.token_ttl_minutes * 60,
        "jti": secrets.token_hex(8),
    }
    return jwt.encode(payload, config.secret_key, algorithm="HS256")


def decode_token(token: str) -> dict | None:
    try:
        return jwt.decode(token, config.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None


class LoginRateLimiter:
    """Простий захист від перебору паролів: не більше N невдалих спроб за вікно."""

    def __init__(self, max_attempts: int = 5, window: timedelta = timedelta(minutes=5)):
        self.max_attempts = max_attempts
        self.window = window.total_seconds()
        self._attempts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._attempts[key]
        while q and now - q[0] > self.window:
            q.popleft()
        return q

    def is_blocked(self, key: str) -> bool:
        with self._lock:
            return len(self._prune(key, time.monotonic())) >= self.max_attempts

    def fail(self, key: str) -> None:
        with self._lock:
            now = time.monotonic()
            self._prune(key, now).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._attempts.pop(key, None)


login_limiter = LoginRateLimiter()
