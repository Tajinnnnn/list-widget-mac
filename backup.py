import json
import logging
import os
import threading

import vault_sync
from config import BACKUP_PATH

# Module-level logger is safe to create before app.py's logging.basicConfig
# runs (it will, since app.py imports this module before doing anything
# else) — basicConfig configures the root handler, which every logger,
# including ones created earlier, funnels into.
logger = logging.getLogger(__name__)

# Guards the entire read-merge-write sequence around BACKUP_PATH so a UI
# save (write_backup, called straight off a JS call) can never interleave
# with a vault sync cycle (read_backup -> merge -> write_backup, in
# sync_worker._run_vault_sync_cycle) — without this, a save landing between
# the sync cycle's read and its write gets silently clobbered by the sync
# cycle's write, which is still working off the pre-save snapshot. RLock,
# not Lock, because _run_vault_sync_cycle holds this same lock while it
# calls write_backup, which acquires it again internally.
_backup_lock = threading.RLock()


def write_backup(data):
    # A Python-owned fallback, independent of WKWebView's localStorage
    # entirely — written with an explicit flush + fsync so it's actually
    # durable on disk the moment this returns, unlike localStorage's
    # opaque, asynchronous persistence (see quit_app). Write to a temp
    # file and atomically rename over the real one so a mid-write kill
    # can never leave behind a corrupt/partial backup — worst case, the
    # previous good backup just doesn't get updated this time.
    try:
        with _backup_lock:
            BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = BACKUP_PATH.with_suffix(".tmp")
            with open(tmp_path, "w") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, BACKUP_PATH)
    except Exception:
        # This is the durability-critical path: if this fails silently, the
        # user's data is only in WKWebView's localStorage (opaque, async —
        # see the comment above) with no Python-owned fallback. Log it so a
        # failure like a full disk or a permissions change leaves a trace.
        logger.exception("write_backup failed")
    try:
        vault_sync.sync_push(json.loads(data))
    except Exception:
        logger.exception("sync_push failed")


def read_backup():
    try:
        return BACKUP_PATH.read_text()
    except Exception:
        return ""
