"""(C) Native regression coverage: real offscreen AppKit/WebKit views."""
from types import SimpleNamespace

import AppKit
import pytest
import WebKit
from webview.platforms.cocoa import BrowserView

import state
import window_chrome
from js_api import JsApi


@pytest.fixture
def native(monkeypatch):
    AppKit.NSApplication.sharedApplication()
    rect = AppKit.NSMakeRect(0, 0, 520, 600)
    window = AppKit.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        rect, AppKit.NSWindowStyleMaskTitled | AppKit.NSWindowStyleMaskResizable,
        AppKit.NSBackingStoreBuffered, False,
    )
    window.setReleasedWhenClosed_(False)
    web = WebKit.WKWebView.alloc().initWithFrame_(rect)
    window.setContentView_(web)
    view = SimpleNamespace(window=window, webview=web)
    monkeypatch.setitem(BrowserView.instances, 'master', view)
    monkeypatch.setattr(state, 'window', SimpleNamespace(native=window, uid='master'))
    monkeypatch.setattr(window_chrome.AppHelper, 'callAfter', lambda fn, *args: fn(*args))
    yield view
    window.close()


def test_glass_reaches_native_layer_and_survives_toggle(native):
    assert JsApi().set_vibrancy(True) is True
    assert not native.webview.valueForKey_('drawsBackground')
    assert not native.window.isOpaque()
    effect = getattr(native, '_vibrancy_view', None)
    assert effect is not None, 'glass layer must actually be installed'
    assert effect.superview() == native.webview.superview()
    assert native.window.contentView() == effect.superview()
    assert not effect.isHidden()
    assert JsApi().set_vibrancy(False) is True
    assert native.window.isOpaque()
    assert native.webview.valueForKey_('drawsBackground')
    assert effect.isHidden()
    assert JsApi().set_vibrancy(True) is True
    assert native._vibrancy_view == effect
    assert not effect.isHidden()


def test_failed_native_toggle_reports_failure(native, monkeypatch, caplog):
    class BrokenView:
        def setValue_forKey_(self, *_):
            raise RuntimeError('unsupported WebKit setting')
        def setUnderPageBackgroundColor_(self, *_):
            raise RuntimeError('unsupported WebKit setting')
    native.webview = BrokenView()
    assert JsApi().set_vibrancy(True) is False
    assert 'vibrancy' in caplog.text.lower()


def test_chrome_setup_does_not_undo_glass(native):
    assert JsApi().set_vibrancy(True) is True
    window_chrome.configure_window_chrome()
    assert native.window.backgroundColor().alphaComponent() == 0
    assert not native.window.isOpaque()
    assert native._vibrancy_view.superview() == native.window.contentView()


def test_timed_out_request_cannot_apply_later(native, monkeypatch):
    callbacks = []
    monkeypatch.setattr(window_chrome.AppKit, 'NSThread', SimpleNamespace(isMainThread=lambda: False))
    monkeypatch.setattr(window_chrome.AppHelper, 'callAfter', lambda fn, *args: callbacks.append(lambda: fn(*args)))
    assert JsApi().set_vibrancy(True) is False
    for callback in callbacks:
        callback()
    assert native.window.isOpaque(), 'a failed request must not change appearance later'
    assert getattr(native, '_list_vibrancy_enabled', False) is False


def test_resizing_keeps_glass_and_web_content_filling_window(native):
    window_chrome.configure_window_chrome()
    assert JsApi().set_vibrancy(True) is True
    native.window.setContentSize_(AppKit.NSMakeSize(640, 480))
    container = native.window.contentView()
    container.layoutSubtreeIfNeeded()
    assert native.webview.frame().size == container.bounds().size
    assert native._vibrancy_view.frame().size == container.bounds().size
