import fcntl
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import AppKit
import pystray
import webview
import WebKit
from PIL import Image
from PyObjCTools import AppHelper

import vault_sync

APP_TITLE = "List"
LOCK_PATH = Path.home() / "Library" / "Application Support" / "List" / ".list.lock"
BACKUP_PATH = Path.home() / "Library" / "Application Support" / "List" / "backup.json"

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


def clear_webkit_cache():
    # Fixing the private_mode data wipe (see notification_loop/__main__)
    # had a side effect: WebKit's disk/memory cache for todo.html now also
    # persists across restarts, so editing the file and relaunching could
    # silently keep showing the old cached version. Clear only the cache
    # data types here — NOT local storage, which is exactly what we just
    # fixed to stop wiping.
    try:
        data_store = WebKit.WKWebsiteDataStore.defaultDataStore()
        cache_types = {
            WebKit.WKWebsiteDataTypeDiskCache,
            WebKit.WKWebsiteDataTypeMemoryCache,
        }
        data_store.removeDataOfTypes_modifiedSince_completionHandler_(
            cache_types, AppKit.NSDate.dateWithTimeIntervalSince1970_(0), lambda: None
        )
    except Exception:
        pass


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
        # Use the window's actual current width, not the WINDOW_WIDTH default
        # — otherwise repositioning after a manual resize shifts the window
        # (and everything in it, including the traffic lights) off its
        # intended spot, since it'd assume the pre-resize width.
        current_width = window.native.frame().size.width if window.native else WINDOW_WIDTH
        x = full.size.width - current_width - SCREEN_MARGIN
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


def quit_app(icon=None, item=None):
    stop_event.set()
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
    if window is not None:
        time.sleep(0.4)
    if icon is not None:
        icon.stop()
    if window is not None:
        window.destroy()


def on_closing():
    hide_window()
    return False


def _handle_sigterm(signum, frame):
    # Sent on logout/shutdown/`kill` (not on Cmd+Q or the tray Quit item,
    # which go through quit_app already) — apply the same flush-before-
    # teardown treatment so a system restart can't silently lose data.
    # Signal handlers interrupt whatever the main thread was doing, so
    # don't do real work here — defer it back onto the normal run loop.
    AppHelper.callAfter(quit_app, tray_icon, None)


signal.signal(signal.SIGTERM, _handle_sigterm)


def _window_bg_color():
    return AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(
        0x16 / 255, 0x18 / 255, 0x1D / 255, 1.0
    )


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

            content_view = ns_window.contentView()

            # Grab the three standard buttons *before* going borderless —
            # standardWindowButton_ only returns real controls for a titled
            # window. Reparent them into the content view so they survive
            # losing the .titled bit next. Anchored via Auto Layout (not a
            # fixed frame) so they stay pinned to the top-left corner
            # correctly when the window is resized, regardless of the
            # content view's flipped-ness.
            button_center_y = 17
            start_x = 13
            spacing = 20

            for index, button_type in enumerate((
                AppKit.NSWindowCloseButton,
                AppKit.NSWindowMiniaturizeButton,
                AppKit.NSWindowZoomButton,
            )):
                button = ns_window.standardWindowButton_(button_type)
                if button is None:
                    continue
                button.retain()
                button.removeFromSuperview()
                button.setTranslatesAutoresizingMaskIntoConstraints_(False)
                content_view.addSubview_(button)
                x = start_x + index * spacing
                button.leadingAnchor().constraintEqualToAnchor_constant_(
                    content_view.leadingAnchor(), x
                ).setActive_(True)
                button.centerYAnchor().constraintEqualToAnchor_constant_(
                    content_view.topAnchor(), button_center_y
                ).setActive_(True)

            # Removing the buttons alone doesn't stick — as long as the
            # window is still "titled", AppKit's own window-chrome upkeep
            # just puts fresh ones back in the titlebar. Going fully
            # borderless (while keeping resizable/closable/miniaturizable,
            # which are independent of the .titled bit) stops that, but
            # loses the automatic rounded corners + shadow, so those need
            # to be reconstructed by hand.
            mask = ns_window.styleMask()
            mask &= ~AppKit.NSWindowStyleMaskTitled
            ns_window.setStyleMask_(mask)
            ns_window.setHasShadow_(True)
            ns_window.setMovableByWindowBackground_(True)

            content_view.setWantsLayer_(True)
            layer = content_view.layer()
            layer.setCornerRadius_(10.0)
            layer.setMasksToBounds_(True)
        except Exception as e:
            with open("/tmp/list_reparent_debug.log", "a") as f:
                f.write(f"EXCEPTION: {e!r}\n")

    AppHelper.callAfter(_apply)


