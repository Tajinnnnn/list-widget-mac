import os
import sys
from pathlib import Path

APP_TITLE = "List"
LOCK_PATH = Path.home() / "Library" / "Application Support" / "List" / ".list.lock"
BACKUP_PATH = Path.home() / "Library" / "Application Support" / "List" / "backup.json"
DEBUG_LOG_PATH = Path.home() / "Library" / "Application Support" / "List" / "debug.log"

WINDOW_WIDTH = 360
WINDOW_HEIGHT = 540
SCREEN_MARGIN = 12
CHECK_INTERVAL_SECONDS = 20
VAULT_SYNC_INTERVAL_SECONDS = 20


def resource_path(relative):
    # In the packaged .app, sys._MEIPASS can point through
    # Contents/Frameworks, where bundled data files are actually just
    # symlinks into Contents/Resources (that's how PyInstaller's macOS
    # BUNDLE step satisfies the bundle-structure convention). Resolving
    # only the base directory doesn't collapse that — todo.html itself is
    # the symlink, so the joined path still ends in a symlink hop unless
    # the whole thing is resolved together. Loading todo.html through that
    # symlinked path made WKWebView's navigation fail silently (no error,
    # no didFinishNavigation, no JS ever ran) — confirmed by testing
    # against Contents/Resources/todo.html (the real file) directly, which
    # loaded fine. realpath() on the full joined path sidesteps whichever
    # exact WebKit mechanism is responsible.
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.realpath(os.path.join(base, relative))
