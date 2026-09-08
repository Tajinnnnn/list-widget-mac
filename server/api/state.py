"""Vercel serverless entrypoint. Thin adapter over sync_api.handle.

Deliberately contains no decisions — auth, dispatch, validation and the
merge all live in sync_api so they are testable without HTTP or Postgres.
"""

import json
import os
import sys
from http.server import BaseHTTPRequestHandler

# The function file runs from api/; the shared modules sit at the project
# root next to it (see build.sh, which copies them in).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import sync_api  # noqa: E402
import sync_store  # noqa: E402

MAX_BODY = 8 * 1024 * 1024  # the live document measured ~38 KB

_store = None


def _get_store():
    # Cached across warm invocations; a cold start pays one connection.
    global _store
    if _store is None:
        _store = sync_store.PostgresStore()
    return _store


class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self._dispatch("OPTIONS")

    def do_GET(self):
        self._dispatch("GET")

    def do_POST(self):
        self._dispatch("POST")

    def do_DELETE(self):
        self._dispatch("DELETE")

    def do_PUT(self):
        self._dispatch("PUT")

    def _dispatch(self, method):
        try:
            body = self._read_body()
        except ValueError as exc:
            self._send(413, {"error": str(exc)})
            return

        try:
            status, payload = sync_api.handle(
                method,
                dict(self.headers.items()),
                body,
                _get_store(),
                os.environ.get("SYNC_SECRET", ""),
            )
        except Exception:
            # Never leak a stack trace or a DSN to the client; the detail
            # goes to the platform log instead.
            self.log_error("sync request failed", exc_info=True)
            self._send(500, {"error": "internal error"})
            return

        self._send(status, payload)

    def _read_body(self):
        try:
            length = int(self.headers.get("content-length") or 0)
        except (TypeError, ValueError):
            return b""
        if length > MAX_BODY:
            raise ValueError("body too large")
        return self.rfile.read(length) if length else b""

    def _send(self, status, payload):
        encoded = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        # Same-origin only: the PWA is served from this deployment, so no
        # cross-origin access is needed and none is granted.
        self.send_header("cache-control", "no-store")
        self.end_headers()
        if status != 204:
            self.wfile.write(encoded)
