"""Patchpipe command-line interface."""

from __future__ import annotations

import argparse
import os

from patchpipe.server import serve


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="patchpipe", description="AI patch maker for multiple devices")
    parser.add_argument(
        "--host",
        default=os.environ.get("PATCHPIPE_HOST"),
        help="bind address (default: 127.0.0.1, or 0.0.0.0 with --lan)",
    )
    parser.add_argument(
        "--lan",
        action="store_true",
        help="listen on all interfaces (0.0.0.0) so other devices on your network can connect",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("PATCHPIPE_PORT", "8765")),
        help="local HTTP port (default: 8765)",
    )
    parser.add_argument("--no-browser", action="store_true", help="do not open a browser tab automatically")
    args = parser.parse_args(argv)
    host = "0.0.0.0" if args.lan else (args.host or "127.0.0.1")
    serve(host=host, port=args.port, open_browser=not args.no_browser)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
