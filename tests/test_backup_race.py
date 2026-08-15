import json
import threading
import time

import pytest

import backup
import state
import sync_worker
import vault_sync


class _FakeWindow:
    # sync_worker calls state.window.evaluate_js after the sync cycle
    # releases the lock; there's no real webview in this test, so this
    # just needs to exist and not blow up.
    def evaluate_js(self, *_args, **_kwargs):
        pass


def test_concurrent_save_and_sync_cycle_no_data_loss(tmp_path, monkeypatch):
    # Reproduces the race from race-fix-brief.md: a sync cycle reads the
    # backup, spends time merging against the vault note, then writes —
    # while a UI save lands in the middle of that window. Without the fix,
    # the sync cycle's write clobbers the save because it was computed from
    # a snapshot taken before the save happened. With the fix
    # (_backup_lock held across the whole read-merge-write sequence in both
    # write_backup and _run_vault_sync_cycle), the two calls are fully
    # serialized, so the save can never be lost.
    backup_path = tmp_path / "backup.json"
    monkeypatch.setattr(backup, "BACKUP_PATH", backup_path)
    monkeypatch.setattr(state, "window", _FakeWindow())
    # sync_push/pull touch the real vault by default (VAULT_ROOT); no-op
    # push and fake-merge below keep this test entirely inside tmp_path.
    monkeypatch.setattr(vault_sync, "sync_push", lambda *a, **k: None)

    backup_path.write_text(json.dumps({"items": ["A"]}))

    sync_started = threading.Event()
    allow_sync_to_finish = threading.Event()

    def fake_sync_pull_and_merge(local_state, vault_root=vault_sync.VAULT_ROOT):
        # Stands in for the real vault read/merge, which takes real wall
        # time (file I/O, parsing). Blocking here — while _backup_lock is
        # still held by _run_vault_sync_cycle — is what widens the race
        # window that a concurrent save must survive.
        sync_started.set()
        assert allow_sync_to_finish.wait(timeout=5), "test harness stalled"
        merged = dict(local_state)
        merged["synced"] = True
        return merged

    monkeypatch.setattr(vault_sync, "sync_pull_and_merge", fake_sync_pull_and_merge)

    sync_thread = threading.Thread(target=sync_worker._run_vault_sync_cycle)
    sync_thread.start()
    assert sync_started.wait(timeout=5), "sync cycle never started"

    # Simulate the user adding a task mid-cycle: a save call landing after
    # the sync cycle already read S0 but before it has written.
    save_thread = threading.Thread(
        target=backup.write_backup, args=(json.dumps({"items": ["A", "B"]}),)
    )
    save_thread.start()

    # Give the save thread a moment to reach (and, with the fix, block on)
    # _backup_lock before letting the sync cycle's write proceed.
    time.sleep(0.2)
    allow_sync_to_finish.set()

    sync_thread.join(timeout=5)
    save_thread.join(timeout=5)

    assert not sync_thread.is_alive(), "sync cycle deadlocked"
    assert not save_thread.is_alive(), "concurrent save deadlocked"

    final = json.loads(backup_path.read_text())
    assert final["items"] == ["A", "B"], (
        "concurrent save was lost — sync cycle overwrote it with a stale merge"
    )


def test_write_backup_lock_is_reentrant(tmp_path, monkeypatch):
    # _run_vault_sync_cycle holds _backup_lock and then calls write_backup,
    # which acquires the same lock again on the same thread. If this were
    # a plain threading.Lock instead of an RLock, that would deadlock.
    backup_path = tmp_path / "backup.json"
    monkeypatch.setattr(backup, "BACKUP_PATH", backup_path)
    monkeypatch.setattr(state, "window", _FakeWindow())
    monkeypatch.setattr(vault_sync, "sync_push", lambda *a, **k: None)
    monkeypatch.setattr(
        vault_sync,
        "sync_pull_and_merge",
        lambda local_state, vault_root=vault_sync.VAULT_ROOT: {**local_state, "synced": True},
    )

    backup_path.write_text(json.dumps({"items": ["A"]}))

    sync_thread = threading.Thread(target=sync_worker._run_vault_sync_cycle)
    sync_thread.start()
    sync_thread.join(timeout=5)

    assert not sync_thread.is_alive(), "reentrant lock acquisition deadlocked"
    assert json.loads(backup_path.read_text()) == {"items": ["A"], "synced": True}
