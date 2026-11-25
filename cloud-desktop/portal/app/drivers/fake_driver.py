"""Імітація Docker для розробки інтерфейсу й автотестів (CD_DRIVER=fake)."""
from __future__ import annotations

import itertools
import threading

from .base import DesktopDriver, DesktopSpec, DriverError, Endpoint


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

    def endpoint(self, cid: str) -> Endpoint:
        return Endpoint("127.0.0.1", self._get(cid)["port"])

    def list_managed(self) -> list[str]:
        return list(self.containers)
