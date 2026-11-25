"""Персональне сховище файлів студентів і здані роботи.

Структура на диску сервера:
    <storage_root>/home/<username>/            — «Мої файли», монтується в кожен стіл студента
    <storage_root>/submissions/<assignment>/<username>/ — копії зданих файлів
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path, PurePosixPath

from .config import config

USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{1,62}$")


class StorageError(Exception):
    pass


def _chown(path: Path) -> None:
    """Файли мають належати користувачу всередині столу (uid 1000), інакше він не зможе їх змінити."""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        try:
            os.chown(path, config.desktop_uid, config.desktop_uid)
        except OSError:
            pass


def _check_username(username: str) -> str:
    if not USERNAME_RE.match(username):
        raise StorageError("Некоректне ім'я користувача")
    return username


def home_dir(username: str, create: bool = True) -> Path:
    path = config.storage_root / "home" / _check_username(username)
    if create and not path.exists():
        path.mkdir(parents=True, exist_ok=True)
        _chown(path)
        _chown(path.parent)
    return path


def host_home_dir(username: str) -> str:
    """Шлях до папки студента так, як його бачить Docker-демон на хості."""
    home_dir(username)
    return str(PurePosixPath(config.host_storage_root) / "home" / _check_username(username))


def safe_path(base: Path, rel: str) -> Path:
    """Перетворити відносний шлях від клієнта на абсолютний усередині base (захист від ../)."""
    rel = (rel or "").replace("\\", "/").strip("/")
    target = (base / rel).resolve()
    base_resolved = base.resolve()
    if target != base_resolved and base_resolved not in target.parents:
        raise StorageError("Недопустимий шлях")
    return target


def dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).lstat().st_size
            except OSError:
                pass
    return total


def list_dir(base: Path, rel: str) -> list[dict]:
    target = safe_path(base, rel)
    if not target.is_dir():
        raise StorageError("Папку не знайдено")
    items = []
    for entry in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if entry.is_symlink():
            continue
        stat = entry.stat()
        items.append({
            "name": entry.name,
            "path": str(entry.relative_to(base.resolve())),
            "is_dir": entry.is_dir(),
            "size": stat.st_size if entry.is_file() else None,
            "modified": stat.st_mtime,
        })
    return items


def clean_name(name: str) -> str:
    name = os.path.basename((name or "").replace("\\", "/")).strip()
    if name in {"", ".", ".."} or "\x00" in name:
        raise StorageError("Некоректна назва файлу")
    return name[:200]


def make_dir(base: Path, rel: str, name: str) -> Path:
    parent = safe_path(base, rel)
    if not parent.is_dir():
        raise StorageError("Папку не знайдено")
    target = parent / clean_name(name)
    target.mkdir(exist_ok=False)
    _chown(target)
    return target


def write_upload(base: Path, rel: str, filename: str, stream, quota_bytes: int) -> Path:
    parent = safe_path(base, rel)
    if not parent.is_dir():
        raise StorageError("Папку не знайдено")
    target = parent / clean_name(filename)
    if target.is_dir():
        raise StorageError("Папка з такою назвою вже існує")
    used = dir_size(base) - (target.stat().st_size if target.exists() else 0)
    limit = min(quota_bytes - used, config.max_upload_mb * 1024 * 1024)
    tmp = target.with_name(f".upload-{os.getpid()}-{target.name}")
    written = 0
    try:
        with open(tmp, "wb") as out:
            while chunk := stream.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    raise StorageError("Перевищено ліміт диска або максимальний розмір файлу")
                out.write(chunk)
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()
    _chown(target)
    return target


def delete_path(base: Path, rel: str) -> None:
    target = safe_path(base, rel)
    if target == base.resolve():
        raise StorageError("Не можна видалити кореневу папку")
    if target.is_dir():
        shutil.rmtree(target)
    elif target.exists():
        target.unlink()
    else:
        raise StorageError("Файл не знайдено")


def _skip_symlinks(directory: str, names: list[str]) -> list[str]:
    return [n for n in names if os.path.islink(os.path.join(directory, n))]


def submission_dir(assignment_id: int, username: str) -> Path:
    return config.storage_root / "submissions" / str(int(assignment_id)) / _check_username(username)


def host_submission_dir(assignment_id: int, username: str) -> str:
    return str(PurePosixPath(config.host_storage_root) / "submissions" / str(int(assignment_id))
               / _check_username(username))


def copy_submission(username: str, assignment_id: int, rel_paths: list[str]) -> list[str]:
    """Скопіювати вибрані файли з «Моїх файлів» у здачу. Повертає список імен."""
    base = home_dir(username)
    dest = submission_dir(assignment_id, username)
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    copied: list[str] = []
    total = 0
    for rel in rel_paths:
        src = safe_path(base, rel)
        if not src.exists() or src.is_symlink():
            raise StorageError(f"Файл не знайдено: {rel}")
        name = src.name
        i = 1
        while (dest / name).exists():
            name = f"{src.stem}-{i}{src.suffix}"
            i += 1
        if src.is_dir():
            total += dir_size(src)
            if total > config.max_upload_mb * 1024 * 1024:
                raise StorageError("Робота завелика")
            # Символьні посилання пропускаємо: студент міг створити у столі посилання
            # на чужі файли, а портал бачить усе сховище.
            shutil.copytree(src, dest / name, ignore=_skip_symlinks)
            archive = shutil.make_archive(str(dest / name), "zip", root_dir=dest / name)
            shutil.rmtree(dest / name)
            name = Path(archive).name
        else:
            total += src.stat().st_size
            if total > config.max_upload_mb * 1024 * 1024:
                raise StorageError("Робота завелика")
            shutil.copy2(src, dest / name)
        copied.append(name)
    return copied
