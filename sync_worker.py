import json
import logging

import vault_sync
import state
from backup import backup_lock, read_backup, write_backup
from config import VAULT_SYNC_INTERVAL_SECONDS
from periodic import run_periodic

logger = logging.getLogger(__name__)


def _run_vault_sync_cycle():
    # Hold backup_lock across the whole read -> merge -> write sequence so
    # a UI save (write_backup, called off a JS call on another thread) can
    # never land between our read and our write — otherwise our write would
    # overwrite the save with a merge that never saw it. write_backup
    # re-acquires the same lock internally, which is why it's an RLock.
    with backup_lock:
        local_raw = read_backup()
        if not local_raw:
            return
        try:
            local_state = json.loads(local_raw)
        except Exception:
            # A corrupt on-disk backup means the sync cycle has nothing
            # trustworthy to merge against — worth a trace, since this is
            # exactly the kind of thing that otherwise surfaces as "my
            # tasks stopped syncing" with no clue why.
            logger.exception("failed to parse local backup during sync cycle")
            return
        merged = vault_sync.sync_pull_and_merge(local_state)
        if merged is None:
            return
        # write_backup no longer raises for a disk-write failure — it
        # catches internally and returns False. Check that return value
        # explicitly: if the write didn't actually land, backup.json on
        # disk is still stale, so pushing `merged` into the UI here would
        # show state that isn't actually durable, which is worse than
        # just leaving the UI showing the last successfully-synced state
        # until the next cycle succeeds.
        if not write_backup(json.dumps(merged)):
            logger.error("write_backup failed to persist during sync cycle")
            return
    # evaluate_js stays outside the lock — it's a UI call, not disk I/O,
    # and can block briefly on the main thread.
    try:
        state.window.evaluate_js(f"window.__applySyncedState({json.dumps(json.dumps(merged))})")
    except Exception:
        pass


def vault_sync_loop():
    run_periodic(VAULT_SYNC_INTERVAL_SECONDS, _run_vault_sync_cycle, run_immediately=True)
