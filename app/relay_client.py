"""Connect GetME! to the cloud relay — same process, no separate agent."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

import httpx
import websockets
from fastapi import FastAPI
from websockets.exceptions import ConnectionClosed

from app.config import get_settings, reload_settings
from relay.protocol import agent_status_message, b64decode, error_message, response_message

logger = logging.getLogger("getme.relay")

HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
}

_relay_task: asyncio.Task | None = None
_state: dict = {"job_status": "idle"}


def relay_enabled() -> bool:
    s = get_settings()
    return bool(s.relay_url and s.relay_session and s.relay_agent_secret)


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def apply_relay_config(config: dict) -> None:
    """Persist studio config and reload settings without restart."""
    env_path = _project_root() / ".env"
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text(encoding="utf-8").splitlines()
    updates = {
        "ADMIN_TOKEN": config.get("admin_token", ""),
        "PUBLIC_BASE_URL": config.get("public_base_url", ""),
        "PATH_PREFIX": config.get("path_prefix", ""),
        "STUDIO_URL": config.get("studio_url", ""),
    }
    for key, val in updates.items():
        if not val:
            continue
        os.environ[key] = val
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={val}"
                found = True
                break
        if not found:
            lines.append(f"{key}={val}")
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    reload_settings()
    logger.info("Relay config synced from studio.")


async def _forward_request(app: FastAPI, msg: dict) -> dict:
    method = msg["method"]
    path = msg.get("path") or "/"
    query = msg.get("query") or ""
    url = path
    if query:
        url += "?" + query
    headers = {
        k: v for k, v in (msg.get("headers") or {}).items() if k.lower() not in HOP_BY_HOP
    }
    body = b64decode(msg.get("body") or "")
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://getme") as client:
        resp = await client.request(method, url, headers=headers, content=body)
    out_headers = {k: v for k, v in resp.headers.items() if k.lower() not in HOP_BY_HOP}
    return response_message(msg["id"], resp.status_code, out_headers, resp.content)


async def _local_json(
    app: FastAPI, method: str, path: str, admin_token: str, json_body: dict | None = None
) -> dict:
    headers = {"X-Admin-Token": admin_token, "Content-Type": "application/json"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://getme") as client:
        resp = await client.request(method, path, headers=headers, json=json_body)
    if resp.headers.get("content-type", "").startswith("application/json"):
        return resp.json()
    return {"detail": resp.text, "status_code": resp.status_code}


async def _poll_status_loop(app: FastAPI, ws, admin_token: str) -> None:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://getme") as client:
        while True:
            await asyncio.sleep(2)
            try:
                drive_connected = False
                r = await client.get("/api/auth/google/status")
                if r.status_code == 200:
                    drive_connected = r.json().get("connected", False)

                payload = {
                    "drive_connected": drive_connected,
                    "job_status": _state.get("job_status", "idle"),
                    "job_id": _state.get("job_id"),
                    "job_progress": _state.get("job_progress") or {},
                    "job_error": _state.get("job_error"),
                }

                job_id = _state.get("job_id")
                if job_id and _state.get("job_status") not in ("done", "error", "idle"):
                    r = await client.get(f"/api/drive/status/{job_id}")
                    if r.status_code == 200:
                        job = r.json()
                        _state["job_status"] = job.get("status", _state["job_status"])
                        _state["job_progress"] = {
                            "total_files": job.get("total_files", 0),
                            "processed_files": job.get("processed_files", 0),
                            "faces_found": job.get("faces_found", 0),
                            "clusters": job.get("clusters", 0),
                        }
                        _state["job_error"] = job.get("error")
                        payload.update(
                            {
                                "job_status": _state["job_status"],
                                "job_progress": _state["job_progress"],
                                "job_error": _state["job_error"],
                            }
                        )

                await ws.send(json.dumps(agent_status_message(payload)))
            except Exception:
                pass


async def _handle_command(app: FastAPI, msg: dict) -> None:
    cmd = msg.get("command")
    payload = msg.get("payload") or {}
    admin_token = payload.get("admin_token") or _state.get("admin_token", "")

    if cmd == "sync_config":
        _state["admin_token"] = admin_token
        _state["drive_link"] = payload.get("drive_link", "")
        apply_relay_config(payload)

    elif cmd == "start_processing":
        drive_link = payload.get("drive_link") or _state.get("drive_link")
        if not drive_link:
            _state["job_status"] = "error"
            _state["job_error"] = "No Drive folder link configured."
            return
        data = await _local_json(
            app,
            "POST",
            "/api/drive/process",
            admin_token,
            {"drive_link": drive_link, "incremental": payload.get("incremental", False)},
        )
        if "job_id" not in data:
            _state["job_status"] = "error"
            _state["job_error"] = data.get("detail") or str(data)
            return
        _state["job_id"] = data["job_id"]
        _state["job_status"] = "pending"
        _state["job_error"] = None
        logger.info("Processing started job_id=%s", data["job_id"])


async def _relay_loop(app: FastAPI) -> None:
    s = get_settings()
    relay = s.relay_url.rstrip("/")
    ws_scheme = "wss" if relay.startswith("https") else "ws"
    ws_host = relay.split("://", 1)[1]
    params = f"event_id={s.relay_session}&agent_secret={s.relay_agent_secret}"
    connect_url = f"{ws_scheme}://{ws_host}/agent/ws?{params}"
    backoff = 2

    while True:
        try:
            async with websockets.connect(connect_url, ping_interval=20, ping_timeout=20) as ws:
                logger.info("Connected to cloud relay (session=%s).", s.relay_session)
                backoff = 2
                poll_task = asyncio.create_task(
                    _poll_status_loop(app, ws, _state.get("admin_token", ""))
                )
                try:
                    async for message in ws:
                        msg = json.loads(message)
                        t = msg.get("type")
                        if t == "command":
                            await _handle_command(app, msg)
                        elif t == "request":
                            try:
                                resp = await _forward_request(app, msg)
                            except Exception as exc:
                                logger.exception("Relay forward failed")
                                resp = error_message(msg["id"], str(exc))
                            await ws.send(json.dumps(resp))
                finally:
                    poll_task.cancel()
                    try:
                        await poll_task
                    except asyncio.CancelledError:
                        pass
        except ConnectionClosed as exc:
            if exc.code == 4401:
                logger.error(
                    "Relay rejected this laptop (invalid session or secret). "
                    "The relay was likely restarted — create a new session in the studio, "
                    "copy the install command, update RELAY_* in .env, and restart GetME."
                )
                return
            logger.warning("Relay disconnected (%s). Reconnecting in %ss…", exc, backoff)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Relay error: %s. Reconnecting in %ss…", exc, backoff)
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2, 60)


async def start_relay_client(app: FastAPI) -> None:
    global _relay_task
    if not relay_enabled():
        return
    if _relay_task and not _relay_task.done():
        return
    _relay_task = asyncio.create_task(_relay_loop(app))
    logger.info("Relay client started.")


async def stop_relay_client() -> None:
    global _relay_task
    if _relay_task and not _relay_task.done():
        _relay_task.cancel()
        try:
            await _relay_task
        except asyncio.CancelledError:
            pass
    _relay_task = None
