"""Postgres-backed store for the sync server.

Satisfies the same two-method contract as sync_api.InMemoryStore:

    read()      -> (doc | None, version)
    apply(fn)   -> (doc, version)   with fn(stored) -> new_doc

`apply` runs the whole read-merge-write inside one transaction with the row
locked FOR UPDATE. merge_docs converging is not sufficient on its own: two
interleaved read-merge-write cycles can still lose an update because
neither one ever sees the other's write.

The sentinel row is created up front (schema.sql, and defensively here)
with a NULL doc, because FOR UPDATE on a row that does not exist locks
nothing — two concurrent first writes would otherwise both insert.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

ROW_ID = "singleton"

_ENSURE_ROW = """
INSERT INTO sync_state (id, doc, version) VALUES (%s, NULL, 0)
ON CONFLICT (id) DO NOTHING
"""
_SELECT_LOCKED = "SELECT doc, version FROM sync_state WHERE id = %s FOR UPDATE"
_SELECT = "SELECT doc, version FROM sync_state WHERE id = %s"
_UPDATE = """
UPDATE sync_state
   SET doc = %s, version = version + 1, updated_at = now()
 WHERE id = %s
RETURNING version
"""


class PostgresStore:
    def __init__(self, dsn=None):
        self._dsn = dsn or os.environ.get("DATABASE_URL")
        if not self._dsn:
            raise RuntimeError("DATABASE_URL is not set")

    def _connect(self):
        # Imported lazily so the module can be imported (and sync_api tested)
        # without the driver installed.
        import psycopg

        return psycopg.connect(self._dsn)

    def read(self):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(_SELECT, (ROW_ID,))
                row = cur.fetchone()
        if row is None:
            return None, 0
        doc, version = row
        return _as_dict(doc), version

    def apply(self, fn):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(_ENSURE_ROW, (ROW_ID,))
                cur.execute(_SELECT_LOCKED, (ROW_ID,))
                row = cur.fetchone()
                stored = _as_dict(row[0]) if row else None
                version = row[1] if row else 0

                new_doc = fn(stored)
                if new_doc == stored:
                    # No-op push (the common case for a poll that found
                    # nothing new). Don't burn a version on it.
                    return stored, version

                cur.execute(_UPDATE, (json.dumps(new_doc), ROW_ID))
                version = cur.fetchone()[0]
                return new_doc, version


def _as_dict(value):
    # psycopg3 decodes jsonb to a Python object already; psycopg2 and a
    # plain text column hand back a string. Accept both.
    if value is None or isinstance(value, dict):
        return value
    return json.loads(value)
