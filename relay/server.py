"""Cloud relay — studio UI, agent sync, guest traffic proxy."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import uuid
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles

from relay.protocol import b64decode, command_message, request_message
from relay.store import RelayStore

logger = logging.getLogger("getme.relay")

PUBLIC_ORIGIN = os.environ.get("RELAY_PUBLIC_ORIGIN", "http://localhost:9000").rstrip("/")
RELAY_ADMIN_TOKEN = os.environ.get("RELAY_ADMIN_TOKEN", "change-me-relay")
REQUEST_TIMEOUT = float(os.environ.get("RELAY_REQUEST_TIMEOUT", "120"))
GETME_REPO = os.environ.get("GETME_REPO", "https://github.com/kambstreat/getme.git")

STATIC_DIR = Path(__file__).parent / "static"

store = RelayStore()
store.set_public_origin(PUBLIC_ORIGIN)

app = FastAPI(title="GetME! Relay", version="0.2.0")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _check_relay_admin(token: str | None) -> None:
    if not token or token != RELAY_ADMIN_TOKEN:
        raise HTTPException(status_code=401, detail="Invalid relay admin token.")


def _session_auth(session_id: str, token: str | None):
    if not token:
        raise HTTPException(status_code=401, detail="Missing session token.")
    s = store.verify_viewer(session_id, token)
    if s is None:
        raise HTTPException(status_code=401, detail="Invalid session token.")
    return s


def _sync_payload(s, session_id: str) -> dict:
    origin = PUBLIC_ORIGIN.rstrip("/")
    return {
        "drive_link": s.drive_link,
        "admin_token": s.admin_token,
        "public_base_url": s.public_base_url,
        "path_prefix": f"/e/{session_id}",
        "studio_url": f"{origin}/studio/{session_id}?token={s.viewer_token}",
    }


async def _send_command(session_id: str, command: str, payload: dict | None = None) -> bool:
    agent = store.get_agent(session_id)
    if agent is None:
        return False
    await agent.websocket.send_json(command_message(command, payload))
    return True


@app.on_event("startup")
async def _startup() -> None:
    logging.basicConfig(level=logging.INFO)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "sessions": len(store.list_events())}


@app.get("/")
async def signup_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "signup.html")


@app.get("/studio/{session_id}")
async def studio_page(session_id: str, token: str = "") -> FileResponse:
    if not store.verify_viewer(session_id, token):
        raise HTTPException(status_code=401, detail="Invalid or missing token.")
    return FileResponse(STATIC_DIR / "studio.html")


# --- Session API (studio) ---------------------------------------------------

@app.post("/api/sessions")
async def create_session(request: Request) -> dict:
    body = await request.json()
    event_name = str(body.get("event_name", "")).strip()
    email = str(body.get("email", "")).strip()
    if not event_name:
        raise HTTPException(status_code=400, detail="event_name is required.")
    session = store.create_session(event_name, email)
    origin = PUBLIC_ORIGIN.rstrip("/")
    return {
        **session.to_public_dict(),
        "studio_url": f"{origin}/studio/{session.session_id}?token={session.viewer_token}",
        "agent_secret": session.agent_secret,  # shown once in studio via install
    }


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str, x_session_token: str | None = Header(default=None)) -> dict:
    s = _session_auth(session_id, x_session_token)
    data = s.to_public_dict()
    data["admin_url"] = s.public_base_url + f"/admin?token={s.admin_token}"
    return data


@app.put("/api/sessions/{session_id}/config")
async def update_config(
    session_id: str,
    request: Request,
    x_session_token: str | None = Header(default=None),
) -> dict:
    s = _session_auth(session_id, x_session_token)
    body = await request.json()
    drive_link = str(body.get("drive_link", "")).strip()
    if not drive_link:
        raise HTTPException(status_code=400, detail="drive_link is required.")
    store.update_session(session_id, drive_link=drive_link)
    await _send_command(session_id, "sync_config", _sync_payload(s, session_id))
    s = store.get_session(session_id)
    data = s.to_public_dict()
    data["admin_url"] = s.public_base_url + f"/admin?token={s.admin_token}"
    return data


@app.post("/api/sessions/{session_id}/process")
async def start_processing(
    session_id: str,
    x_session_token: str | None = Header(default=None),
) -> dict:
    s = _session_auth(session_id, x_session_token)
    if not s.agent_connected:
        raise HTTPException(status_code=503, detail="Agent offline. Install and run the agent on your laptop.")
    if not s.drive_link:
        raise HTTPException(status_code=400, detail="Save a Drive folder link first.")
    store.update_session(session_id, job_status="pending", job_error=None)
    ok = await _send_command(
        session_id,
        "start_processing",
        {"drive_link": s.drive_link, "admin_token": s.admin_token, "incremental": False},
    )
    if not ok:
        raise HTTPException(status_code=503, detail="Could not reach agent.")
    s = store.get_session(session_id)
    return s.to_public_dict()


@app.post("/api/sessions/{session_id}/google/start")
async def google_start(
    session_id: str,
    x_session_token: str | None = Header(default=None),
) -> dict:
    """Start Google OAuth from the studio (same tab — no admin page)."""
    s = _session_auth(session_id, x_session_token)
    if not s.agent_connected:
        raise HTTPException(status_code=503, detail="GetME offline. Run it on your laptop first.")
    status, data = await _proxy_get_json(
        session_id,
        "/api/auth/google/start",
        {"X-Admin-Token": s.admin_token},
    )
    if status != 200:
        raise HTTPException(status_code=status, detail=data.get("detail", "Could not start Google sign-in."))
    return data


@app.get("/api/sessions/{session_id}/install")
async def install_info(
    session_id: str,
    x_session_token: str | None = Header(default=None),
) -> dict:
    s = _session_auth(session_id, x_session_token)
    origin = PUBLIC_ORIGIN.rstrip("/")
    script_url = f"{origin}/api/sessions/{session_id}/install.sh?token={s.viewer_token}"
    one_liner = f'curl -fsSL "{script_url}" | bash'
    return {
        "one_liner": one_liner,
        "script_url": script_url,
        "note": "Install script runs GetME! with relay built in (one process).",
    }


@app.get("/api/sessions/{session_id}/install.sh")
async def install_script(session_id: str, token: str = "") -> PlainTextResponse:
    s = store.verify_viewer(session_id, token)
    if s is None:
        raise HTTPException(status_code=401, detail="Invalid token.")
    script = f"""#!/usr/bin/env bash
