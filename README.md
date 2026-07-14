# List (macOS menu bar widget)

A small to-do list that lives in the menu bar — left-click the icon to pop
the list open directly, right-click for Hide/Quit. Ported from a Windows
system-tray version (`pywebview` + `pystray`) to macOS.

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
- Adding a task plays a soft "bubble pop" sound and slides the row in;
  checking one off plays a warm "check" sound and slides it away —
  synthesized at runtime via the Web Audio API (no bundled audio files).
- Checked-off tasks move to the **Completed** view (🗂️ in the header)
  rather than disappearing — restore or permanently delete them there.
- **Settings** (⚙️ in the header) controls how long completed tasks stick
  around before being purged for good: end of day, after N hours, or
  never (manual clear only via the footer button).

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

## Uninstall

```bash
launchctl bootout gui/$(id -u)/club.build4fun.listwidget 2>/dev/null
rm ~/Library/LaunchAgents/club.build4fun.listwidget.plist
rm -rf /Applications/List.app
rm -rf ~/Library/Application\ Support/List   # single-instance lock file
rm -rf ~/Library/WebKit/club.build4fun.listwidget   # saved tasks
```

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
