"""GetME! FastAPI application entry point."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.database import db
from app.routers import auth, drive, match

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
LOG_FILE = "data/getme.log"

app = FastAPI(title="GetME!", version="0.1.0")


def _setup_logging() -> None:
    """Mirror app logs to a file so errors survive terminal scrollback."""
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    handler = logging.FileHandler(LOG_FILE)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)


@app.on_event("startup")
def _startup() -> None:
    _setup_logging()
    db.init_db()
    db.purge_expired_tokens()


app.include_router(auth.router)
app.include_router(drive.router)
app.include_router(match.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "clusters": db.cluster_count()}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(
        os.path.join(STATIC_DIR, "index.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/admin")
def admin() -> FileResponse:
    return FileResponse(
        os.path.join(STATIC_DIR, "admin.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


# Static assets (css/js) served under /static.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
