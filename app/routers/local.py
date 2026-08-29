"""Local testing endpoints: process photos from a folder on this machine."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.models.schemas import JobStatus, LocalProcessRequest, ProcessResponse
from app.services import local_photos, processing

router = APIRouter(prefix="/api/local", tags=["local"])


@router.get("/status")
def local_status() -> dict:
    """Show the active test-photos folder and how many images are in it."""
    path = local_photos.resolved_dir()
    images = local_photos.list_images() if path.is_dir() else []
    return {
        "dir": str(path),
        "exists": path.is_dir(),
        "image_count": len(images),
        "images": [img["name"] for img in images],
    }


@router.post("/process", response_model=ProcessResponse)
def process_local(req: LocalProcessRequest = LocalProcessRequest()) -> ProcessResponse:
    folder = (req.folder or "").strip()
    if folder:
        try:
            path = local_photos.set_dir(folder)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    else:
        path = local_photos.resolved_dir()
        if not path.is_dir():
            raise HTTPException(status_code=400, detail=f"Not a folder: {path}")

    incremental = bool(req.incremental)
    images = local_photos.list_images()
    if not images and not incremental:
        raise HTTPException(
            status_code=400,
            detail=f"No images in {path}. Add JPG/PNG/WebP files and try again.",
        )
    job_id = processing.start_local_job(incremental=incremental)
    mode = "incremental" if incremental else "full"
    return ProcessResponse(
        job_id=job_id,
        status="pending",
        message=f"Local processing started ({mode} mode) from {path}.",
    )


@router.get("/job/{job_id}", response_model=JobStatus)
def local_job_status(job_id: str) -> JobStatus:
    job = processing.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id.")
    return job
