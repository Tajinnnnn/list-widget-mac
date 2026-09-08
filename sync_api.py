"""Request logic for the cross-device sync server.

Kept as a pure function over a store so auth, dispatch, validation and the
merge itself are testable without HTTP or Postgres:

    api/state.py    thin HTTP adapter (Vercel serverless entrypoint)
    sync_store.py   the Postgres store
    sync_api.py     this — everything that decides anything

The contract is two endpoints on one path:

    GET  /api/state  -> {"doc": <document|null>, "version": <int>}
    POST /api/state  <- {"doc": <document>}
                     -> {"doc": <merged document>, "version": <int>}

POST is a read-merge-write, which is why the store takes a callback
(`apply`) rather than exposing separate read and write calls — the whole
sequence has to happen inside one transaction or two interleaved pushes
can lose an update even though merge_docs itself converges.

See docs/superpowers/specs/2026-09-08-iphone-pwa-sync-design.md.
"""

import hmac
import json
import logging

import vault_sync

logger = logging.getLogger(__name__)

_BEARER = "bearer "


class InMemoryStore:
    """Non-persistent store used by the tests and by local development."""

    def __init__(self, doc=None, version=0):
        self._doc = doc
        self._version = version

    def read(self):
        return self._doc, self._version

    def apply(self, fn):
        new_doc = fn(self._doc)
        if new_doc != self._doc:
            self._doc = new_doc
            self._version += 1
        return self._doc, self._version


def _header(headers, name):
    # Header casing varies by runtime (WSGI upper-cases, BaseHTTPRequestHandler
    # preserves what the client sent), so never index headers directly.
    target = name.lower()
    for key, value in (headers or {}).items():
        if key.lower() == target:
            return value
    return None


def _authorized(headers, secret) -> bool:
    provided = _header(headers, "authorization") or ""
    if provided[: len(_BEARER)].lower() != _BEARER:
        return False
    # compare_digest rather than == so a wrong secret cannot be recovered
    # one character at a time from response timing.
    return hmac.compare_digest(provided[len(_BEARER):].strip(), secret)


def _valid_document(doc) -> bool:
    """Reject anything the client could not subsequently load().

    Storing a malformed document would brick every device at once, since
    they all pull the same row — so this gate is deliberately strict about
    the one field todo.html's load() requires.
    """
    return isinstance(doc, dict) and isinstance(doc.get("lists"), list)


def handle(method, headers, body, store, secret):
    """Returns (status_code, payload_dict). Payload is JSON-serializable."""
    method = (method or "").upper()

    # Preflight needs no credentials. Answered before the secret check so a
    # browser can complete it even if the client has not been configured.
    if method == "OPTIONS":
        return 204, {}

    if not secret:
        # Fail closed. An unset secret must never mean "no auth required".
        logger.error("sync secret is not configured; refusing all requests")
        return 503, {"error": "server not configured"}

    # Checked before the body is touched, so a probe cannot distinguish a
    # bad secret from a bad payload.
    if not _authorized(headers, secret):
        return 401, {"error": "unauthorized"}

    if method == "GET":
        doc, version = store.read()
        return 200, {"doc": doc, "version": version}

    if method != "POST":
        return 405, {"error": "method not allowed"}

    if not body:
        return 400, {"error": "empty body"}

    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        return 400, {"error": "malformed json"}

    if not isinstance(parsed, dict) or "doc" not in parsed:
        return 400, {"error": "missing doc"}

    incoming = parsed["doc"]
    if not _valid_document(incoming):
        return 400, {"error": "doc must be an object with a lists array"}

    def merge_into(stored):
        if stored is None:
            # First write. Still routed through merge_docs so what lands in
            # the row is the canonical form, matching every later write.
            return vault_sync.merge_docs(incoming, incoming)
        # incoming first: merge_docs carries `active` over from its first
        # argument, and the pushing client should keep the tab it is
        # actually looking at rather than adopting the other device's.
        return vault_sync.merge_docs(incoming, stored)

    doc, version = store.apply(merge_into)
    return 200, {"doc": doc, "version": version}
