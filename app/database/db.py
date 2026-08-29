"""SQLite persistence for clusters, file mappings, and download tokens.

Schema overview:
- clusters:   one row per detected person (face_id + quality-weighted centroid)
- cluster_files: face_id -> Drive file mapping (many-to-many; a file can hold
  several faces, a person appears in many files)
- tokens:     short-lived tokens issued on a successful selfie match, scoped to
  a single face_id so a user can browse/download only their own photos
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from typing import Iterable, Iterator

from app.config import get_settings


SCHEMA = """
CREATE TABLE IF NOT EXISTS clusters (
    face_id     TEXT PRIMARY KEY,
    centroid    TEXT NOT NULL,            -- JSON list[float], normalized
    face_count  INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS cluster_files (
    face_id     TEXT NOT NULL,
    file_id     TEXT NOT NULL,
    file_name   TEXT,
    PRIMARY KEY (face_id, file_id),
    FOREIGN KEY (face_id) REFERENCES clusters(face_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_cluster_files_face ON cluster_files(face_id);

CREATE TABLE IF NOT EXISTS tokens (
    token       TEXT PRIMARY KEY,
    face_id     TEXT NOT NULL,
    created_at  REAL NOT NULL,
    expires_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS meta (
    key         TEXT PRIMARY KEY,
    value       TEXT
);

CREATE TABLE IF NOT EXISTS processed_files (
    file_id     TEXT PRIMARY KEY,
    file_name   TEXT,
    processed_at REAL NOT NULL
);
"""


def _db_path() -> str:
    return get_settings().database_path


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    path = _db_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def reset_clusters() -> None:
    """Clear previous results before a new processing run."""
    with get_conn() as conn:
        conn.execute("DELETE FROM cluster_files;")
        conn.execute("DELETE FROM clusters;")
        conn.execute("DELETE FROM tokens;")


def save_clusters(clusters: dict[str, dict]) -> None:
    """Persist clustering output.

    `clusters` maps face_id -> {"centroid": list[float],
                                "file_ids": list[str],
                                "file_names": dict[file_id, name],
                                "face_count": int}
    """
    now = time.time()
    with get_conn() as conn:
        for face_id, data in clusters.items():
            conn.execute(
                "INSERT OR REPLACE INTO clusters (face_id, centroid, face_count, created_at) "
                "VALUES (?, ?, ?, ?);",
                (face_id, json.dumps(data["centroid"]), int(data.get("face_count", 0)), now),
            )
            file_names = data.get("file_names", {})
            rows = [
                (face_id, file_id, file_names.get(file_id))
                for file_id in data["file_ids"]
            ]
            conn.executemany(
                "INSERT OR REPLACE INTO cluster_files (face_id, file_id, file_name) "
                "VALUES (?, ?, ?);",
                rows,
            )


def load_centroids() -> dict[str, list[float]]:
    with get_conn() as conn:
        rows = conn.execute("SELECT face_id, centroid FROM clusters;").fetchall()
    return {r["face_id"]: json.loads(r["centroid"]) for r in rows}


def load_clusters() -> dict[str, dict]:
    """Load all cluster data including centroids, file mappings, and counts."""
    with get_conn() as conn:
        cluster_rows = conn.execute(
            "SELECT face_id, centroid, face_count FROM clusters;"
        ).fetchall()
        
        clusters: dict[str, dict] = {}
        for row in cluster_rows:
            face_id = row["face_id"]
            clusters[face_id] = {
                "centroid": json.loads(row["centroid"]),
                "face_count": row["face_count"],
                "file_ids": [],
                "file_names": {},
            }
        
        # Load file associations
        file_rows = conn.execute(
            "SELECT face_id, file_id, file_name FROM cluster_files;"
        ).fetchall()
        
        for row in file_rows:
            face_id = row["face_id"]
            if face_id in clusters:
                clusters[face_id]["file_ids"].append(row["file_id"])
                if row["file_name"]:
                    clusters[face_id]["file_names"][row["file_id"]] = row["file_name"]
    
    return clusters


def get_files_for_face(face_id: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT file_id, file_name FROM cluster_files WHERE face_id = ? ORDER BY file_name;",
            (face_id,),
        ).fetchall()
    return [{"file_id": r["file_id"], "file_name": r["file_name"]} for r in rows]


def cluster_count() -> int:
    with get_conn() as conn:
        row = conn.execute("SELECT COUNT(*) AS c FROM clusters;").fetchone()
    return int(row["c"])


def list_cluster_summaries() -> list[dict]:
    """face_id + counts only — no embedding payloads (fast faces grid)."""
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT c.face_id AS face_id,
                   c.face_count AS face_count,
                   COUNT(cf.file_id) AS photo_count
            FROM clusters c
            LEFT JOIN cluster_files cf ON cf.face_id = c.face_id
            GROUP BY c.face_id
            ORDER BY c.face_count DESC, c.face_id ASC;
            """
        ).fetchall()
    return [
        {
            "face_id": r["face_id"],
            "face_count": int(r["face_count"] or 0),
            "photo_count": int(r["photo_count"] or 0),
        }
        for r in rows
    ]


# --- tokens -----------------------------------------------------------------

def create_token(face_id: str) -> str:
    token = secrets.token_urlsafe(24)
    now = time.time()
    ttl = get_settings().token_ttl_seconds
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO tokens (token, face_id, created_at, expires_at) VALUES (?, ?, ?, ?);",
            (token, face_id, now, now + ttl),
        )
    return token


def resolve_token(token: str) -> str | None:
    """Return the face_id for a valid, unexpired token, else None."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT face_id, expires_at FROM tokens WHERE token = ?;",
            (token,),
        ).fetchone()
    if row is None:
        return None
    if row["expires_at"] < time.time():
        return None
    return row["face_id"]


def purge_expired_tokens() -> int:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM tokens WHERE expires_at < ?;", (time.time(),))
        return cur.rowcount


def set_meta(key: str, value: str) -> None:
    with get_conn() as conn:
        conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?);", (key, value))


def get_meta(key: str) -> str | None:
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?;", (key,)).fetchone()
    return row["value"] if row else None


def delete_meta(key: str) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM meta WHERE key = ?;", (key,))


# --- processed files tracking -----------------------------------------------

def get_processed_file_ids() -> set[str]:
    """Return set of all file IDs that have been processed."""
    with get_conn() as conn:
        rows = conn.execute("SELECT file_id FROM processed_files;").fetchall()
    return {r["file_id"] for r in rows}


def mark_files_processed(file_metadata: list[dict]) -> None:
    """Mark files as processed in the database."""
    now = time.time()
    with get_conn() as conn:
        rows = [(f["id"], f.get("name"), now) for f in file_metadata]
        conn.executemany(
            "INSERT OR REPLACE INTO processed_files (file_id, file_name, processed_at) "
            "VALUES (?, ?, ?);",
            rows,
        )
