# List Widget ↔ Obsidian Vault Sync — Design

## Purpose

The widget's to-do lists currently live only in `~/Library/Application Support/List/backup.json`
(and mirrored WKWebView localStorage). This feature makes today's tasks visible and editable
from the Obsidian vault (`Tajin Brain`), so tasks can be checked off, added, or edited from
either the widget or today's daily note, with changes flowing both ways.

## Non-goals

- Syncing anything other than *today's* daily note. Past notes are frozen once the day rolls
  over (matches the vault's convention that `01 Journals/daily/` is author-owned, not
  LLM/automation-rewritten — see vault `CLAUDE.md`).
- A general-purpose two-way markdown/JSON sync library. This is scoped to this one file format
  and this one app.
- Syncing while the widget is fully quit. Reconciliation happens on next launch instead (see
  "Sync triggers" below) — no separate background daemon.

## Architecture

All sync logic lives inside `app.py`, reusing the existing background-daemon-thread pattern
already used for due-task notifications (`notification_loop`). No new process, no new launchd
job.

```
┌─────────────────┐   write_backup()    ┌──────────────────────┐
│   todo.html      │ ───────────────────▶│  app.py (Python)     │
│  (state, JS)     │                      │  - vault_sync.py     │
└─────────────────┘                      │  - poll today's note │
        ▲                                 │  - merge + tombstone │
        │ evaluate_js(...)                └──────────┬───────────┘
        └───────────────────────────────────────────┘│
                                                        ▼
                                    01 Journals/daily/<today>.md
                                            ## Tasks section
```

**Configuration:** `VAULT_ROOT` is a hardcoded constant in `vault_sync.py`
(`/Users/tajin/Documents/Coding/Obsidian/Tajin Brain`), matching the existing style of
`LOCK_PATH`/`BACKUP_PATH` in `app.py` — this is single-user, single-machine software, not
something that needs a settings UI. If the vault ever moves, this constant is updated the same
way those paths would be.

New module: `vault_sync.py`, imported by `app.py`. Pure functions, independently testable:

- `render_tasks_section(state: dict) -> str` — state → markdown for `## Tasks`.
- `parse_tasks_section(markdown: str) -> dict` — markdown → partial state (ids, text, done,
  due, pinned, repeat; no `notified`/settings/color, which aren't represented in markdown).
- `merge(local: dict, remote: dict) -> dict` — item-level last-write-wins merge using
  `updatedAt`, honoring tombstones (see "Merge strategy").
- `today_note_path(vault_root: Path) -> Path` — `01 Journals/daily/YYYY-MM-DD.md`, computed
  fresh each call so day-rollover is automatic.
- `ensure_note_exists(path: Path)` — if today's note doesn't exist yet, create it from
  `01 Journals/_daily-template.md` before writing the Tasks section into it.

## Data flow

**Push (widget → note), on every save:**
`todo.html`'s existing `save()` already calls `window.pywebview.api.save_backup(json)` on every
change. `write_backup()` in `app.py` is extended to also call
`vault_sync.render_tasks_section(state)` and splice the result into today's note (replacing the
content between `## Tasks` and the next `##` heading or EOF, leaving everything else in the note
untouched). This is synchronous with the existing backup write, so it inherits the same
temp-file + `os.replace()` atomic-write safety already used for `backup.json`.

**Pull (note → widget), background poll:**
A new daemon thread (same `threading.Thread(daemon=True)` pattern as `notification_loop`) polls
today's note's mtime every ~20s. On change:
1. Read + `parse_tasks_section()`.
2. `merge()` against current in-memory state.
3. If the merge changed anything, push the merged state into the webview via
   `window.evaluate_js()` (same mechanism `notification_loop` already uses to call into JS) and
   call `todo.html`'s existing `save()` path so `backup.json` and localStorage stay consistent.
4. Re-render the note from the merged state (normalizes formatting, attaches ids to any new
   lines the user added by hand in Obsidian).

**Reconcile on launch:**
Before the window is shown, read today's note (if it exists) and run the same merge step once,
so edits made in the vault while the widget was closed (e.g. from another device via Obsidian
Sync) are picked up immediately.

