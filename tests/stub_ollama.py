"""Stub Ollama HTTP server for EvalKit provider tests.

Handed from Providers to Tests (Lead-approved). Gives a fully offline
OllamaProvider fixture: ephemeral loopback port, no network, deterministic
payloads. The three REQUIRED lines in this file are hard-won on Windows:
omit any of them and the connection aborts mid-test (WinError 10053).

Usage inside a pytest module:

    import threading
    from http.server import HTTPServer

    from evalkit.provider import OllamaProvider

    server = HTTPServer(("127.0.0.1", 0), StubOllama)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    provider = OllamaProvider(base_url=f"http://127.0.0.1:{port}", model="stub:latest")
    ... assertions ...
    server.shutdown()

Override StubOllama.get_payload / post_payload (or subclass) to simulate
protocol errors: return non-JSON bytes for ProviderProtocolError on
unparseable bodies, or omit the "response" key for missing-field errors.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler

__all__ = ["StubOllama"]


class StubOllama(BaseHTTPRequestHandler):
    """Minimal stand-in for Ollama's /api/tags and /api/generate endpoints."""

    # REQUIRED (Windows): without HTTP/1.1 framing urllib POSTs abort
    # the connection with WinError 10053 mid-test.
    protocol_version = "HTTP/1.1"

    canned_models = [
        {"name": "stub:latest", "size": 1, "details": {"family": "stub"}}
    ]
    canned_generate = {"response": "ok", "model": "stub:latest"}

    def get_payload(self) -> bytes:
        """Body served for GET /api/tags. Override to force protocol errors."""
        return json.dumps({"models": self.canned_models}).encode("utf-8")

    def post_payload(self) -> bytes:
        """Body served for POST /api/generate. Override to force errors."""
        return json.dumps(self.canned_generate).encode("utf-8")

    def _respond(self, body: bytes) -> None:
        # REQUIRED: exact Content-Length AND Connection: close; keep-alive
        # framing is what trips BaseHTTPRequestHandler on Windows.
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._respond(self.get_payload())

    def do_POST(self) -> None:
        # REQUIRED: drain the request body before responding, or the
        # unread bytes abort the connection on Windows.
        length = int(self.headers.get("Content-Length", 0))
        if length:
            self.rfile.read(length)
        self._respond(self.post_payload())

    def log_message(self, *args: object) -> None:
        pass  # keep pytest output clean