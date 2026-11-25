"""Запис подій у журнал дій."""
from __future__ import annotations

import logging

from fastapi import Request
from sqlalchemy.orm import Session

from .config import config
from .models import AuditLog, User

log = logging.getLogger("cloud_desktop.audit")


def client_ip(request: Request | None) -> str:
    if request is None:
        return ""
    peer = request.client.host if request.client else ""
    # Заголовкам з адресою клієнта віримо лише від нашого Nginx (CD_TRUSTED_PROXIES).
    if peer in config.trusted_proxies:
        forwarded = request.headers.get("x-real-ip") or request.headers.get("x-forwarded-for", "").split(",")[0]
        if forwarded.strip():
            return forwarded.strip()[:64]
    return peer


def audit(db: Session, action: str, user: User | None = None, details: str = "",
          request: Request | None = None, username: str | None = None) -> None:
    entry = AuditLog(
        user_id=user.id if user else None,
        username=username or (user.username if user else ""),
        action=action,
        details=details[:2000],
        ip=client_ip(request),
    )
    db.add(entry)
    log.info("%s %s %s", entry.username or "-", action, details)
