"""Messages between cloud relay, browser, and local agent."""

from __future__ import annotations

import base64
from typing import Any


def b64encode(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def b64decode(text: str) -> bytes:
    return base64.b64decode(text.encode("ascii"))


def request_message(
    request_id: str,
    method: str,
    path: str,
    query: str,
    headers: dict[str, str],
    body: bytes,
) -> dict[str, Any]:
    return {
        "type": "request",
        "id": request_id,
        "method": method,
        "path": path,
        "query": query,
        "headers": headers,
        "body": b64encode(body) if body else "",
    }


def response_message(
    request_id: str,
    status: int,
    headers: dict[str, str],
    body: bytes,
) -> dict[str, Any]:
    return {
        "type": "response",
        "id": request_id,
        "status": status,
        "headers": headers,
        "body": b64encode(body) if body else "",
    }


def error_message(request_id: str, detail: str) -> dict[str, Any]:
    return {"type": "error", "id": request_id, "detail": detail}


def command_message(command: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {"type": "command", "command": command, "payload": payload or {}}


def agent_status_message(payload: dict[str, Any]) -> dict[str, Any]:
    return {"type": "agent_status", **payload}
