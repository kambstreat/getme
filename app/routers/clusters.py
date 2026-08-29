"""Local debug view: centroids + face groupings."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from PIL import Image, ImageOps

from app.database import db
from app.services.centroid_images import (
    best_crop_key_for_cluster,
    load_emb_cache,
    member_keys_from_allfaces,
)

router = APIRouter(tags=["clusters"])

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
FULLPICS_DIR = DATA_DIR / "fullpics"
CENTROIDS_DIR = DATA_DIR / "centroids"
FACE_THUMBS_DIR = DATA_DIR / "face_thumbs"
PHOTO_THUMBS_DIR = DATA_DIR / "photo_thumbs"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
FACE_THUMB_SIZE = 128
PHOTO_THUMB_SIZE = 400
_EMB_BY_KEY: dict[str, np.ndarray] | None = None


def _safe_id(value: str) -> str:
    if not value or "/" in value or ".." in value or "\\" in value:
        raise HTTPException(status_code=400, detail="Invalid id.")
    return value


def _find_fullpic(file_name: str) -> Path | None:
    if not file_name:
        return None
    stem = Path(file_name).stem
    suffix = Path(file_name).suffix.lower() or ".jpg"
    for cand in (
        FULLPICS_DIR / file_name,
        FULLPICS_DIR / f"{stem}{suffix}",
        FULLPICS_DIR / f"{stem}.JPG",
        FULLPICS_DIR / f"{stem}.jpg",
        FULLPICS_DIR / f"{stem}.jpeg",
        FULLPICS_DIR / f"{stem}.png",
        FULLPICS_DIR / f"{stem}.webp",
    ):
        if cand.is_file():
            return cand
    return None


def _ensure_photo_thumb(file_name: str) -> Path | None:
    """400px preview for a full photo (cached)."""
    src = _find_fullpic(file_name)
    if src is None:
        return None
    PHOTO_THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    thumb = PHOTO_THUMBS_DIR / f"{src.stem}.jpg"
    if thumb.is_file() and thumb.stat().st_mtime >= src.stat().st_mtime:
        return thumb
    try:
        with Image.open(src) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((PHOTO_THUMB_SIZE, PHOTO_THUMB_SIZE))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=78, optimize=True)
            thumb.write_bytes(buf.getvalue())
        return thumb
    except Exception:
        return None


def _ensure_face_thumb(face_id: str) -> Path | None:
    """Build a small JPEG thumb from the centroid crop (cached on disk)."""
    FACE_THUMBS_DIR.mkdir(parents=True, exist_ok=True)
    thumb = FACE_THUMBS_DIR / f"{face_id}.jpg"
    src = CENTROIDS_DIR / f"{face_id}.jpg"
    if not src.is_file():
        return None
    if thumb.is_file() and thumb.stat().st_mtime >= src.stat().st_mtime:
        return thumb
    try:
        with Image.open(src) as im:
            im = im.convert("RGB")
            im.thumbnail((FACE_THUMB_SIZE, FACE_THUMB_SIZE))
            buf = io.BytesIO()
            im.save(buf, format="JPEG", quality=72, optimize=True)
            thumb.write_bytes(buf.getvalue())
        return thumb
    except Exception:
        return None


def _emb_by_key() -> dict[str, np.ndarray]:
    global _EMB_BY_KEY
    if _EMB_BY_KEY is None:
        path = DATA_DIR / "emb_cache.npz"
        if path.is_file():
            _EMB_BY_KEY, _ = load_emb_cache(path)
        else:
            _EMB_BY_KEY = {}
    return _EMB_BY_KEY


def _best_centroid_image(face_id: str, centroid: list[float] | None) -> str | None:
    """URL of the face crop nearest the embedding centroid (not an arbitrary first crop)."""
    allfaces_dir = DATA_DIR / "allfaces"
    keys = member_keys_from_allfaces(face_id, allfaces_dir)
    if not keys:
        crop_name = f"{face_id}.jpg"
        return (
            f"/data/centroids/{crop_name}"
            if (DATA_DIR / "centroids" / crop_name).is_file()
            else None
        )
    best = best_crop_key_for_cluster(centroid or [], keys, _emb_by_key()) if centroid else None
    if best is None:
        best = keys[0]
    src = allfaces_dir / f"{face_id}__{best}.jpg"
    if src.is_file():
        return f"/data/allfaces/{src.name}"
    crop_name = f"{face_id}.jpg"
    return (
        f"/data/centroids/{crop_name}"
        if (DATA_DIR / "centroids" / crop_name).is_file()
        else None
    )


def _full_photo_urls(file_name: str) -> dict | None:
    """Return preview + full URLs when a local full photo exists."""
    full = _find_fullpic(file_name)
    if full is None:
        return None
    thumb = _ensure_photo_thumb(file_name)
    return {
        "name": file_name,
        "url": f"/data/fullpics/{full.name}",
        "preview_url": (
            f"/data/photo_thumbs/{thumb.name}" if thumb else f"/data/fullpics/{full.name}"
        ),
    }


def _crops_for(face_id: str, allfaces_dir: Path, allowed_names: set[str] | None = None) -> list[str]:
    crops: list[str] = []
    if not allfaces_dir.is_dir():
        return crops
    for p in sorted(allfaces_dir.iterdir()):
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        if not p.name.startswith(f"{face_id}__"):
            continue
        if allowed_names:
            # face_id__{photo}_f{idx}.jpg — require photo name from this cluster
            rest = p.stem[len(face_id) + 2 :]
            photo = rest.rsplit("_f", 1)[0] if "_f" in rest else rest
            if photo not in allowed_names:
                continue
        crops.append(p.name)
    return crops


@router.get("/api/faces")
def list_faces() -> dict:
    """One small representative thumb per person (no allfaces / fullpics)."""
    summaries = db.list_cluster_summaries()
    people = []
    for row in summaries:
        face_id = row["face_id"]
        thumb = _ensure_face_thumb(face_id)
        people.append(
            {
                "face_id": face_id,
                "face_count": row["face_count"],
                "photo_count": row["photo_count"],
                "image": f"/data/face_thumbs/{face_id}.jpg" if thumb else None,
            }
        )
    return {"count": len(people), "people": people}


@router.get("/api/faces/thumb/{face_id}")
def face_thumb(face_id: str) -> Response:
    """Serve a 128px face thumb; builds it from the centroid on first request."""
    face_id = _safe_id(face_id)
    thumb = _ensure_face_thumb(face_id)
    if thumb is None:
        raise HTTPException(status_code=404, detail="Face thumb not found.")
    return Response(
        content=thumb.read_bytes(),
        media_type="image/jpeg",
        headers={"Cache-Control": "public, max-age=86400"},
    )


@router.get("/api/person/{face_id}")
def person_detail(face_id: str) -> dict:
    """One person's photos only — keeps the faces overview fast."""
    face_id = _safe_id(face_id)
    clusters = db.load_clusters()
    data = clusters.get(face_id)
    if data is None:
        raise HTTPException(status_code=404, detail="Person not found.")

    files = db.get_files_for_face(face_id)
    photos = []
    for f in files:
        name = f.get("file_name") or f["file_id"]
        item = _full_photo_urls(name)
        if item:
            photos.append(item)
        else:
            photos.append(
                {
                    "name": name,
                    "url": None,
                    "preview_url": None,
                    "file_id": f["file_id"],
                }
            )

    thumb = _ensure_face_thumb(face_id)
    return {
        "face_id": face_id,
        "face_count": int(data.get("face_count", 0)),
        "photo_count": len(files),
        "image": f"/data/face_thumbs/{face_id}.jpg" if thumb else None,
        "photos": photos,
    }


@router.get("/api/clusters")
def list_clusters() -> dict:
    clusters = db.load_clusters()
    allfaces_dir = DATA_DIR / "allfaces"
    people = []
    for face_id, data in sorted(clusters.items(), key=lambda x: -x[1].get("face_count", 0)):
        files = []
        full_photos = []
        allowed_names: set[str] = set()
        for fid in data.get("file_ids", []):
            name = data.get("file_names", {}).get(fid, fid)
            files.append({"file_id": fid, "name": name})
            allowed_names.add(name)
            photo = _full_photo_urls(name)
            if photo:
                full_photos.append(photo)
        crops = _crops_for(face_id, allfaces_dir, allowed_names)

        people.append(
            {
                "face_id": face_id,
                "face_count": data.get("face_count", 0),
                "files": files,
                "centroid_image": _best_centroid_image(face_id, data.get("centroid")),
                "face_crops": [f"/data/allfaces/{name}" for name in crops],
                "full_photos": full_photos,
            }
        )
    return {"count": len(people), "people": people}
