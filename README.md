# List (macOS menu bar widget)

A small to-do list that lives in the menu bar — left-click the icon to pop
the list open directly, right-click for Hide/Quit. Ported from a Windows
system-tray version (`pywebview` + `pystray`) to macOS. The original
Windows version now lives on as its own project, sibling to this one:
[`list-widget-windows`](../list-widget-windows) — the two have diverged
since the port, so features added here (Calendar view, tab colors,
sounds, etc.) aren't automatically in that repo.

## Project layout

- `todo.html` — the entire UI/logic (tabs, due dates, repeats, sounds,
  animations, the Completed/Settings views, localStorage persistence).
  Pure HTML/JS.
- `app.py` — the native shell: creates the hidden `pywebview` window, the
  menu bar icon (`pystray`, left-click toggles the window directly,
  right-click shows Hide/Quit), positions the window under the menu bar,
  fires native notifications for due tasks, and enforces single-instance.
- `make_icon.py` — generates `icon.icns` (app icon) and `menubar_icon.png`
  (status bar glyph, a monochrome template image) from a small vector
  drawing.
- `list.spec` — PyInstaller build spec that bundles everything into
  `List.app`, with `LSUIElement` set so it never shows a Dock icon.

## Features

- Tabs for multiple lists, pinning, due dates/repeats (with explicit
  hour/minute/AM-PM fields, since the native time input silently follows
  the system's 24-hour-vs-12-hour locale setting) and a native calendar
  picker, native macOS notifications for due tasks.
- Drag tasks by the ⣿ handle (visible on hover) to manually reorder them
  within a list.
- Right-click a tab to rename it or set a color (preset swatches or a
  native color-wheel picker via a hidden `<input type="color">`).
- Adding a task plays a soft "bubble pop" sound and slides the row in;
  checking one off plays a warm "check" sound and slides it away —
  synthesized at runtime via the Web Audio API (no bundled audio files).
- Checked-off tasks move to the **Completed** view (🗂️ in the header)
  rather than disappearing — restore or permanently delete them there.
- **Settings** (⚙️ in the header) controls how long completed tasks stick
  around before being purged for good: end of day, after N hours, or
  never. There's no separate manual "clear" button — completed tasks
  live in the Completed view (restore/delete individually) until the
  retention timer sweeps them.
- Settings also has a "Translucent background" switch — a frosted,
  see-through look like Control Center, via a live-toggleable
  `NSVisualEffectView` (see "Live vibrancy toggle" below).
- Seamless window chrome: no title text, no titlebar strip, no header
  label — just the archive/settings icons, with the traffic lights
  floating directly over the app's own background (see "Seamless
  titlebar" below for how, since it's not a documented pywebview
  option).
- **Calendar** view (▦ in the header, with its own ☰ layout switcher):
  three interchangeable layouts — a day view with an hour grid, an
  agenda list grouped by Today/Tomorrow/This week/Later, and a mini
  month calendar with dots on days that have due tasks. Pulls due,
  not-yet-done tasks from every list (not just the active one), each
  tagged with its list's color.
- All in-app icons are plain monochrome Unicode symbols (☰ ▦ ☑ ⚙ ★ ◷),
  not colored emoji — matches native menu bar icon styling instead of
  looking like a mobile app.

## Develop

```bash
uv sync
uv run python app.py
```

Note: running it this way (not as a packaged `.app`) will show a Dock icon —
that's expected. It's a side effect of running via a bare `python`
interpreter instead of a real app bundle, and doesn't happen in the built
app (see "The Dock icon flip" below).

## Build the app

```bash
uv run python make_icon.py     # regenerate icons if the design changed
uv run pyinstaller list.spec --noconfirm
```

Output: `dist/List.app`.

## Install

```bash
cp -R dist/List.app /Applications/List.app
```

## Auto-start at login

A LaunchAgent is installed at
`~/Library/LaunchAgents/club.build4fun.listwidget.plist`, pointing at
`/Applications/List.app/Contents/MacOS/List`.

