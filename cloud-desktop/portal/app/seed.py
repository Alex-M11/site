"""Початкові дані: адміністратор і (опційно) демо-набір для захисту й тестування."""
from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import config
from .models import ROLE_ADMIN, ROLE_STUDENT, ROLE_TEACHER, Assignment, Group, Template, User, utcnow
from .security import hash_password

log = logging.getLogger("cloud_desktop.seed")


def ensure_admin(db: Session) -> None:
    if db.scalar(select(User).where(User.role == ROLE_ADMIN)):
        return
    password = config.admin_password
    if not password:
        password = secrets.token_urlsafe(12)
        log.warning("Створено адміністратора %s з тимчасовим паролем: %s  (змініть його після входу!)",
                    config.admin_username, password)
    db.add(User(username=config.admin_username, full_name="Адміністратор", role=ROLE_ADMIN,
                password_hash=hash_password(password)))
    db.commit()


def seed_demo(db: Session) -> None:
    if db.scalar(select(Group).limit(1)):
        return
    tag = config.image_tag
    kn, kb = Group(name="КН-21", description="Комп'ютерні науки"), Group(name="КБ-22", description="Кібербезпека")
    db.add_all([kn, kb])
    teacher = User(username="teacher", full_name="Іваненко Олена Петрівна", role=ROLE_TEACHER,
                   password_hash=hash_password("Teacher123"), teaching=[kn, kb])
    db.add(teacher)
    students = [
        User(username="student1", full_name="Коваленко Андрій", group=kn),
        User(username="student2", full_name="Шевчук Марія", group=kn),
        User(username="student3", full_name="Бондар Олег", group=kb),
    ]
    for s in students:
        s.role, s.password_hash = ROLE_STUDENT, hash_password("Student123")
    db.add_all(students)
    templates = [
        Template(name="Ubuntu 22.04", subject="Операційні системи", os_family="ubuntu",
                 description="Чистий робочий стіл Ubuntu з терміналом, Firefox і офісним пакетом.",
                 image=f"kasmweb/ubuntu-jammy-desktop:{tag}", cpu=1, memory_mb=2048, groups=[kn, kb]),
        Template(name="Kali Linux — Мережі", subject="Комп'ютерні мережі", os_family="kali",
                 description="Kali Linux з nmap, Wireshark і Burp Suite. Скануйте лише навчальні цілі!",
                 image=f"kasmweb/kali-rolling-desktop:{tag}", cpu=2, memory_mb=3072, groups=[kb]),
        Template(name="Програмування", subject="Основи програмування", os_family="vscode",
                 description="VS Code для програмування." if config.standalone else "VS Code, Python 3, GCC, Node.js і Git.",
                 image=f"kasmweb/vs-code:{tag}" if config.standalone else "college/dev-desktop:latest",
                 cpu=1, memory_mb=2048, groups=[kn]),
    ]
    if not config.standalone:   # образ з MySQL збирається лише на Linux-сервері
        templates.append(Template(
            name="SQL", subject="Бази даних", os_family="mysql",
            description="Ubuntu з MySQL Server і DBeaver. Користувач MySQL: student / student.",
            image="college/mysql-desktop:latest", cpu=1, memory_mb=2048, groups=[kn, kb]))
    for t in templates:
        t.created_by = teacher
    db.add_all(templates)
    db.flush()
    db.add(Assignment(title="Лабораторна 1. SELECT і JOIN",
                      description="Створіть базу college, таблиці students і groups, напишіть 5 запитів. "
                                  "Здайте файл lab1.sql з папки «Мої файли».",
                      group=kn, template=templates[3] if len(templates) > 3 else None, teacher=teacher, due_at=utcnow() + timedelta(days=7)))
    db.add(Assignment(title="Лабораторна 1. Сканування мережі",
                      description="Проскануйте дозволений навчальний хост scanme.nmap.org за допомогою nmap "
                                  "(-sV, -O) і здайте звіт report.txt. Сканувати інші адреси заборонено.",
                      group=kb, template=templates[1], teacher=teacher, due_at=utcnow() + timedelta(days=10)))
    db.commit()
    log.info("Додано демо-дані: teacher/Teacher123, student1..3/Student123")
