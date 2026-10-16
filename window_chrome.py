import logging
from concurrent.futures import Future, TimeoutError

import AppKit
import WebKit
from PyObjCTools import AppHelper

import state

logger = logging.getLogger(__name__)


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


def _window_bg_color():
    return AppKit.NSColor.colorWithSRGBRed_green_blue_alpha_(
        0x0A / 255, 0x09 / 255, 0x0C / 255, 1.0
    )


def _browser_view():
    from webview.platforms.cocoa import BrowserView

    return BrowserView.instances.get(getattr(state.window, "uid", "master"))


def _content_container(browser_view):
    # Own the compositing stack rather than inserting siblings into AppKit's
    # private NSThemeFrame, which is rebuilt when the titlebar changes.
    container = getattr(browser_view, "_list_container", None)
    if container is None:
        web = browser_view.webview
        window = browser_view.window
        container = AppKit.NSView.alloc().initWithFrame_(web.frame())
        container.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
        web.retain()
        window.setContentView_(container)
        web.setFrame_(container.bounds())
        web.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
        container.addSubview_(web)
        web.release()
        browser_view._list_container = container
    return container


def configure_window_chrome():
    # window.native (the NSWindow) only exists once pywebview has actually
    # built the native window, which happens lazily inside webview.start() —
    # not yet when create_window() returns. "loaded" fires after that, but
    # from a background thread, so the actual mutation has to hop back to
    # the main thread (NSWindow geometry/style changes require it).
    def _apply():
        try:
            ns_window = state.window.native
            if ns_window is None:
                return
            ns_window.setTitlebarAppearsTransparent_(True)
            ns_window.setTitleVisibility_(AppKit.NSWindowTitleHidden)
            ns_window.setStyleMask_(
                ns_window.styleMask() | AppKit.NSWindowStyleMaskFullSizeContentView
            )
            browser_view = _browser_view()
            if browser_view is None:
                raise RuntimeError("Native browser is not ready")
            enabled = getattr(browser_view, "_list_vibrancy_enabled", False)
            ns_window.setOpaque_(not enabled)
            ns_window.setBackgroundColor_(AppKit.NSColor.clearColor() if enabled else _window_bg_color())
            content_view = _content_container(browser_view)

            # Grab the three standard buttons *before* going borderless —
            # standardWindowButton_ only returns real controls for a titled
            # window. Reparent them into the content view so they survive
            # losing the .titled bit next. Anchored via Auto Layout (not a
            # fixed frame) so they stay pinned to the top-left corner
            # correctly when the window is resized, regardless of the
            # content view's flipped-ness.
            button_center_y = 24
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
        except Exception:
            # Was a raw open()/write() straight to DEBUG_LOG_PATH (predating
            # the standardized logging setup in app.py) — now routed through
            # the same logger everything else durability-critical uses, so
            # this and the rest of the app's warnings land in one file in
            # one format instead of two different ones interleaved.
            logger.exception("configure_window_chrome failed")

    AppHelper.callAfter(_apply)


def _apply_vibrancy_now(enabled):
    """Apply on the AppKit thread; return the actual outcome to the bridge."""
    try:
        browser_view = _browser_view()
        if browser_view is None:
            raise RuntimeError("Native browser is not ready")
        web = browser_view.webview
        window = browser_view.window
        # WebKit's drawsTransparentBackground setter is deprecated. This KVC
        # setting is still private, so fail visibly if a future WebKit drops it.
        web.setValue_forKey_(not enabled, "drawsBackground")
        web.setUnderPageBackgroundColor_(
            AppKit.NSColor.clearColor() if enabled else _window_bg_color()
        )
        container = _content_container(browser_view)
        effect = getattr(browser_view, "_vibrancy_view", None)
        if enabled and effect is None:
            effect = AppKit.NSVisualEffectView.alloc().initWithFrame_(container.bounds())
            effect.setAutoresizingMask_(AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable)
            effect.setState_(AppKit.NSVisualEffectStateActive)
            effect.setMaterial_(AppKit.NSVisualEffectMaterialHUDWindow)
            effect.setAppearance_(AppKit.NSAppearance.appearanceNamed_(AppKit.NSAppearanceNameDarkAqua))
            effect.setBlendingMode_(AppKit.NSVisualEffectBlendingModeBehindWindow)
            container.addSubview_positioned_relativeTo_(effect, AppKit.NSWindowBelow, web)
            browser_view._vibrancy_view = effect
        if effect is not None:
            effect.setHidden_(not enabled)
        window.setOpaque_(not enabled)
        window.setBackgroundColor_(AppKit.NSColor.clearColor() if enabled else _window_bg_color())
        window.setHasShadow_(True)
        browser_view._list_vibrancy_enabled = enabled
        return True
    except Exception:
        logger.exception("apply_vibrancy failed")
        return False


def apply_vibrancy(enabled):
    if AppKit.NSThread.isMainThread():
        return _apply_vibrancy_now(bool(enabled))
    # pywebview invokes bridge methods on workers. Waiting there is safe;
    # never wait on the AppKit thread or call evaluate_js from this callback.
    result = Future()

    def apply():
        if result.set_running_or_notify_cancel():
            result.set_result(_apply_vibrancy_now(bool(enabled)))

    AppHelper.callAfter(apply)
    try:
        return result.result(timeout=5)
    except TimeoutError:
        # Cancellation and callback startup are atomic. A failed queued
        # request must never run later and disagree with the saved/CSS state.
        if result.cancel():
            logger.error("apply_vibrancy timed out waiting for AppKit")
            return False
        # AppKit already began the short synchronous operation: return its
        # actual result rather than pretending a running mutation was cancelled.
        return result.result()
