"""Local filesystem photo source for testing without Google Drive."""

from __future__ import annotations

import io
import mimetypes
from pathlib import Path

from app.config import get_settings

LOCAL_ID_PREFIX = "local:"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def is_local_id(file_id: str) -> bool:
    return bool(file_id) and file_id.startswith(LOCAL_ID_PREFIX)


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def _coerce_path(raw: str) -> Path:
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (_project_root() / path).resolve()
    else:
        path = path.resolve()
    return path


def resolved_dir() -> Path:
    """Active test-photo folder: last processed path, else LOCAL_PHOTOS_DIR."""
    from app.database import db

    stored = db.get_meta("local_photos_dir")
    raw = stored or get_settings().local_photos_dir
    path = _coerce_path(raw)
    if not path.exists() and stored is None:
        path.mkdir(parents=True, exist_ok=True)
    return path


def set_dir(raw: str) -> Path:
    """Point local ingest/match at an existing folder of images."""
    from app.database import db

    path = _coerce_path(raw)
    if not path.is_dir():
        raise FileNotFoundError(f"Not a folder: {path}")
    db.set_meta("local_photos_dir", str(path))
    return path


def _rel_from_id(file_id: str) -> str:
    if not is_local_id(file_id):
        raise ValueError(f"Not a local file id: {file_id!r}")
    return file_id[len(LOCAL_ID_PREFIX) :]


def _safe_path(rel: str) -> Path:
    """Resolve a photo path under LOCAL_PHOTOS_DIR (non-recursive; no path escape).

    Symlinks whose *directory entry* lives in LOCAL_PHOTOS_DIR are allowed
    (target may be outside), so local test folders can symlink sample images.
    """
    base = resolved_dir()
    # Non-recursive: only bare filenames
    name = Path(rel).name
    if name != rel.replace("\\", "/").lstrip("/") or name in ("", ".", ".."):
        raise ValueError(f"Invalid local photo name: {rel!r}")
    candidate = base / name
    if candidate.parent.resolve() != base.resolve():
        raise ValueError(f"Path escapes local photos dir: {rel!r}")
    return candidate


def list_images() -> list[dict]:
    """List image files in LOCAL_PHOTOS_DIR (non-recursive)."""
    base = resolved_dir()
    files: list[dict] = []
    for path in sorted(base.iterdir()):
        if not path.is_file():
            continue
        if path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        mime, _ = mimetypes.guess_type(path.name)
        files.append(
            {
                "id": f"{LOCAL_ID_PREFIX}{path.name}",
                "name": path.name,
                "mimeType": mime or "image/jpeg",
            }
        )
    return files


def stream_file(file_id: str) -> io.BytesIO:
    """Read a local image fully into a BytesIO buffer."""
    path = _safe_path(_rel_from_id(file_id))
    if not path.is_file():
        raise FileNotFoundError(f"Local photo not found: {file_id}")
    return io.BytesIO(path.read_bytes())


def copy_to_fullpics(file_ids: list[str] | None = None) -> int:
    """Copy processed local originals into data/fullpics for the clusters viewer.

    Returns number of files copied.
    """
    import shutil

    fullpics = _project_root() / "data" / "fullpics"
    fullpics.mkdir(parents=True, exist_ok=True)
    count = 0
    images = list_images()
    if file_ids is not None:
        wanted = set(file_ids)
        images = [img for img in images if img["id"] in wanted]
    for img in images:
        src = _safe_path(_rel_from_id(img["id"]))
        dst = fullpics / img["name"]
        shutil.copy2(src, dst)
        count += 1
    return count
