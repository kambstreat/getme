"""Build the Mac-first one-command install script for videographers."""

from __future__ import annotations

import os
import shlex

GETME_REPO = os.environ.get("GETME_REPO", "https://github.com/kambstreat/getme.git")
OAUTH_CLIENT_URL = os.environ.get("GETME_OAUTH_CLIENT_URL", "").strip()


def build_install_script(
    *,
    public_origin: str,
    session_id: str,
    agent_secret: str,
    repo: str | None = None,
    oauth_client_url: str | None = None,
) -> str:
    """Return a bash installer tailored to this session."""
    repo = repo or GETME_REPO
    oauth_url = oauth_client_url if oauth_client_url is not None else OAUTH_CLIENT_URL
    # Quote for safe embedding in the generated bash script
    relay_url = shlex.quote(public_origin.rstrip("/"))
    sid = shlex.quote(session_id)
    secret = shlex.quote(agent_secret)
    repo_q = shlex.quote(repo)
    oauth_q = shlex.quote(oauth_url) if oauth_url else '""'

    return f"""#!/usr/bin/env bash
set -euo pipefail

echo ""
echo "========================================"
echo "  GetME! — Mac installer"
echo "========================================"
echo ""
echo "This installs GetME on your Mac and connects it to your studio."
echo "First run can take 5–15 minutes (downloads face models)."
echo "Keep this Terminal window open during your event."
echo ""

INSTALL_DIR="${{GETME_INSTALL_DIR:-$HOME/getme-agent}}"
RELAY_URL={relay_url}
SESSION_ID={sid}
AGENT_SECRET={secret}
REPO_URL={repo_q}
OAUTH_CLIENT_URL={oauth_q}

step() {{ echo ""; echo "==> $*"; }}
die() {{ echo ""; echo "ERROR: $*" >&2; exit 1; }}

# --- OS hint -----------------------------------------------------------------
OS="$(uname -s 2>/dev/null || echo unknown)"
if [[ "$OS" == "Darwin" ]]; then
  echo "Detected macOS."
elif [[ "$OS" == "Linux" ]]; then
  echo "Detected Linux (Mac-first installer; continuing)."
else
  echo "Warning: untested OS ($OS). Continuing anyway."
fi

# --- Tools: curl, git --------------------------------------------------------
command -v curl >/dev/null 2>&1 || die "curl is required."

ensure_git() {{
  if command -v git >/dev/null 2>&1; then
    return 0
  fi
  step "git not found"
  if [[ "$OS" == "Darwin" ]]; then
    if command -v brew >/dev/null 2>&1; then
      echo "Installing git via Homebrew…"
      brew install git
    else
      echo "Opening Xcode Command Line Tools installer (accept the dialog)…"
      xcode-select --install 2>/dev/null || true
      die "Install the Command Line Tools (or Homebrew), then re-run this command."
    fi
  else
    die "Install git, then re-run this command."
  fi
  command -v git >/dev/null 2>&1 || die "git still not found after install."
}}
ensure_git

# --- Python 3.10–3.12 (TensorFlow has no 3.14 wheels) ------------------------
find_python() {{
  local candidate
  for candidate in python3.12 python3.11 python3.10; do
    if command -v "$candidate" >/dev/null 2>&1; then
      if "$candidate" -c 'import sys; raise SystemExit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)' 2>/dev/null; then
        echo "$candidate"
        return 0
      fi
    fi
  done
  return 1
}}

ensure_python() {{
  local py
  if py="$(find_python)"; then
    echo "$py"
    return 0
  fi
  echo "==> Python 3.10–3.12 not found" >&2
  if [[ "$OS" == "Darwin" ]]; then
    if ! command -v brew >/dev/null 2>&1; then
      echo "" >&2
      echo "Homebrew is required to install Python automatically." >&2
      echo "Paste this, then re-run the GetME install command:" >&2
      echo "" >&2
      echo '  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"' >&2
      echo "" >&2
      die "Homebrew not installed."
    fi
    echo "Installing Python 3.12 via Homebrew (may take a few minutes)…" >&2
    brew install python@3.12
    if [[ -x /opt/homebrew/bin/python3.12 ]]; then
      export PATH="/opt/homebrew/bin:$PATH"
    elif [[ -x /usr/local/bin/python3.12 ]]; then
      export PATH="/usr/local/bin:$PATH"
    fi
  else
    die "Install Python 3.10, 3.11, or 3.12, then re-run."
  fi
  if py="$(find_python)"; then
    echo "$py"
    return 0
  fi
  die "Python 3.10–3.12 still not found after install."
}}

PYTHON="$(ensure_python)"
step "Using $PYTHON ($($PYTHON --version 2>&1))"

# --- Clone / update repo -----------------------------------------------------
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

if [[ ! -d .git ]]; then
  step "Downloading GetME into $INSTALL_DIR"
  if [[ -n "$(ls -A . 2>/dev/null || true)" ]]; then
    die "Directory $INSTALL_DIR is not empty and is not a GetME clone. Move it aside or set GETME_INSTALL_DIR."
  fi
  git clone "$REPO_URL" .
else
  step "GetME already present — updating"
  git fetch --quiet origin 2>/dev/null || true
  git pull --ff-only 2>/dev/null || echo "(skipped git pull — using local copy)"
fi

# --- Virtualenv --------------------------------------------------------------
if [[ -d .venv ]]; then
  PY_MINOR="$(.venv/bin/python -c 'import sys; print(sys.version_info.minor)' 2>/dev/null || echo 99)"
  if [[ "$PY_MINOR" -ge 14 ]]; then
    step "Removing incompatible Python 3.$PY_MINOR venv"
    rm -rf .venv
  fi
fi
if [[ ! -d .venv ]]; then
  step "Creating virtual environment"
  "$PYTHON" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
PY_MINOR="$(python -c 'import sys; print(sys.version_info.minor)')"
if [[ "$PY_MINOR" -ge 14 ]]; then
  die "This venv is Python 3.$PY_MINOR. Remove it and re-run: rm -rf $INSTALL_DIR/.venv"
fi

# --- Dependencies ------------------------------------------------------------
step "Installing packages (first time ~5–15 min — TensorFlow is large)"
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt

# --- OAuth client (optional URL from relay operator) -------------------------
if [[ -n "$OAUTH_CLIENT_URL" ]]; then
  step "Downloading Google OAuth client"
  curl -fsSL "$OAUTH_CLIENT_URL" -o oauth_client.json \\
    || die "Could not download oauth_client.json from GETME_OAUTH_CLIENT_URL."
  echo "Saved oauth_client.json"
elif [[ ! -f oauth_client.json ]]; then
  echo ""
  echo "NOTE: oauth_client.json not found. Connect Google Drive will fail until"
  echo "the operator provides GETME_OAUTH_CLIENT_URL on the relay, or you copy"
  echo "oauth_client.json into $INSTALL_DIR"
  echo ""
fi

# --- Write / update .env (portable — no GNU sed) -----------------------------
step "Writing relay session config"
export RELAY_URL SESSION_ID AGENT_SECRET
python - <<'PY'
import os
from pathlib import Path

env_path = Path(".env")
lines = env_path.read_text(encoding="utf-8").splitlines() if env_path.exists() else []
updates = {{
    "RELAY_URL": os.environ["RELAY_URL"],
    "RELAY_SESSION": os.environ["SESSION_ID"],
    "RELAY_AGENT_SECRET": os.environ["AGENT_SECRET"],
}}
for key, val in updates.items():
    found = False
    for i, line in enumerate(lines):
        if line.startswith(key + "="):
            lines[i] = f"{{key}}={{val}}"
            found = True
            break
    if not found:
        lines.append(f"{{key}}={{val}}")
env_path.write_text("\\n".join(lines) + "\\n", encoding="utf-8")
print("Updated .env with RELAY_URL / RELAY_SESSION / RELAY_AGENT_SECRET")
PY

# --- Port 8000 check ---------------------------------------------------------
if command -v lsof >/dev/null 2>&1; then
  if lsof -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
    echo ""
    echo "Port 8000 is already in use. Stopping the old process…"
    PIDS="$(lsof -tiTCP:8000 -sTCP:LISTEN || true)"
    if [[ -n "$PIDS" ]]; then
      # shellcheck disable=SC2086
      kill $PIDS 2>/dev/null || true
      sleep 1
    fi
    if lsof -iTCP:8000 -sTCP:LISTEN >/dev/null 2>&1; then
      die "Could not free port 8000. Quit the other GetME/uvicorn and re-run."
    fi
  fi
fi

# --- Reachability hint -------------------------------------------------------
if curl -fsS --max-time 5 "$RELAY_URL/health" >/dev/null 2>&1; then
  echo "Relay reachable at $RELAY_URL"
else
  echo "Warning: could not reach relay at $RELAY_URL/health — check your internet / relay URL."
fi

step "Starting GetME on http://127.0.0.1:8000"
echo ""
echo "When studio shows GetME: online, you are done with Terminal."
echo "Leave this window open. Press Ctrl+C only when the event is over."
echo ""
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
"""
