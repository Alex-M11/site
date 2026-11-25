"""Точка входу порталу «Хмарний робочий стіл для студентів»."""
from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from starlette.concurrency import run_in_threadpool

from .config import config
from .db import create_schema, db_session, init_engine
from .drivers import DriverError
from .deps import CSRF_HEADER, CSRF_VALUE, user_from_request
from .routers import admin, assignments, auth, files, sessions, teacher, templates
from .seed import ensure_admin, seed_demo
from .sessions_service import maintenance

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("cloud_desktop")
STATIC = Path(__file__).parent / "static"


async def _maintenance_loop() -> None:
    while True:
        await asyncio.sleep(config.idle_check_seconds)
        try:
            def run():
                with db_session() as db:
                    return maintenance(db)
            result = await run_in_threadpool(run)
            if any(result.values()):
                log.info("Обслуговування сесій: %s", result)
        except Exception:  # noqa: BLE001 — цикл не повинен падати
            log.exception("Помилка фонового обслуговування")


def startup() -> None:
    init_engine(config.database_url)
    create_schema()
    config.storage_root.mkdir(parents=True, exist_ok=True)
    with db_session() as db:
        ensure_admin(db)
        if config.demo_seed:
            seed_demo(db)
    if config.secret_key_generated:
        log.warning("CD_SECRET_KEY не задано: після перезапуску всі користувачі вийдуть із системи.")
    elif len(config.secret_key) < 32:
        log.warning("CD_SECRET_KEY закороткий: використайте щонайменше 32 випадкові символи.")
    if config.driver == "fake":
        log.warning("Працює fake-драйвер: робочі столи імітуються. Для справжніх столів CD_DRIVER=docker.")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    startup()
    task = asyncio.create_task(_maintenance_loop()) if config.background_tasks else None
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(title="Хмарний робочий стіл для студентів", version="1.1.0", lifespan=lifespan,
              docs_url="/api/docs" if config.api_docs else None,
              openapi_url="/api/openapi.json" if config.api_docs else None, redoc_url=None)

# Сторінки порталу вантажать лише власні скрипти й стилі; стилі через атрибути style — тому 'unsafe-inline'
# лише для style-src. Сторінки KasmVNC (/desktop/) і Swagger мають власні правила.
CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; frame-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'; "
       "object-src 'none'")


@app.middleware("http")
async def csrf_and_headers(request: Request, call_next):
    # Змінювати дані можна лише з нашого JS: браузер не дає іншим сайтам додати цей заголовок без CORS.
    if request.method in {"POST", "PUT", "PATCH", "DELETE"} and request.url.path.startswith("/api/") \
            and request.headers.get(CSRF_HEADER) != CSRF_VALUE \
            and not request.headers.get("authorization", "").lower().startswith("bearer "):
        return JSONResponse({"detail": "Запит відхилено (CSRF)"}, status_code=403)
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    path = request.url.path
    if not path.startswith("/desktop/"):
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        if not path.startswith("/api/docs"):
            response.headers.setdefault("Content-Security-Policy", CSP)
    return response


@app.exception_handler(DriverError)
async def driver_error(_request: Request, exc: DriverError):
    # Docker недоступний або відмовив — пояснення замість «Internal Server Error».
    return JSONResponse({"detail": str(exc)}, status_code=503)


for r in (auth.router, templates.router, sessions.router, files.router, assignments.router,
          teacher.router, admin.router):
    app.include_router(r)

app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/session/{session_id}", include_in_schema=False)
def desktop_page(session_id: int):
    return FileResponse(STATIC / "desktop.html", headers={"Cache-Control": "no-cache"})


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True, "driver": config.driver, "version": app.version}


if config.driver == "fake":
    @app.get("/desktop/{session_id}/", include_in_schema=False)
    @app.get("/desktop/{session_id}-view/", include_in_schema=False)
    def fake_desktop(session_id: int):
        """Демо-режим без Docker: замість справжнього столу — заглушка."""
        return HTMLResponse((STATIC / "fake-desktop.html").read_text(encoding="utf-8"))
elif config.builtin_proxy:
    # Без Nginx (Windows-версія): портал сам передає сторінку й WebSocket KasmVNC.
    from .desktop_proxy import router as desktop_proxy_router
    app.include_router(desktop_proxy_router)


def _is_local(request: Request) -> bool:
    try:
        return ipaddress.ip_address(request.client.host).is_loopback if request.client else False
    except ValueError:
        return False


@app.get("/metrics", include_in_schema=False)
def metrics(request: Request):
    """Метрики для Prometheus (доступні з localhost або адміністратору)."""
    with db_session() as db:
        user = user_from_request(request, db)
        if not _is_local(request) and not (user and user.role == "admin"):
            raise HTTPException(403)
        stats = admin.server_stats(db)
    lines = [
        "# HELP cd_active_sessions Активні робочі столи (creating+running+paused)",
        "# TYPE cd_active_sessions gauge",
        f"cd_active_sessions {stats['active_sessions']}",
        "# HELP cd_sessions Робочі столи за станом",
        "# TYPE cd_sessions gauge",
    ]
    lines += [f'cd_sessions{{status="{k}"}} {v}' for k, v in stats["sessions"].items()]
    lines += ["# TYPE cd_users gauge", f"cd_users {stats['users']}",
              "# TYPE cd_logins_24h gauge", f"cd_logins_24h {stats['logins_24h']}"]
    mem = stats.get("memory") or {}
    if mem.get("total"):
        lines += ["# TYPE cd_memory_available_bytes gauge", f"cd_memory_available_bytes {mem['available']}"]
    return PlainTextResponse("\n".join(lines) + "\n")
