import signal
import time

import AppKit
from PyObjCTools import AppHelper

import state
from config import SCREEN_MARGIN, WINDOW_WIDTH


def position_near_menu_bar():
    try:
        screen = AppKit.NSScreen.mainScreen()
        full = screen.frame()
        visible_frame = screen.visibleFrame()
        # Distance from the top of the screen down to the top of the usable
        # area — i.e. the menu bar's height (varies with notch displays).
        menu_bar_height = full.size.height - (visible_frame.origin.y + visible_frame.size.height)
        # Use the window's actual current width, not the WINDOW_WIDTH default
        # — otherwise repositioning after a manual resize shifts the window
        # (and everything in it, including the traffic lights) off its
        # intended spot, since it'd assume the pre-resize width.
        current_width = state.window.native.frame().size.width if state.window.native else WINDOW_WIDTH
        x = full.size.width - current_width - SCREEN_MARGIN
        y = menu_bar_height + SCREEN_MARGIN
        state.window.move(x, y)
    except Exception:
        pass


def show_window(icon=None, item=None):
    if state.window is None:
        return
    position_near_menu_bar()
    state.window.show()
    state.visible = True


def hide_window(icon=None, item=None):
    if state.window is None:
        return
    state.window.hide()
    state.visible = False


def toggle_window(icon=None, item=None):
    if state.visible:
        hide_window()
    else:
        show_window()


def quit_app(icon=None, item=None):
    state.stop_event.set()
    # WKWebView's localStorage writes aren't guaranteed to have hit disk
    # the instant localStorage.setItem() returns in JS — the actual
    # persistence happens in WebKit's separate networking/storage
    # process, asynchronously. Destroying the window immediately after
    # a task was just added/edited risked tearing down before that
    # flush landed. This runs on the main thread (tray menu callbacks
    # are dispatched there), so don't call back into the WebView here —
    # evaluate_js() blocks on the same main run loop we're currently
    # occupying and would deadlock. A plain sleep is safe: the actual
    # flush happens in that other process regardless of whether our
    # run loop is spinning.
    if state.window is not None:
        time.sleep(0.4)
    if icon is not None:
        icon.stop()
    if state.window is not None:
        state.window.destroy()


def on_closing():
    hide_window()
    return False


def _handle_sigterm(signum, frame):
    # Sent on logout/shutdown/`kill` (not on Cmd+Q or the tray Quit item,
    # which go through quit_app already) — apply the same flush-before-
    # teardown treatment so a system restart can't silently lose data.
    # Signal handlers interrupt whatever the main thread was doing, so
    # don't do real work here — defer it back onto the normal run loop.
    AppHelper.callAfter(quit_app, state.tray_icon, None)


signal.signal(signal.SIGTERM, _handle_sigterm)
