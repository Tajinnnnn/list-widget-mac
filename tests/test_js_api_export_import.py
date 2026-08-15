from pathlib import Path

import pytest

import state
from js_api import JsApi, _first_path


class _DialogWindow:
    # Stands in for the real pywebview window: create_file_dialog is the
    # only method export/import touch. Tests configure `dialog_result` to
    # drive the three paths every dialog call can take — a chosen path, or
    # None/() to simulate the user hitting Cancel.
    def __init__(self, dialog_result):
        self.dialog_result = dialog_result

    def create_file_dialog(self, *_args, **_kwargs):
        return self.dialog_result


@pytest.mark.parametrize(
    "result",
    [
        ("/tmp/list.txt",),
        ["/tmp/list.txt"],
        "/tmp/list.txt",
    ],
    ids=["tuple", "list", "bare-string"],
)
def test_first_path_normalizes_every_dialog_return_shape(result):
    # pywebview's file-dialog result shape varies by backend (tuple, list,
    # or a bare string) — every shape must resolve to the same path so
    # export_list_text/import_list_text behave identically regardless of
    # which shape the dialog happens to return.
    assert _first_path(result) == "/tmp/list.txt"


def test_export_list_text_success(tmp_path, monkeypatch):
    target = tmp_path / "list.txt"
    monkeypatch.setattr(state, "window", _DialogWindow((str(target),)))

    api = JsApi()
    assert api.export_list_text("a\nb\n", "list") is True
    assert target.read_text() == "a\nb\n"


def test_export_list_text_write_failure_returns_false_not_exception(tmp_path, monkeypatch):
    target = tmp_path / "list.txt"
    monkeypatch.setattr(state, "window", _DialogWindow((str(target),)))

    def boom(self, *_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", boom)

    api = JsApi()
    assert api.export_list_text("a\nb\n", "list") is False


def test_export_list_text_dialog_cancelled_returns_none_not_false(monkeypatch):
    # Cancelling the save dialog is not a failure — it must stay
    # distinguishable from a real write error so the JS side doesn't show
    # a spurious "couldn't export" alert every time the user backs out.
    monkeypatch.setattr(state, "window", _DialogWindow(None))

    api = JsApi()
    assert api.export_list_text("a\nb\n", "list") is None


def test_export_list_text_no_window_returns_none(monkeypatch):
    monkeypatch.setattr(state, "window", None)

    api = JsApi()
    assert api.export_list_text("a\nb\n", "list") is None


def test_import_list_text_success(tmp_path, monkeypatch):
    source = tmp_path / "list.txt"
    source.write_text("one\ntwo\n")
    monkeypatch.setattr(state, "window", _DialogWindow((str(source),)))

    api = JsApi()
    assert api.import_list_text() == "one\ntwo\n"


def test_import_list_text_read_failure_returns_false_not_exception(tmp_path, monkeypatch):
    # Simulates picking a binary file (e.g. a .png) through the "All files"
    # filter — read_text raises UnicodeDecodeError, which must not cross
    # the pywebview JS bridge as an unhandled rejection.
    source = tmp_path / "image.png"
    source.write_bytes(b"\x89PNG\r\n\x1a\n")
    monkeypatch.setattr(state, "window", _DialogWindow((str(source),)))

    def boom(self, *_args, **_kwargs):
        raise UnicodeDecodeError("utf-8", b"\x89PNG", 0, 1, "invalid start byte")

    monkeypatch.setattr(Path, "read_text", boom)

    api = JsApi()
    assert api.import_list_text() is False


def test_import_list_text_dialog_cancelled_returns_none_not_false(monkeypatch):
    # Cancelling the open dialog is not a failure — distinct from the False
    # sentinel used for a real read failure (see comment above and in
    # js_api.py), so the JS side only alerts on a genuine error.
    monkeypatch.setattr(state, "window", _DialogWindow(()))

    api = JsApi()
    assert api.import_list_text() is None


def test_import_list_text_no_window_returns_none(monkeypatch):
    monkeypatch.setattr(state, "window", None)

    api = JsApi()
    assert api.import_list_text() is None
