"""Write display centroid JPGs = crop nearest the embedding centroid."""

from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np


def best_crop_key_for_cluster(
    centroid: list[float] | np.ndarray,
    member_keys: list[str],
    embeddings_by_key: dict[str, np.ndarray],
) -> str | None:
    """Return emb_cache-style key (e.g. p5.JPG_f0) closest to the cluster centroid."""
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
