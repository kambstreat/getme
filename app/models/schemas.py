"""Pydantic request/response models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ProcessRequest(BaseModel):
    drive_link: str = Field(..., description="Google Drive folder link or ID containing event photos.")
    incremental: bool = Field(
        default=False,
        description="If True, only process new files not seen before."
    )


class ProcessResponse(BaseModel):
    job_id: str
    status: str
    message: str


class JobStatus(BaseModel):
    job_id: str
    status: Literal["pending", "listing", "processing", "clustering", "done", "error"]
    total_files: int = 0
    processed_files: int = 0
    faces_found: int = 0
    clusters: int = 0
    error: str | None = None

    @property
    def percent(self) -> float:
        if self.total_files == 0:
            return 0.0
        return round(100.0 * self.processed_files / self.total_files, 1)


class MatchResult(BaseModel):
    matched: bool
    photo_count: int = 0
    confidence: float | None = None
    token: str | None = None
    message: str | None = None


class GalleryItem(BaseModel):
    index: int
    file_id: str
    name: str
    thumb_url: str


class GalleryResponse(BaseModel):
    token: str
    photo_count: int
    items: list[GalleryItem]


class PollingRequest(BaseModel):
    drive_link: str = Field(..., description="Google Drive folder link or ID to monitor.")
    interval_seconds: int = Field(
        default=300, 
        ge=60, 
        le=3600,
        description="Polling interval in seconds (min: 60, max: 3600)."
    )


class PollingResponse(BaseModel):
    success: bool
    message: str | None = None
    error: str | None = None
    folder_id: str | None = None
    interval_seconds: int | None = None


class PollingStatusResponse(BaseModel):
    active: bool
    folder_id: str | None = None
