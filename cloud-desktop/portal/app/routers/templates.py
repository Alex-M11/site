"""Каталог середовищ і шаблони, які створюють викладачі."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..db import get_db
from ..deps import current_user, require_teacher
from ..models import ROLE_ADMIN, DesktopSession, Group, Template, User
from ..serializers import session_out, template_out
from ..sessions_service import teacher_group_ids, visible_templates
from ..settings_store import get_setting

router = APIRouter(prefix="/api/templates", tags=["templates"])


class TemplateIn(BaseModel):
    name: str = Field(min_length=2, max_length=128)
    subject: str = Field(default="", max_length=128)
    description: str = Field(default="", max_length=5000)
    image: str = Field(min_length=1, max_length=255)
    cpu: float = Field(default=1.0, gt=0)
    memory_mb: int = Field(default=2048, ge=256)
    shm_mb: int = Field(default=512, ge=64, le=4096)
    env: dict[str, str] = Field(default_factory=dict)
    is_active: bool = True
    group_ids: list[int] = Field(default_factory=list)


@router.get("")
def list_templates(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Середовища, доступні користувачу, разом зі станом його столів."""
    sessions = {s.template_id: s for s in db.scalars(
        select(DesktopSession).where(DesktopSession.user_id == user.id))}
    result = []
    for t in visible_templates(db, user):
        item = template_out(t)
        s = sessions.get(t.id)
        item["session"] = session_out(s) if s else None
        result.append(item)
    return result


@router.get("/images")
def image_catalog(user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    return get_setting(db, "image_catalog")


def _apply(db: Session, user: User, t: Template, data: TemplateIn) -> None:
    catalog = {i["image"]: i for i in get_setting(db, "image_catalog")}
    if data.image not in catalog:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Образ не входить до дозволеного каталогу")
    max_cpu, max_mem = get_setting(db, "max_cpu"), get_setting(db, "max_memory_mb")
    if data.cpu > max_cpu or data.memory_mb > max_mem:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            f"Ліміти шаблону: до {max_cpu} CPU і {max_mem} МБ пам'яті")
    for key in data.env:
        if not key.replace("_", "").isalnum() or key.upper() == "VNC_PW":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Недопустима змінна оточення: {key}")
    groups = db.scalars(select(Group).where(Group.id.in_(data.group_ids))).all() if data.group_ids else []
    if len(groups) != len(set(data.group_ids)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Групу не знайдено")
    if user.role != ROLE_ADMIN:
        allowed = teacher_group_ids(user)
        old = {g.id for g in t.groups}
        # Викладач призначає шаблон лише своїм групам, але не чіпає чужі призначення.
        if any(g.id not in allowed and g.id not in old for g in groups):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Можна призначати лише свої групи")
        groups = list(groups) + [g for g in t.groups if g.id not in allowed and g not in groups]
    t.name, t.subject, t.description = data.name.strip(), data.subject.strip(), data.description
    t.image, t.os_family = data.image, catalog[data.image].get("os", "other")
    t.cpu, t.memory_mb, t.shm_mb = data.cpu, data.memory_mb, data.shm_mb
    t.env, t.is_active = dict(data.env), data.is_active
    t.groups = list(groups)


def _editable(db: Session, user: User, template_id: int) -> Template:
    t = db.get(Template, template_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Шаблон не знайдено")
    if user.role != ROLE_ADMIN and t.created_by_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Редагувати можна лише власні шаблони")
    return t


@router.get("/manage")
def manageable(user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    q = select(Template).order_by(Template.subject, Template.name)
    items = []
    for t in db.scalars(q):
        item = template_out(t)
        item["editable"] = user.role == ROLE_ADMIN or t.created_by_id == user.id
        items.append(item)
    return items


@router.post("", status_code=201)
def create_template(data: TemplateIn, request: Request, user: User = Depends(require_teacher),
                    db: Session = Depends(get_db)):
    t = Template(created_by_id=user.id, name="", image="")
    _apply(db, user, t, data)
    db.add(t)
    db.flush()
    audit(db, "template_create", user, f"{t.name} ({t.image})", request)
    db.commit()
    return template_out(t)


@router.put("/{template_id}")
def update_template(template_id: int, data: TemplateIn, request: Request,
                    user: User = Depends(require_teacher), db: Session = Depends(get_db)):
    t = _editable(db, user, template_id)
    _apply(db, user, t, data)
    audit(db, "template_update", user, t.name, request)
    db.commit()
    return template_out(t)


@router.delete("/{template_id}")
def delete_template(template_id: int, request: Request, user: User = Depends(require_teacher),
                    db: Session = Depends(get_db)):
    t = _editable(db, user, template_id)
    active = db.scalar(select(DesktopSession).where(DesktopSession.template_id == t.id))
    if active is not None:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            "У шаблону є столи студентів. Вимкніть його (is_active) або спершу видаліть столи.")
    audit(db, "template_delete", user, t.name, request)
    db.delete(t)
    db.commit()
    return {"ok": True}
