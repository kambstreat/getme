"""User endpoints: selfie match, gallery, thumbnails, ZIP download."""

from __future__ import annotations

import io

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse

from app.database import db
from app.http_utils import url_path
from app.models.schemas import GalleryItem, GalleryResponse, MatchResult
from app.services import match_service

router = APIRouter(prefix="/api", tags=["match"])

MAX_SELFIE_BYTES = 15 * 1024 * 1024  # 15 MB upload cap


@router.post("/match", response_model=MatchResult)
async def match(selfie: UploadFile = File(...)) -> MatchResult:
    if selfie.content_type is None or not selfie.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="Please upload an image file.")
    raw = await selfie.read()
    if len(raw) > MAX_SELFIE_BYTES:
        raise HTTPException(status_code=413, detail="Image too large (max 15 MB).")
    result = match_service.match_selfie(io.BytesIO(raw))
    return MatchResult(**result)


@router.get("/gallery/{token}", response_model=GalleryResponse)
def gallery(token: str) -> GalleryResponse:
    face_id = db.resolve_token(token)
    if face_id is None:
        raise HTTPException(status_code=404, detail="Invalid or expired link.")
    items = match_service.gallery_items(face_id)
    return GalleryResponse(
        token=token,
        photo_count=len(items),
        items=[
            GalleryItem(
                index=i,
                file_id=item["file_id"],
                name=item["name"],
                thumb_url=url_path(f"/api/thumb/{token}/{i}"),
            )
            for i, item in enumerate(items)
        ],
    )


@router.get("/thumb/{token}/{index}")
def thumb(token: str, index: int) -> Response:
    face_id = db.resolve_token(token)
    if face_id is None:
        raise HTTPException(status_code=404, detail="Invalid or expired link.")
    items = match_service.gallery_items(face_id)
    if index < 0 or index >= len(items):
        raise HTTPException(status_code=404, detail="Photo not found.")
    data = match_service.make_thumbnail(items[index]["file_id"])
    return Response(content=data, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})


@router.get("/download/{token}")
def download(token: str) -> StreamingResponse:
    face_id = db.resolve_token(token)
    if face_id is None:
        raise HTTPException(status_code=404, detail="Invalid or expired link.")
    return StreamingResponse(
        match_service.stream_zip(face_id),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=my_photos.zip"},
    )