set -euo pipefail
echo "GetME! Agent installer"
INSTALL_DIR="${{GETME_INSTALL_DIR:-$HOME/getme-agent}}"
RELAY_URL="{PUBLIC_ORIGIN}"
SESSION_ID="{s.session_id}"
AGENT_SECRET="{s.agent_secret}"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"
if [[ ! -d .git ]]; then
  echo "Cloning GetME…"
  git clone {GETME_REPO} . 2>/dev/null || git clone {GETME_REPO} repo && mv repo/* repo/.git . 2>/dev/null || true
fi
if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt
pip install -q httpx websockets
echo "Starting GetME! (keeps running — leave this window open)…"
ENV_FILE=".env"
touch "$ENV_FILE"
for kv in "RELAY_URL=$RELAY_URL" "RELAY_SESSION=$SESSION_ID" "RELAY_AGENT_SECRET=$AGENT_SECRET"; do
  key="${{kv%%=*}}"
  if grep -q "^$key=" "$ENV_FILE" 2>/dev/null; then
    sed -i "s|^$key=.*|$kv|" "$ENV_FILE"
  else
    echo "$kv" >> "$ENV_FILE"
  fi
done
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
"""
    return PlainTextResponse(script, media_type="text/plain")


# --- Agent WebSocket --------------------------------------------------------

@app.websocket("/agent/ws")
async def agent_websocket(websocket: WebSocket) -> None:
    await websocket.accept()
    session_id = websocket.query_params.get("event_id", "").strip()
    agent_secret = websocket.query_params.get("agent_secret", "").strip()
    agent = await store.connect_agent(websocket, session_id, agent_secret)
    if agent is None:
        await websocket.close(code=4401, reason="Invalid session or secret")
        return

    logger.info("Agent connected for session %s", session_id)
    s = store.get_session(session_id)
    if s:
        await websocket.send_json(command_message("sync_config", _sync_payload(s, session_id)))

    try:
        while True:
            raw = await websocket.receive_json()
            msg_type = raw.get("type")

            if msg_type == "response":
                req_id = raw["id"]
                fut = agent.pending.pop(req_id, None)
                if fut and not fut.done():
                    fut.set_result(raw)
            elif msg_type == "error":
                req_id = raw["id"]
                fut = agent.pending.pop(req_id, None)
                if fut and not fut.done():
                    fut.set_exception(RuntimeError(raw.get("detail", "Agent error")))
            elif msg_type == "agent_status":
                store.update_session(
                    session_id,
                    drive_connected=raw.get("drive_connected", False),
                    job_status=raw.get("job_status", "idle"),
                    job_id=raw.get("job_id"),
                    job_progress=raw.get("job_progress") or {},
                    job_error=raw.get("job_error"),
                )
            elif msg_type == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        logger.info("Agent disconnected for session %s", session_id)
    finally:
        store.disconnect_agent(session_id)


# --- Guest/admin proxy to local app -----------------------------------------

async def _proxy_get_json(
    session_id: str, path: str, extra_headers: dict[str, str]
) -> tuple[int, dict]:
    agent = store.get_agent(session_id)
    if agent is None:
        raise HTTPException(
            status_code=503,
            detail="GetME offline. Run it on your laptop first.",
        )

    req_id = uuid.uuid4().hex
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    agent.pending[req_id] = fut

    msg = request_message(req_id, "GET", path, "", extra_headers, b"")
    try:
        await agent.websocket.send_json(msg)
        raw = await asyncio.wait_for(fut, timeout=REQUEST_TIMEOUT)
    except asyncio.TimeoutError:
        agent.pending.pop(req_id, None)
        raise HTTPException(status_code=504, detail="Local app timed out.") from None
    except Exception as exc:
        agent.pending.pop(req_id, None)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    status = int(raw.get("status", 502))
    body = b64decode(raw.get("body") or "")
    try:
        return status, json.loads(body)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=body.decode("utf-8", errors="replace")) from exc


async def _proxy_to_agent(session_id: str, request: Request, path: str) -> Response:
    agent = store.get_agent(session_id)
    if agent is None:
        return JSONResponse(
            status_code=503,
            content={"detail": "Event offline. The videographer needs to run the agent on their laptop."},
        )

    body = await request.body()
    headers = {
        k: v
        for k, v in request.headers.items()
        if k.lower() not in ("host", "connection", "content-length", "transfer-encoding")
    }
    headers["x-forwarded-prefix"] = f"/e/{session_id}"
    headers["x-forwarded-proto"] = request.url.scheme
    headers["x-forwarded-host"] = request.headers.get("host", "")

    req_id = uuid.uuid4().hex
    loop = asyncio.get_running_loop()
    fut: asyncio.Future = loop.create_future()
    agent.pending[req_id] = fut

    msg = request_message(
        req_id,
        request.method,
        "/" + path if path else "/",
        request.url.query,
        headers,
        body,
    )
    try:
        await agent.websocket.send_json(msg)
        raw = await asyncio.wait_for(fut, timeout=REQUEST_TIMEOUT)
    except asyncio.TimeoutError:
        agent.pending.pop(req_id, None)
        return JSONResponse(status_code=504, detail="Local app timed out.")
    except Exception as exc:
        agent.pending.pop(req_id, None)
        return JSONResponse(status_code=502, detail=str(exc))

    status = int(raw.get("status", 502))
    resp_headers = raw.get("headers") or {}
    resp_body = b64decode(raw.get("body") or "")
    skip = {"content-encoding", "transfer-encoding", "content-length", "connection"}
    out_headers = {k: v for k, v in resp_headers.items() if k.lower() not in skip}
    return Response(content=resp_body, status_code=status, headers=out_headers)


@app.api_route("/e/{session_id}/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_path(session_id: str, path: str, request: Request) -> Response:
    if store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Unknown event.")
    return await _proxy_to_agent(session_id, request, path)


@app.api_route("/e/{session_id}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_root(session_id: str, request: Request) -> Response:
    if store.get_session(session_id) is None:
        raise HTTPException(status_code=404, detail="Unknown event.")
    return await _proxy_to_agent(session_id, request, "")
