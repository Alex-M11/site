"""Налаштування, які адміністратор змінює з порталу (ліміти, каталог образів)."""
from __future__ import annotations

import json
from typing import Any

from sqlalchemy.orm import Session

from .config import config
from .models import Setting


def default_image_catalog() -> list[dict]:
    tag = config.image_tag
    catalog = [
        {"image": f"kasmweb/ubuntu-jammy-desktop:{tag}", "label": "Ubuntu 22.04 (робочий стіл)", "os": "ubuntu"},
        {"image": f"kasmweb/kali-rolling-desktop:{tag}", "label": "Kali Linux", "os": "kali"},
        {"image": f"kasmweb/vs-code:{tag}", "label": "VS Code", "os": "vscode"},
        {"image": "college/dev-desktop:latest", "label": "Програмування (VS Code, Python, C/C++, Node.js)", "os": "vscode"},
        {"image": "college/mysql-desktop:latest", "label": "Ubuntu + MySQL", "os": "mysql"},
    ]
    if config.standalone:   # образи college/* збираються на Linux-сервері
        catalog = [i for i in catalog if not i["image"].startswith("college/")]
    return catalog


DEFAULTS: dict[str, Any] = {
    "max_active_sessions": 20,        # усього на сервері (running + paused + creating)
    "max_sessions_per_user": 2,       # одночасно відкритих столів на студента
    "idle_timeout_minutes": 30,       # автовимкнення при простої
    "default_quota_mb": 2048,         # персональний диск студента
    "quota_hard_percent": 120,        # понад цей % квоти запущені столи зупиняються
    "max_container_disk_mb": 10240,   # скільки контейнер може записати поза «Моїми файлами»
    "max_cpu": 2.0,                   # максимум, який викладач може дати шаблону
    "max_memory_mb": 4096,
    "image_catalog": None,            # None → default_image_catalog()
    "check_images": ["python:3.12-slim", "gcc:14", "node:22-slim"],  # образи для автоперевірки
}

LIMITS = {
    "max_active_sessions": (1, 500),
    "max_sessions_per_user": (1, 10),
    "idle_timeout_minutes": (5, 24 * 60),
    "default_quota_mb": (100, 1024 * 1024),
    "quota_hard_percent": (100, 500),
    "max_container_disk_mb": (512, 1024 * 1024),
    "max_cpu": (0.25, 64),
    "max_memory_mb": (256, 256 * 1024),
}


def get_setting(db: Session, key: str) -> Any:
    row = db.get(Setting, key)
    if row is not None:
        return json.loads(row.value)
    if key == "image_catalog":
        return default_image_catalog()
    value = DEFAULTS[key]
    return list(value) if isinstance(value, list) else value


def all_settings(db: Session) -> dict[str, Any]:
    return {key: get_setting(db, key) for key in DEFAULTS}


def set_setting(db: Session, key: str, value: Any) -> None:
    if key not in DEFAULTS:
        raise KeyError(key)
    if key in LIMITS:
        lo, hi = LIMITS[key]
        cast = float if isinstance(DEFAULTS[key], float) else int
        value = cast(value)
        if not lo <= value <= hi:
            raise ValueError(f"{key}: значення має бути в межах {lo}…{hi}")
    if key == "check_images":
        if not isinstance(value, list) or not all(isinstance(i, str) and i.strip() for i in value):
            raise ValueError("check_images: потрібен список назв образів")
        value = [i.strip() for i in value]
    if key == "image_catalog":
        if not isinstance(value, list) or not all(isinstance(i, dict) and i.get("image") for i in value):
            raise ValueError("image_catalog: потрібен список об'єктів з полем image")
        value = [{"image": str(i["image"]), "label": str(i.get("label") or i["image"]),
                  "os": str(i.get("os") or "other")} for i in value]
    row = db.get(Setting, key)
    if row is None:
        db.add(Setting(key=key, value=json.dumps(value)))
    else:
        row.value = json.dumps(value)
