"""Selfie matching plus live delivery helpers (thumbnails + ZIP).

Photos are streamed from Drive on demand; nothing is stored locally.
"""

from __future__ import annotations

import io
import zipfile
from typing import Iterator

from PIL import Image, ImageOps

from app.config import get_settings
from app.database import db
from app.services import drive_service, face_service

THUMB_MAX = 400  # px, longest edge for gallery thumbnails


def match_selfie(selfie_bytes: io.BytesIO) -> dict:
    """Match a selfie to a cluster; on success issue a scoped token."""
    embedding = face_service.embed_selfie(selfie_bytes)
    if embedding is None:
        return {"matched": False, "message": "No face detected. Please use a clear, front-facing photo."}

    centroids = db.load_centroids()
    if not centroids:
        return {"matched": False, "message": "No event photos have been processed yet."}

    face_id, similarity = face_service.best_match(embedding, centroids)
    threshold = get_settings().match_threshold

    if face_id is None or similarity < threshold:
        return {"matched": False, "message": "We couldn't find your photos. Try another selfie."}

    files = db.get_files_for_face(face_id)
    token = db.create_token(face_id)
    return {
        "matched": True,
        "photo_count": len(files),
        "confidence": round(similarity * 100, 1),
        "token": token,
    }


def gallery_items(face_id: str) -> list[dict]:
    files = db.get_files_for_face(face_id)
    return [{"file_id": f["file_id"], "name": f["file_name"] or f["file_id"]} for f in files]


def make_thumbnail(file_id: str) -> bytes:
    """Stream one photo from Drive and return a small JPEG thumbnail."""
    service = drive_service.build_service()
    buffer = drive_service.stream_file(service, file_id)
    image = Image.open(buffer)
    image = ImageOps.exif_transpose(image).convert("RGB")
    image.thumbnail((THUMB_MAX, THUMB_MAX))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=82)
    out.seek(0)
    return out.read()


def stream_zip(face_id: str) -> Iterator[bytes]:
    """Yield a ZIP archive of all matched photos, streamed from Drive."""
    files = db.get_files_for_face(face_id)
    service = drive_service.build_service()

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        used_names: set[str] = set()
        for f in files:
            try:
                data = drive_service.stream_file(service, f["file_id"]).read()
            except Exception:
                continue
            name = f["file_name"] or f"{f['file_id']}.jpg"
            # de-duplicate names within the archive
            base = name
            n = 1
            while name in used_names:
                stem, _, ext = base.rpartition(".")
                name = f"{stem}_{n}.{ext}" if stem else f"{base}_{n}"
                n += 1
            used_names.add(name)
            zf.writestr(name, data)
    buffer.seek(0)
    yield buffer.read()
