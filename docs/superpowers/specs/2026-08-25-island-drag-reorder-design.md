# Island Drag-to-Reorder + Tab Strip Auto-Scroll — Design

(C)

## Purpose

Two related tab-strip gaps:

1. **Islands can't be moved.** Individual tabs (`buildTabEl`) are `draggable` with full
   reorder/group logic. Island containers (`buildIslandWrapper`, `buildIslandPill`) only accept
   drops (tabs joining the island) — they can't be picked up and dragged themselves, so an
   island's position in the tab strip relative to other tabs/islands is fixed once formed.
2. **The tab strip doesn't auto-scroll during a drag.** `.tabs` has `overflow-x: auto`, but
   nothing scrolls it when a dragged tab/island is held near the strip's edge, so you can't drag
   something to a position that's currently off-screen.

## Non-goals

- No change to existing tab drag-and-drop (reorder via left/right edges, group via center) —
  unchanged.
- No change to how a tab joins/leaves an island (drag-into-island, the "Move to" right-click
  flyout) — unchanged.
- No merging/nesting of two islands when one is dropped onto another — confirmed explicitly: an
  island dropped onto another island only reorders position, never joins.
- No mid-island drop targets. Dropping between two members of a *different* island is not
  supported — see rationale below.
- No visible scroll affordance (fade/arrow buttons) for the auto-scroll — purely invisible,
  hover-near-edge-triggered.

## Data model

No new state fields. Reuses `state.lists` (ordering + `islandId`) and `state.islands`.

## Part 1: Island drag-to-reorder

### New drag-state variable

```js
// id of the island currently being drag-reordered (parallel to draggedListId).
let draggedIslandId = null;
```

### Making islands draggable

Both `buildIslandWrapper` and `buildIslandPill` gain `draggable = true` plus `dragstart`/`dragend`
handlers mirroring `buildTabEl`'s existing pattern:

```js
wrap.draggable = true;
wrap.ondragstart = ev => {
  draggedIslandId = island.id;
  wrap.classList.add("dragging");
  ev.dataTransfer.effectAllowed = "move";
  ev.dataTransfer.setData("text/plain", island.id);
};
wrap.ondragend = () => {
  wrap.classList.remove("dragging");
  tabsEl.querySelectorAll(".drag-over-left, .drag-over-right, .drag-over-group")
    .forEach(el => el.classList.remove("drag-over-left", "drag-over-right", "drag-over-group"));
  draggedIslandId = null;
};
```

Same pair of handlers on `pill` in `buildIslandPill`.

This coexists safely with the label's existing `onclick` (collapse) and `dblclick` (rename): the
browser only fires `dragstart` past a small pointer-move threshold, the same reason `tab.onclick`
and `tab.draggable` already coexist without conflict.

**Drag-source precedence:** member tabs inside `wrap.body` are independently `draggable`. Per the
HTML5 DnD spec, the browser picks the *nearest* draggable ancestor to the pointer as the drag
source — so starting a drag on a member tab still drags that tab (existing behavior, untouched).
Starting a drag on the island's label or the empty gaps in its body drags the whole island, since
`wrap` is the nearest draggable ancestor there.

### Drop targets

Considered and rejected: allowing a drop between two members of a *different* island. Rejected
because `normalizeIslandContiguity()` (called by every `save()`) re-glues each island's members
into one contiguous block positioned at that island's first-encountered member — so a mid-island
drop would silently snap to "before/after the whole island" once saved, which is a confusing
result. Valid targets are therefore only:

- **A standalone tab** (`buildTabEl`, `l.islandId === null`) — the tab's own rect split 50/50:
  left half = insert the dragged island before it, right half = insert after. No center "join"
  zone (islands never absorb into a tab this way).
- **Another island's wrapper/pill as a whole** — that island's own rect split 50/50: left half =
  insert before its first member, right half = insert after its last member.
- Member tabs *inside* another island are explicitly not separate drop targets — see below.

### Wiring into existing handlers

**`buildTabEl`'s `tab.ondragover`/`tab.ondrop`** (currently guarded by
`if (!draggedListId || draggedListId === l.id) return;`): add a branch above the existing tab-drag
logic, active only when `l.islandId` is null (a standalone tab) and an island drag is in progress:

