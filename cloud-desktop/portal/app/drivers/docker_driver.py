"""Драйвер, що керує контейнерами робочих столів через Docker API."""
from __future__ import annotations

import http.client
import logging
import ssl

from .base import DesktopDriver, DesktopSpec, DriverError, Endpoint

log = logging.getLogger("cloud_desktop.docker")

MANAGED_LABEL = "cloud-desktop.managed"


class DockerDriver(DesktopDriver):
    name = "docker"

    def __init__(self, network: str, desktop_port: int = 6901, bind_host: str = "127.0.0.1",
                 disk_size: str = "", client=None) -> None:
        if client is None:
            import docker  # імпорт тут, щоб fake-режим працював без пакета docker
            client = docker.from_env()
        self.client = client
        self.network = network
        self.desktop_port = desktop_port
        self.bind_host = bind_host
        self.disk_size = disk_size
        from docker import errors
        self._errors = errors

    # --- допоміжне -------------------------------------------------------
    def _container(self, cid: str):
        try:
            return self.client.containers.get(cid)
        except self._errors.NotFound:
            raise DriverError("Контейнер не знайдено") from None
        except self._errors.APIError as exc:
            raise DriverError(f"Помилка Docker: {exc.explanation or exc}") from exc

    def ensure_network(self) -> None:
        """Мережа для столів: контейнери не бачать один одного (ICC вимкнено), але мають інтернет."""
        try:
            self.client.networks.get(self.network)
        except self._errors.NotFound:
            log.info("Створюю мережу %s", self.network)
            self.client.networks.create(
                self.network, driver="bridge",
                options={"com.docker.network.bridge.enable_icc": "false"},
                labels={MANAGED_LABEL: "true"},
            )

    def ensure_image(self, image: str) -> None:
        try:
            self.client.images.get(image)
        except self._errors.ImageNotFound:
            log.info("Завантажую образ %s (може тривати кілька хвилин)", image)
            try:
                self.client.images.pull(image)
            except self._errors.APIError as exc:
                raise DriverError(f"Не вдалося завантажити образ {image}: {exc.explanation or exc}") from exc

    def build_create_kwargs(self, spec: DesktopSpec) -> dict:
        env = {"VNC_PW": spec.vnc_password, **spec.env}
        kwargs = dict(
            image=spec.image,
            name=spec.name,
            detach=True,
            environment=env,
            labels={MANAGED_LABEL: "true", **spec.labels},
            volumes={spec.files_host_path: {"bind": spec.files_container_path, "mode": "rw"}},
            # Порт столу доступний лише на localhost сервера; ззовні — тільки через Nginx порталу.
            ports={f"{self.desktop_port}/tcp": (self.bind_host, None)},
            network=self.network,
            mem_limit=f"{spec.memory_mb}m",
            memswap_limit=f"{spec.memory_mb}m",
            nano_cpus=int(spec.cpu * 1_000_000_000),
            shm_size=f"{spec.shm_mb}m",
            pids_limit=2048,
            security_opt=["no-new-privileges:true"],
            restart_policy={"Name": "no"},
            hostname="desktop",
        )
        if self.disk_size:
            kwargs["storage_opt"] = {"size": self.disk_size}
        return kwargs

    # --- інтерфейс драйвера ---------------------------------------------------
    def create(self, spec: DesktopSpec) -> str:
        self.ensure_network()
        self.ensure_image(spec.image)
        try:
            container = self.client.containers.create(**self.build_create_kwargs(spec))
        except self._errors.APIError as exc:
            raise DriverError(f"Не вдалося створити контейнер: {exc.explanation or exc}") from exc
        try:
            container.start()
        except self._errors.APIError as exc:
            container.remove(force=True)
            raise DriverError(f"Не вдалося запустити контейнер: {exc.explanation or exc}") from exc
        return container.id

    def start(self, cid: str) -> None:
        self._container(cid).start()

    def stop(self, cid: str) -> None:
        container = self._container(cid)
        if container.status == "paused":
            container.unpause()
        container.stop(timeout=10)

    def pause(self, cid: str) -> None:
        self._container(cid).pause()

    def unpause(self, cid: str) -> None:
        self._container(cid).unpause()

    def remove(self, cid: str) -> None:
        try:
            self.client.containers.get(cid).remove(force=True)
        except self._errors.NotFound:
            pass

    def status(self, cid: str) -> str:
        try:
            container = self.client.containers.get(cid)
        except self._errors.NotFound:
            return "missing"
        return {"running": "running", "paused": "paused", "restarting": "running"}.get(container.status, "stopped")

    def endpoint(self, cid: str) -> Endpoint:
        container = self._container(cid)
        container.reload()
        bindings = (container.attrs.get("NetworkSettings", {}).get("Ports") or {}).get(f"{self.desktop_port}/tcp")
        if not bindings:
            raise DriverError("Порт робочого столу не опубліковано")
        host = bindings[0].get("HostIp") or self.bind_host
        if host in ("0.0.0.0", "::"):
            host = "127.0.0.1"
        return Endpoint(host, int(bindings[0]["HostPort"]))

    def is_ready(self, cid: str) -> bool:
        if self.status(cid) != "running":
            return False
        # TCP-з'єднання приймає docker-proxy ще до старту KasmVNC, тому чекаємо на HTTP-відповідь
        # (401 без пароля — теж ознака, що сервер столу вже працює).
        try:
            ep = self.endpoint(cid)
            conn = http.client.HTTPSConnection(ep.host, ep.port, timeout=2,
                                               context=ssl._create_unverified_context())
            try:
                conn.request("GET", "/")
                return conn.getresponse().status < 500
            finally:
                conn.close()
        except (OSError, http.client.HTTPException, DriverError):
            return False

    def list_managed(self) -> list[str]:
        return [c.id for c in self.client.containers.list(all=True, filters={"label": f"{MANAGED_LABEL}=true"})]

    def server_stats(self) -> dict:
        info = self.client.info()
        return {"containers_running": info.get("ContainersRunning"), "images": info.get("Images"),
                "docker_version": info.get("ServerVersion")}
