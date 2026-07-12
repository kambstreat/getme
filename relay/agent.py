"""Launch GetME! with relay credentials (one process — app is the agent)."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from urllib.parse import urlparse

logger = logging.getLogger("getme.agent")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Run GetME! connected to the cloud relay (same as uvicorn with RELAY_* env vars)."
    )
    parser.add_argument("--relay-url", required=True)
    parser.add_argument("--event", required=True, help="Session id from studio")
    parser.add_argument("--secret", required=True)
    parser.add_argument("--local", default="http://127.0.0.1:8000", help="Bind address for GetME")
    parser.add_argument(
        "--auto-server",
        action="store_true",
        help="Ignored — kept for compatibility with older install scripts.",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if args.auto_server:
        logger.info("--auto-server is no longer needed; GetME includes the relay client.")

    os.environ["RELAY_URL"] = args.relay_url.rstrip("/")
    os.environ["RELAY_SESSION"] = args.event
    os.environ["RELAY_AGENT_SECRET"] = args.secret

    parsed = urlparse(args.local)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port or 8000

    import uvicorn

    logger.info("Starting GetME! on %s:%s (relay session=%s)", host, port, args.event)
    uvicorn.run("app.main:app", host=host, port=port)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
