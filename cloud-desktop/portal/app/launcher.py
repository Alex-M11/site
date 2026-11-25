"""Запускач автономної версії (Windows .exe): портал на цьому ПК, без Nginx і MySQL.

* Дані — у %LOCALAPPDATA%\\CloudDesktop (Windows) або ~/.local/share/cloud-desktop.
* Є Docker Desktop → справжні робочі столи (портал сам проксіює KasmVNC).
  Немає → демо-режим: портал працює повністю, а замість столу — заглушка.
* Вікно з адресою, логінами і кнопками; закриття вікна зупиняє портал і запущені столи.

Параметри: --demo (не використовувати Docker), --port N, --no-browser, --console (без вікна).
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

APP_NAME = "Хмарний робочий стіл"


def data_dir() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
        return base / "CloudDesktop"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "cloud-desktop"


def read_or_create(path: Path, factory) -> str:
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    value = factory()
    path.write_text(value, encoding="utf-8")
    return value


def docker_available() -> tuple[bool, str]:
    try:
        import docker
        client = docker.from_env(timeout=5)
        client.ping()
        if client.info().get("OSType") != "linux":
            # Docker Desktop у режимі Windows-контейнерів: образи столів (Linux) не запустяться.
            return False, "Docker працює з Windows-контейнерами — перемкніть на Linux-контейнери"
        return True, f"Docker {client.version().get('Version', '')}"
    except Exception:  # noqa: BLE001 — будь-яка причина = Docker недоступний
        return False, "Docker Desktop не знайдено або не запущено"


def free_port(preferred: int) -> int:
    for port in [preferred, *range(preferred + 1, preferred + 50)]:
        with socket.socket() as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise SystemExit("Немає вільного порту для порталу")


def prepare_environment(args) -> dict:
    root = data_dir()
    root.mkdir(parents=True, exist_ok=True)
    (root / "storage").mkdir(exist_ok=True)
    secret = read_or_create(root / "secret.key", lambda: secrets.token_urlsafe(48))
    admin_pw = read_or_create(root / "admin-password.txt",
                              lambda: "Adm" + secrets.token_hex(4) + "7")
    use_docker, docker_info = (False, "Docker вимкнено параметром --demo") if args.demo else docker_available()
    env = {
        "CD_DATABASE_URL": "sqlite:///" + (root / "portal.db").as_posix(),
        "CD_STORAGE_ROOT": str(root / "storage"),
        "CD_HOST_STORAGE_ROOT": str(root / "storage"),
        "CD_SECRET_KEY": secret,
        "CD_DRIVER": "docker" if use_docker else "fake",
        "CD_BUILTIN_PROXY": "1",
        "CD_STANDALONE": "1",
        "CD_DEMO_SEED": "1",
        "CD_ADMIN_USERNAME": "admin",
        "CD_ADMIN_PASSWORD": admin_pw,
        "CD_COOKIE_SECURE": "0",
        "CD_API_DOCS": "0",
        "CD_PBKDF2_ITERATIONS": "200000",
    }
    for key, value in env.items():
        os.environ.setdefault(key, value)
    return {"root": root, "admin_pw": admin_pw, "docker": use_docker, "docker_info": docker_info}


class PortalServer:
    def __init__(self, port: int):
        import uvicorn

        from app.main import app   # імпорт після налаштування оточення
        self.config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", lifespan="on")
        self.server = uvicorn.Server(self.config)
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def start(self) -> bool:
        self.thread.start()
        for _ in range(300):
            if self.server.started:
                return True
            if not self.thread.is_alive():
                return False
            time.sleep(0.1)
        return False

    def stop(self) -> None:
        stop_all_desktops()
        self.server.should_exit = True
        self.thread.join(timeout=15)


def stop_all_desktops() -> int:
    """Щоб столи не займали пам'ять ПК після закриття програми (файли зберігаються)."""
    try:
        from sqlalchemy import select

        from app.db import db_session
        from app.models import ACTIVE_STATES, DesktopSession
        from app.sessions_service import stop_session
        with db_session() as db:
            sessions = db.scalars(select(DesktopSession).where(DesktopSession.status.in_(ACTIVE_STATES))).all()
            for sess in sessions:
                stop_session(db, None, sess, reason="session_stop_on_exit")
            return len(sessions)
    except Exception:  # noqa: BLE001 — при виході не падаємо
        return 0


