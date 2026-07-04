"""Admin endpoints: kick off processing and poll status."""

from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException

from app.config import get_settings
from app.models.schemas import (
    JobStatus,
    PollingRequest,
    PollingResponse,
    PollingStatusResponse,
    ProcessRequest,
    ProcessResponse,
)
from app.services import processing

router = APIRouter(prefix="/api/drive", tags=["drive"])


def _check_admin(token: str | None) -> None:
    expected = get_settings().admin_token
    if not token or token != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing admin token.")


@router.post("/process", response_model=ProcessResponse)
def process(req: ProcessRequest, x_admin_token: str | None = Header(default=None)) -> ProcessResponse:
    _check_admin(x_admin_token)
    try:
        # Validate the link early so the admin gets immediate feedback.
        from app.services import drive_service

        drive_service.extract_folder_id(req.drive_link)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    job_id = processing.start_job(req.drive_link, incremental=req.incremental)
    mode = "incremental" if req.incremental else "full"
    return ProcessResponse(
        job_id=job_id, 
        status="pending", 
        message=f"Processing started ({mode} mode)."
    )


@router.get("/status/{job_id}", response_model=JobStatus)
def status(job_id: str) -> JobStatus:
    job = processing.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown job id.")
    return job


@router.post("/polling/start", response_model=PollingResponse)
def start_polling(
    req: PollingRequest, 
    x_admin_token: str | None = Header(default=None)
) -> PollingResponse:
    """Start continuous polling for new images in the Drive folder."""
    _check_admin(x_admin_token)
    
    try:
        from app.services import drive_service
        drive_service.extract_folder_id(req.drive_link)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    
    result = processing.start_polling(req.drive_link, req.interval_seconds)
    return PollingResponse(**result)


@router.post("/polling/stop", response_model=PollingResponse)
def stop_polling(x_admin_token: str | None = Header(default=None)) -> PollingResponse:
    """Stop the active polling loop."""
    _check_admin(x_admin_token)
    result = processing.stop_polling()
    return PollingResponse(**result)


@router.get("/polling/status", response_model=PollingStatusResponse)
def polling_status() -> PollingStatusResponse:
    """Get the current polling status."""
    result = processing.is_polling()
    return PollingStatusResponse(**result)
