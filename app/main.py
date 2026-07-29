"""GetME! FastAPI application entry point."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.database import db
from app.http_utils import path_prefix
from app.relay_client import relay_enabled, start_relay_client, stop_relay_client
from app.routers import auth, clusters, drive, match

STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
LOG_FILE = "data/getme.log"

app = FastAPI(title="GetME!", version="0.1.0")


def _setup_logging() -> None:
    """Mirror app logs to file and terminal."""
    os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not any(isinstance(h, logging.FileHandler) for h in root.handlers):
        fh = logging.FileHandler(LOG_FILE)
        fh.setFormatter(fmt)
        root.addHandler(fh)
    if not any(isinstance(h, logging.StreamHandler) for h in root.handlers):
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        root.addHandler(sh)


@app.on_event("startup")
async def _startup() -> None:
    _setup_logging()
    db.init_db()
    db.purge_expired_tokens()
    await start_relay_client(app)


@app.on_event("shutdown")
async def _shutdown() -> None:
    await stop_relay_client()


app.include_router(auth.router)
app.include_router(drive.router)
app.include_router(match.router)
app.include_router(clusters.router)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "clusters": db.cluster_count(),
        "path_prefix": path_prefix(),
        "relay": relay_enabled(),
    }


def _html_prefix(request: Request | None) -> str:
    prefix = path_prefix()
    if not prefix and request is not None:
        prefix = request.headers.get("x-forwarded-prefix", "").rstrip("/")
    return prefix


def _serve_html(filename: str, request: Request | None = None) -> HTMLResponse:
    prefix = _html_prefix(request)
    path = os.path.join(STATIC_DIR, filename)
    with open(path, encoding="utf-8") as f:
        html = f.read().replace("__BASE_PATH__", prefix)
    return HTMLResponse(
        html,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/")
def index(request: Request) -> HTMLResponse:
    return _serve_html("index.html", request)


@app.get("/admin")
def admin(request: Request) -> HTMLResponse:
    return _serve_html("admin.html", request)


# Static assets (css/js) + local face crop folders for the clusters viewer.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
os.makedirs(os.path.join(DATA_DIR, "centroids"), exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "allfaces"), exist_ok=True)
app.mount("/data/centroids", StaticFiles(directory=os.path.join(DATA_DIR, "centroids")), name="centroids")
app.mount("/data/allfaces", StaticFiles(directory=os.path.join(DATA_DIR, "allfaces")), name="allfaces")
os.makedirs(os.path.join(DATA_DIR, "fullpics"), exist_ok=True)
app.mount("/data/fullpics", StaticFiles(directory=os.path.join(DATA_DIR, "fullpics")), name="fullpics")
