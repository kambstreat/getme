"""Face detection, ArcFace embeddings, quality filtering, and clustering.

Images are processed from in-memory bytes (streamed from Drive). DeepFace is
used with the ArcFace model and RetinaFace detector. Embeddings are L2-normalized
so cosine distance reflects identity; clusters are formed with DBSCAN and given
a quality-weighted centroid so clean frontal faces anchor each person.
"""

from __future__ import annotations

import io

import numpy as np
from PIL import Image, ImageOps

from app.config import get_settings


def _load_rgb_array(image_bytes: io.BytesIO) -> np.ndarray:
    """Decode bytes into an RGB numpy array, honoring EXIF orientation."""
    image = Image.open(image_bytes)
    image = ImageOps.exif_transpose(image)  # respect camera rotation
    image = image.convert("RGB")
    return np.asarray(image)


def _quality_score(facial_area: dict, confidence: float) -> float:
    """Heuristic quality in [0, 1]: blends detector confidence and frontality.

    Frontal faces have width/height ~0.7-0.9; very narrow boxes suggest a
    profile view and are scored lower so they pull the centroid less.
    """
    w = float(facial_area.get("w", 0))
    h = float(facial_area.get("h", 1)) or 1.0
    aspect = w / h
    frontality = 1.0 - min(1.0, abs(aspect - 0.8) * 2.0)
    frontality = max(0.0, frontality)
    return 0.5 * float(confidence) + 0.5 * frontality


def extract_faces(image_bytes: io.BytesIO, file_id: str, file_name: str | None = None) -> list[dict]:
    """Detect faces in one image and return embedding records.

    Each record: {file_id, file_name, embedding (np.ndarray, normalized),
                  quality}. Returns [] when no usable face is found.
    """
    from deepface import DeepFace  # imported lazily; heavy TF import

    settings = get_settings()
    img = _load_rgb_array(image_bytes)
    img_h, img_w = img.shape[:2]
    min_width = img_w * settings.min_face_width_fraction

    try:
        reps = DeepFace.represent(
            img_path=img,
            model_name=settings.face_model,
            detector_backend=settings.face_detector,
            enforce_detection=False,
            align=True,
        )
    except Exception:
        return []

    faces: list[dict] = []
    for rep in reps:
        facial_area = rep.get("facial_area", {}) or {}
        confidence = float(rep.get("face_confidence", rep.get("confidence", 1.0)) or 0.0)

        width = float(facial_area.get("w", 0))
        if width < min_width:
            continue
        if confidence < settings.min_face_confidence:
            continue

        embedding = np.asarray(rep["embedding"], dtype=np.float32)
        norm = np.linalg.norm(embedding)
        if norm == 0:
            continue
        embedding = embedding / norm

        faces.append(
            {
                "file_id": file_id,
                "file_name": file_name,
                "embedding": embedding,
                "quality": _quality_score(facial_area, confidence),
            }
        )
    return faces


def embed_selfie(image_bytes: io.BytesIO) -> np.ndarray | None:
    """Return a normalized ArcFace embedding for the largest detected face."""
    from deepface import DeepFace

    settings = get_settings()
    img = _load_rgb_array(image_bytes)
    try:
        reps = DeepFace.represent(
            img_path=img,
            model_name=settings.face_model,
            detector_backend=settings.face_detector,
            enforce_detection=True,
            align=True,
        )
    except Exception:
        return None

    if not reps:
        return None

    # Choose the largest face (selfies usually have one dominant face).
    reps.sort(key=lambda r: (r.get("facial_area", {}) or {}).get("w", 0), reverse=True)
    embedding = np.asarray(reps[0]["embedding"], dtype=np.float32)
    norm = np.linalg.norm(embedding)
    if norm == 0:
        return None
    return embedding / norm


def cluster_faces(all_faces: list[dict]) -> dict[str, dict]:
    """Cluster face embeddings into people (agglomerative, cosine distance).

    Average-linkage agglomerative clustering judges clusters by their overall
    cohesion rather than any single close pair, so two look-alike people don't
    chain into one cluster the way they can with DBSCAN. Faces appearing in a
    single photo naturally form their own one-member cluster.

    After agglomerative clustering, near-duplicate centroids (same person split
    by pose/angle) are merged when cosine similarity is high.

    Returns face_id -> {centroid, file_ids, file_names, face_count}.
    """
    from sklearn.cluster import AgglomerativeClustering

    if not all_faces:
        return {}

    settings = get_settings()
    embeddings = np.vstack([f["embedding"] for f in all_faces]).astype(np.float32)

    if len(all_faces) == 1:
        labels = np.zeros(1, dtype=int)
    else:
        labels = AgglomerativeClustering(
            n_clusters=None,
            distance_threshold=settings.cluster_eps,
            metric="cosine",
            linkage="average",
        ).fit_predict(embeddings)

    groups: dict[int, list[int]] = {}
    for idx, label in enumerate(labels):
        groups.setdefault(int(label), []).append(idx)

    def _build(indices: list[int]) -> dict:
        vecs = embeddings[indices]
        weights = np.array([all_faces[i]["quality"] for i in indices], dtype=np.float32)
        if weights.sum() <= 0:
            weights = np.ones(len(indices), dtype=np.float32)
        weights = weights / weights.sum()

        centroid = (vecs * weights[:, None]).sum(axis=0)
        c_norm = np.linalg.norm(centroid)
        if c_norm > 0:
            centroid = centroid / c_norm

        file_ids: list[str] = []
        file_names: dict[str, str] = {}
        for i in indices:
            fid = all_faces[i]["file_id"]
            if fid not in file_names:
                file_ids.append(fid)
            if all_faces[i].get("file_name"):
                file_names[fid] = all_faces[i]["file_name"]

        return {
            "centroid": centroid.astype(float).tolist(),
            "file_ids": file_ids,
            "file_names": file_names,
            "face_count": len(indices),
            "_indices": list(indices),
        }

    raw: dict[str, dict] = {f"tmp_{lab}": _build(idxs) for lab, idxs in groups.items()}

    def _file_ids_of(key: str) -> set[str]:
        return {all_faces[i]["file_id"] for i in raw[key]["_indices"]}

    # Merge near-duplicate people (pose/angle splits). Cosine distance threshold
    # eps=0.35 ⇒ similarity 0.65; use a slightly stricter merge bar.
    # Never merge clusters that share a photo — two faces in one image are
    # different people (blocks lookalike merges like neighbors in a group shot).
    merge_sim = max(0.70, 1.0 - float(settings.cluster_eps) * 0.85)
    ids = list(raw.keys())
    centroids = {k: np.asarray(raw[k]["centroid"], dtype=np.float32) for k in ids}
    absorbed: set[str] = set()
    for i, a in enumerate(ids):
        if a in absorbed:
            continue
        for b in ids[i + 1 :]:
            if b in absorbed:
                continue
            sim = float(np.dot(centroids[a], centroids[b]))
            if sim < merge_sim:
                continue
            if _file_ids_of(a) & _file_ids_of(b):
                continue
            combined = raw[a]["_indices"] + raw[b]["_indices"]
            raw[a] = _build(combined)
            centroids[a] = np.asarray(raw[a]["centroid"], dtype=np.float32)
            absorbed.add(b)

    clusters: dict[str, dict] = {}
    n = 0
    for key, data in raw.items():
        if key in absorbed:
            continue
        data.pop("_indices", None)
        clusters[f"face_{n}"] = data
        n += 1
    return clusters


