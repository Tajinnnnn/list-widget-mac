# Sidebar and glass implementation plan (C)

Approved: left sidebar with collapsible island groups, Icarus colors/controls, retain and repair glass. User said “go.”

Goal: keep every existing task/list workflow available in a compact, navigable widget with reliable native glass.
Architecture: preserve the single-page UI and state format. Change navigation layout in todo.html; isolate native composition in window_chrome.py and report actual completion through js_api.py.

- [x] Reproduce glass using a real WKWebView. Test enable/disable/re-enable, native failure reporting, and chrome setup after enabling. Use a dedicated content container so blur, web content, and traffic lights compose predictably. Keep all AppKit writes on the main thread.
- [x] Replace the horizontal strip with a 168px sidebar, vertical island rows, keyboard-accessible selection, a collapse button and current-view title. On narrow windows use an overlay drawer so the task column keeps its width. Convert list drop zones to top/center/bottom. Retain menus, list colors, grouped state, sync, and task behavior.
- [x] Apply Icarus dark plum/pink palette and restrained borders; retain a translucent body only after native success. Make the switch wait for native completion and display an error on failure. Native default 520x600; minimum 360x400.
- [x] Verify actual rendered UI at desktop and phone widths using an isolated fixture; exercise switching views, add/rename, groups, drag reordering, collapse/reopen, and glass failure/success. Run existing Python tests, native regression tests and package build. Preserve existing app and data when installing.

Constraints: no task/note deletion; preserve concurrent backup/sync edits. New artifacts marked (C). No change to sync schema or server deployment. Do not operate the user's live task data during verification.

Verification/decisions:
- Correction after full test: drawsTransparentBackground has no readable getter but its deprecated setter still works. Confirmed failures: effect inserted into private NSThemeFrame; late chrome setup overwrites the clear background; bridge reports success on native failure. drawsBackground supports both reads and writes.
- Inline execution after user approval; no additional design approval needed.

## Final verification

- Python suite: 146 passed, including real native regression tests.
- Browser fixture: navigation, create/rename, task add, all views, grouping, vertical drag, narrow widths and glass error handling passed.
- Native ephemeral smoke: startup glass and repeated toggles passed with correct native composition; separate resize test passed.
- Fresh reviewer identified queued timeout mutation; reproduced failing test, then fixed with atomic Future cancellation.
- Packaged app built and signature verified. Installed UI bytes match tested source.
- Installed at /Applications/List.app. Prior app and task backup preserved. Old running app did not exit on SIGTERM; no force quit used. User must quit/reopen List.
- UI automation could not attach to the menu-bar-only app, so verification used an isolated real WKWebView preview and browser screenshot rather than operating live tasks.

## Folder collapse follow-up

The shared-backup merge picks collapsed=false on timestamp ties. Its 3-second poll then reopens folders. Folder expansion now lives in a per-device localStorage preference keyed by island ID, reapplied during sync and recovery; collapse clicks no longer write the shared task document. Verified failing-then-passing integration test using real merge_docs, shared polling, reload, larger-backup recovery, and vault sync. Sidebar checks and all 146 Python tests pass. Updated app installed; restart required for the running process.
