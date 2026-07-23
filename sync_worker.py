import json

import vault_sync
import state
from backup import read_backup, write_backup
from config import VAULT_SYNC_INTERVAL_SECONDS


def _run_vault_sync_cycle():
    local_raw = read_backup()
    if not local_raw:
        return
    try:
        local_state = json.loads(local_raw)
    except Exception:
        return
    merged = vault_sync.sync_pull_and_merge(local_state)
    if merged is None:
        return
    try:
        write_backup(json.dumps(merged))
    except Exception:
        return
    try:
        state.window.evaluate_js(f"window.__applySyncedState({json.dumps(json.dumps(merged))})")
    except Exception:
        pass


def vault_sync_loop():
    state.window.events.loaded.wait(timeout=15)
    _run_vault_sync_cycle()
    while not state.stop_event.is_set():
        if state.stop_event.wait(VAULT_SYNC_INTERVAL_SECONDS):
            break
        _run_vault_sync_cycle()
