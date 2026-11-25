"""Персональне сховище «Мої файли»: ті самі файли видно всередині кожного столу студента."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..audit import audit
from ..config import config
from ..db import get_db
from ..deps import current_user
from ..models import User
from ..quota import measure, quota_bytes, state as quota_state
from ..storage import (
    StorageError, delete_path, dir_size, home_dir, list_dir, make_dir, move_path, read_text, safe_path,
    write_text, write_upload,
)

router = APIRouter(prefix="/api/files", tags=["files"])


class MkdirIn(BaseModel):
    path: str = ""
    name: str


class TextIn(BaseModel):
    path: str
    content: str = ""


class MoveIn(BaseModel):
    path: str
    to: str


def _err(exc: Exception) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))


@router.get("")
def listing(path: str = "", user: User = Depends(current_user), db: Session = Depends(get_db)):
    base = home_dir(user.username)
    try:
        items = list_dir(base, path)
    except StorageError as exc:
        raise _err(exc) from exc
    used = dir_size(base)
    user.disk_used_bytes = used
    db.commit()
    return {"path": path.strip("/"), "items": items, "used": used, "quota": quota_bytes(db, user),
            "quota_state": quota_state(db, user, used), "desktop_path": config.container_files_path}


@router.post("/upload")
def upload(request: Request, path: str = Form(""), file: UploadFile = File(...),
           user: User = Depends(current_user), db: Session = Depends(get_db)):
    base = home_dir(user.username)
    try:
        target = write_upload(base, path, file.filename or "", file.file, quota_bytes(db, user))
    except StorageError as exc:
        raise _err(exc) from exc
    audit(db, "file_upload", user, str(target.relative_to(base.resolve())), request)
    measure(user)
    db.commit()
    return {"ok": True}


@router.post("/mkdir")
def mkdir(data: MkdirIn, user: User = Depends(current_user)):
    try:
        make_dir(home_dir(user.username), data.path, data.name)
    except FileExistsError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "Така папка вже існує") from exc
    except StorageError as exc:
        raise _err(exc) from exc
    return {"ok": True}


@router.get("/download")
def download(path: str, user: User = Depends(current_user)):
    try:
        target = safe_path(home_dir(user.username), path)
    except StorageError as exc:
        raise _err(exc) from exc
    if not target.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Файл не знайдено")
    return FileResponse(target, filename=target.name)


@router.delete("")
def remove(path: str, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    try:
        delete_path(home_dir(user.username), path)
    except StorageError as exc:
        raise _err(exc) from exc
    audit(db, "file_delete", user, path, request)
    measure(user)
    db.commit()
    return {"ok": True}


@router.get("/content")
def get_text(path: str, user: User = Depends(current_user)):
    """Вміст текстового файлу (для редактора в демо-столі)."""
    try:
        return {"path": path.strip("/"), "content": read_text(home_dir(user.username), path)}
    except StorageError as exc:
        raise _err(exc) from exc


@router.put("/content")
def put_text(data: TextIn, request: Request, user: User = Depends(current_user), db: Session = Depends(get_db)):
    base = home_dir(user.username)
    try:
        target = write_text(base, data.path, data.content, quota_bytes(db, user))
    except StorageError as exc:
        raise _err(exc) from exc
    audit(db, "file_save", user, str(target.relative_to(base.resolve())), request)
    measure(user)
    db.commit()
    return {"ok": True}


@router.post("/move")
def move(data: MoveIn, user: User = Depends(current_user)):
    try:
        target = move_path(home_dir(user.username), data.path, data.to)
    except StorageError as exc:
        raise _err(exc) from exc
    return {"ok": True, "path": str(target.relative_to(home_dir(user.username).resolve()))}