def apply_vibrancy(enabled):
    # pywebview only supports vibrancy/transparent as create_window()-time
    # constructor flags, so toggling it live from a Settings switch means
    # reaching into the same private bits pywebview itself would use: the
    # actual WKWebView (via BrowserView.instances, keyed by window uid) and
    # an NSVisualEffectView inserted behind it.
    def _apply(_retries_left=15):
        try:
            from webview.platforms.cocoa import BrowserView

            browser_view = BrowserView.instances.get("master")
            if browser_view is None:
                # Under file:// loading (see the html_path fix in __main__),
                # window.pywebview.api can go truthy on the JS side before
                # BrowserView.instances["master"] is registered on this side
                # — the old HTTP-server loading path happened to be slow
                # enough that this never raced. Retry instead of silently
                # dropping the call, so startup reapply doesn't depend on
                # winning that race.
                if _retries_left > 0:
                    AppHelper.callLater(0.2, _apply, _retries_left - 1)
                return
            webview_native = browser_view.webview
            ns_window = browser_view.window

            # drawsTransparentBackground is a private, deprecated KVC hook
            # that WebKit was resetting on its own repaints (worse now that
            # the traffic-light buttons are reparented as real subviews
            # directly on this WKWebView, which changes how it composites).
            # underPageBackgroundColor is the public, supported API for
            # "what shows through where the page itself doesn't paint" —
            # use that as the actual mechanism and keep the old hook as a
            # cheap extra nudge.
            webview_native.setUnderPageBackgroundColor_(
                AppKit.NSColor.clearColor() if enabled else _window_bg_color()
            )
            webview_native.setValue_forKey_(bool(enabled), "drawsTransparentBackground")
            ns_window.setOpaque_(not enabled)
            # The window's own backgroundColor was set to a solid opaque
            # color once at startup (configure_window_chrome) and never
            # revisited — that solid fill was likely blocking the "behind
            # window" blur from ever sampling real desktop content.
            ns_window.setBackgroundColor_(
                AppKit.NSColor.clearColor() if enabled else _window_bg_color()
            )

            # (The old titlebar decoration view that used to cause a seam
            # here is permanently hidden now — see configure_window_chrome.)

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
                    effect.setMaterial_(AppKit.NSVisualEffectMaterialHUDWindow)
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

    def save_backup(self, data):
        write_backup(data)
        return True

    def load_backup(self):
        return read_backup()

    def export_list_text(self, text, suggested_name):
        if window is None:
            return False
        result = window.create_file_dialog(
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
        if window is None:
            return None
        result = window.create_file_dialog(
            webview.FileDialog.OPEN,
            directory=str(Path.home() / "Downloads"),
            file_types=("Text files (*.txt)", "All files (*.*)"),
        )
        if not result:
            return None
        path = result[0] if isinstance(result, (list, tuple)) else result
        return Path(path).read_text()


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


def _run_vault_sync_cycle():
    local_raw = read_backup()
    if not local_raw:
        return
    try:
        local_state = json.loads(local_raw)
    except Exception:
        return
    merged = vault_sync.sync_pull_and_merge(local_state)
    if merged is None:
        return
    try:
        write_backup(json.dumps(merged))
    except Exception:
        return
    try:
        window.evaluate_js(f"window.__applySyncedState({json.dumps(json.dumps(merged))})")
    except Exception:
        pass


def vault_sync_loop():
    window.events.loaded.wait(timeout=15)
    _run_vault_sync_cycle()
    while not stop_event.is_set():
        if stop_event.wait(VAULT_SYNC_INTERVAL_SECONDS):
            break
        _run_vault_sync_cycle()


if __name__ == "__main__":
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
    threading.Thread(target=vault_sync_loop, daemon=True).start()

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
