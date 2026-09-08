# iPhone PWA + Cross-Device Sync — Design

> `(C)` Claude-generated design document (2026-09-08).

## Purpose

The widget runs only on macOS. Its state lives in WKWebView `localStorage`, mirrored to
`~/Library/Application Support/List/backup.json`, and two-way-synced to today's Obsidian
daily note via `vault_sync.py`. None of those are reachable from a phone.

This feature makes the same list usable on an iPhone, with edits flowing both ways between
devices. It ships as a PWA (installed to the home screen) served from a small sync server
that owns the authoritative document.

The existing UI is the asset that makes this cheap: `todo.html` is 3,778 lines of
dependency-free HTML/JS, every native call is already guarded behind
`if (window.pywebview && ...)`, and the conflict-resolution discipline (`updatedAt`
stamps + tombstones) already exists.

## Non-goals

- **iOS push notifications.** Due-task alerts stay Mac-only for now. iOS Web Push
  (16.4+, home-screen PWAs only) needs a service-worker push handler, VAPID keys, and a
  server-side due-date scheduler. Its own project.
- **A WidgetKit home-screen widget.** WidgetKit renders SwiftUI only — it cannot display
  HTML, so it is a second app sharing a data format, not a port. Deferred deliberately;
  this design builds the sync layer such a widget would need anyway.
- **App Store distribution / the $99/yr Apple Developer Program.** Not required for a PWA.
- **Real user accounts.** Single-user, one shared secret. Signup/sessions/password reset
  are a layer above the sync engine and do not change it.
- **Shared or multi-user lists.** Concurrent editors are a materially harder merge problem
  than one person on two devices.
- **Moving vault sync off the Mac.** See "The vault stays Mac-only" below.

## Decisions

| Decision | Choice |
|---|---|
| iPhone form | PWA now (home-screen icon), native widget deferred |
| Sync users | Single user, one shared secret |
| iPhone feature scope | Full parity with the Mac app |
| Merge location | Server-side, in Python |
| Hosting | Vercel Python serverless + Neon Postgres |
| Freshness | Debounced push on save, pull on focus, 30s poll |
| iOS notifications | Out of scope |

## Architecture

```
List.app (Mac)  <--HTTPS-->  Sync server  <--HTTPS-->  iPhone PWA
  localStorage                merge_docs()              localStorage
  backup.json                 Neon Postgres             service worker
       |
       v
  Obsidian daily note  (Mac writes only)
```

- The server exposes exactly two endpoints and holds one row. All conflict resolution
  happens there, in Python.
- Both clients run the **same `todo.html`**. A `Platform` seam decides whether persistence
  goes through `window.pywebview.api` (Mac) or `fetch()` (web). The list logic is unaware
  of which.
- **The vault stays Mac-only.** The iPhone cannot reach `VAULT_ROOT`
  (`vault_sync.py:11`), so the Mac remains the sole writer of the `## Tasks` section.
  Consequence: a task added on the phone reaches today's daily note the next time the Mac
  is awake, not instantly. Acceptable — the Mac runs from a LaunchAgent at login.
- **`active` (the selected tab) is per-device and is not synced.** Which tab you are
  looking at should not jump because the other device changed it.

## Why `merge()` is not reused verbatim

