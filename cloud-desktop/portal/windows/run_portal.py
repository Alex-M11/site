"""Точка входу для PyInstaller (CloudDesktop.exe); можна запускати і як скрипт: python windows/run_portal.py"""
import multiprocessing
import sys
from pathlib import Path

if not getattr(sys, "frozen", False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # portal/ — щоб знайти пакет app

from app.launcher import main  # noqa: E402

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
