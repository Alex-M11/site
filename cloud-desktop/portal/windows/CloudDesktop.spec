# -*- mode: python ; coding: utf-8 -*-
# Збірка: cd portal && pyinstaller windows/CloudDesktop.spec   (на Windows — див. windows/README.md)
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).parent          # portal/
APP = ROOT / "app"

hidden = (collect_submodules("app") + collect_submodules("uvicorn") + collect_submodules("alembic")
          + collect_submodules("websockets") + ["sqlalchemy.dialects.sqlite", "multipart", "python_multipart"])

a = Analysis(
    [str(ROOT / "windows" / "run_portal.py")],
    pathex=[str(ROOT)],
    datas=[(str(APP / "static"), "app/static"),
           (str(APP / "migrations"), "app/migrations")],   # Alembic читає міграції як файли
    hiddenimports=hidden,
    excludes=["pytest", "pymysql", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="CloudDesktop",
    icon=str(ROOT / "windows" / "cloud.ico") if (ROOT / "windows" / "cloud.ico").exists() else None,
    console=False,          # лише вікно запускача; логи — у %LOCALAPPDATA%\CloudDesktop\portal.log
    upx=False,
    version=str(ROOT / "windows" / "version.txt") if (ROOT / "windows" / "version.txt").exists() else None,
)