```js
tab.ondragover = ev => {
  if (draggedIslandId && !l.islandId) {
    ev.preventDefault();
    const rect = tab.getBoundingClientRect();
    const pct = (ev.clientX - rect.left) / rect.width;
    tab.classList.toggle("drag-over-left", pct < 0.5);
    tab.classList.toggle("drag-over-right", pct >= 0.5);
    return;
  }
  if (!draggedListId || draggedListId === l.id) return;
  // ...existing tab-drag logic, unchanged...
};
tab.ondrop = ev => {
  ev.preventDefault();
  ev.stopPropagation();
  tab.classList.remove("drag-over-left", "drag-over-right", "drag-over-group");
  if (draggedIslandId && !l.islandId) {
    const rect = tab.getBoundingClientRect();
    const pct = (ev.clientX - rect.left) / rect.width;
    reorderIsland(draggedIslandId, l.id, pct < 0.5);
    return;
  }
  if (!draggedListId || draggedListId === l.id) return;
  // ...existing tab-drag logic, unchanged...
};
```

Member tabs (`l.islandId` set) fall through both new guards untouched — their existing handler
body still no-ops when `draggedListId` isn't set, which means the dragover/drop event is left
un-`preventDefault`ed/un-stopped and bubbles up to the enclosing island wrapper's own handler.
That bubbling is what makes "member tabs aren't separate drop targets" work for free.

**`buildIslandWrapper`'s `wrap.ondragover`/`wrap.ondrop`** and **`buildIslandPill`'s** equivalents
(currently guarded by `if (!draggedListId) return;`, used for "a tab joins this island"): add an
analogous branch, active when `draggedIslandId` is set and isn't this island's own id:

```js
wrap.ondragover = ev => {
  if (draggedIslandId && draggedIslandId !== island.id) {
    ev.preventDefault();
    const rect = wrap.getBoundingClientRect();
    const pct = (ev.clientX - rect.left) / rect.width;
    wrap.classList.toggle("drag-over-left", pct < 0.5);
    wrap.classList.toggle("drag-over-right", pct >= 0.5);
    return;
  }
  // ...existing "tab joins island" dragover logic, unchanged...
};
wrap.ondrop = ev => {
  ev.preventDefault();
  ev.stopPropagation();
  wrap.classList.remove("drag-over-left", "drag-over-right", "drag-over-group");
  if (draggedIslandId && draggedIslandId !== island.id) {
    const pct = (ev.clientX - wrap.getBoundingClientRect().left) / wrap.getBoundingClientRect().width;
    reorderIsland(draggedIslandId, pct < 0.5 ? members[0].id : members[members.length - 1].id, pct < 0.5);
    return;
  }
  // ...existing "tab joins island" drop logic, unchanged...
};
```

New CSS needed: `.island.drag-over-left`, `.island.drag-over-right`, and the `-pill` equivalents,
matching the existing `.tab.drag-over-left`/`-right` box-shadow treatment.

### The move itself

```js
// Pulls every member of `islandId` out of state.lists as one contiguous
// block (preserving their relative order) and reinserts them immediately
// before/after targetListId. Mirrors spliceListTo, but moves a block of
// tabs instead of a single one.
function spliceIslandTo(islandId, targetListId, insertBefore) {
  const lists = state.lists;
  const members = lists.filter(l => l.islandId === islandId);
  if (!members.length) return false;
  const memberIds = new Set(members.map(m => m.id));
  const remaining = lists.filter(l => !memberIds.has(l.id));
  const toIdx = remaining.findIndex(x => x.id === targetListId);
  if (toIdx === -1) {
    remaining.push(...members);
  } else {
    remaining.splice(insertBefore ? toIdx : toIdx + 1, 0, ...members);
  }
  state.lists = remaining;
  return true;
}

function reorderIsland(islandId, targetListId, insertBefore) {
  if (!spliceIslandTo(islandId, targetListId, insertBefore)) return;
  save();
  renderTabs();
}
```

Placed alongside the existing island helpers (`groupTabs`, `dissolveIslandIfSingleton`, etc.).

## Part 2: Tab strip auto-scroll during drag

### Trigger point

`tabsEl.ondragover` already runs continuously while any drag (tab, island, or tab-into-island) is
over the strip. Extending this one handler covers all three drag types without duplicating logic.

### Mechanics

