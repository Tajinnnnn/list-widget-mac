import fcntl
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import AppKit
import pystray
import webview
from PIL import Image
from PyObjCTools import AppHelper

APP_TITLE = "List"
LOCK_PATH = Path.home() / "Library" / "Application Support" / "List" / ".list.lock"

WINDOW_WIDTH = 360
WINDOW_HEIGHT = 540
SCREEN_MARGIN = 12
CHECK_INTERVAL_SECONDS = 20


def resource_path(relative):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, relative)


_lock_fd = None


def already_running():
    global _lock_fd
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    _lock_fd = os.open(LOCK_PATH, os.O_CREAT | os.O_RDWR)
    try:
        fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return False
    except OSError:
        return True


window = None
tray_icon = None
visible = False
stop_event = threading.Event()


def position_near_menu_bar():
    try:
        screen = AppKit.NSScreen.mainScreen()
        full = screen.frame()
        visible_frame = screen.visibleFrame()
        # Distance from the top of the screen down to the top of the usable
        # area — i.e. the menu bar's height (varies with notch displays).
        menu_bar_height = full.size.height - (visible_frame.origin.y + visible_frame.size.height)
        x = full.size.width - WINDOW_WIDTH - SCREEN_MARGIN
        y = menu_bar_height + SCREEN_MARGIN
        window.move(x, y)
    except Exception:
        pass


def show_window(icon=None, item=None):
    global visible
    if window is None:
        return
    position_near_menu_bar()
    window.show()
    visible = True


def hide_window(icon=None, item=None):
    global visible
    if window is None:
        return
    window.hide()
    visible = False


def toggle_window(icon=None, item=None):
    if visible:
        hide_window()
    else:
        show_window()


def quit_app(icon, item):
    stop_event.set()
    icon.stop()
    if window is not None:
        window.destroy()


def on_closing():
    hide_window()
    return False


def _window_bg_color():
    return AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(
        0x16 / 255, 0x18 / 255, 0x1D / 255, 1.0
    )


def _decoration_view(ns_window):
    # pywebview itself explicitly recolors this exact view — the titlebar's
    # decoration view — to NSColor.windowBackgroundColor() right after
    # creating the window, specifically so it "does not change with the
    # window color". That system gray is the visible seam above the
    # traffic lights unless we override it with our own color instead.
    return ns_window.contentView().superview().subviews().lastObject()


def configure_window_chrome():
    # window.native (the NSWindow) only exists once pywebview has actually
    # built the native window, which happens lazily inside webview.start() —
    # not yet when create_window() returns. "loaded" fires after that, but
    # from a background thread, so the actual mutation has to hop back to
    # the main thread (NSWindow geometry/style changes require it).
    def _apply():
        try:
            ns_window = window.native
            if ns_window is None:
                return
            ns_window.setTitlebarAppearsTransparent_(True)
            ns_window.setTitleVisibility_(AppKit.NSWindowTitleHidden)
            ns_window.setStyleMask_(
                ns_window.styleMask() | AppKit.NSWindowStyleMaskFullSizeContentView
            )
            ns_window.setBackgroundColor_(_window_bg_color())

            decoration_view = _decoration_view(ns_window)
            if decoration_view is not None:
                decoration_view.setBackgroundColor_(_window_bg_color())
        except Exception:
            pass

    AppHelper.callAfter(_apply)


def apply_vibrancy(enabled):
    # pywebview only supports vibrancy/transparent as create_window()-time
    # constructor flags, so toggling it live from a Settings switch means
    # reaching into the same private bits pywebview itself would use: the
    # actual WKWebView (via BrowserView.instances, keyed by window uid) and
    # an NSVisualEffectView inserted behind it.
    def _apply():
        try:
            from webview.platforms.cocoa import BrowserView

            browser_view = BrowserView.instances.get("master")
            if browser_view is None:
                return
            webview_native = browser_view.webview
            ns_window = browser_view.window

            webview_native.setValue_forKey_(bool(enabled), "drawsTransparentBackground")
            ns_window.setOpaque_(not enabled)

            # The decoration view paints its own solid fill regardless of
            # what's behind it, so it has to be told about vibrancy too —
            # otherwise it shows up as an opaque seam above the traffic
            # lights once the content below it turns translucent.
            decoration_view = _decoration_view(ns_window)
            if decoration_view is not None:
                decoration_view.setBackgroundColor_(
                    AppKit.NSColor.clearColor() if enabled else _window_bg_color()
                )

            effect = getattr(browser_view, "_vibrancy_view", None)
            if enabled:
                if effect is None:
                    effect = AppKit.NSVisualEffectView.alloc().initWithFrame_(
                        webview_native.bounds()
                    )
                    effect.setAutoresizingMask_(
                        AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable
                    )
                    effect.setWantsLayer_(True)
                    effect.setState_(AppKit.NSVisualEffectStateActive)
                    effect.setMaterial_(AppKit.NSVisualEffectMaterialSidebar)
                    effect.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
                    webview_native.superview().addSubview_positioned_relativeTo_(
                        effect, AppKit.NSWindowBelow, webview_native
                    )
                    browser_view._vibrancy_view = effect
                else:
                    effect.setHidden_(False)
            elif effect is not None:
                effect.setHidden_(True)
        except Exception:
            pass

    AppHelper.callAfter(_apply)


