"""Minimal HTTP healthcheck server on localhost."""

from __future__ import annotations

import json
import logging
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Callable

log = logging.getLogger(__name__)


class HealthHandler(BaseHTTPRequestHandler):
    """Serves GET /health with JSON status."""

    status_func: Callable[[], dict[str, Any]]  # set on the class before serving

    def do_GET(self) -> None:
        if self.path.rstrip("/") == "/health":
            status = self.status_func()
            body = json.dumps(status, default=str).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def log_message(self, fmt: str, *args: Any) -> None:
        # suppress default access logs
        pass


class HealthServer:
    """Run an HTTP health endpoint in a background thread."""

    def __init__(self, port: int, status_func: Callable[[], dict[str, Any]]) -> None:
        self._port = port
        self._status_func = status_func
        self._server: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        # create a handler subclass with our status_func bound
        handler = type("H", (HealthHandler,), {"status_func": staticmethod(self._status_func)})
        self._server = HTTPServer(("127.0.0.1", self._port), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True, name="health")
        self._thread.start()
        log.info("healthcheck_started", extra={"port": self._port})

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
