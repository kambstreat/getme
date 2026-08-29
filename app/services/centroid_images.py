"""Write display centroid JPGs = crop nearest the embedding centroid."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

import numpy as np

from app.services import face_service


def data_dirs() -> tuple[Path, Path, Path]:
    root = Path(__file__).resolve().parent.parent.parent
    data = root / "data"
    return data / "allfaces", data / "centroids", data / "fullpics"


def clear_viewer_assets(*, clear_fullpics: bool = True) -> None:
    """Remove stale cluster viewer images so face_id labels cannot mix runs."""
    allfaces, centroids, fullpics = data_dirs()
    face_thumbs = allfaces.parent / "face_thumbs"
    photo_thumbs = allfaces.parent / "photo_thumbs"
    for d in (allfaces, centroids, face_thumbs, photo_thumbs):
        d.mkdir(parents=True, exist_ok=True)
        for p in d.iterdir():
            if p.is_file():
                p.unlink()
    if clear_fullpics:
        fullpics.mkdir(parents=True, exist_ok=True)
        for p in fullpics.iterdir():
            if p.is_file():
                p.unlink()


def _safe_name(name: str) -> str:
    return re.sub(r"[^\w.\-]+", "_", name) or "photo"


def write_labeled_crops(all_faces: list[dict], clusters: dict[str, dict]) -> int:
    """Assign each face crop to its nearest cluster and write allfaces/ + centroids/.

    Returns number of crop files written.
    """
    if not all_faces or not clusters:
        return 0

    allfaces, centroids, _ = data_dirs()
    allfaces.mkdir(parents=True, exist_ok=True)
    centroids.mkdir(parents=True, exist_ok=True)

    centroids_vec = {
        fid: np.asarray(data["centroid"], dtype=np.float32) for fid, data in clusters.items()
    }
    # Clear previous labeled crops only (fullpics handled separately)
    for p in allfaces.iterdir():
        if p.is_file():
            p.unlink()
    for p in centroids.iterdir():
        if p.is_file():
            p.unlink()

    written = 0
    best_for_cluster: dict[str, tuple[float, Path]] = {}

    for face in all_faces:
        crop = face.get("crop_jpeg")
        if not crop:
            continue
        emb = np.asarray(face["embedding"], dtype=np.float32)
        face_id, sim = face_service.best_match(emb, {k: v.tolist() for k, v in centroids_vec.items()})
        if face_id is None:
            continue
        # Same-photo guard: only label if this file is in the cluster's files
        file_ids = set(clusters[face_id].get("file_ids") or [])
        if face["file_id"] not in file_ids:
            # Still allow if similarity is clearly this person (file list uses unique files)
            # Prefer matching via file membership when available
            pass
        # Prefer: face belongs to cluster that contains its file_id
        candidates = [
            fid for fid, data in clusters.items() if face["file_id"] in (data.get("file_ids") or [])
        ]
        if candidates:
            # pick closest among clusters that include this photo
            best_id = None
            best_sim = -1.0
            for fid in candidates:
                s = float(np.dot(emb, centroids_vec[fid]))
                if s > best_sim:
                    best_sim = s
                    best_id = fid
            face_id = best_id or face_id
            sim = best_sim if best_id else sim

        name = _safe_name(face.get("file_name") or face["file_id"])
        idx = int(face.get("face_index", 0))
        out = allfaces / f"{face_id}__{name}_f{idx}.jpg"
        out.write_bytes(crop)
        written += 1
        prev = best_for_cluster.get(face_id)
        if prev is None or sim > prev[0]:
            best_for_cluster[face_id] = (float(sim), out)

    for face_id, (_, src) in best_for_cluster.items():
        shutil.copy2(src, centroids / f"{face_id}.jpg")

    # Drop bulky crop bytes from memory
    for face in all_faces:
        face.pop("crop_jpeg", None)

    return written


def best_crop_key_for_cluster(
    centroid: list[float] | np.ndarray,
    member_keys: list[str],
    embeddings_by_key: dict[str, np.ndarray],
) -> str | None:
    """Return emb-cache-style key (e.g. p5.JPG_f0) closest to the cluster centroid."""
    c = np.asarray(centroid, dtype=np.float32)
    n = np.linalg.norm(c)
    if n > 0:
        c = c / n
    best_key: str | None = None
    best_sim = -1.0
    for key in member_keys:
        emb = embeddings_by_key.get(key)
        if emb is None:
            continue
        sim = float(np.dot(c, emb))
        if sim > best_sim:
            best_sim = sim
            best_key = key
    return best_key


def load_emb_cache(path: Path) -> tuple[dict[str, np.ndarray], list[str]]:
    """Load emb_cache.npz → {photo_fidx: unit embedding}, and original names."""
    z = np.load(path, allow_pickle=True)
    X = z["X"].astype(np.float32)
    X = X / np.linalg.norm(X, axis=1, keepdims=True).clip(min=1e-12)
    names = [str(n) for n in z["names"]]
    by_key: dict[str, np.ndarray] = {}
    for i, name in enumerate(names):
        # names are photo#fidx → disk keys are photo_fidx
        if "#" in name:
            photo, fidx = name.split("#", 1)
            key = f"{photo}_{fidx}"
        else:
            key = name
        by_key[key] = X[i]
    return by_key, names


def member_keys_from_allfaces(face_id: str, allfaces_dir: Path) -> list[str]:
    """Parse crop filenames face_id__{photo}_{fidx}.jpg → keys."""
    keys: list[str] = []
    if not allfaces_dir.is_dir():
        return keys
    prefix = f"{face_id}__"
    for p in sorted(allfaces_dir.iterdir()):
        if not p.name.startswith(prefix):
            continue
        if p.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            continue
        keys.append(p.stem[len(prefix) :])  # photo_fidx
    return keys


def write_centroid_images(
    clusters: dict[str, dict],
    *,
    emb_cache_path: Path,
    allfaces_dir: Path,
    centroids_dir: Path,
) -> dict[str, str]:
    """Overwrite centroids/{face_id}.jpg with the crop nearest each embedding centroid.

    Returns face_id → chosen crop filename (under allfaces).
    """
    centroids_dir.mkdir(parents=True, exist_ok=True)
    embeddings_by_key, _ = load_emb_cache(emb_cache_path)
    chosen: dict[str, str] = {}

    for face_id, data in clusters.items():
        keys = member_keys_from_allfaces(face_id, allfaces_dir)
        if not keys:
            continue
        best = best_crop_key_for_cluster(
            data.get("centroid") or [],
            keys,
            embeddings_by_key,
        )
        if best is None:
            best = keys[0]
        src = allfaces_dir / f"{face_id}__{best}.jpg"
        if not src.is_file():
            # try any extension
            matches = list(allfaces_dir.glob(f"{face_id}__{best}.*"))
            if not matches:
                continue
            src = matches[0]
        dst = centroids_dir / f"{face_id}.jpg"
        shutil.copy2(src, dst)
        chosen[face_id] = src.name
    return chosen
