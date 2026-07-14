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

- Tabs for multiple lists, pinning, due dates/repeats with a native
  calendar picker, native macOS notifications for due tasks.
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
`drawsTransparentBackground` on the webview, makes the window non-opaque,
and inserts an `NSVisualEffectView` behind the webview. `todo.html` toggles
a `body.vibrancy` CSS class (translucent instead of solid `--bg`) in lock
step so the blur actually shows through.

## Seamless titlebar (why `app.py` pokes at private-ish AppKit views)

`configure_window_chrome()` (hung off `window.events.loaded`, since
`window.native` — the actual `NSWindow` — doesn't exist until pywebview
builds it inside `webview.start()`) does three things:

1. `setTitlebarAppearsTransparent_(True)` + `setTitleVisibility_(NSWindowTitleHidden)`
   + adds `NSWindowStyleMaskFullSizeContentView` to the style mask — the
   documented way to hide the title text and let content draw behind the
   titlebar.
2. `setBackgroundColor_(...)` on the window itself, matching `--bg`.
3. Overrides the background color of `window.contentView().superview().subviews().lastObject()`
   — pywebview's own `cocoa.py` explicitly recolors this exact view (the
   titlebar's decoration view) to `NSColor.windowBackgroundColor()` right
   after creating the window "so it does not change with the window
   color". That system gray is what shows up as a seam above the traffic
   lights if you only do (1) and (2) — (3) is what actually removes it.

All of this has to run via `AppHelper.callAfter`, since the `loaded` event
fires off the main thread and NSWindow won't allow geometry/style changes
from anywhere else.

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
