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
        if state.window is None:
            return False
        result = state.window.create_file_dialog(
            webview.FileDialog.SAVE,
            directory=str(Path.home() / "Downloads"),
            save_filename=f"{suggested_name}.txt",
        )
        if not result:
            return False
        path = result[0] if isinstance(result, (list, tuple)) else result
        Path(path).write_text(text)
        return True

    def import_list_text(self):
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
        return Path(path).read_text()
