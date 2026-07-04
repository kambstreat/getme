"""Background processing orchestration and in-memory job tracking.

A processing run: list images in the Drive folder -> stream + extract faces
(sequentially; ArcFace/TensorFlow does not fork cleanly for multiprocessing)
-> cluster all embeddings -> persist clusters to SQLite.

Job state is kept in a process-local registry. For the single-machine,
single-event scope this is sufficient; a restart simply requires re-running.

Polling mode: continuously monitors a Drive folder for new images and processes
them incrementally without re-processing existing images.
"""

from __future__ import annotations

import threading
import time
import uuid

from app.database import db
from app.models.schemas import JobStatus
from app.services import drive_service, face_service

_jobs: dict[str, JobStatus] = {}
_lock = threading.Lock()

# Polling state
_polling_active = False
_polling_thread: threading.Thread | None = None
_polling_folder_id: str | None = None


def get_job(job_id: str) -> JobStatus | None:
    with _lock:
        job = _jobs.get(job_id)
        # return a copy so callers don't mutate shared state
        return job.model_copy() if job else None


def latest_done_job() -> JobStatus | None:
    with _lock:
        done = [j for j in _jobs.values() if j.status == "done"]
    return done[-1].model_copy() if done else None


def _update(job_id: str, **fields) -> None:
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        for key, value in fields.items():
            setattr(job, key, value)


def start_job(drive_link: str, incremental: bool = False) -> str:
    """Start a processing job.
    
    Args:
        drive_link: Google Drive folder link or ID
        incremental: If True, only process new files not seen before
    """
    job_id = uuid.uuid4().hex
    with _lock:
        _jobs[job_id] = JobStatus(job_id=job_id, status="pending")
    thread = threading.Thread(
        target=_run_job, 
        args=(job_id, drive_link, incremental), 
        daemon=True
    )
    thread.start()
    return job_id


def _run_job(job_id: str, drive_link: str, incremental: bool = False) -> None:
    try:
        folder_id = drive_service.extract_folder_id(drive_link)
        service = drive_service.build_service()

        _update(job_id, status="listing")
        images = drive_service.list_images(service, folder_id)
        
        # Filter out already processed files if in incremental mode
        if incremental:
            processed_ids = db.get_processed_file_ids()
            new_images = [img for img in images if img["id"] not in processed_ids]
            _update(
                job_id, 
                total_files=len(new_images), 
                status="processing"
            )
            
            if not new_images:
                _update(
                    job_id, 
                    status="done", 
                    error="No new images to process.",
                    clusters=db.cluster_count()
                )
                return
            
            images_to_process = new_images
        else:
            _update(job_id, total_files=len(images), status="processing")
            images_to_process = images

        if not images_to_process:
            _update(job_id, status="error", error="No images found in the Drive folder.")
            return

        all_faces: list[dict] = []
        processed_metadata: list[dict] = []
        
        for i, meta in enumerate(images_to_process, start=1):
            try:
                buffer = drive_service.stream_file(service, meta["id"])
                faces = face_service.extract_faces(buffer, meta["id"], meta.get("name"))
                all_faces.extend(faces)
                processed_metadata.append(meta)
            except Exception:
                # Skip unreadable/corrupt files but keep going.
                pass
            _update(job_id, processed_files=i, faces_found=len(all_faces))

        _update(job_id, status="clustering")
        
        if incremental:
            # Load existing clusters and merge new faces
            existing_clusters = db.load_clusters()
            updated_clusters = face_service.cluster_faces_incremental(all_faces, existing_clusters)
            # Save without resetting existing data
            db.save_clusters(updated_clusters)
        else:
            # Full reset and re-cluster everything
            clusters = face_service.cluster_faces(all_faces)
            db.reset_clusters()
            db.save_clusters(clusters)
        
        # Mark files as processed
        db.mark_files_processed(processed_metadata)
        
        _update(job_id, status="done", clusters=db.cluster_count())
    except FileNotFoundError as exc:
        _update(job_id, status="error", error=f"Service account file missing: {exc}")
    except Exception as exc:  # noqa: BLE001 - surface any failure to the UI
        _update(job_id, status="error", error=str(exc))


# --- Polling for continuous incoming images -----------------------------------

def is_polling() -> dict:
    """Return polling status."""
    global _polling_active, _polling_folder_id
    with _lock:
        return {
            "active": _polling_active,
            "folder_id": _polling_folder_id,
        }


def start_polling(drive_link: str, interval_seconds: int = 300) -> dict:
    """Start polling a Drive folder for new images at regular intervals.
    
    Args:
        drive_link: Google Drive folder link or ID to monitor
        interval_seconds: How often to check for new images (default: 5 minutes)
    
    Returns:
        Status dict with success/error information
    """
    global _polling_active, _polling_thread, _polling_folder_id
    
    with _lock:
        if _polling_active:
            return {
                "success": False,
                "error": "Polling is already active. Stop it first before starting a new one."
            }
    
    try:
        folder_id = drive_service.extract_folder_id(drive_link)
    except Exception as exc:
        return {"success": False, "error": f"Invalid drive link: {exc}"}
    
    def _polling_loop():
        global _polling_active
        while True:
            with _lock:
                if not _polling_active:
                    break
            
            try:
                # Run an incremental job
                job_id = start_job(drive_link, incremental=True)
                
                # Wait for job to complete (with timeout)
                timeout = 3600  # 1 hour max per job
                elapsed = 0
                while elapsed < timeout:
                    job = get_job(job_id)
                    if job and job.status in ["done", "error"]:
                        break
                    time.sleep(5)
                    elapsed += 5
                
            except Exception:
                # Log error but keep polling
                pass
            
            # Sleep until next poll
            time.sleep(interval_seconds)
    
    with _lock:
        _polling_active = True
        _polling_folder_id = folder_id
    
    _polling_thread = threading.Thread(target=_polling_loop, daemon=True)
    _polling_thread.start()
    
    return {
        "success": True,
        "message": f"Polling started. Checking for new images every {interval_seconds} seconds.",
        "folder_id": folder_id,
        "interval_seconds": interval_seconds,
    }


def stop_polling() -> dict:
    """Stop the active polling loop."""
    global _polling_active, _polling_folder_id
    
    with _lock:
        if not _polling_active:
            return {"success": False, "error": "No active polling to stop."}
        
        _polling_active = False
        _polling_folder_id = None
    
    return {
        "success": True,
        "message": "Polling stopped.",
    }
