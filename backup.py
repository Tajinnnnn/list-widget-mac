import json
import os

import vault_sync
from config import BACKUP_PATH


def write_backup(data):
    # A Python-owned fallback, independent of WKWebView's localStorage
    # entirely — written with an explicit flush + fsync so it's actually
    # durable on disk the moment this returns, unlike localStorage's
    # opaque, asynchronous persistence (see quit_app). Write to a temp
    # file and atomically rename over the real one so a mid-write kill
    # can never leave behind a corrupt/partial backup — worst case, the
    # previous good backup just doesn't get updated this time.
    try:
        BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = BACKUP_PATH.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, BACKUP_PATH)
    except Exception:
        pass
    try:
        vault_sync.sync_push(json.loads(data))
    except Exception:
        pass


def read_backup():
    try:
        return BACKUP_PATH.read_text()
    except Exception:
        return ""
