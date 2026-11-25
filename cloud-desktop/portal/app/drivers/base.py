"""Інтерфейс драйвера робочих столів.

Портал не залежить від конкретної технології: зараз є Docker-драйвер (контейнери з KasmVNC)
і fake-драйвер для розробки. Пізніше можна додати драйвер для KVM/Proxmox (Windows).
"""
from __future__ import annotations

from dataclasses import dataclass, field


class DriverError(Exception):
    pass


@dataclass
class DesktopSpec:
    name: str
    image: str
    cpu: float
    memory_mb: int
    shm_mb: int
    vnc_password: str
    files_host_path: str
    files_container_path: str
    env: dict[str, str] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class Endpoint:
    host: str
    port: int


class DesktopDriver:
    name = "base"

    def create(self, spec: DesktopSpec) -> str:
        """Створити й запустити стіл. Повертає ідентифікатор контейнера."""
        raise NotImplementedError

    def start(self, container_id: str) -> None:
        raise NotImplementedError

    def stop(self, container_id: str) -> None:
        raise NotImplementedError

    def pause(self, container_id: str) -> None:
        raise NotImplementedError

    def unpause(self, container_id: str) -> None:
        raise NotImplementedError

    def remove(self, container_id: str) -> None:
        raise NotImplementedError

    def status(self, container_id: str) -> str:
        """running | paused | stopped | missing"""
        raise NotImplementedError

    def endpoint(self, container_id: str) -> Endpoint:
        raise NotImplementedError

    def is_ready(self, container_id: str) -> bool:
        """Чи вже відповідає сервер робочого столу всередині контейнера."""
        return self.status(container_id) == "running"

    def list_managed(self) -> list[str]:
        """Ідентифікатори всіх контейнерів, створених порталом."""
        return []
