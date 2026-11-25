#!/usr/bin/env python3
"""Тест навантаження (тиждень 7): N студентів одночасно запускають робочі столи.

Скрипт створює тестових студентів (loadtest01…), запускає їм столи паралельно, вимірює час
до готовності й пам'ять сервера, а в кінці видаляє столи. Запускати на самому сервері:

    python3 scripts/loadtest.py --url https://desk.college.edu.ua --admin admin --password '...' \
        --students 20 --template "Ubuntu 22.04"

Перед тестом тимчасово підніміть ліміт «Максимум активних столів» в адмінці.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import statistics
import time

import httpx

H = {"X-Requested-With": "cloud-desktop"}
PASSWORD = "Loadtest2026x"


def mem_available() -> int | None:
    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        return None
    return None


def client(url: str, verify: bool) -> httpx.Client:
    return httpx.Client(base_url=url, headers=H, verify=verify, timeout=60)


def login(url: str, verify: bool, username: str, password: str) -> httpx.Client:
    c = client(url, verify)
    r = c.post("/api/auth/login", json={"username": username, "password": password})
    r.raise_for_status()
    return c


def prepare(admin: httpx.Client, n: int, group: str) -> list[str]:
    groups = {g["name"]: g["id"] for g in admin.get("/api/admin/groups").json()}
    gid = groups.get(group) or admin.post("/api/admin/groups", json={"name": group}).json()["id"]
    existing = {u["username"] for u in admin.get("/api/admin/users", params={"q": "loadtest"}).json()}
    names = [f"loadtest{i:02d}" for i in range(1, n + 1)]
    for name in names:
        if name not in existing:
            admin.post("/api/admin/users", json={"username": name, "full_name": f"Навантаження {name[-2:]}",
                                                 "password": PASSWORD, "group_id": gid}).raise_for_status()
    return names


def run_one(url: str, verify: bool, username: str, template_name: str, timeout: int) -> dict:
    c = login(url, verify, username, PASSWORD)
    tpl = next(t for t in c.get("/api/templates").json() if t["name"] == template_name)
    t0 = time.monotonic()
    r = c.post("/api/sessions", json={"template_id": tpl["id"]})
    if r.status_code != 200:
        return {"user": username, "ok": False, "error": r.json().get("detail")}
    sid = r.json()["id"]
    while time.monotonic() - t0 < timeout:
        info = c.get(f"/api/sessions/{sid}").json()
        if info["status"] == "error":
            return {"user": username, "ok": False, "error": info["error"], "sid": sid}
        if info.get("ready"):
            # перевіряємо, що стіл реально відповідає через Nginx
            page = c.get(f"/desktop/{sid}/")
            return {"user": username, "ok": page.status_code == 200, "seconds": time.monotonic() - t0,
                    "sid": sid, "error": None if page.status_code == 200 else f"HTTP {page.status_code}"}
        time.sleep(2)
    return {"user": username, "ok": False, "error": "timeout", "sid": sid}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--url", default="https://localhost")
    p.add_argument("--admin", default="admin")
    p.add_argument("--password", required=True)
    p.add_argument("--students", type=int, default=10)
    p.add_argument("--template", default="Ubuntu 22.04")
    p.add_argument("--group", default="LOADTEST")
    p.add_argument("--timeout", type=int, default=300)
    p.add_argument("--hold", type=int, default=60, help="скільки секунд тримати столи перед видаленням")
    p.add_argument("--insecure", action="store_true", help="не перевіряти сертифікат (самопідписаний)")
    args = p.parse_args()
    verify = not args.insecure

    admin = login(args.url, verify, args.admin, args.password)
    # шаблон має бути доступний тестовій групі
    names = prepare(admin, args.students, args.group)
    tpl = next((t for t in admin.get("/api/templates/manage").json() if t["name"] == args.template), None)
    if tpl is None:
        raise SystemExit(f"Шаблон «{args.template}» не знайдено")
    gid = next(g["id"] for g in admin.get("/api/admin/groups").json() if g["name"] == args.group)
    if gid not in [g["id"] for g in tpl["groups"]]:
        body = {k: tpl[k] for k in ("name", "subject", "description", "image", "cpu", "memory_mb", "shm_mb", "env", "is_active")}
        body["group_ids"] = [g["id"] for g in tpl["groups"]] + [gid]
        admin.put(f"/api/templates/{tpl['id']}", json=body).raise_for_status()

    mem_before = mem_available()
    print(f"Запускаю {len(names)} столів «{args.template}» одночасно…")
    t0 = time.monotonic()
    with cf.ThreadPoolExecutor(max_workers=len(names)) as pool:
        results = list(pool.map(lambda u: run_one(args.url, verify, u, args.template, args.timeout), names))
    total = time.monotonic() - t0
    ok = [r for r in results if r["ok"]]
    print(f"\nУспішно: {len(ok)}/{len(results)} за {total:.0f} с")
    if ok:
        times = [r["seconds"] for r in ok]
        print(f"Час до готовності: медіана {statistics.median(times):.1f} с, максимум {max(times):.1f} с")
    for r in results:
        if not r["ok"]:
            print(f"  ✗ {r['user']}: {r['error']}")
    print(f"Тримаю столи {args.hold} с, щоб виміряти пам'ять…")
    time.sleep(args.hold)
    mem_after = mem_available()
    if mem_before and mem_after and ok:
        used = mem_before - mem_after
        print(f"Пам'ять: зайнято {used / 2**30:.1f} ГБ, ≈{used / len(ok) / 2**30:.2f} ГБ на стіл; "
              f"вільно {mem_after / 2**30:.1f} ГБ")
    stats = admin.get("/api/admin/stats").json()
    print(f"Load average: {stats['load']}, ядер: {stats['cpu_count']}")

    print("Видаляю тестові столи…")
    for r in results:
        if r.get("sid"):
            admin.delete(f"/api/sessions/{r['sid']}")


if __name__ == "__main__":
    main()
