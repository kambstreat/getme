"""Google OAuth ("Sign in with Google") credential management.

Testing-mode flow: the developer registers one OAuth client in Google Cloud
Console and adds organizers as test users. Each installation connects a Google
account through the browser; the resulting token (access + refresh) is stored
in the SQLite meta table and refreshed automatically on use.

Note: while the OAuth app is in "testing" status, Google expires refresh
tokens after 7 days, so the account must be reconnected weekly.
"""

from __future__ import annotations

import json
import os

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow

from app.config import get_settings
from app.database import db

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

_TOKEN_META_KEY = "google_oauth_token"

# oauthlib refuses plain-http redirects by default; required for localhost.
os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")
# Google may grant extra scopes (e.g. openid); don't treat that as an error.
os.environ.setdefault("OAUTHLIB_RELAX_TOKEN_SCOPE", "1")


def redirect_uri() -> str:
    return get_settings().public_base_url.rstrip("/") + "/api/auth/google/callback"


def build_flow(state: str | None = None) -> Flow:
    """Build the authorization-code flow from the OAuth client secrets file."""
    settings = get_settings()
    if not os.path.exists(settings.google_oauth_client_file):
        raise FileNotFoundError(
            f"OAuth client file not found: {settings.google_oauth_client_file!r}. "
            "Download it from Google Cloud Console and set GOOGLE_OAUTH_CLIENT_FILE."
        )
    return Flow.from_client_secrets_file(
        settings.google_oauth_client_file,
        scopes=SCOPES,
        state=state,
        redirect_uri=redirect_uri(),
    )


def authorization_url() -> tuple[str, str, str | None]:
    """Return (auth_url, state, code_verifier) for the consent redirect.

    The PKCE code_verifier must be presented again during the token exchange,
    so the caller has to persist it until the callback arrives.
    """
    flow = build_flow()
    auth_url, state = flow.authorization_url(
        access_type="offline",  # ask for a refresh token
        prompt="consent",  # re-issue a refresh token even on reconnect
        include_granted_scopes="true",
    )
    return auth_url, state, getattr(flow, "code_verifier", None)


def save_credentials(creds: Credentials) -> None:
    db.set_meta(_TOKEN_META_KEY, creds.to_json())


def load_credentials() -> Credentials | None:
    """Load stored credentials, refreshing them if expired.

    Returns None when no account is connected. Raises on refresh failure
    (e.g. token revoked or expired after 7 days in testing mode).
    """
    raw = db.get_meta(_TOKEN_META_KEY)
    if not raw:
        return None
    creds = Credentials.from_authorized_user_info(json.loads(raw), scopes=SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        save_credentials(creds)
    return creds


def clear_credentials() -> None:
    db.delete_meta(_TOKEN_META_KEY)


def is_connected() -> bool:
    return db.get_meta(_TOKEN_META_KEY) is not None