`vault_sync.merge(local, remote, note_mtime)` is well-tested (57 of the project's 81 tests)
but is specifically a **document-to-markdown** merge. Four reasons it cannot serve
device-to-device sync as written:

1. **`remote` is a different shape.** `parse_tasks_section` (`vault_sync.py:222`) returns
   `{lists: [{id, name, items}]}` with markdown-parsed items keyed `id`. A device document
   has `_id`, `updatedAt`, `type`, `pinned`, `islandId`, subtasks, plus `settings`,
   `islands`, `trash`, `active`.
2. **It takes one timestamp for the entire remote** (`note_mtime`), because markdown carries
   no per-item times. A device document *has* per-item `updatedAt`; routing it through
   `merge()` would discard resolution the data already has.
3. **Its vault exclusions invert for devices.** `vault_sync.py:411-417` skips
   `syncToVault: false` lists and `type: "note"` items from tombstoning, because
   `render_tasks_section` deliberately omits them from the note. Correct for markdown;
   for devices it means notes and vault-excluded lists would never delete across devices.
4. **It merges only `lists` and `tombstones`.** `settings`, `islands`, and `trash` are
   untouched.

The plan is therefore a **sibling** function in the same module, sharing
`purge_old_tombstones` and the tombstone discipline. `merge()` is unchanged and keeps
owning the vault path.

## Data model

### `merge_docs(a: dict, b: dict) -> dict`

Symmetric, per-item last-write-wins over ISO-8601 `updatedAt` strings (lexicographic
comparison is correct for the fixed-width UTC format the client emits).

- **Items** — union by `_id`. Present in both: the copy with the greater `updatedAt` wins.
  Present in one: included unless the other side holds a tombstone with a strictly greater
  `updatedAt`.
- **An item's home list** is taken from the winning copy, so a cross-list move on one device
  is respected rather than duplicating the item.
- **Tombstones** — union by `_id`, keeping the greater `updatedAt`. Purged through the
  existing `purge_old_tombstones` (3-day horizon).
- **Lists** — union by `id`. A new per-list `updatedAt` decides `name`, `color`, and
  `syncToVault`. Membership order comes from the side whose list `updatedAt` is newer;
  items that side does not know about are appended, and the client re-runs its existing
  `normalizeIslandContiguity()` / `normalizeSubtaskContiguity()` after applying.
- **`settings`** — whole-object LWW via a new `settings.updatedAt`.
- **`islands`** — union by id, per-island `updatedAt`.
- **`trash`** — union by `_id`, LWW; the existing `trashRetention` purge still applies
  client-side.
- **`active`** — never merged; preserved from whichever document the caller treats as local.
- **Tie-break.** When two `updatedAt` values are equal, take the copy whose
  `json.dumps(obj, sort_keys=True)` is lexicographically smaller. Arbitrary but
  deterministic, which is what makes symmetry hold.

Two properties the test suite asserts directly:

- **Symmetry:** `merge_docs(a, b) == merge_docs(b, a)`
- **Idempotence:** `merge_docs(a, a) == a`

Symmetry plus idempotence is what removes the need for an optimistic-concurrency retry
loop: concurrent pushes converge regardless of arrival order.

### New timestamp coverage

`stampUpdatedAtAndTombstones()` (`todo.html:864`) currently stamps **items only** — a list
rename, a tab color change, a settings toggle, and an island edit are all invisible to LWW.
It is extended to stamp:

- `list.updatedAt` — tracked fields: `name`, `color`, `syncToVault`, and item-id order
- `settings.updatedAt` — any tracked settings field
- `island.updatedAt` — any tracked island field
- `trash` entries — stamped on entry

It keeps its existing `lastItemFields` snapshot-diff approach, extended to lists, settings,
and islands, so a save that changes nothing still stamps nothing.

### Server storage

```sql
CREATE TABLE IF NOT EXISTS state (
  id         text        PRIMARY KEY DEFAULT 'singleton',
  doc        jsonb       NOT NULL,
  version    bigint      NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now()
);
```

One row. The live document measured 37.6 KB, so whole-document transfer per sync is
correct and no delta protocol, pagination, or compression is warranted.

## Part 1: `merge_docs` (`vault_sync.py`)

Added alongside `merge()`, sharing `_gen_id`, `purge_old_tombstones`, and the module's
existing helpers. Pure — no filesystem access, no `VAULT_ROOT` use — so the server can
import the module without touching a vault path.

## Part 2: `Platform` seam (`todo.html`)

The native surface is exactly five bridge methods (`js_api.py`): `set_vibrancy`,
`save_backup`, `load_backup`, `export_list_text`, `import_list_text`. They are called from
seven sites in `todo.html` (lines 1351, 1364, 2095, 2190, 2988, 3761, 3772).

Introduce a single `Platform` object with two implementations selected once at startup:

| Method | `PywebviewPlatform` | `WebPlatform` |
|---|---|---|
| `saveState(json)` | `api.save_backup` | debounced `POST /api/state` |
| `loadState()` | `api.load_backup` | `GET /api/state` |
| `exportText(text, name)` | `api.export_list_text` | Blob + `<a download>` |
| `importText()` | `api.import_list_text` | hidden `<input type="file">` |
| `setVibrancy(on)` | `api.set_vibrancy` | no-op |
| `canVibrancy` | `true` | `false` |

`recoverFromBackupIfNewer()` keeps its "strictly more items wins" heuristic on Mac and
becomes a plain pull on web (where the server is authoritative and cannot be stale in the
way `localStorage` can).

## Part 3: Sync server

Vercel Python serverless functions plus Neon Postgres. The same deployment serves
`todo.html`, the manifest, the service worker, and the icons as static files.

- `GET /api/state` -> `{doc, version}`
- `POST /api/state` with `{doc}` -> server reads the stored row, computes
  `merge_docs(stored, incoming)`, writes it back if changed, and returns
  `{doc: merged, version}`

Auth is a shared secret in an `Authorization: Bearer <secret>` header — a header, not a
URL segment, so it stays out of server logs and `Referer`. The secret is stored in
`localStorage` after first entry and never appears in the manifest or in git.

The read-modify-write in `POST` runs inside a transaction with `SELECT ... FOR UPDATE` on
the row. `merge_docs` converging is not sufficient on its own — two interleaved
read-modify-write cycles can still lose an update if neither sees the other's write.

## Part 4: PWA shell

- `manifest.webmanifest` — `display: standalone`, name "List", theme color matched to the
  app background, 192px and 512px icons generated by extending `make_icon.py`.
- Service worker — cache-first for the shell (`todo.html`, manifest, icons), network-only
  for `/api/*`. Never cache API responses; `localStorage` is already the offline store.
- `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">`
  plus `env(safe-area-inset-*)` padding for the notch and home indicator.
- `apple-mobile-web-app-capable` for older iOS.
- **Web Audio unlock.** iOS suspends `AudioContext` until a user gesture. The existing
  synthesized pop/check sounds get a one-time `resume()` on first `pointerdown`, or they
  are silently dead on the phone.
- **Applying a pulled document is deferred while the user is mid-edit.** If an input has
  focus or an inline editor is open, a newly pulled document is held and applied on blur —
  otherwise a background poll clobbers a half-typed task.

## Part 5: Responsive layout

All four `@media` queries in `todo.html` are `prefers-color-scheme: light`. There are
**zero width breakpoints** — this is greenfield responsive work, and along with Part 6 it is
the bulk of the effort.

- `width: 460px` (line 44) -> `width: 100%; max-width: 460px`
- A single `max-width: 480px` breakpoint covering the header icon row, the tab strip
  (horizontal scroll already exists from the island work), and the fixed widths at lines
  390, 454, and 739
- Calendar defaults to the **agenda** layout on narrow screens; the hour-grid day view
  remains reachable but is not the default
- Touch targets to a 44px minimum
- Traffic-light clearance in the window chrome is suppressed on web (there is no titlebar)
- The explicit hour/minute/AM-PM due-time fields already work well on touch and are
  unchanged

## Part 6: Touch reorder

All three drag interactions use HTML5 native drag-and-drop (`draggable` +
`dragstart`/`dragover`/`dragend` + `dataTransfer`), which **never fires from touch on iOS
Safari**. Not degraded — inert. All three are rebuilt on Pointer Events behind one shared
`makeReorderable()` helper:

1. **Tab reorder** — `todo.html:1460` (`draggedListId`)
2. **Task row reorder** — `todo.html:2384` (`draggedItemId`)
3. **Attached-note drag-out to un-route** — `todo.html:2562` (`draggedAttachedFromId`)

`makeReorderable()` lifts immediately on mouse and after a 350ms long-press on touch,
tracks with `setPointerCapture`, and reuses the edge auto-scroll logic from the tab-strip
work in `2026-08-25-island-drag-reorder-design.md`.

**Site 3 needs a new affordance, not a port.** Dragging a note *out* of a task has no
natural touch equivalent. It becomes a long-press context menu with an "Un-route" item —
the same interaction pattern as the existing right-click tab menu, so it does not feel
bolted on. The mouse drag-out gesture is retained on Mac.

## Sequencing

Each slice is independently useful and independently abandonable.

1. **Server + Mac client.** No iPhone. The Mac behaves identically to today but round-trips
   through the server. Proves `merge_docs` against the real 37.6 KB document at zero
   user-visible risk.
2. **iPhone, read-only.** Serve `todo.html`, install to the home screen, pull and render.
   Small work, disproportionate payoff — the list is visible on the phone.
3. **iPhone editing.** Check off, add, edit, due dates. Sync becomes bidirectional.
4. **Responsive polish + touch reorder.** Parts 5 and 6.

The cheap half delivers the actual request by the end of slice 2. If attention moves on
after that, the result is a working list on the phone rather than a half-refactored Mac app.

## Testing

- **`merge_docs`** — mirrors `test_vault_sync.py`'s structure, plus explicit symmetry and
  idempotence assertions, cross-list moves, tombstone-vs-edit races, and a stale-device
  case (a phone dark for a day must not resurrect items deleted on the Mac).
- **Endpoints** — tested against a fake store: auth rejection, empty-database first write,
  concurrent `POST` serialization.
- **`Platform` seam** — existing `test_js_api_export_import.py` extended; the web
  implementation is exercised headlessly.
- **Regression gate** — the full 81-test suite passes before any slice merges. The Mac app
  is in daily use; all work happens in a git worktree and `/Applications/List.app` is not
  replaced until a slice is green.
- **Manual, on a real iPhone.** Install to home screen, offline edit, reconnect, audio
  unlock, safe-area rendering, and all three reorder gestures. Desktop Safari's responsive
  mode does not reproduce iOS touch, storage, or install behavior.

## Risks

| Risk | Mitigation |
|---|---|
| Breaking the daily driver — this refactors storage and all three drag paths in a single 3,778-line file | Git worktree; the 81-test suite is the merge gate; the installed app is untouched until a slice is green |
| `merge_docs` resolves a conflict wrong and loses a task | Symmetry/idempotence properties plus a mirrored version of the 57-test vault-sync suite, written before any client is wired to it |
| iOS evicts the PWA's `localStorage` | The server is authoritative, so eviction degrades to a re-pull. Non-issue by design |
| Anyone with the URL and secret reads the list | It is a to-do list, not money. Bearer header rather than URL; secret out of git and out of the manifest |
| A Vercel deploy does not actually go live (cf. the 14-day stale fleur-relay alias) | Every deploy is `npx vercel --prod`, verified with `vercel inspect <domain>` — not `alias ls` |
| A background pull overwrites an in-progress edit | Pulled documents are deferred while an input has focus and applied on blur (Part 4) |
