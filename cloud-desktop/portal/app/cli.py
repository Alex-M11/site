"""Службові команди для адміністратора сервера.

    docker compose exec portal python -m app.cli reset-password admin
    docker compose exec portal python -m app.cli create-admin новий.адмін
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from .config import config
from . import db as db_module
from .db import create_schema, db_session, init_engine
from .models import ROLE_ADMIN, User
from .security import hash_password, temp_password
from .storage import USERNAME_RE


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="Службові команди порталу")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("reset-password", help="видати тимчасовий пароль (і розблокувати акаунт)")
    p.add_argument("username")
    p = sub.add_parser("create-admin", help="створити ще одного адміністратора")
    p.add_argument("username")
    args = parser.parse_args(argv)

    if db_module.engine is None:        # окремий процес: під'єднатися до БД з налаштувань
        init_engine(config.database_url)
        create_schema()
    username = args.username.strip().lower()
    with db_session() as db:
        user = db.scalar(select(User).where(User.username == username))
        if args.cmd == "create-admin":
            if user is not None:
                print(f"Користувач {username} уже існує", file=sys.stderr)
                return 1
            if not USERNAME_RE.match(username):
                print("Некоректний логін", file=sys.stderr)
                return 1
            user = User(username=username, full_name="Адміністратор", role=ROLE_ADMIN, password_hash="")
            db.add(user)
        elif user is None:
            print(f"Користувача {username} не знайдено", file=sys.stderr)
            return 1
        password = temp_password(12)
        user.password_hash = hash_password(password)
        user.must_change_password = True
        user.is_active = True
        user.token_version = (user.token_version or 0) + 1
        db.commit()
    print(f"Логін: {username}\nТимчасовий пароль: {password}\n(змініть його після входу)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
