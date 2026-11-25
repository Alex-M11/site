"""Конфігурація порталу. Усі значення беруться зі змінних оточення з префіксом CD_."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def _bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


@dataclass
class Config:
    database_url: str = field(default_factory=lambda: os.environ.get(
        "CD_DATABASE_URL", "sqlite:///./data/portal.db"))
    secret_key: str = field(default_factory=lambda: os.environ.get("CD_SECRET_KEY", ""))
    # docker — справжні контейнери; fake — імітація для розробки й тестів без Docker.
    driver: str = field(default_factory=lambda: os.environ.get("CD_DRIVER", "fake"))
    # Де портал бачить файли студентів.
    storage_root: Path = field(default_factory=lambda: Path(
        os.environ.get("CD_STORAGE_ROOT", "./data/storage")).resolve())
    # Той самий каталог, але як його бачить Docker на хості (для bind mount).
    host_storage_root: str = field(default_factory=lambda: os.environ.get("CD_HOST_STORAGE_ROOT", ""))
    desktop_network: str = field(default_factory=lambda: os.environ.get("CD_DESKTOP_NETWORK", "cd_desktops"))
    desktop_port: int = field(default_factory=lambda: _int("CD_DESKTOP_PORT", 6901))
    desktop_user: str = field(default_factory=lambda: os.environ.get("CD_DESKTOP_USER", "kasm_user"))
    desktop_uid: int = field(default_factory=lambda: _int("CD_DESKTOP_UID", 1000))
    container_files_path: str = field(default_factory=lambda: os.environ.get(
        "CD_CONTAINER_FILES_PATH", "/home/kasm-user/Мої_файли"))
    # Адреса, на якій портал (і nginx) бачать опубліковані порти столів.
    desktop_bind_host: str = field(default_factory=lambda: os.environ.get("CD_DESKTOP_BIND_HOST", "127.0.0.1"))
    # Опційно: розмір диска контейнера (працює лише з overlay2 на XFS з pquota), напр. "10G".
    container_disk_size: str = field(default_factory=lambda: os.environ.get("CD_CONTAINER_DISK_SIZE", ""))
    token_ttl_minutes: int = field(default_factory=lambda: _int("CD_TOKEN_TTL_MINUTES", 480))
    cookie_secure: bool = field(default_factory=lambda: _bool("CD_COOKIE_SECURE", False))
    pbkdf2_iterations: int = field(default_factory=lambda: _int("CD_PBKDF2_ITERATIONS", 390_000))
    admin_username: str = field(default_factory=lambda: os.environ.get("CD_ADMIN_USERNAME", "admin"))
    admin_password: str = field(default_factory=lambda: os.environ.get("CD_ADMIN_PASSWORD", ""))
    demo_seed: bool = field(default_factory=lambda: _bool("CD_DEMO_SEED", False))
    image_tag: str = field(default_factory=lambda: os.environ.get("CD_KASM_TAG", "1.17.0"))
    idle_check_seconds: int = field(default_factory=lambda: _int("CD_IDLE_CHECK_SECONDS", 60))
    background_tasks: bool = field(default_factory=lambda: _bool("CD_BACKGROUND_TASKS", True))
    max_upload_mb: int = field(default_factory=lambda: _int("CD_MAX_UPLOAD_MB", 200))

    def __post_init__(self) -> None:
        if not self.host_storage_root:
            self.host_storage_root = str(self.storage_root)
        if not self.secret_key:
            # Для розробки генеруємо ключ на один запуск. У продакшені його треба задати.
            self.secret_key = secrets.token_urlsafe(48)
            self.secret_key_generated = True
        else:
            self.secret_key_generated = False


config = Config()


def reload_config() -> Config:
    """Перечитати оточення (використовується в тестах)."""
    new = Config()
    config.__dict__.update(new.__dict__)
    return config
