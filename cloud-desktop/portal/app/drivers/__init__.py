from __future__ import annotations

from ..config import config
from .base import DesktopDriver, DesktopSpec, DriverError, Endpoint

_driver: DesktopDriver | None = None


def get_driver() -> DesktopDriver:
    global _driver
    if _driver is None:
        if config.driver == "docker":
            from .docker_driver import DockerDriver
            _driver = DockerDriver(config.desktop_network, config.desktop_port,
                                   config.desktop_bind_host, config.container_disk_size)
        elif config.driver == "fake":
            from .fake_driver import FakeDriver
            _driver = FakeDriver()
        else:
            raise RuntimeError(f"Невідомий драйвер: {config.driver}")
    return _driver


def set_driver(driver: DesktopDriver | None) -> None:
    global _driver
    _driver = driver


__all__ = ["DesktopDriver", "DesktopSpec", "DriverError", "Endpoint", "get_driver", "set_driver"]