```bash
# reload after rebuilding/reinstalling the app
launchctl bootout gui/$(id -u)/club.build4fun.listwidget 2>/dev/null
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/club.build4fun.listwidget.plist

# stop auto-start entirely
launchctl bootout gui/$(id -u)/club.build4fun.listwidget
rm ~/Library/LaunchAgents/club.build4fun.listwidget.plist
```

The LaunchAgent only starts the app at login (`RunAtLoad`); quitting it
from the tray menu during a session does not restart it (`KeepAlive` is
off), matching how the Windows version behaved.

## Data

Tasks are stored in the WKWebView's `localStorage`, under
`~/Library/WebKit/club.build4fun.listwidget/` (keyed by the app's bundle
identifier — same storage that persisted `todo.widget.v3` on Windows,
just macOS's equivalent). Uninstalling the app does not delete this
automatically.

`webview.start()` must be called with `private_mode=False` — pywebview
defaults `private_mode` to `True`, which wipes all local storage (every
saved task) on every single launch, not just reinstalls. This is easy to
reintroduce by accident if `webview.start()` ever gets called without
that argument again.

That fix has a side effect worth knowing about while developing: WebKit's
disk/memory cache for `todo.html` now also survives restarts (previously,
wiping *everything* on launch incidentally wiped the HTML cache too, which
masked this). Editing `todo.html` and relaunching could silently keep
showing the old cached version. `clear_webkit_cache()` (called once at
startup, before the window loads) clears just the cache data types —
`WKWebsiteDataTypeDiskCache` / `WKWebsiteDataTypeMemoryCache` — leaving
local storage alone.

`quit_app()` also waits ~0.4s before tearing down the window. WKWebView's
actual localStorage persistence happens asynchronously in WebKit's
separate networking/storage process, not synchronously the instant
`localStorage.setItem()` returns in JS — destroying the window right
after a task was just added/edited risked losing that write. This
runs on the main thread (tray/menu callbacks are dispatched there), so
it can't call back into the WebView to force/await a flush —
`evaluate_js()` blocks on that same main run loop and would deadlock. A
plain `time.sleep()` is safe regardless, since the actual write happens
in that other process independent of whether our run loop is spinning.
SIGTERM (sent on logout/shutdown, unlike Cmd+Q or the tray Quit item)
gets the same treatment via a signal handler that defers back onto the
run loop rather than doing the flush-and-sleep inline.

## Uninstall

```bash
launchctl bootout gui/$(id -u)/club.build4fun.listwidget 2>/dev/null
rm ~/Library/LaunchAgents/club.build4fun.listwidget.plist
rm -rf /Applications/List.app
rm -rf ~/Library/Application\ Support/List   # single-instance lock file
rm -rf ~/Library/WebKit/club.build4fun.listwidget   # saved tasks
```

## Live vibrancy toggle

pywebview only supports a translucent/blurred window via `vibrancy=True`
and `transparent=True` passed to `create_window()` — both constructor-time
only, so they can't back a runtime Settings switch without recreating the
window. Instead, `app.py` exposes a `JsApi.set_vibrancy(enabled)` method via
pywebview's `js_api=` bridge (`window.pywebview.api.set_vibrancy(...)` from
JS, available after the `pywebviewready` event fires). That method reaches
into `webview.platforms.cocoa.BrowserView.instances["master"]` to grab the
actual `WKWebView` and `NSWindow` pywebview created, then does by hand what
`vibrancy=True`/`transparent=True` would have done at startup: sets
`underPageBackgroundColor` on the webview (the public, supported API for
this — `drawsTransparentBackground` is a private, deprecated KVC hook kept
only as a cheap extra nudge, not the real mechanism), makes the window
non-opaque, **clears the window's own `backgroundColor`** (it defaults to
a solid opaque fill from `configure_window_chrome` and blocks the blur
from ever sampling real content if left alone — this was the actual fix
after `underPageBackgroundColor` alone still didn't work), and inserts an
`NSVisualEffectView` behind the webview. `todo.html` toggles a
`body.vibrancy` CSS class (a heavily tinted, mostly-opaque color, not
fully see-through — see below) in lock step.

