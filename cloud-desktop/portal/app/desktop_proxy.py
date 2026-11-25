"""Вбудований проксі робочих столів — для запуску без Nginx (Windows-версія, розробка).

У звичайному розгортанні /desktop/<id>/ проксіює Nginx (швидше й надійніше). Тут те саме робить портал:
перевіряє доступ (authorize_desktop), підставляє пароль KasmVNC і передає HTTP та WebSocket до контейнера.
Вмикається CD_BUILTIN_PROXY=1.
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import ssl

import httpx
from fastapi import APIRouter, HTTPException, Request, WebSocket
from fastapi.responses import PlainTextResponse, StreamingResponse
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool
from websockets.asyncio.client import connect as ws_connect

from .db import db_session
from .routers.sessions import DesktopAccess, authorize_desktop

log = logging.getLogger("cloud_desktop.proxy")
router = APIRouter(include_in_schema=False)

# KasmVNC у контейнері має самопідписаний сертифікат; з'єднання йде лише на 127.0.0.1.
_TLS = ssl.create_default_context()
_TLS.check_hostname = False
_TLS.verify_mode = ssl.CERT_NONE
_client: httpx.AsyncClient | None = None
HOP_BY_HOP = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
              "transfer-encoding", "upgrade", "host", "cookie", "authorization"}


def client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(verify=_TLS, timeout=httpx.Timeout(30, connect=5), trust_env=False)
    return _client


async def _authorize(conn, uri: str) -> DesktopAccess:
    def check():
        with db_session() as db:
            return authorize_desktop(conn, db, uri)
    return await run_in_threadpool(check)


@router.websocket("/desktop/{target}/websockify")
async def desktop_ws(websocket: WebSocket, target: str):
    uri = f"/desktop/{target}/websockify"
    try:
        access = await _authorize(websocket, uri)
    except HTTPException as exc:
        await websocket.close(code=4000 + exc.status_code)
        return
    protocols = [p.strip() for p in websocket.headers.get("sec-websocket-protocol", "").split(",") if p.strip()]
    try:
        # KasmVNC відхиляє WebSocket без заголовка Origin — передаємо той, що надіслав браузер.
        origin = websocket.headers.get("origin") or f"http://{websocket.headers.get('host', 'localhost')}"
        upstream = await ws_connect(f"wss://{access.upstream}/websockify", ssl=_TLS, max_size=None,
                                    subprotocols=protocols or None, open_timeout=10, ping_interval=None,
                                    origin=origin, additional_headers={"Authorization": access.authorization})
    except Exception as exc:  # noqa: BLE001 — будь-яка помилка з'єднання зі столом
        log.warning("Не вдалося під'єднатися до столу %s: %s", target, exc)
        await websocket.close(code=1011)
        return
    await websocket.accept(subprotocol=upstream.subprotocol)

    async def browser_to_desktop():
        while True:
            msg = await websocket.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if msg.get("bytes") is not None:
                await upstream.send(msg["bytes"])
            elif msg.get("text") is not None:
                await upstream.send(msg["text"])

    async def desktop_to_browser():
        async for data in upstream:
            if isinstance(data, bytes):
                await websocket.send_bytes(data)
            else:
                await websocket.send_text(data)

    tasks = [asyncio.create_task(browser_to_desktop()), asyncio.create_task(desktop_to_browser())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        await upstream.close()
        with contextlib.suppress(Exception):
            await websocket.close()


@router.api_route("/desktop/{target}/{path:path}", methods=["GET", "HEAD"])
async def desktop_http(request: Request, target: str, path: str):
    uri = f"/desktop/{target}/{path}"
    try:
        access = await _authorize(request, uri)
    except HTTPException as exc:
        if exc.status_code == 401:
            return PlainTextResponse("Потрібно увійти в портал", status_code=401)
        return PlainTextResponse("Доступ заборонено", status_code=exc.status_code)
    headers = {k: v for k, v in request.headers.items() if k.lower() not in HOP_BY_HOP}
    headers["Authorization"] = access.authorization
    url = f"https://{access.upstream}/{path}"
    upstream_req = client().build_request(request.method, url, params=request.query_params, headers=headers)
    try:
        resp = await client().send(upstream_req, stream=True)
    except httpx.HTTPError as exc:
        log.warning("Стіл %s не відповідає: %s", target, exc)
        return PlainTextResponse("Робочий стіл не відповідає", status_code=502)
    out_headers = {k: v for k, v in resp.headers.items() if k.lower() not in HOP_BY_HOP}
    return StreamingResponse(resp.aiter_raw(), status_code=resp.status_code, headers=out_headers,
                             background=BackgroundTask(resp.aclose))
