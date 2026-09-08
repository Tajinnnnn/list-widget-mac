"""Local dev server for the PWA path — no Vercel, no Postgres.

Serves todo.html straight from the parent directory (so an edit is picked
up on reload without running build.sh) and backs /api/state with
sync_api.InMemoryStore. That exercises the real request logic and the real
merge; only the storage and the HTTP adapter are stand-ins.

    uv run python server/devserver.py
    open http://localhost:8787   # sync key: "dev"

State is in memory, so restarting the server empties the server-side
document. The browser's localStorage survives, and the next push re-seeds
the server from it — which is itself worth exercising.
"""

import json
import os
import sys
from http.server import HTTPServer, SimpleHTTPRequestHandler

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

import sync_api  # noqa: E402

PORT = int(os.environ.get("PORT", "8787"))
SECRET = os.environ.get("SYNC_SECRET", "dev")

_store = sync_api.InMemoryStore()

# Served from the parent dir so the live todo.html is what loads.
_ROUTES = {
    "/": os.path.join(ROOT, "todo.html"),
    "/index.html": os.path.join(ROOT, "todo.html"),
    "/manifest.webmanifest": os.path.join(HERE, "public", "manifest.webmanifest"),
    "/sw.js": os.path.join(HERE, "public", "sw.js"),
    "/icon-192.png": os.path.join(HERE, "public", "icon-192.png"),
    "/icon-512.png": os.path.join(HERE, "public", "icon-512.png"),
}

_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".webmanifest": "application/manifest+json",
    ".png": "image/png",
}


class Handler(SimpleHTTPRequestHandler):
    def do_OPTIONS(self):
        self._api("OPTIONS")

    def do_GET(self):
        if self.path.split("?")[0] == "/api/state":
            self._api("GET")
        else:
            self._static()

    def do_POST(self):
        self._api("POST")

    def _api(self, method):
        length = int(self.headers.get("content-length") or 0)
        body = self.rfile.read(length) if length else b""
        status, payload = sync_api.handle(
            method, dict(self.headers.items()), body, _store, SECRET
        )
        encoded = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(encoded)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        if status != 204:
            self.wfile.write(encoded)

    def _static(self):
        path = _ROUTES.get(self.path.split("?")[0])
        if not path or not os.path.isfile(path):
            self.send_error(404)
            return
        with open(path, "rb") as fh:
            data = fh.read()
        ext = os.path.splitext(path)[1]
        self.send_response(200)
        self.send_header("content-type", _TYPES.get(ext, "application/octet-stream"))
        self.send_header("content-length", str(len(data)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    print(f"serving http://localhost:{PORT}  (sync key: {SECRET!r})", flush=True)
    HTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
