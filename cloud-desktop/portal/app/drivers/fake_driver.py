"""Імітація Docker для розробки інтерфейсу й автотестів (CD_DRIVER=fake)."""
from __future__ import annotations

import itertools
import threading

import os
import subprocess

from .base import CheckResult, CheckSpec, DesktopDriver, DesktopSpec, DriverError, Endpoint


class FakeDriver(DesktopDriver):
    name = "fake"

    def __init__(self) -> None:
        self.containers: dict[str, dict] = {}
        self._ids = itertools.count(1)
        self._ports = itertools.count(20000)
        self._lock = threading.Lock()
        self.fail_next_create = False

    def create(self, spec: DesktopSpec) -> str:
        with self._lock:
            if self.fail_next_create:
                self.fail_next_create = False
                raise DriverError("Імітована помилка створення контейнера")
            cid = f"fake{next(self._ids):06d}"
            self.containers[cid] = {"spec": spec, "status": "running", "port": next(self._ports)}
            return cid

    def _get(self, cid: str) -> dict:
        try:
            return self.containers[cid]
        except KeyError:
            raise DriverError("Контейнер не знайдено") from None

    def start(self, cid: str) -> None:
        self._get(cid)["status"] = "running"

    def stop(self, cid: str) -> None:
        self._get(cid)["status"] = "stopped"

    def pause(self, cid: str) -> None:
        self._get(cid)["status"] = "paused"

    def unpause(self, cid: str) -> None:
        self._get(cid)["status"] = "running"

    def remove(self, cid: str) -> None:
        self.containers.pop(cid, None)

    def status(self, cid: str) -> str:
        c = self.containers.get(cid)
        return c["status"] if c else "missing"

    def is_ready(self, cid: str, auth: tuple[str, str] | None = None) -> bool:
        return self.status(cid) == "running"

    def endpoint(self, cid: str) -> Endpoint:
        return Endpoint("127.0.0.1", self._get(cid)["port"])

    def run_check(self, spec: CheckSpec) -> CheckResult:
        """Лише для розробки й тестів: скрипт виконується локально без ізоляції."""
        env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "WORK": spec.work_host_path, "HOME": "/tmp"}
        try:
            proc = subprocess.run(["sh", "-c", spec.script], cwd=spec.work_host_path, env=env, timeout=spec.timeout,
                                  capture_output=True, text=True)
        except subprocess.TimeoutExpired as exc:
            out = (exc.stdout or b"").decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            return CheckResult(None, out, timed_out=True)
        return CheckResult(proc.returncode, proc.stdout + proc.stderr)

    def disk_usage(self, cid: str) -> int | None:
        c = self.containers.get(cid)
        return c.get("disk", 0) if c else None

    def list_managed(self) -> list[str]:
        return list(self.containers)