**Day rollover while running:**
The poll thread recomputes `today_note_path()` every cycle, so at midnight the next poll simply
starts targeting the new day's note. The old note is not touched again.

## Merge strategy

Each item gains an `updatedAt` ISO timestamp field, bumped on any local change (create, edit
text, toggle done, change due/pinned/repeat). Deletions become tombstones
(`{"_id", "deleted": true, "updatedAt": ...}`) rather than being removed outright.

`merge(local, remote)`:
- Union of items by `_id` across both sides.
- Item present on only one side → kept.
- Item on both sides → the copy with the newer `updatedAt` wins outright (whole-item, not
  field-level — simpler, and fine at personal-to-do-list edit frequency).
- Tombstones are treated as items for comparison purposes; a tombstone newer than the other
  side's copy wins (i.e. deletion sticks). A live copy newer than a tombstone resurrects the
  item (i.e. a genuine edit after a delete un-deletes it).
- Tombstones are purged 3 days after their `updatedAt` (both sides will have long since
  observed them by then; bounds unbounded growth in `backup.json`).
- Lists (tabs) merge the same way, by list `id`.

Items added directly in the markdown (no `<!--id:...-->` comment) are treated as new — a fresh
id is minted for them on the next merge and written back into the note.

## Markdown format

```markdown
## Tasks
### Tasks
- [ ] Get haircut <!--id:mrm5zkqtyfzzs-->
- [ ] Change card for gym 📅 2026-08-01 <!--id:mrkk9bxt9b00c-->
- [x] Gym 📌 🔁 daily <!--id:mrk70f4x3ffix-->

### Build4fun
- [ ] Build kickstarter product website <!--id:mrlg9aiq17zpb-->

### Completed today
- [x] Gym (Tasks) 📌 🔁 daily <!--id:mrk70f4x3ffix-->
```

- One `###` subsection per list/tab (by name).
- 📅 due date, 🔁 repeat, 📌 pinned — Obsidian-Tasks-plugin-compatible shorthand, readable
  without that plugin installed.
- `<!--id:...-->` HTML comment per line, invisible in Obsidian's rendered view, used for
  stable identity across renames.
- "Completed today" is a rollup of items where `done && completedAt` falls on today's date,
  annotated with their source list name. They also remain listed in their own list's section
  above — intentional duplication, not a bug — until the widget's own `retention: "endOfDay"`
  sweep removes them from state entirely (existing behavior, unchanged).
- Fields not represented in markdown (`notified`, list `color`, `active` tab, `settings`)
  round-trip only through `backup.json`, never through the note.

## Error handling

- Malformed/hand-edited markdown that doesn't parse cleanly (e.g. a checkbox line with no
  recognizable text): skip that line during `parse_tasks_section`, don't fail the whole
  merge. Log to the existing `List` log location, don't surface a UI error for a background
  sync.
- Note file missing (deleted, or vault moved) at poll time: skip that cycle silently, retry
  next interval. Push side calls `ensure_note_exists()` first, so it self-heals by recreating
  the note from the template.
- Vault root not found at the configured path: sync is a no-op (log once, don't retry-spam);
  the widget continues to function purely from `backup.json` as it does today.

## Testing

- Unit tests for `vault_sync.py`'s pure functions: `render_tasks_section` /
  `parse_tasks_section` round-trip (state → markdown → state produces the same items modulo
  fields not represented in markdown), and `merge()` against hand-built local/remote fixtures
  covering: disjoint additions on both sides, same-item edited on both sides (newer wins),
  delete-vs-edit ordering in both directions, tombstone purge after 3 days.
- Manual test pass through the actual app for the two live paths (push-on-save, poll-driven
  pull, launch-time reconcile, midnight rollover) — these depend on the pywebview run loop and
  aren't practical to unit test.

## Open questions / accepted limitations

- Whole-item (not field-level) LWW means if you edit two different fields of the same task on
  both sides between polls (e.g. rename it in the widget, reschedule its due date in Obsidian),
  one edit is fully discarded rather than merged field-by-field. Accepted for v1 given expected
  edit frequency; field-level merge is a possible future refinement if this proves annoying in
  practice.
- No sync while the widget is quit beyond the launch-time reconcile — see Non-goals.