def best_match(selfie_embedding: np.ndarray, centroids: dict[str, list[float]]) -> tuple[str | None, float]:
    """Return (face_id, similarity) of the closest centroid by cosine similarity."""
    best_id: str | None = None
    best_sim = -1.0
    for face_id, centroid in centroids.items():
        c = np.asarray(centroid, dtype=np.float32)
        sim = float(np.dot(selfie_embedding, c))  # both are unit vectors
        if sim > best_sim:
            best_sim = sim
            best_id = face_id
    return best_id, best_sim


def cluster_faces_incremental(new_faces: list[dict], existing_clusters: dict[str, dict]) -> dict[str, dict]:
    """Add new faces to existing clusters or create new clusters for them.
    
    Strategy:
    1. For each new face, find the closest existing cluster centroid
    2. If similarity is above threshold, add to that cluster and update centroid
    3. Otherwise, cluster all unmatched faces together and create new clusters
    
    Returns updated clusters dict.
    """
    if not new_faces:
        return existing_clusters
    
    settings = get_settings()
    # Use a slightly stricter threshold for incremental matching
    match_threshold = settings.cluster_eps * 0.8
    
    matched_faces: dict[str, list[dict]] = {fid: [] for fid in existing_clusters}
    unmatched_faces: list[dict] = []
    # file_ids claimed by a cluster during this incremental pass (same-photo guard)
    claimed: dict[str, set[str]] = {
        fid: set(existing_clusters[fid].get("file_ids", [])) for fid in existing_clusters
    }
    
    # Match new faces to existing clusters
    for face in new_faces:
        embedding = face["embedding"]
        best_id: str | None = None
        best_sim = -1.0
        
        for face_id, cluster_data in existing_clusters.items():
            # Same photo already has someone in this cluster → different person
            if face["file_id"] in claimed.get(face_id, set()):
                continue
            centroid = np.asarray(cluster_data["centroid"], dtype=np.float32)
            # Cosine similarity (both are normalized)
            sim = float(np.dot(embedding, centroid))
            if sim > best_sim:
                best_sim = sim
                best_id = face_id
        
        # If similarity is high enough, assign to existing cluster
        if best_id and (1.0 - best_sim) < match_threshold:
            matched_faces[best_id].append(face)
            claimed.setdefault(best_id, set()).add(face["file_id"])
        else:
            unmatched_faces.append(face)
    
    # Update existing clusters with matched faces
    for face_id, new_matched in matched_faces.items():
        if not new_matched:
            continue
        
        cluster = existing_clusters[face_id]
        # Merge new faces into cluster
        for face in new_matched:
            fid = face["file_id"]
            if fid not in cluster["file_ids"]:
                cluster["file_ids"].append(fid)
            if face.get("file_name"):
                cluster["file_names"][fid] = face["file_name"]
        
        # Recompute centroid with new faces
        all_embeddings = [f["embedding"] for f in new_matched]
        all_embeddings.append(np.asarray(cluster["centroid"], dtype=np.float32))
        
        all_qualities = [f["quality"] for f in new_matched]
        # Weight existing centroid by face_count to preserve its influence
        all_qualities.append(float(cluster["face_count"]))
        
        weights = np.array(all_qualities, dtype=np.float32)
        weights = weights / weights.sum()
        
        embeddings_array = np.vstack(all_embeddings)
        centroid = (embeddings_array * weights[:, None]).sum(axis=0)
        c_norm = np.linalg.norm(centroid)
        if c_norm > 0:
            centroid = centroid / c_norm
        
        cluster["centroid"] = centroid.astype(float).tolist()
        cluster["face_count"] += len(new_matched)
    
    # Cluster unmatched faces and create new clusters
    if unmatched_faces:
        new_clusters = cluster_faces(unmatched_faces)
        existing_clusters.update(new_clusters)
    
    return existing_clusters
