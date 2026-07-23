import AppKit
import pystray
from PIL import Image

import state
from config import APP_TITLE, resource_path
from window_controls import hide_window, quit_app, toggle_window


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
    icon_image = Image.open(resource_path("menubar_icon.png"))
    menu = pystray.Menu(
        pystray.MenuItem("Hide", hide_window),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_app),
    )
    state.tray_icon = TrayIcon(
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

    state.tray_icon.run_detached(setup=_setup)
