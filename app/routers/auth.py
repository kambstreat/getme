"""Google account connection endpoints (OAuth authorization-code flow).

Flow: admin clicks "Connect Google Drive" -> GET /start returns Google's
consent URL -> browser visits it -> Google redirects to /callback with a
code -> we exchange it for tokens, persist them, and bounce back to /admin.
"""

from __future__ import annotations

import logging
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.http_utils import url_path
from app.services import google_auth

logger = logging.getLogger("getme.auth")

router = APIRouter(prefix="/api/auth/google", tags=["auth"])

# OAuth state -> PKCE code_verifier for flows awaiting the Google callback.
# Process-local, like the job registry; fine for a single-admin app.
_pending_states: dict[str, str | None] = {}


def _check_admin(token: str | None) -> None:
    expected = get_settings().admin_token
    if not token or token != expected:
        raise HTTPException(status_code=401, detail="Invalid or missing admin token.")


def _oauth_return_url(*, success: bool, error: str | None = None) -> str:
    """Return to studio when configured; otherwise fall back to admin page."""
    studio = get_settings().studio_url.strip()
    if studio:
        params = {"drive_connected": "1"} if success else {"drive_error": error or "unknown"}
        sep = "&" if "?" in studio else "?"
        return studio + sep + urlencode(params)
    if success:
        return url_path("/admin?drive_connected=1")
    return url_path(f"/admin?drive_error={quote(error or 'unknown')}")


@router.get("/start")
def start(x_admin_token: str | None = Header(default=None)) -> dict:
    _check_admin(x_admin_token)
    try:
        auth_url, state, code_verifier = google_auth.authorization_url()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _pending_states[state] = code_verifier
    return {"auth_url": auth_url}


@router.get("/callback")
def callback(request: Request) -> RedirectResponse:
    params = request.query_params
    if params.get("error"):
        logger.error("Google returned an OAuth error: %s", params["error"])
        return RedirectResponse(_oauth_return_url(success=False, error=params["error"]))

    state = params.get("state")
    if not state or state not in _pending_states:
        logger.error(
            "OAuth callback with unknown state (server restarted mid-flow?). "
            "Pending states: %d", len(_pending_states),
        )
        return RedirectResponse(
            _oauth_return_url(success=False, error="Sign-in session expired - click Connect again.")
        )
    code_verifier = _pending_states.pop(state)

    try:
        flow = google_auth.build_flow(state=state)
        if code_verifier:
            flow.code_verifier = code_verifier
        flow.fetch_token(authorization_response=str(request.url))
    except Exception as exc:  # noqa: BLE001 - surface OAuth errors to the admin
        logger.exception("OAuth token exchange failed")
        detail = f"{type(exc).__name__}: {exc}"[:200]
        return RedirectResponse(_oauth_return_url(success=False, error=detail))

    google_auth.save_credentials(flow.credentials)
    logger.info("Google Drive account connected.")
    return RedirectResponse(_oauth_return_url(success=True))


@router.get("/status")
def status() -> dict:
    return {"connected": google_auth.is_connected()}


@router.post("/disconnect")
def disconnect(x_admin_token: str | None = Header(default=None)) -> dict:
    _check_admin(x_admin_token)
    google_auth.clear_credentials()
    return {"connected": False}
