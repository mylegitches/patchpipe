"""Unified local browser server for Patchpipe."""

from __future__ import annotations

import json
import mimetypes
import os
import socket
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Mapping
from urllib.parse import unquote

from patchpipe.devices.juno_ds.errors import PatchmakerError as JunoError
from patchpipe.devices.juno_ds.errors import PatchValidationError as JunoValidationError
from patchpipe.devices.juno_ds.service import GuiService as JunoGuiService
from patchpipe.devices.pod_hd.errors import PatchmakerError as PodError
from patchpipe.devices.pod_hd.errors import ValidationError as PodValidationError
from patchpipe.devices.pod_hd.service import GuiService as PodGuiService

MAX_REQUEST_BYTES = 2 * 1024 * 1024
ROOT = Path(__file__).resolve().parent
HUB_DIR = ROOT / "hub"
JUNO_ASSETS = ROOT / "devices" / "juno_ds" / "web_assets"
POD_ASSETS = ROOT / "devices" / "pod_hd" / "web_assets"


class PatchpipeServer:
    def __init__(self) -> None:
        self.juno = JunoGuiService()
        self.pod_hd = PodGuiService()

    def dispatch_api(self, path: str, payload: object | None) -> dict[str, object]:
        if path.startswith("/api/juno-ds"):
            subpath = "/api" + path[len("/api/juno-ds") :]
            return self.juno.dispatch(subpath, payload)
        if path.startswith("/api/pod-hd"):
            subpath = "/api" + path[len("/api/pod-hd") :]
            return self.pod_hd.dispatch(subpath, payload)
        raise ValueError(f"unknown API route: {path}")


def _content_type(path: Path) -> str:
    guessed, _ = mimetypes.guess_type(path.name)
    if guessed:
        return guessed
    if path.suffix == ".svg":
        return "image/svg+xml"
    return "application/octet-stream"


def make_handler(server: PatchpipeServer) -> type[BaseHTTPRequestHandler]:
    class PatchpipeRequestHandler(BaseHTTPRequestHandler):
        server_version = "Patchpipe/0.1"

        def _send_bytes(self, status: HTTPStatus, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: HTTPStatus, value: Mapping[str, object]) -> None:
            body = json.dumps(value).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            path = unquote(self.path.split("?", 1)[0])
            if path == "/health":
                return self._json(HTTPStatus.OK, {"status": "ok"})
            if path in ("/", "/index.html"):
                return self._send_bytes(HTTPStatus.OK, (HUB_DIR / "hub.html").read_bytes(), "text/html; charset=utf-8")
            if path == "/favicon.ico":
                return self._send_bytes(HTTPStatus.OK, (HUB_DIR / "favicon.ico").read_bytes(), "image/x-icon")
            if path.startswith("/hub/"):
                asset = HUB_DIR / path[len("/hub/") :]
                if asset.is_file():
                    return self._send_bytes(HTTPStatus.OK, asset.read_bytes(), _content_type(asset))
            if path in ("/juno-ds", "/juno-ds/"):
                return self._send_bytes(HTTPStatus.OK, (JUNO_ASSETS / "index.html").read_bytes(), "text/html; charset=utf-8")
            if path.startswith("/juno-ds/"):
                asset = JUNO_ASSETS / path[len("/juno-ds/") :]
                if asset.is_file():
                    return self._send_bytes(HTTPStatus.OK, asset.read_bytes(), _content_type(asset))
            if path in ("/pod-hd", "/pod-hd/"):
                return self._send_bytes(HTTPStatus.OK, (POD_ASSETS / "index.html").read_bytes(), "text/html; charset=utf-8")
            if path.startswith("/pod-hd/"):
                asset = POD_ASSETS / path[len("/pod-hd/") :]
                if asset.is_file():
                    return self._send_bytes(HTTPStatus.OK, asset.read_bytes(), _content_type(asset))
            if path == "/api/juno-ds/ports":
                try:
                    self._json(HTTPStatus.OK, server.dispatch_api(path, None))
                except (JunoError, PodError, OSError, RuntimeError, ValueError) as error:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
                return
            if path.startswith("/api/"):
                return self._json(HTTPStatus.NOT_FOUND, {"error": f"unknown API route: {path}"})
            self.send_error(HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > MAX_REQUEST_BYTES:
                    raise ValueError("request body size is invalid")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                self._json(HTTPStatus.OK, server.dispatch_api(unquote(self.path.split("?", 1)[0]), payload))
            except (JunoError, PodError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as error:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            except Exception as error:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": str(error)})

        def log_message(self, format: str, *args: object) -> None:
            return

    return PatchpipeRequestHandler


def _lan_addresses() -> list[str]:
    """Best-effort list of IPv4 addresses reachable from the local network."""
    addresses: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if not ip.startswith("127.") and ip not in addresses:
                addresses.append(ip)
    except OSError:
        pass
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if ip not in addresses:
                addresses.insert(0, ip)
    except OSError:
        pass
    return addresses


def serve(*, host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    if not (HUB_DIR / "hub.html").is_file():
        raise FileNotFoundError(f"Patchpipe UI assets missing at {HUB_DIR}")
    local_only = host in ("127.0.0.1", "localhost", "::1")
    display_host = "127.0.0.1" if host == "0.0.0.0" else host
    url = f"http://{display_host}:{port}"
    try:
        httpd = ThreadingHTTPServer((host, port), make_handler(PatchpipeServer()))
    except OSError as error:
        if getattr(error, "winerror", None) == 10048 or error.errno in {48, 98, 10048}:
            raise SystemExit(
                f"Port {port} is already in use. Close the other Patchpipe window or run:\n"
                f"  python -m patchpipe.cli --port {port + 1}"
            ) from error
        raise
    print(f"Patchpipe running at {url}")
    if local_only:
        print("Leave this window open while using Patchpipe.")
    else:
        print(f"Listening on all interfaces ({host}:{port})")
        lan_ips = _lan_addresses()
        if lan_ips:
            print("Other devices on your LAN can use:")
            for ip in lan_ips:
                print(f"  http://{ip}:{port}")
        else:
            print(f"Other devices on your LAN can use: http://<this-pc-ip>:{port}")
        print("Allow port {0} through Windows Firewall if connections are blocked.".format(port))
    print("Press Ctrl+C to stop.")
    if open_browser and local_only and os.environ.get("PATCHPIPE_OPEN_BROWSER", "1") != "0":
        threading.Timer(0.25, webbrowser.open, args=(url,)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
