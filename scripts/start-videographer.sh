#!/usr/bin/env bash
# Run on the videographer laptop before an event (relay mode).
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .venv/bin/activate ]]; then
  echo "Missing .venv — run: python3 -m venv .venv && pip install -r requirements.txt"
  exit 1
fi
source .venv/bin/activate

: "${RELAY_URL:?Set RELAY_URL, e.g. https://relay.example.com}"
: "${RELAY_EVENT:?Set RELAY_EVENT, e.g. wedding}"
: "${RELAY_SECRET:?Set RELAY_SECRET from relay admin}"

echo "Starting GetME! on localhost:8000..."
uvicorn app.main:app --host 127.0.0.1 --port 8000 &
APP_PID=$!

cleanup() { kill "$APP_PID" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

sleep 2
echo "Connecting agent to $RELAY_URL (event=$RELAY_EVENT)..."
python -m relay agent --relay-url "$RELAY_URL" --event "$RELAY_EVENT" --secret "$RELAY_SECRET"
