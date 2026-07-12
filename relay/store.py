"""In-memory sessions, agent connections, and job state."""

from __future__ import annotations

import asyncio
import re
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket


def _slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s[:32] or "event"


@dataclass
class Session:
    session_id: str
    agent_secret: str
    viewer_token: str
    event_name: str
    email: str = ""
    created_at: float = field(default_factory=time.time)
    drive_link: str = ""
    admin_token: str = field(default_factory=lambda: secrets.token_urlsafe(24))
    agent_connected: bool = False
    # Job state mirrored from agent
    job_status: str = "idle"  # idle | pending | listing | processing | clustering | done | error
    job_id: str | None = None
    job_progress: dict[str, Any] = field(default_factory=dict)
    job_error: str | None = None
    drive_connected: bool = False

    @property
    def public_base_url(self) -> str:
        origin = RelayStore.public_origin.rstrip("/")
        return f"{origin}/e/{self.session_id}"

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "event_name": self.event_name,
            "email": self.email,
            "agent_connected": self.agent_connected,
            "drive_link": self.drive_link,
            "drive_connected": self.drive_connected,
            "job_status": self.job_status,
            "job_id": self.job_id,
            "job_progress": self.job_progress,
            "job_error": self.job_error,
            "guest_url": self.public_base_url + "/",
            "admin_url": self.public_base_url + "/admin",
            "studio_url": f"{RelayStore.public_origin.rstrip('/')}/studio/{self.session_id}",
        }


@dataclass
class ConnectedAgent:
    websocket: WebSocket
    session_id: str
    pending: dict[str, asyncio.Future] = field(default_factory=dict)


class RelayStore:
    public_origin: str = "http://localhost:9000"

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._agents: dict[str, ConnectedAgent] = {}

    def set_public_origin(self, origin: str) -> None:
        RelayStore.public_origin = origin.rstrip("/")

    def create_session(self, event_name: str, email: str = "") -> Session:
        base = _slugify(event_name)
        session_id = base
        n = 2
        while session_id in self._sessions:
            session_id = f"{base}-{n}"
            n += 1
        session = Session(
            session_id=session_id,
            agent_secret=secrets.token_urlsafe(32),
            viewer_token=secrets.token_urlsafe(24),
            event_name=event_name.strip() or "My Event",
            email=email.strip(),
        )
        self._sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Session | None:
        return self._sessions.get(session_id)

    def verify_viewer(self, session_id: str, token: str) -> Session | None:
        s = self._sessions.get(session_id)
        if s is None or not secrets.compare_digest(s.viewer_token, token):
            return None
        return s

    def update_session(self, session_id: str, **fields) -> Session | None:
        s = self._sessions.get(session_id)
        if s is None:
            return None
        for k, v in fields.items():
            if hasattr(s, k):
                setattr(s, k, v)
        return s

    async def connect_agent(
        self, websocket: WebSocket, session_id: str, agent_secret: str
    ) -> ConnectedAgent | None:
        s = self._sessions.get(session_id)
        if s is None or not secrets.compare_digest(s.agent_secret, agent_secret):
            return None
        if session_id in self._agents:
            old = self._agents[session_id]
            for fut in old.pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("Agent replaced"))
            try:
                await old.websocket.close()
            except Exception:
                pass
        agent = ConnectedAgent(websocket=websocket, session_id=session_id)
        self._agents[session_id] = agent
        s.agent_connected = True
        return agent

    def disconnect_agent(self, session_id: str) -> None:
        self._agents.pop(session_id, None)
        s = self._sessions.get(session_id)
        if s:
            s.agent_connected = False

    def get_agent(self, session_id: str) -> ConnectedAgent | None:
        return self._agents.get(session_id)

    # Back-compat for guest proxy routes
    def get_event(self, event_id: str) -> Session | None:
        return self.get_session(event_id)

    def list_events(self) -> list[dict[str, Any]]:
        return [s.to_public_dict() for s in self._sessions.values()]
