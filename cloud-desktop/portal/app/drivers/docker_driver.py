"""Драйвер, що керує контейнерами робочих столів через Docker API."""
from __future__ import annotations

import base64
import http.client
import logging
import ssl
import time

from requests.exceptions import ConnectionError as RequestsConnectionError
from requests.exceptions import ReadTimeout

from .base import CheckResult, CheckSpec, DesktopDriver, DesktopSpec, DriverError, Endpoint

log = logging.getLogger("cloud_desktop.docker")

MANAGED_LABEL = "cloud-desktop.managed"
CHECK_LABEL = "cloud-desktop.check"
BRIDGE_NAME = "cd-desktops"
MAX_CHECK_OUTPUT = 20_000


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
            # Ім'я мосту має збігатися з scripts/firewall.sh, інакше правила iptables не діятимуть.
            self.client.networks.create(
                self.network, driver="bridge",
                options={"com.docker.network.bridge.enable_icc": "false",
                         "com.docker.network.bridge.name": BRIDGE_NAME},
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
                log.error("Образ %s не вдалося завантажити: %s", image, exc.explanation or exc)
                raise DriverError(
                    f"Середовище «{image}» ще не встановлено на сервері. Повідомте викладача або адміністратора "
                    "(адміністратору: scripts/build-images.sh або docker pull).") from exc

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

    def _call(self, what: str, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except self._errors.APIError as exc:
            raise DriverError(f"{what}: {exc.explanation or exc}") from exc

    def start(self, cid: str) -> None:
        self._call("Не вдалося запустити стіл", self._container(cid).start)

    def stop(self, cid: str) -> None:
        container = self._container(cid)
        if container.status == "paused":
            self._call("Не вдалося зняти стіл з паузи", container.unpause)
        self._call("Не вдалося зупинити стіл", container.stop, timeout=10)

    def pause(self, cid: str) -> None:
        container = self._container(cid)
        # cgroup freezer іноді не встигає «заморозити» процеси, що саме стартують — пробуємо ще раз.
        for attempt in range(3):
            try:
                container.pause()
                return
            except self._errors.APIError as exc:
                if attempt == 2:
                    raise DriverError("Не вдалося призупинити стіл (система зайнята). Спробуйте ще раз "
                                      f"за кілька секунд. ({exc.explanation or exc})") from exc
                time.sleep(1.5)

    def unpause(self, cid: str) -> None:
        self._call("Не вдалося зняти стіл з паузи", self._container(cid).unpause)

    def remove(self, cid: str) -> None:
        try:
            self.client.containers.get(cid).remove(force=True)
        except self._errors.NotFound:
            pass
        except self._errors.APIError as exc:
            raise DriverError(f"Не вдалося видалити контейнер: {exc.explanation or exc}") from exc

    def status(self, cid: str) -> str:
        try:
            container = self.client.containers.get(cid)
        except self._errors.NotFound:
            return "missing"
        except self._errors.APIError as exc:
            log.warning("Docker не відповів про стан %s: %s", cid[:12], exc)
            return "unknown"
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

    def is_ready(self, cid: str, auth: tuple[str, str] | None = None) -> bool:
        # TCP-з'єднання приймає docker-proxy ще до старту KasmVNC, тому чекаємо на HTTP-відповідь.
        # Обов'язково з паролем: анонімні запити KasmVNC вважає перебором і блокує адресу Nginx.
        if self.status(cid) != "running":
            return False
        try:
            ep = self.endpoint(cid)
            conn = http.client.HTTPSConnection(ep.host, ep.port, timeout=2,
                                               context=ssl._create_unverified_context())
            headers = {}
            if auth:
                headers["Authorization"] = "Basic " + base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
            try:
                conn.request("GET", "/", headers=headers)
                return conn.getresponse().status < 400
            finally:
                conn.close()
        except (OSError, http.client.HTTPException, DriverError):
            return False

    def build_check_kwargs(self, spec: CheckSpec) -> dict:
        return dict(
            image=spec.image,
            command=["sh", "-c", spec.script],
            detach=True,
            working_dir="/work",
            volumes={spec.work_host_path: {"bind": "/work", "mode": "ro"}},
            environment={"WORK": "/work", "HOME": "/tmp"},
            network_disabled=True,            # перевірка не має доступу до мережі
            read_only=True,                   # і не може змінити ні образ, ні здані файли
            tmpfs={"/tmp": "size=64m"},
            mem_limit=f"{spec.memory_mb}m",
            memswap_limit=f"{spec.memory_mb}m",
            nano_cpus=int(spec.cpu * 1_000_000_000),
            pids_limit=128,
            user="1000:1000",
            cap_drop=["ALL"],
            security_opt=["no-new-privileges:true"],
            labels={CHECK_LABEL: "true"},
        )

    def run_check(self, spec: CheckSpec) -> CheckResult:
        self.ensure_image(spec.image)
        container = self.client.containers.create(**self.build_check_kwargs(spec))
        timed_out = False
        try:
            container.start()
            try:
                exit_code = container.wait(timeout=spec.timeout).get("StatusCode")
            except (ReadTimeout, RequestsConnectionError):   # перевищено ліміт часу
                timed_out, exit_code = True, None
                container.kill()
            output = container.logs(stdout=True, stderr=True)[-MAX_CHECK_OUTPUT:].decode(errors="replace")
        except self._errors.APIError as exc:
            raise DriverError(f"Не вдалося виконати перевірку: {exc.explanation or exc}") from exc
        finally:
            try:
                container.remove(force=True)
            except self._errors.APIError:
                pass
        return CheckResult(exit_code, output, timed_out)

    def disk_usage(self, cid: str) -> int | None:
        try:
            rows = self.client.api.containers(all=True, size=True, filters={"id": cid})
        except self._errors.APIError:
            return None
        return int(rows[0].get("SizeRw") or 0) if rows else None

    def list_managed(self) -> list[str]:
        return [c.id for c in self.client.containers.list(all=True, filters={"label": f"{MANAGED_LABEL}=true"})]

    def server_stats(self) -> dict:
        info = self.client.info()
        return {"containers_running": info.get("ContainersRunning"), "images": info.get("Images"),
                "docker_version": info.get("ServerVersion")}
