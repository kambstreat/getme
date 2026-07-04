"""Application configuration loaded from environment / .env file."""

from __future__ import annotations

import os
from functools import lru_cache

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

    # Face recognition
    face_model: str = "ArcFace"
    face_detector: str = "retinaface"
    cluster_eps: float = 0.40
    cluster_min_samples: int = 2
    match_threshold: float = 0.50
    min_face_width_fraction: float = 0.03
    min_face_confidence: float = 0.50

    # Processing
    worker_processes: int = 0  # 0 => auto (cpu_count)

    # App
    admin_token: str = "change-me"
    token_ttl_seconds: int = 86_400
    database_path: str = "data/getme.db"

    @property
    def resolved_worker_processes(self) -> int:
        if self.worker_processes and self.worker_processes > 0:
            return self.worker_processes
        return max(1, os.cpu_count() or 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
