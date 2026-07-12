"""HTTP helpers for serving behind the cloud relay."""

from __future__ import annotations

from app.config import get_settings


def path_prefix() -> str:
    """URL prefix when served via relay, e.g. /e/wedding (no trailing slash)."""
    return get_settings().path_prefix.rstrip("/")


def url_path(path: str) -> str:
    """Join configured prefix with an absolute path."""
    p = path if path.startswith("/") else f"/{path}"
    prefix = path_prefix()
    return f"{prefix}{p}" if prefix else p
