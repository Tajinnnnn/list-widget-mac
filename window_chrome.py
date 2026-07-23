import AppKit
import WebKit
from PyObjCTools import AppHelper

import state
from config import DEBUG_LOG_PATH


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
            ns_window = state.window.native
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
            DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(DEBUG_LOG_PATH, "a") as f:
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
