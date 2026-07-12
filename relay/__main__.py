"""Run the cloud relay server or launch GetME! with relay credentials.

Cloud (you deploy once):
  python -m relay server

Videographer laptop (GetME includes the relay client):
  RELAY_URL=https://YOUR_RELAY RELAY_SESSION=SESSION RELAY_AGENT_SECRET=SECRET \\
    uvicorn app.main:app --host 127.0.0.1 --port 8000

Or use the studio install script /:
  python -m relay agent --relay-url https://YOUR_RELAY --event SESSION --secret SECRET
"""

from __future__ import annotations

import argparse
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m relay")
    sub = parser.add_subparsers(dest="cmd", required=True)

    srv = sub.add_parser("server", help="Run cloud relay (deploy on VPS)")
    srv.add_argument("--host", default="0.0.0.0")
    srv.add_argument("--port", type=int, default=int(os.environ.get("PORT", "9000")))

    ag = sub.add_parser("agent", help="Run GetME! with relay credentials")
    ag.add_argument("--relay-url", required=True)
    ag.add_argument("--event", required=True)
    ag.add_argument("--secret", required=True)
    ag.add_argument("--local", default="http://127.0.0.1:8000")
    ag.add_argument(
        "--auto-server",
        action="store_true",
        help="Ignored (kept for older install scripts)",
    )

    args = parser.parse_args()

    if args.cmd == "server":
        import uvicorn

        uvicorn.run("relay.server:app", host=args.host, port=args.port)
    elif args.cmd == "agent":
        from relay.agent import main as agent_main

        agent_main(
            [
                "--relay-url",
                args.relay_url,
                "--event",
                args.event,
                "--secret",
                args.secret,
                "--local",
                args.local,
            ]
            + (["--auto-server"] if args.auto_server else [])
        )


if __name__ == "__main__":
    main()