def make_icon(size: int = 64):
    """Значок програми (малюється в коді — без окремих файлів): синій квадрат із білою хмарою."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = size // 5
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=(37, 99, 235, 255))
    w = (255, 255, 255, 255)
    s = size / 64
    d.ellipse([14 * s, 26 * s, 34 * s, 46 * s], fill=w)
    d.ellipse([24 * s, 16 * s, 46 * s, 38 * s], fill=w)
    d.ellipse([36 * s, 26 * s, 52 * s, 44 * s], fill=w)
    d.rectangle([22 * s, 34 * s, 46 * s, 46 * s], fill=w)
    return img


def write_credentials(url: str, info: dict) -> Path:
    path = info["root"] / "Логіни і паролі.txt"
    lines = [APP_NAME, "", f"Адреса порталу: {url}",
             "Режим: " + ("справжні робочі столи (Docker)" if info["docker"]
                          else f"демо — {info['docker_info']}. Щоб запускати справжні Ubuntu і Kali, встановіть "
                               "і запустіть Docker Desktop (WSL 2, Linux-контейнери), потім перезапустіть програму."), ""]
    lines += [f"{role:<22} {login:<10} {pw or info['admin_pw']}" for role, login, pw in ACCOUNTS]
    lines += ["", "Пароль адміністратора змініть у порталі: Профіль → Змінити пароль.",
              f"Дані порталу: {info['root']}"]
    path.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8-sig")   # BOM — щоб Блокнот показав кирилицю
    return path


def open_path(path: Path) -> None:
    if os.name == "nt":
        os.startfile(path)  # noqa: S606 — Провідник / Блокнот
    else:
        webbrowser.open(path.as_uri())


def message_box(text: str, error: bool = False) -> None:
    """Вікно повідомлення Windows (у .exe немає консолі, куди писати)."""
    if os.name == "nt":
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, APP_NAME, 0x10 if error else 0x40)
    else:
        print(text, file=sys.stderr if error else sys.stdout)


def run_tray(url: str, info: dict, server: PortalServer) -> None:
    import pystray

    def quit_app(icon, _item):
        icon.title = "Зупиняю портал і робочі столи…"
        server.stop()
        icon.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Відкрити портал", lambda *_: webbrowser.open(url), default=True),
        pystray.MenuItem("Логіни і паролі", lambda *_: open_path(info["credentials"])),
        pystray.MenuItem("Папка з даними", lambda *_: open_path(info["root"])),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Режим: " + ("Docker — справжні столи" if info["docker"] else "демо (без Docker)"),
                         None, enabled=False),
        pystray.MenuItem("Зупинити й вийти", quit_app),
    )
    # Linux-бекенд (Xlib) не вміє кирилицю в підказці; у Windows — Unicode API.
    title = f"{APP_NAME} — {url}" if os.name == "nt" else f"Cloud Desktop - {url}"
    icon = pystray.Icon("CloudDesktop", make_icon(64), title, menu)

    def setup(i):
        i.visible = True
        try:
            i.notify("Портал працює. Клацніть значок, щоб відкрити його в браузері.", APP_NAME)
        except Exception:  # noqa: BLE001 — сповіщення є не в усіх системах
            pass
    icon.run(setup=setup)


def instance_file() -> Path:
    return data_dir() / "instance.json"


def running_instance() -> str | None:
    """Якщо портал уже запущено (подвійний клік ще раз) — повернути його адресу."""
    try:
        port = json.loads(instance_file().read_text(encoding="utf-8"))["port"]
        with socket.create_connection(("127.0.0.1", int(port)), timeout=2) as conn:
            conn.sendall(b"GET /healthz HTTP/1.0\r\nHost: localhost\r\n\r\n")
            data = b""
            while chunk := conn.recv(4096):    # заголовки й тіло можуть прийти окремо
                data += chunk
            if b'"ok":true' in data:
                return f"http://127.0.0.1:{port}/"
    except (OSError, ValueError, KeyError):
        pass
    return None


ACCOUNTS = [("Адміністратор", "admin", None), ("Викладач", "teacher", "Teacher123"),
            ("Студент", "student1", "Student123"), ("Студент (інша група)", "student3", "Student123")]


def run_window(url: str, info: dict, server: PortalServer) -> None:
    import tkinter as tk
    from tkinter import ttk

    win = tk.Tk()
    win.title(APP_NAME)
    win.geometry("560x470")
    win.minsize(520, 440)
    frm = ttk.Frame(win, padding=18)
    frm.pack(fill="both", expand=True)
    ttk.Label(frm, text="☁ " + APP_NAME, font=("Segoe UI", 16, "bold")).pack(anchor="w")
    ttk.Label(frm, text=f"Портал працює: {url}", font=("Segoe UI", 10)).pack(anchor="w", pady=(6, 0))
    mode = (f"Режим: справжні робочі столи ({info['docker_info']})" if info["docker"] else
            f"Режим: демо ({info['docker_info']}) — замість столів заглушка")
    ttk.Label(frm, text=mode, foreground="#12a150" if info["docker"] else "#c27c0e").pack(anchor="w", pady=(2, 10))
    if info["docker"]:
        ttk.Label(frm, wraplength=510, foreground="#667085",
                  text="Перший запуск кожного середовища завантажує образ (3–6 ГБ) — це може тривати кілька хвилин."
                  ).pack(anchor="w", pady=(0, 8))
    else:
        ttk.Label(frm, wraplength=510, foreground="#667085",
                  text="Щоб запускати справжні Ubuntu і Kali, встановіть Docker Desktop (з WSL 2), запустіть його "
                       "і перезапустіть цю програму.").pack(anchor="w", pady=(0, 8))

    table = ttk.Treeview(frm, columns=("role", "login", "password"), show="headings", height=4)
    for col, title, width in (("role", "Роль", 170), ("login", "Логін", 120), ("password", "Пароль", 160)):
        table.heading(col, text=title)
        table.column(col, width=width, anchor="w")
    for role, login, pw in ACCOUNTS:
        table.insert("", "end", values=(role, login, pw or info["admin_pw"]))
    table.pack(fill="x")
    ttk.Label(frm, foreground="#667085", wraplength=510,
              text=f"Дані: {info['root']}").pack(anchor="w", pady=(8, 10))

    btns = ttk.Frame(frm)
    btns.pack(fill="x", pady=(4, 0))
    ttk.Button(btns, text="Відкрити портал", command=lambda: webbrowser.open(url)).pack(side="left")
    ttk.Button(btns, text="Папка з даними", command=lambda: open_path(info["root"])).pack(side="left", padx=8)
    status = ttk.Label(frm, text="", foreground="#667085")
    status.pack(anchor="w", pady=(10, 0))

    def quit_app():
        status.config(text="Зупиняю портал і робочі столи…")
        win.update()
        server.stop()
        win.destroy()

    ttk.Button(btns, text="Зупинити й вийти", command=quit_app).pack(side="right")
    win.protocol("WM_DELETE_WINDOW", quit_app)
    win.mainloop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="CloudDesktop", description=APP_NAME)
    parser.add_argument("--demo", action="store_true", help="не використовувати Docker (заглушка замість столів)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--console", action="store_true", help="без вікна, лише текст у консолі")
    args = parser.parse_args(argv)

    if sys.stdout is None or sys.stderr is None:
        # .exe без консолі: логи — у файл поруч із даними (стане в пригоді, якщо щось не запуститься).
        data_dir().mkdir(parents=True, exist_ok=True)
        log = open(data_dir() / "portal.log", "a", encoding="utf-8", buffering=1)  # noqa: SIM115
        sys.stdout = sys.stderr = log
    existing = running_instance()
    if existing:
        if not args.no_browser:
            webbrowser.open(existing)
        print(f"Портал уже запущено: {existing}")
        return 0
    info = prepare_environment(args)
    port = free_port(args.port)
    url = f"http://127.0.0.1:{port}/"
    try:
        server = PortalServer(port)
        started = server.start()
    except Exception as exc:  # noqa: BLE001
        started, server = False, None
        print(f"Помилка запуску: {exc!r}", file=sys.stderr)
    if not started:
        message_box(f"Не вдалося запустити портал.\nПодробиці: {data_dir() / 'portal.log'}", error=True)
        return 1
    instance_file().write_text(json.dumps({"port": port, "pid": os.getpid()}), encoding="utf-8")
    info["credentials"] = write_credentials(url, info)
    print(f"{APP_NAME}: {url}  ({'Docker' if info['docker'] else 'демо-режим'})")
    print(f"Адміністратор: admin / {info['admin_pw']}   Викладач: teacher / Teacher123   Студент: student1 / Student123")
    if not args.no_browser:
        webbrowser.open(url)

    if not args.console:
        # Windows: значок у треї; інші системи: вікно Tkinter. Не вийшло — консоль.
        # (Xlib-трей без панелі завдань зависає, тому поза Windows — лише вікно.)
        runners = [run_tray, run_window] if os.name == "nt" else [run_window]
        for runner in runners:
            try:
                runner(url, info, server)
                instance_file().unlink(missing_ok=True)
                return 0
            except Exception as exc:  # noqa: BLE001 — немає графіки або бібліотеки → наступний варіант
                print(f"{runner.__name__} недоступний: {exc!r}")
    print("Натисніть Ctrl+C, щоб зупинити.")
    try:
        while server.thread.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    server.stop()
    instance_file().unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
