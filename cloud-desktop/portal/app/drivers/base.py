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
class CheckSpec:
    """Автоперевірка роботи: скрипт у чистому контейнері, здані файли — у /work (лише читання)."""
    image: str
    script: str
    work_host_path: str
    timeout: int = 60
    memory_mb: int = 512
    cpu: float = 1.0


@dataclass
class CheckResult:
    exit_code: int | None
    output: str
    timed_out: bool = False


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
        """running | paused | stopped | missing | unknown (Docker тимчасово не відповів)"""
        raise NotImplementedError

    def endpoint(self, container_id: str) -> Endpoint:
        raise NotImplementedError

    def is_ready(self, container_id: str, auth: tuple[str, str] | None = None) -> bool:
        """Чи вже відповідає сервер робочого столу всередині контейнера.

        auth — логін і пароль KasmVNC. Без них KasmVNC рахує перевірку невдалою спробою входу і
        після кількох таких спроб блокує адресу, з якої приходять усі підключення (Nginx)."""
        return self.status(container_id) == "running"

    def run_check(self, spec: CheckSpec) -> CheckResult:
        raise NotImplementedError

    def disk_usage(self, container_id: str) -> int | None:
        """Скільки байтів контейнер записав у свій шар (поза змонтованими папками)."""
        return None

    def list_managed(self) -> list[str]:
        """Ідентифікатори всіх контейнерів, створених порталом."""
        return []
