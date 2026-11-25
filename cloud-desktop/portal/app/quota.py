"""Контроль місця на диску.

* «Мої_файли» студента: портал рахує розмір у фоні. Понад квоту — попередження, не можна завантажувати
  файли й запускати нові столи. Понад жорстку межу (квота × quota_hard_percent) — запущені столи
  зупиняються (файли залишаються), поки студент не звільнить місце.
* Сам контейнер (усе поза «Моїми_файлами»): понад max_container_disk_mb стіл зупиняється, а наступний
  запуск створює його заново.

Жорстко заборонити запис на рівні файлової системи можна квотами XFS (див. docs/admin-guide.md).
"""
from __future__ import annotations

from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .config import config
from .models import User, utcnow
from .settings_store import get_setting
from .storage import dir_size

MB = 1024 * 1024
CHECK_INTERVAL = timedelta(minutes=5)


def quota_bytes(db: Session, user: User) -> int:
    return (user.quota_mb or get_setting(db, "default_quota_mb")) * MB


def hard_limit_bytes(db: Session, user: User) -> int:
    return quota_bytes(db, user) * get_setting(db, "quota_hard_percent") // 100


def measure(user: User) -> int:
    home = config.storage_root / "home" / user.username
    used = dir_size(home) if home.exists() else 0
    user.disk_used_bytes = used
    user.disk_checked_at = utcnow()
    return used


def needs_measure(user: User) -> bool:
    return user.disk_checked_at is None or utcnow() - user.disk_checked_at > CHECK_INTERVAL


def state(db: Session, user: User, used: int | None = None) -> dict:
    used = user.disk_used_bytes if used is None else used
    used = used or 0
    quota = quota_bytes(db, user)
    level = "ok"
    if used > hard_limit_bytes(db, user):
        level = "blocked"
    elif used > quota:
        level = "over"
    elif used > quota * 0.9:
        level = "warn"
    return {"used": used, "quota": quota, "hard_limit": hard_limit_bytes(db, user), "level": level}


def ensure_can_start(db: Session, user: User) -> None:
    """Перед запуском столу: рахуємо місце заново й не пускаємо, якщо квоту перевищено."""
    used = measure(user)
    if used > quota_bytes(db, user):
        raise HTTPException(
            status.HTTP_507_INSUFFICIENT_STORAGE,
            f"Папка «Мої файли» займає {used / MB:.0f} МБ при квоті {quota_bytes(db, user) / MB:.0f} МБ. "
            "Видаліть зайве в розділі «Мої файли» і запустіть стіл знову.")