Two things worth knowing if this needs touching again:

- **Blur radius is not adjustable.** NSVisualEffectView materials
  (`.sidebar`, `.hudWindow`, `.fullScreenUI`, ...) differ in *tint*, not
  blur strength — swapping materials was tested and made no visible
  difference. macOS doesn't expose blur radius as a public API; matching
  Control Center's blur exactly isn't possible without implementing blur
  from scratch (continuously capturing + filtering whatever's behind the
  window), which is a much bigger, more fragile undertaking than this
  feature warrants. `body.vibrancy`'s tint is intentionally high (~90%
  opacity) specifically to compensate — it's doing more of the visual
  work than the actual blur is.
- **Startup reapply is a race, not just an event listener.** If vibrancy
  was left on, `todo.html` needs to reapply it once `window.pywebview.api`
  exists. Relying solely on the `pywebviewready` event was flaky — it can
  fire before the listener attaches, silently skipping the whole session.
  There's now also a `setTimeout` poll as a guaranteed fallback alongside
  the event.

## Seamless titlebar (why `app.py` pokes at private-ish AppKit views)

The goal: the traffic lights float inline with our own header controls (like
Claude Desktop), with no separate titlebar strip/seam at all. Getting there
took more than transparency tricks — `configure_window_chrome()` (hung off
`window.events.loaded`, since `window.native` doesn't exist until pywebview
builds it inside `webview.start()`, and has to run via `AppHelper.callAfter`
since that event fires off the main thread) does, in order:

1. `setTitlebarAppearsTransparent_(True)` + `setTitleVisibility_(NSWindowTitleHidden)`
   + `NSWindowStyleMaskFullSizeContentView` — hides the title text and lets
   content draw behind the titlebar. On its own this still leaves a visible
   seam: the native titlebar container reserves its full historical height
   as an (invisible but blocking) overlay, so anything our own content
   draws in that band renders *behind* it, not on top.
2. Grabs the three standard buttons via `standardWindowButton_` and
   re-parents them directly into the content view, positioned with Auto
   Layout constraints (not a fixed frame — a frame doesn't move when the
   window resizes, which just re-breaks the alignment).
3. Just removing the buttons from the titlebar doesn't stick on its own —
   as long as the window is still "titled", AppKit's own chrome-management
   machinery notices they're missing and puts fresh ones right back. The
   fix is to change the style mask to drop `NSWindowStyleMaskTitled`
   entirely (closable/resizable/miniaturizable are independent bits and
   stay on) — but a borderless window loses its automatic rounded corners
   and shadow, so those get reconstructed by hand: `setHasShadow_(True)`,
   and a `CALayer` corner radius + `masksToBounds` on the content view.
   `setMovableByWindowBackground_(True)` is set too, though it mostly does
   nothing here since the WKWebView covers nearly the entire window (no
   native "background" left to grab-drag from) — acceptable since this
   window repositions itself near the menu bar every time it's shown
   anyway.

## The Dock icon flip (why `app.py` re-asserts activation policy)

pywebview's Cocoa backend force-sets the app to a "Regular" activation
policy (Dock icon + Cmd+Tab entry) the moment it's imported. `app.py`
switches it to "Accessory" right after creating the window — but
pywebview's own `webview.start()` calls `activateIgnoringOtherApps_`
once as its run loop spins up, which flips the policy back to Regular
as an observed side effect. `app.py` re-asserts Accessory a handful of
times over the first ~3 seconds after `webview.start()` to ride past
that one-time flip. The built `.app`'s `Info.plist` also sets
`LSUIElement` for good measure, though the runtime flip happens
regardless of that setting.
