from pathlib import Path

import webview

import state
from backup import read_backup, write_backup
from window_chrome import apply_vibrancy


class JsApi:
    def set_vibrancy(self, enabled):
        apply_vibrancy(bool(enabled))
        return True

    def save_backup(self, data):
        write_backup(data)
        return True

    def load_backup(self):
        return read_backup()

    def export_list_text(self, text, suggested_name):
        # None means "no dialog result" (no window, or the user cancelled the
        # save dialog) — an intentional no-op the JS side should stay quiet
        # about. False is reserved for an actual write failure so the JS
        # side can show an error only when something really went wrong.
        if state.window is None:
            return None
        result = state.window.create_file_dialog(
            webview.FileDialog.SAVE,
            directory=str(Path.home() / "Downloads"),
            save_filename=f"{suggested_name}.txt",
        )
        if not result:
            return None
        path = result[0] if isinstance(result, (list, tuple)) else result
        try:
            Path(path).write_text(text)
        except Exception:
            return False
        return True

    def import_list_text(self):
        # Same None (cancelled/no-op) vs False (real read failure) split as
        # export_list_text — see comment there.
        if state.window is None:
            return None
        result = state.window.create_file_dialog(
            webview.FileDialog.OPEN,
            directory=str(Path.home() / "Downloads"),
            file_types=("Text files (*.txt)", "All files (*.*)"),
        )
        if not result:
            return None
        path = result[0] if isinstance(result, (list, tuple)) else result
        try:
            return Path(path).read_text()
        except Exception:
            return False
