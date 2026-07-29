"""Local debug view: centroids + face groupings."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from fastapi import APIRouter
from fastapi.responses import HTMLResponse

from app.database import db
from app.services.centroid_images import (
    best_crop_key_for_cluster,
    load_emb_cache,
    member_keys_from_allfaces,
)

router = APIRouter(tags=["clusters"])

DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
FULLPICS_DIR = DATA_DIR / "fullpics"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
_EMB_BY_KEY: dict[str, np.ndarray] | None = None


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
    if not file_name:
        return None
    stem = Path(file_name).stem
    suffix = Path(file_name).suffix.lower() or ".jpg"
    full = None
    for cand in (
        FULLPICS_DIR / file_name,
        FULLPICS_DIR / f"{stem}{suffix}",
        FULLPICS_DIR / f"{stem}.JPG",
        FULLPICS_DIR / f"{stem}.jpg",
    ):
        if cand.is_file():
            full = cand
            break
    if full is None:
        return None
    preview = FULLPICS_DIR / f"{stem}_preview.jpg"
    return {
        "name": file_name,
        "url": f"/data/fullpics/{full.name}",
        "preview_url": (
            f"/data/fullpics/{preview.name}" if preview.is_file() else f"/data/fullpics/{full.name}"
        ),
    }


def _crops_for(face_id: str, allfaces_dir: Path) -> list[str]:
    crops: list[str] = []
    if not allfaces_dir.is_dir():
        return crops
    for p in sorted(allfaces_dir.iterdir()):
        if p.suffix.lower() not in IMAGE_EXTS:
            continue
        if p.name.startswith(f"{face_id}__"):
            crops.append(p.name)
    return crops


@router.get("/api/clusters")
def list_clusters() -> dict:
    clusters = db.load_clusters()
    allfaces_dir = DATA_DIR / "allfaces"
    people = []
    for face_id, data in sorted(clusters.items(), key=lambda x: -x[1].get("face_count", 0)):
        crops = _crops_for(face_id, allfaces_dir)
        files = []
        full_photos = []
        for fid in data.get("file_ids", []):
            name = data.get("file_names", {}).get(fid, fid)
            files.append({"file_id": fid, "name": name})
            photo = _full_photo_urls(name)
            if photo:
                full_photos.append(photo)

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


@router.get("/clusters", response_class=HTMLResponse)
def clusters_page() -> HTMLResponse:
    html_path = DATA_DIR.parent / "static" / "clusters.html"
    if not html_path.is_file():
        return HTMLResponse("<h1>clusters.html missing</h1>", status_code=500)
    return HTMLResponse(
        html_path.read_text(encoding="utf-8"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )
