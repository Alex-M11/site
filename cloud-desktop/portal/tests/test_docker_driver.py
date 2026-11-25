"""Перевірка параметрів, з якими Docker-драйвер створює контейнери (без справжнього Docker)."""
from unittest import mock

import pytest

from app.drivers.base import DesktopSpec

docker = pytest.importorskip("docker")


def make_driver(**kw):
    from app.drivers.docker_driver import DockerDriver
    client = mock.MagicMock()
    return DockerDriver("cd_desktops", client=client, **kw), client


def spec():
    return DesktopSpec(name="cd-student1-t1-abc", image="kasmweb/ubuntu-jammy-desktop:1.17.0", cpu=1.5,
                       memory_mb=2048, shm_mb=512, vnc_password="pw", files_host_path="/srv/cd/home/student1",
                       files_container_path="/home/kasm-user/Мої_файли", env={"LAUNCH_URL": "https://x"},
                       labels={"cloud-desktop.user": "student1"})


def test_create_kwargs_limits_and_isolation():
    d, _ = make_driver()
    kw = d.build_create_kwargs(spec())
    assert kw["mem_limit"] == "2048m" and kw["memswap_limit"] == "2048m"
    assert kw["nano_cpus"] == 1_500_000_000
    assert kw["shm_size"] == "512m"
    assert kw["ports"] == {"6901/tcp": ("127.0.0.1", None)}  # порт лише на localhost
    assert kw["network"] == "cd_desktops"
    assert kw["environment"]["VNC_PW"] == "pw" and kw["environment"]["LAUNCH_URL"] == "https://x"
    assert kw["volumes"] == {"/srv/cd/home/student1": {"bind": "/home/kasm-user/Мої_файли", "mode": "rw"}}
    assert "no-new-privileges:true" in kw["security_opt"]
    assert kw["labels"]["cloud-desktop.managed"] == "true"
    assert "privileged" not in kw and "storage_opt" not in kw


def test_disk_size_option():
    d, _ = make_driver(disk_size="10G")
    assert d.build_create_kwargs(spec())["storage_opt"] == {"size": "10G"}


def test_network_created_without_icc():
    d, client = make_driver()
    client.networks.get.side_effect = docker.errors.NotFound("no")
    d.ensure_network()
    _, kwargs = client.networks.create.call_args
    assert kwargs["options"]["com.docker.network.bridge.enable_icc"] == "false"


def test_endpoint_reads_published_port():
    d, client = make_driver()
    container = client.containers.get.return_value
    container.attrs = {"NetworkSettings": {"Ports": {"6901/tcp": [{"HostIp": "127.0.0.1", "HostPort": "49153"}]}}}
    ep = d.endpoint("abc")
    assert (ep.host, ep.port) == ("127.0.0.1", 49153)


def test_failed_start_removes_container():
    from app.drivers.base import DriverError
    d, client = make_driver()
    created = client.containers.create.return_value
    created.start.side_effect = docker.errors.APIError("boom")
    with pytest.raises(DriverError):
        d.create(spec())
    created.remove.assert_called_once_with(force=True)


def test_status_mapping():
    d, client = make_driver()
    client.containers.get.return_value.status = "exited"
    assert d.status("x") == "stopped"
    client.containers.get.side_effect = docker.errors.NotFound("gone")
    assert d.status("x") == "missing"
