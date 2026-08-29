"""Application configuration loaded from environment / .env file."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Google Drive
    google_service_account_file: str = "service_account.json"
    # OAuth client secrets JSON ("Sign in with Google" flow). When an account
    # is connected via /api/auth/google, it takes precedence over the
    # service account file.
    google_oauth_client_file: str = "oauth_client.json"
    # Base URL this server is reachable at; used to build the OAuth redirect URI.
    public_base_url: str = "http://localhost:8000"
    # Path prefix when using the cloud relay, e.g. /e/wedding (must match PUBLIC_BASE_URL).
    path_prefix: str = ""
    # After OAuth, redirect here instead of /admin (set by relay sync).
    studio_url: str = ""

    # Face recognition
    face_model: str = "ArcFace"
    face_detector: str = "retinaface"
    # Cosine distance for agglomerative clustering (higher = group more poses).
    cluster_eps: float = 0.45
    # After clustering, merge people if centroid cosine similarity >= this.
    # Lower merges looking-up/down splits more aggressively. Same-photo pairs never merge.
    cluster_merge_sim: float = 0.55
    cluster_min_samples: int = 2
    match_threshold: float = 0.50
    min_face_width_fraction: float = 0.03
    min_face_confidence: float = 0.50

    # Processing
    worker_processes: int = 0  # 0 => auto (cpu_count)

    # Cloud relay (optional — when set, GetME connects to your relay as the agent)
    relay_url: str = ""
    relay_session: str = ""
    relay_agent_secret: str = ""

    # Local testing photos (no Google Drive). Relative to project root or absolute.
    local_photos_dir: str = "test-photos"

    # Frontend: path to a UI client directory (HTML/JS/CSS). Empty = API only.
    # Default ships the agent web UI. Point at another folder for a different client.
    # Examples: clients/web-agent  |  "" for API-only  |  /path/to/custom-ui
    getme_ui: str = "clients/web-agent"

    # App
    admin_token: str = "change-me"
    token_ttl_seconds: int = 86_400
    database_path: str = "data/getme.db"

    @property
    def resolved_worker_processes(self) -> int:
        if self.worker_processes and self.worker_processes > 0:
            return self.worker_processes
        return max(1, os.cpu_count() or 1)

    @property
    def resolved_ui_dir(self) -> str | None:
        """Absolute UI directory if enabled and present, else None (API-only)."""
        raw = (self.getme_ui or "").strip()
        if not raw:
            return None
        path = Path(raw).expanduser()
        if not path.is_absolute():
            root = Path(__file__).resolve().parent.parent
            path = (root / path).resolve()
        else:
            path = path.resolve()
        return str(path) if path.is_dir() else None


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reload_settings() -> Settings:
    get_settings.cache_clear()
    return get_settings()
