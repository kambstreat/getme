"""GetME! FastAPI application entry point.

API-first: JSON routes always load. Browser UI is optional via GETME_UI
(default: clients/web-agent). Set GETME_UI= for API-only mode so other
frontends (studio, desktop app, CLI) can use the same backend.
"""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.database import db
from app.http_utils import path_prefix
from app.relay_client import relay_enabled, start_relay_client, stop_relay_client
from app.routers import auth, clusters, drive, local, match

ROOT_DIR = os.path.dirname(os.path.dirname(__file__))
DATA_DIR = os.path.join(ROOT_DIR, "data")
LOG_FILE = "data/getme.log"

app = FastAPI(title="GetME!", version="0.1.0")

# Allow alternate frontends (desktop webview, another origin) to call the API.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.environ.get("GETME_CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


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
    ui = get_settings().resolved_ui_dir
    logging.getLogger(__name__).info(
        "UI: %s", ui if ui else "API-only (GETME_UI empty or missing)"
    )


@app.on_event("shutdown")
async def _shutdown() -> None:
    await stop_relay_client()


app.include_router(auth.router)
app.include_router(drive.router)
app.include_router(local.router)
app.include_router(match.router)
app.include_router(clusters.router)


@app.get("/health")
def health() -> dict:
    settings = get_settings()
    return {
        "status": "ok",
        "clusters": db.cluster_count(),
        "path_prefix": path_prefix(),
        "relay": relay_enabled(),
        "ui": settings.resolved_ui_dir is not None,
        "ui_dir": settings.getme_ui or None,
    }


def _ui_dir() -> str:
    path = get_settings().resolved_ui_dir
    if not path:
        raise HTTPException(
            status_code=404,
            detail="No UI mounted. Set GETME_UI to a client folder (e.g. clients/web-agent), or use the JSON API.",
        )
    return path


def _html_prefix(request: Request | None) -> str:
    prefix = path_prefix()
    if not prefix and request is not None:
        prefix = request.headers.get("x-forwarded-prefix", "").rstrip("/")
    return prefix


def _serve_html(filename: str, request: Request | None = None) -> HTMLResponse:
    prefix = _html_prefix(request)
    path = os.path.join(_ui_dir(), filename)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail=f"UI page missing: {filename}")
    with open(path, encoding="utf-8") as f:
        html = f.read().replace("__BASE_PATH__", prefix)
    return HTMLResponse(
        html,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


def _register_ui_routes() -> None:
    """Page routes only when a UI client directory is configured."""
    if not get_settings().resolved_ui_dir:
        return

    @app.get("/")
    def index(request: Request) -> HTMLResponse:
        return _serve_html("index.html", request)

    @app.get("/admin")
    def admin(request: Request) -> HTMLResponse:
        return _serve_html("admin.html", request)

    @app.get("/faces")
    def faces(request: Request) -> HTMLResponse:
        return _serve_html("faces.html", request)

    @app.get("/person")
    def person(request: Request) -> HTMLResponse:
        return _serve_html("person.html", request)

    @app.get("/clusters")
    def clusters_page(request: Request) -> HTMLResponse:
        return _serve_html("clusters.html", request)

    app.mount("/static", StaticFiles(directory=_ui_dir()), name="static")


_register_ui_routes()

# Runtime media (not a frontend — always available for API clients).
os.makedirs(os.path.join(DATA_DIR, "centroids"), exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "allfaces"), exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "face_thumbs"), exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "photo_thumbs"), exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "fullpics"), exist_ok=True)
app.mount("/data/centroids", StaticFiles(directory=os.path.join(DATA_DIR, "centroids")), name="centroids")
app.mount("/data/allfaces", StaticFiles(directory=os.path.join(DATA_DIR, "allfaces")), name="allfaces")
app.mount("/data/face_thumbs", StaticFiles(directory=os.path.join(DATA_DIR, "face_thumbs")), name="face_thumbs")
app.mount("/data/photo_thumbs", StaticFiles(directory=os.path.join(DATA_DIR, "photo_thumbs")), name="photo_thumbs")
app.mount("/data/fullpics", StaticFiles(directory=os.path.join(DATA_DIR, "fullpics")), name="fullpics")