```js
const AUTOSCROLL_ZONE = 48;   // px from edge that triggers scrolling
const AUTOSCROLL_MAX_SPEED = 12; // px per frame at the very edge

let autoscrollDir = 0; // -1, 0, or 1
let autoscrollSpeed = 0;
let autoscrollFrame = null;

function autoscrollStep() {
  if (autoscrollDir === 0) { autoscrollFrame = null; return; }
  tabsEl.scrollLeft += autoscrollDir * autoscrollSpeed;
  autoscrollFrame = requestAnimationFrame(autoscrollStep);
}

function updateAutoscroll(clientX) {
  const rect = tabsEl.getBoundingClientRect();
  const distFromLeft = clientX - rect.left;
  const distFromRight = rect.right - clientX;

  if (distFromLeft < AUTOSCROLL_ZONE) {
    autoscrollDir = -1;
    autoscrollSpeed = AUTOSCROLL_MAX_SPEED * (1 - Math.max(0, distFromLeft) / AUTOSCROLL_ZONE);
  } else if (distFromRight < AUTOSCROLL_ZONE) {
    autoscrollDir = 1;
    autoscrollSpeed = AUTOSCROLL_MAX_SPEED * (1 - Math.max(0, distFromRight) / AUTOSCROLL_ZONE);
  } else {
    autoscrollDir = 0;
  }

  if (autoscrollDir !== 0 && autoscrollFrame === null) {
    autoscrollFrame = requestAnimationFrame(autoscrollStep);
  }
}

function stopAutoscroll() {
  autoscrollDir = 0;
  if (autoscrollFrame !== null) { cancelAnimationFrame(autoscrollFrame); autoscrollFrame = null; }
}
```

Wired into the existing strip-level handler:

```js
tabsEl.ondragover = ev => {
  if (draggedListId || draggedIslandId) {
    ev.preventDefault();
    updateAutoscroll(ev.clientX);
  }
};
tabsEl.ondragleave = ev => {
  if (ev.target === tabsEl) stopAutoscroll();
};
tabsEl.ondrop = ev => {
  stopAutoscroll();
  // ...existing drop-into-open-space logic, unchanged...
};
```

Also call `stopAutoscroll()` from every existing `ondragend` handler (tab and island) as a
belt-and-suspenders cleanup, in case `drop`/`dragleave` don't fire cleanly (e.g. drag cancelled by
pressing Escape).

**Why `requestAnimationFrame` over `setInterval`:** self-throttles to the paint cycle, so scroll
speed stays visually smooth regardless of how bursty native `dragover` firing is.

### Interaction with drop-zone highlighting

No changes needed to how `drag-over-left`/`-right`/`-group` are computed on individual elements —
each element's handler already recomputes its highlight from the live pointer position on every
`dragover` fire, so as the strip scrolls beneath the (stationary) pointer, highlighting keeps
tracking correctly without extra work.

## Testing

No JS test harness exists for `todo.html` (pytest in `tests/` only covers `vault_sync.py`) —
verify manually via `uv run python app.py`:

**Island reorder:**
1. Form two islands (drag-group tabs together) plus at least one standalone tab. Drag island A by
   its label and drop on the left half of a standalone tab — confirm A's members move as a block
   to sit immediately before that tab, in their original relative order.
2. Drag island A and drop on the right half of island B's wrapper — confirm A's block lands
   immediately after B's last member, and B is untouched (no merge).
3. Drag island A and drop on the left half of collapsed island B's pill — same check, collapsed
   form.
4. Confirm dragging a member tab *out of* its island (existing behavior) still works unchanged —
   grabbing a tab inside the wrapper drags just that tab, not the island.
5. Confirm dropping an island onto itself, or onto one of its own members, is a no-op.

**Auto-scroll:**
1. Create enough tabs/islands to overflow the visible strip width. Start dragging a tab (or
   island) and hold the pointer within ~48px of the strip's right edge without releasing —
   confirm the strip scrolls right on its own, revealing more tabs, and speeds up closer to the
   edge.
2. Move the pointer back toward the middle of the strip — confirm scrolling stops immediately.
3. Drag toward the left edge — confirm the mirrored behavior.
4. Drop successfully after auto-scrolling into a previously off-screen position — confirm the
   drop target resolves correctly (not to whatever was under the pointer before scrolling).
5. Cancel a drag mid-auto-scroll (Escape key or dropping outside the window) — confirm scrolling
   stops and doesn't get stuck running.
