# Move Tab to Island (via right-click) — Design

(C)

## Purpose

Islands (grouped tabs) can currently only be formed by dragging one tab onto another's center
zone (`groupTabs`, `todo.html`). There's no way to move a tab into an island, out of one, or into
a brand-new island without a drag gesture. This adds a "Move to" item to the tab's existing
right-click menu (`showTabMenu`) that does the same job through a menu instead.

## Non-goals

- No change to drag-and-drop grouping/ungrouping — it keeps working exactly as it does today.
- No change to how islands render (wrapper/pill), collapse, get renamed, or get colored.
- No bulk "move multiple tabs" — one tab at a time, same scope as the rest of `showTabMenu`.

## Data model

No new state fields. Reuses the existing `list.islandId` (on each tab in `state.lists`) and
`state.islands` (`{ id, name, color, collapsed }`).

## New helper functions

Added near the existing island helpers (`groupTabs`, `ungroupIsland`, `dissolveIslandIfSingleton`,
`adoptIslandColor`, `nextIslandName`, `spliceListTo`), around `todo.html:1134`.

```js
// Moves tab `l` into an existing island `islandId`. Appends it after that
// island's last current member so it doesn't land mid-group. Adopts the
// island's color (matches drag-to-group behavior). Dissolves l's previous
// island if l was its last non-solo member.
function moveTabToIsland(l, islandId) {
  if (l.islandId === islandId) return;
  const island = state.islands.find(x => x.id === islandId);
  if (!island) return;

  const prevIslandId = l.islandId;
  const members = state.lists.filter(x => x.islandId === islandId && x.id !== l.id);
  const lastMember = members[members.length - 1];

  l.islandId = islandId;
  adoptIslandColor(l, islandId);
  if (lastMember) spliceListTo(l.id, lastMember.id, false);
  if (prevIslandId) dissolveIslandIfSingleton(prevIslandId);

  save(); renderTabs(); renderList();
}

// Creates a brand-new island containing only `l`. Position in state.lists
// is left as-is — a solo island has no contiguity to maintain.
function moveTabToNewIsland(l) {
  const islandId = uid();
  state.islands.push({ id: islandId, name: nextIslandName(), color: null, collapsed: false });
  const prevIslandId = l.islandId;
  l.islandId = islandId;
  if (prevIslandId) dissolveIslandIfSingleton(prevIslandId);
  save(); renderTabs(); renderList();
}

// Pops `l` out of its island back to a standalone tab. No-op if it's not
// in one.
function removeTabFromIsland(l) {
  const islandId = l.islandId;
  if (!islandId) return;
  l.islandId = null;
  dissolveIslandIfSingleton(islandId);
  save(); renderTabs(); renderList();
}
```

`moveTabToIsland` is only ever invoked with an island id drawn from `state.islands` minus the
tab's own current island, so `lastMember` is guaranteed to exist whenever it's called from the UI
(an island only appears in the dropdown if it already has at least one other member).

## UI — "Move to" menu item

Added to `showTabMenu` (`todo.html:1702`) immediately after the existing "Rename" button, before
"Export as text".

The item itself is a `.tab-menu-item` reading `Move to ▸`. It doesn't fire an action on click —
it opens a flyout submenu on hover.

**Submenu contents, in order:**

1. **Remove from island** (`.tab-menu-item.danger`-free, plain item) — only rendered if
   `l.islandId` is set. Calls `removeTabFromIsland(l)` and closes both menus.
2. Separator — only rendered if item 1 is present AND there's at least one other island to list.
3. One `.tab-menu-item` per island in `state.islands` where `island.id !== l.islandId`, labeled
   with the island's name. Click calls `moveTabToIsland(l, island.id)` and closes both menus.
4. Separator — always rendered before item 5.
5. **New island…** — always present. Click calls `moveTabToNewIsland(l)` and closes both menus.

If `state.islands` is empty and `l.islandId` is null, the submenu contains only item 5.

**Flyout mechanics:**

- Reuses the `.tab-menu` CSS class for visual consistency (panel/border/shadow/padding), plus an
  additional `.tab-submenu` class for identification/cleanup.
- On `mouseenter` of the "Move to" item, open the submenu after a short delay (~150ms) positioned
  to the right of the item, top-aligned with it. If it would overflow the right edge of the
  window, flip it to the left of the main menu instead — same clamping approach the main menu
  already uses (`Math.max(8, Math.min(x, maxX))`).
- On `mouseleave` of the "Move to" item or the submenu itself, close the submenu after a short
  grace delay (~200ms), canceled if the pointer re-enters either element in that window — this is
  what lets the cursor cross the gap between the item and the flyout without it closing
  prematurely.
- Any click on the document (the existing `tabMenuCloser` listener) closes both the main menu and
  the submenu, same as today.

**`closeTabMenu()` change:** currently does `document.querySelector(".tab-menu")` (singular),
which would leave the submenu orphaned in the DOM once it also carries the `.tab-menu` class.
Change to `document.querySelectorAll(".tab-menu").forEach(el => el.remove())` so both the main
menu and any open submenu get cleared together.

## Testing

Existing test suite lives in `tests/`. This is a pure front-end (`todo.html`) interaction change
with no Python-side surface — verify manually in the running app:

- Right-click a standalone tab → "Move to" → pick an existing island → tab joins it, adopts its
  color, appears after its current members.
- Right-click a tab already in an island → "Move to" → confirm its own island is excluded from
  the list, "Remove from island" is present, picking a *different* island moves it there and
  dissolves the old island if it's now down to one member.
- Right-click a tab → "Move to" → "New island…" → confirms a fresh island is created with the
  default incrementing name and the tab moves into it solo.
- With zero islands in state, confirm the submenu shows only "New island…".
- Confirm mouse can cross from "Move to" into the submenu without it closing, and that clicking
  elsewhere closes both menus.