class JsApi:
    def set_vibrancy(self, enabled):
        apply_vibrancy(bool(enabled))
        return True


class TrayIcon(pystray.Icon):
    """Left-click toggles the window directly; right-click shows a small
    Hide/Quit menu. Plain pystray always pops the attached menu open on any
    click, which meant a left-click never reached the window at all — you
    had to open the menu, then click "Open List" as a second step."""

    def __call__(self):
        event = AppKit.NSApp.currentEvent()
        if event is not None and event.type() == AppKit.NSEventTypeRightMouseUp:
            if self._menu_handle:
                nsmenu, _ = self._menu_handle
                AppKit.NSMenu.popUpContextMenu_withEvent_forView_(
                    nsmenu, event, self._status_item.button()
                )
        else:
            toggle_window()


def setup_tray():
    # pystray's macOS backend creates an NSStatusItem, which (like all AppKit
    # objects) must happen on the main thread. run_detached() hands the icon
    # off to share pywebview's own NSApplication run loop instead of
    # starting a second one via run().
    global tray_icon
    icon_image = Image.open(resource_path("menubar_icon.png"))
    menu = pystray.Menu(
        pystray.MenuItem("Hide", hide_window),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    )
    tray_icon = TrayIcon(
        APP_TITLE,
        icon_image,
        APP_TITLE,
        menu,
        darwin_nsapplication=AppKit.NSApplication.sharedApplication(),
    )

    def _setup(icon):
        icon.visible = True
        # pystray doesn't mark the NSImage as a template image, so it would
        # otherwise render as flat black instead of adapting to light/dark
        # menu bars like native menu bar icons do.
        try:
            icon._status_item.button().image().setTemplate_(True)
        except Exception:
            pass
        # visible = True attaches the menu to the status item, which makes
        # AppKit pop it open on every click. Detach it — TrayIcon.__call__
        # pops it up manually, only on right-click.
        icon._status_item.setMenu_(None)

    tray_icon.run_detached(setup=_setup)


def applescript_quote(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def notify(title, message):
    script = f"display notification {applescript_quote(message)} with title {applescript_quote(title)}"
    try:
        subprocess.run(["osascript", "-e", script], check=False)
    except Exception:
        pass


def notification_loop():
    window.events.loaded.wait(timeout=15)
    while not stop_event.is_set():
        if stop_event.wait(CHECK_INTERVAL_SECONDS):
            break
        try:
            result = window.evaluate_js("window.__checkDueTasks()")
            due_items = json.loads(result) if result else []
        except Exception:
            due_items = []
        for item in due_items:
            notify(f"Due now — {item.get('list', APP_TITLE)}", item.get("text", ""))


if __name__ == "__main__":
    if already_running():
        sys.exit(0)

    html_path = resource_path("todo.html")
    window = webview.create_window(
        APP_TITLE,
        html_path,
        width=WINDOW_WIDTH,
        height=WINDOW_HEIGHT,
        min_size=(300, 400),
        background_color="#16181d",
        hidden=True,
        js_api=JsApi(),
    )
    window.events.closing += on_closing
    window.events.loaded += configure_window_chrome

    # pywebview's Cocoa backend defaults the app to a Regular activation
    # policy (Dock icon + Cmd+Tab entry) as soon as it's imported above.
    # Switch to Accessory so this behaves like a menu-bar-only utility.
    AppKit.NSApplication.sharedApplication().setActivationPolicy_(
        AppKit.NSApplicationActivationPolicyAccessory
    )

    setup_tray()
    threading.Thread(target=notification_loop, daemon=True).start()

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

    AppHelper.callLater(0.2, _reassert_accessory_policy)

    # pywebview defaults private_mode to True, which wipes ALL local
    # storage (i.e. every saved task) on every single launch — not just
    # rebuilds. This is the fix for that.
    webview.start(private_mode=False)
