import sys
import threading

import AppKit
import webview
from PyObjCTools import AppHelper

import state
from config import APP_TITLE, WINDOW_HEIGHT, WINDOW_WIDTH, resource_path
from js_api import JsApi
from notifications import notification_loop
from single_instance import already_running
from sync_worker import vault_sync_loop
from tray import setup_tray
from window_chrome import clear_webkit_cache, configure_window_chrome
from window_controls import on_closing


def _reassert_accessory_policy(attempts_left=6):
    # pywebview's run loop calls activateIgnoringOtherApps_ once shortly
    # after start(), which flips the policy back to Regular (showing a
    # Dock icon) even though we set Accessory above. Keep re-asserting
    # it for the first few seconds until that one-time flip has passed.
    AppKit.NSApplication.sharedApplication().setActivationPolicy_(
        AppKit.NSApplicationActivationPolicyAccessory
    )
    if attempts_left > 1:
        AppHelper.callLater(0.5, _reassert_accessory_policy, attempts_left - 1)


def main():
    if already_running():
        sys.exit(0)

    clear_webkit_cache()

    # A plain filesystem path makes pywebview's is_local_url() think this
    # needs its local HTTP server (bottle, on a fixed-but-not-guaranteed-
    # free port). If that port is ever taken (another process, or a
    # lingering socket from an abrupt previous exit — this really
    # happened during testing), the page loads under a *different*
    # origin than usual, and WKWebView's localStorage is origin-scoped:
    # a different origin means a completely different, empty storage
    # bucket, which looked exactly like randomly losing saved tasks.
    # An explicit file:// URL sidesteps the HTTP server (and that whole
    # failure mode) entirely, and is stable across every launch.
    html_path = "file://" + resource_path("todo.html")
    state.window = webview.create_window(
        APP_TITLE,
        html_path,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        min_size=(300, 400),
        background_color="#16181d",
        hidden=True,
        js_api=JsApi(),
    )
    state.window.events.closing += on_closing
    state.window.events.loaded += configure_window_chrome

    # pywebview's Cocoa backend defaults the app to a Regular activation
    # policy (Dock icon + Cmd+Tab entry) as soon as it's imported above.
    # Switch to Accessory so this behaves like a menu-bar-only utility.
    AppKit.NSApplication.sharedApplication().setActivationPolicy_(
        AppKit.NSApplicationActivationPolicyAccessory
    )

    setup_tray()
    threading.Thread(target=notification_loop, daemon=True).start()
    threading.Thread(target=vault_sync_loop, daemon=True).start()

    AppHelper.callLater(0.2, _reassert_accessory_policy)

    # pywebview defaults private_mode to True, which wipes ALL local
    # storage (i.e. every saved task) on every single launch — not just
    # rebuilds. This is the fix for that.
    webview.start(private_mode=False)


if __name__ == "__main__":
    main()
