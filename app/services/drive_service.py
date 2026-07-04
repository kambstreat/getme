"""Google Drive access: parse links, list images, stream bytes in memory.

Photos are never written to local disk - they are streamed into memory for
face processing (during ingestion) and for ZIP delivery (on download).
"""

from __future__ import annotations

import io
import os
import re

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

from app.config import get_settings

# Read-only is all we need for the live-event scope.
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

IMAGE_MIME_PREFIX = "image/"

_FOLDER_PATTERNS = [
    re.compile(r"/folders/([A-Za-z0-9_-]+)"),
    re.compile(r"[?&]id=([A-Za-z0-9_-]+)"),
]


def extract_folder_id(drive_link: str) -> str:
    """Extract a Drive folder ID from a share link or accept a raw ID."""
    link = drive_link.strip()
    for pattern in _FOLDER_PATTERNS:
        m = pattern.search(link)
        if m:
            return m.group(1)
    # Assume the caller passed a bare folder ID.
    if re.fullmatch(r"[A-Za-z0-9_-]{10,}", link):
        return link
    raise ValueError(f"Could not extract a Drive folder ID from: {drive_link!r}")


def build_service():
    """Build a Drive client.

    Prefers a Google account connected via OAuth (/api/auth/google); falls
    back to a service account key file when no account is connected.
    """
    from app.services import google_auth

    creds = google_auth.load_credentials()
    if creds is None:
        settings = get_settings()
        if not os.path.exists(settings.google_service_account_file):
            raise FileNotFoundError(
                "No Google account connected and no service account key found. "
                "Connect Google Drive from the admin console, or set "
                "GOOGLE_SERVICE_ACCOUNT_FILE."
            )
        creds = service_account.Credentials.from_service_account_file(
            settings.google_service_account_file, scopes=SCOPES
        )
    # cache_discovery=False avoids noisy warnings and filesystem cache writes.
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def list_images(service, folder_id: str) -> list[dict]:
    """List image files in a folder (handles pagination).

    Returns list of {"id", "name", "mimeType"}.
    """
    files: list[dict] = []
    page_token = None
    query = (
        f"'{folder_id}' in parents and trashed = false "
        f"and mimeType contains 'image/'"
    )
    while True:
        resp = (
            service.files()
            .list(
                q=query,
                spaces="drive",
                fields="nextPageToken, files(id, name, mimeType)",
                pageToken=page_token,
                pageSize=1000,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
            )
            .execute()
        )
        files.extend(resp.get("files", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            break
    return files


def stream_file(service, file_id: str) -> io.BytesIO:
    """Download a Drive file fully into an in-memory buffer."""
    request = service.files().get_media(fileId=file_id, supportsAllDrives=True)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    buffer.seek(0)
    return buffer
