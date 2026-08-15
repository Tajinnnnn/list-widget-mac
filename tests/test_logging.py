import json
import logging
import os

import backup
import vault_sync


def _local_state(**list_overrides):
    # Mirrors tests/test_vault_sync.py's helper of the same name — kept as a
    # local copy rather than imported so this file doesn't take a dependency
    # on test_vault_sync.py's internals.
    lst = {
        "id": "list1", "name": "Tasks", "color": None,
        "items": [
            {"_id": "a1", "text": "Existing task", "done": False, "due": None,
             "notified": False, "pinned": False, "repeat": None, "completedAt": None,
             "updatedAt": "2026-07-14T10:00:00.000Z"},
        ],
    }
    lst.update(list_overrides)
    return {"lists": [lst], "active": "list1", "settings": {}, "tombstones": []}


def test_write_backup_disk_failure_logs_warning_with_traceback(tmp_path, monkeypatch, caplog):
    # Force the disk-write step specifically (not sync_push) to fail, the
    # same way the brief's repro does: a full disk or permissions error at
    # the os.replace commit step, after the temp file was already written.
    backup_path = tmp_path / "backup.json"
    monkeypatch.setattr(backup, "BACKUP_PATH", backup_path)
    monkeypatch.setattr(vault_sync, "sync_push", lambda *a, **k: None)

    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)

    with caplog.at_level(logging.WARNING, logger="backup"):
        backup.write_backup(json.dumps({"items": ["A"]}))

    records = [r for r in caplog.records if r.name == "backup"]
    assert len(records) == 1
    # logger.exception logs at ERROR, which satisfies "WARNING-or-above".
    assert records[0].levelno >= logging.WARNING
    assert "write_backup failed" in records[0].getMessage()
    assert records[0].exc_info is not None, "expected a traceback attached to the log record"

    # The backup file itself must not have been silently left in a broken
    # state — no partial commit should have landed.
    assert not backup_path.exists()


def test_write_backup_success_produces_no_warning_log(tmp_path, monkeypatch, caplog):
    backup_path = tmp_path / "backup.json"
    monkeypatch.setattr(backup, "BACKUP_PATH", backup_path)
    monkeypatch.setattr(vault_sync, "sync_push", lambda *a, **k: None)

    with caplog.at_level(logging.WARNING):
        backup.write_backup(json.dumps({"items": ["A"]}))

    assert caplog.records == []
    assert backup_path.read_text() == json.dumps({"items": ["A"]})


def test_sync_push_failure_logs_warning_with_traceback(tmp_path, monkeypatch, caplog):
    def boom(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(vault_sync, "write_tasks_section", boom)

    with caplog.at_level(logging.WARNING, logger="vault_sync"):
        vault_sync.sync_push(_local_state(), vault_root=tmp_path)

    records = [r for r in caplog.records if r.name == "vault_sync"]
    assert len(records) == 1
    assert records[0].levelno >= logging.WARNING
    assert "sync_push failed" in records[0].getMessage()
    assert records[0].exc_info is not None


def test_sync_pull_and_merge_merge_failure_logs_warning_instead_of_silent_none(
    tmp_path, monkeypatch, caplog
):
    # Get a real note on disk with content that differs from local, so
    # sync_pull_and_merge actually reaches the merge() call rather than
    # short-circuiting on "note missing" or "note matches local".
    local = _local_state()
    vault_sync.sync_push(local, vault_root=tmp_path)
    path = vault_sync.today_note_path(tmp_path)
    path.write_text(path.read_text().replace("Existing task", "Edited by hand"))

    def boom(*_args, **_kwargs):
        raise ValueError("simulated bug in merge()")

    monkeypatch.setattr(vault_sync, "merge", boom)

    with caplog.at_level(logging.WARNING, logger="vault_sync"):
        result = vault_sync.sync_pull_and_merge(local, vault_root=tmp_path)

    # Still returns None on failure (callers depend on that contract) —
    # what changed is that the failure is no longer silent.
    assert result is None

    records = [r for r in caplog.records if r.name == "vault_sync"]
    assert len(records) == 1
    assert records[0].levelno >= logging.WARNING
    assert "sync_pull_and_merge failed" in records[0].getMessage()
    assert records[0].exc_info is not None, "expected a traceback attached to the log record"


def test_sync_pull_and_merge_success_produces_no_warning_log(tmp_path, caplog):
    local = _local_state()
    vault_sync.sync_push(local, vault_root=tmp_path)
    path = vault_sync.today_note_path(tmp_path)
    path.write_text(path.read_text().replace("Existing task", "Edited by hand"))

    with caplog.at_level(logging.WARNING):
        merged = vault_sync.sync_pull_and_merge(local, vault_root=tmp_path)

    assert merged is not None
    assert caplog.records == []
