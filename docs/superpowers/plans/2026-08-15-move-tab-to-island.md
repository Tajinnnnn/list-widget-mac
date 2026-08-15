# Move Tab to Island (via right-click) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Move to" item to a tab's right-click menu that opens a hover flyout listing the
app's current islands, so a tab can be moved into an existing island, into a new island, or
removed from its current island — without dragging.

**Architecture:** Pure front-end change, entirely inside `todo.html` (vanilla JS + inline CSS, no
build step, no framework). Three new helper functions operate on the existing `state.lists` /
`state.islands` model; one new UI branch in `showTabMenu` renders the "Move to" item and its
flyout submenu, reusing the existing `.tab-menu` CSS class and the existing `closeTabMenu`
lifecycle.

**Tech Stack:** Vanilla JS, inline `<style>` CSS, pywebview desktop shell (`app.py`). No JS test
framework exists in this project (`tests/` is pytest-only, covering `vault_sync.py`) — verification
is manual, driving the running app.

## Global Constraints

- Single file touched: `todo.html`. No Python-side changes — `app.py` and friends are untouched.
- Reuse existing helpers/patterns exactly: `adoptIslandColor`, `dissolveIslandIfSingleton`,
  `nextIslandName`, `spliceListTo`, `uid`, `save`/`renderTabs`/`renderList`, the `.tab-menu` /
  `.tab-menu-item` / `.tab-menu-sep` CSS classes, and the `tabMenuCloser` +
  `document.addEventListener("click", ...)` close-on-outside-click pattern.
- No new state fields — only `list.islandId` and `state.islands`, both already present.
- Match existing code style: no comments except where a non-obvious constraint needs explaining
  (this file already follows that convention — see e.g. the comment above `buildIslandWrapper`).
- Run the app with `uv run python app.py` from the project root to manually verify (per
  `README.md`).

---

### Task 1: Island move/remove helper functions + `closeTabMenu` multi-element fix

**Files:**
- Modify: `todo.html:1155-1160` (insert new functions right after `groupTabs`)
- Modify: `todo.html:1693-1700` (`closeTabMenu`)

**Interfaces:**
- Consumes: `state.islands`, `state.lists`, `adoptIslandColor(list, islandId)`,
  `dissolveIslandIfSingleton(islandId)`, `nextIslandName()`, `spliceListTo(draggedId, targetId,
  insertBefore)`, `uid()`, `save()`, `renderTabs()`, `renderList()` — all already defined earlier
  in `todo.html`.
- Produces: `moveTabToIsland(l, islandId)`, `moveTabToNewIsland(l)`, `removeTabFromIsland(l)` — all
  three take a list object (`l`, an entry from `state.lists`) and mutate + persist state. Task 2
  wires these into the UI.

- [ ] **Step 1: Add the three helper functions right after `groupTabs`**

Find this exact block (the end of `groupTabs`, `todo.html:1155-1162`):

```js
    if (prevIslandId) dissolveIslandIfSingleton(prevIslandId);

    save();
    renderTabs();
    renderList();
  }

  // "active" shows open tasks; "completed" shows the current list's
  // finished tasks (still just a view over the same underlying data).
```

Replace it with (adds three new functions between the closing `}` of `groupTabs` and the
`viewMode` comment):

```js
    if (prevIslandId) dissolveIslandIfSingleton(prevIslandId);

    save();
    renderTabs();
    renderList();
  }

  // Moves tab `l` into an existing island `islandId`, via the tab's
  // right-click "Move to" menu (as opposed to groupTabs' drag-and-drop
  // path). Appends after that island's current last member so it doesn't
  // land mid-group. Dissolves l's previous island if l was its last
  // non-solo member.
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

    save();
    renderTabs();
    renderList();
  }

  // Creates a brand-new island containing only `l`. Position in
  // state.lists is left as-is — a solo island has no contiguity to
  // maintain.
  function moveTabToNewIsland(l) {
    const islandId = uid();
    state.islands.push({ id: islandId, name: nextIslandName(), color: null, collapsed: false });
    const prevIslandId = l.islandId;
    l.islandId = islandId;
    if (prevIslandId) dissolveIslandIfSingleton(prevIslandId);

    save();
    renderTabs();
    renderList();
  }

  // Pops `l` out of its island back to a standalone tab. No-op if it's
  // not in one.
  function removeTabFromIsland(l) {
    const islandId = l.islandId;
    if (!islandId) return;
    l.islandId = null;
    dissolveIslandIfSingleton(islandId);

    save();
    renderTabs();
    renderList();
  }

  // "active" shows open tasks; "completed" shows the current list's
  // finished tasks (still just a view over the same underlying data).
```

- [ ] **Step 2: Fix `closeTabMenu` to remove every `.tab-menu` element, not just the first**

Task 2 will give the flyout submenu the class `tab-menu tab-submenu` so it shares the panel
styling. `closeTabMenu` currently only removes a single `.tab-menu` via `querySelector`, which
would orphan the submenu in the DOM. Find this exact block (`todo.html:1693-1700`):

```js
  function closeTabMenu() {
    if (tabMenuCloser) {
      document.removeEventListener("click", tabMenuCloser);
      tabMenuCloser = null;
    }
    const existing = document.querySelector(".tab-menu");
    if (existing) existing.remove();
  }
```

Replace with:

```js
  function closeTabMenu() {
    if (tabMenuCloser) {
      document.removeEventListener("click", tabMenuCloser);
      tabMenuCloser = null;
    }
    document.querySelectorAll(".tab-menu").forEach(el => el.remove());
  }
```

- [ ] **Step 3: Manually verify the helpers with the running app's dev console**

There's no JS test harness in this project — verify via the app itself:

```bash
uv run python app.py
```

Once the widget window is open, open its WebKit inspector (right-click the window → Inspect
Element, or enable it via `WEBVIEW_DEBUG=1 uv run python app.py` if the app doesn't show it by
default) and run in the console:

```js
// Create two tabs and an island by dragging one onto the other first (or,
// if you already have 2+ tabs, group them via drag), then in the console:
console.log(state.islands);        // should list the island you just made
const l = state.lists.find(x => !x.islandId);  // a standalone tab
moveTabToIsland(l, state.islands[0].id);
console.log(l.islandId === state.islands[0].id);  // true
removeTabFromIsland(l);
console.log(l.islandId);           // null
moveTabToNewIsland(l);
console.log(state.islands.some(i => i.id === l.islandId));  // true
```

Expected: all three `console.log` assertions print `true` / the expected value, and `renderTabs()`
having run means the tab strip visibly updates after each call without needing a manual refresh.

- [ ] **Step 4: Commit**

```bash
git add todo.html
git commit -m "feat: add island move/remove helpers for tab context menu"
```

---

### Task 2: "Move to" menu item + hover flyout submenu

**Files:**
- Modify: `todo.html:453` (CSS, add `.tab-submenu` stacking rule)
- Modify: `todo.html:1702-1717` (`showTabMenu` — insert the "Move to" item)
- Modify: `todo.html` (add `submenuOpenTimer` / `submenuCloseTimer` state and the
  `closeSubmenu` / `positionFlyout` / `buildMoveToSubmenu` helpers near `showTabMenu`)

**Interfaces:**
- Consumes: `moveTabToIsland`, `moveTabToNewIsland`, `removeTabFromIsland` (Task 1),
  `closeTabMenu()`, `state.islands`, the tab object `l` already in scope inside `showTabMenu`.
- Produces: no new externally-consumed functions — this task is the UI leaf that wires Task 1's
  helpers to the menu. `closeSubmenu()` and `buildMoveToSubmenu(l)` are used only within this task.

- [ ] **Step 1: Add `.tab-submenu` stacking rule to the CSS**

Find this exact line (`todo.html:453`):

```css
  .tab-menu-sep { border-top: 1px solid var(--line); margin: 4px 0; }
```

Replace with:

```css
  .tab-menu-sep { border-top: 1px solid var(--line); margin: 4px 0; }
  .tab-submenu { z-index: 11; }
```

- [ ] **Step 2: Add submenu timer state and the `closeSubmenu` / `positionFlyout` helpers**

Find this exact block (`todo.html:1691-1701`, right before `showTabMenu`):

```js
  let tabMenuCloser = null;

  function closeTabMenu() {
    if (tabMenuCloser) {
      document.removeEventListener("click", tabMenuCloser);
      tabMenuCloser = null;
    }
    document.querySelectorAll(".tab-menu").forEach(el => el.remove());
  }

  function showTabMenu(l, tab, x, y) {
```

Replace with:

```js
  let tabMenuCloser = null;

  function closeTabMenu() {
    if (tabMenuCloser) {
      document.removeEventListener("click", tabMenuCloser);
      tabMenuCloser = null;
    }
    document.querySelectorAll(".tab-menu").forEach(el => el.remove());
  }

  function closeSubmenu() {
    document.querySelectorAll(".tab-submenu").forEach(el => el.remove());
  }

  // Positions a flyout (the "Move to" submenu) beside its anchor button.
  // Prefers opening to the right; flips to the left of the anchor if
  // there isn't enough room, mirroring the viewport-edge clamping the
  // main tab-menu already does for its own x/y.
  function positionFlyout(el, anchorRect) {
    document.body.appendChild(el);
    const menuWidth = el.offsetWidth;
    const menuHeight = el.offsetHeight;
    const left = (anchorRect.right + 4 + menuWidth <= window.innerWidth - 8)
      ? anchorRect.right + 4
      : Math.max(8, anchorRect.left - menuWidth - 4);
    const maxTop = window.innerHeight - menuHeight - 8;
    el.style.left = left + "px";
    el.style.top = Math.max(8, Math.min(anchorRect.top, maxTop)) + "px";
  }

  // Builds the "Move to" flyout for tab `l`: an optional "Remove from
  // island" (only if l is currently in one), every other island, and an
  // always-present "New island…" entry.
  function buildMoveToSubmenu(l) {
    const submenu = document.createElement("div");
    submenu.className = "tab-menu tab-submenu";
    submenu.onclick = ev => ev.stopPropagation();

    const otherIslands = state.islands.filter(x => x.id !== l.islandId);

    if (l.islandId) {
      const removeBtn = document.createElement("button");
      removeBtn.className = "tab-menu-item";
      removeBtn.textContent = "Remove from island";
      removeBtn.onclick = () => {
        closeTabMenu();
        removeTabFromIsland(l);
      };
      submenu.appendChild(removeBtn);

      if (otherIslands.length) {
        submenu.appendChild(Object.assign(document.createElement("div"), { className: "tab-menu-sep" }));
      }
    }

    otherIslands.forEach(island => {
      const btn = document.createElement("button");
      btn.className = "tab-menu-item";
      btn.textContent = island.name;
      btn.onclick = () => {
        closeTabMenu();
        moveTabToIsland(l, island.id);
      };
      submenu.appendChild(btn);
    });

    submenu.appendChild(Object.assign(document.createElement("div"), { className: "tab-menu-sep" }));

    const newIslandBtn = document.createElement("button");
    newIslandBtn.className = "tab-menu-item";
    newIslandBtn.textContent = "New island…";
    newIslandBtn.onclick = () => {
      closeTabMenu();
      moveTabToNewIsland(l);
    };
    submenu.appendChild(newIslandBtn);

    return submenu;
  }

  let submenuOpenTimer = null;
  let submenuCloseTimer = null;

  function showTabMenu(l, tab, x, y) {
```

- [ ] **Step 3: Add the "Move to" menu item, wired to open/close the flyout on hover**

Find this exact block (`todo.html:1709-1717`, the "Rename" button inside `showTabMenu`):

```js
    const renameBtn = document.createElement("button");
    renameBtn.className = "tab-menu-item";
    renameBtn.textContent = "Rename";
    renameBtn.onclick = () => {
      closeTabMenu();
      const nameEl = tab.querySelector(".tab-name-text");
      if (nameEl) renameTab(l, tab, nameEl, true);
    };
    menu.appendChild(renameBtn);
```

Replace with (adds the "Move to" item right after it):

```js
    const renameBtn = document.createElement("button");
    renameBtn.className = "tab-menu-item";
    renameBtn.textContent = "Rename";
    renameBtn.onclick = () => {
      closeTabMenu();
      const nameEl = tab.querySelector(".tab-name-text");
      if (nameEl) renameTab(l, tab, nameEl, true);
    };
    menu.appendChild(renameBtn);

    const moveToBtn = document.createElement("button");
    moveToBtn.className = "tab-menu-item";
    moveToBtn.textContent = "Move to ▸";

    const scheduleSubmenuOpen = () => {
      clearTimeout(submenuCloseTimer);
      clearTimeout(submenuOpenTimer);
      submenuOpenTimer = setTimeout(() => {
        closeSubmenu();
        const submenu = buildMoveToSubmenu(l);
        positionFlyout(submenu, moveToBtn.getBoundingClientRect());
        submenu.onmouseenter = () => clearTimeout(submenuCloseTimer);
        submenu.onmouseleave = scheduleSubmenuClose;
      }, 150);
    };
    const scheduleSubmenuClose = () => {
      clearTimeout(submenuOpenTimer);
      clearTimeout(submenuCloseTimer);
      submenuCloseTimer = setTimeout(closeSubmenu, 200);
    };
    moveToBtn.onmouseenter = scheduleSubmenuOpen;
    moveToBtn.onmouseleave = scheduleSubmenuClose;
    menu.appendChild(moveToBtn);
```

- [ ] **Step 4: Manually verify every scenario from the spec's Testing section**

```bash
uv run python app.py
```

With the widget running:

1. **Standalone tab → existing island:** Drag two tabs together to form an island (so at least
   one island exists), then right-click a third standalone tab. Hover "Move to ▸" — the flyout
   should appear to the right showing the island's name, a separator, and "New island…" (no
   "Remove from island", since this tab isn't in one). Click the island's name. Expected: the tab
   joins the island (renders inside the island wrapper/pill), adopts the island's color if it has
   one, and appears after the island's other members.

2. **Tab in an island → different island:** Form a second island the same way. Right-click a tab
   that's already in island A. Hover "Move to ▸" — expected: "Remove from island" appears at the
   top, island A itself is NOT listed, island B is listed. Click island B. Expected: the tab
   leaves A and joins B; if A now has ≤1 member left, it dissolves (its remaining tab, if any,
   becomes standalone).

3. **New island:** Right-click any tab, hover "Move to ▸", click "New island…". Expected: a new
   island appears (default incrementing name, e.g. "Island 2") containing only that tab, and if
   the tab was previously in another island that one dissolves if left with ≤1 member.

4. **Zero islands:** Start from (or reset to) a state with no islands at all. Right-click a tab,
   hover "Move to ▸". Expected: the flyout shows only "New island…" (no separator floating above
   it with nothing else, no "Remove from island").

5. **Hover/close mechanics:** Right-click a tab, hover "Move to ▸" until the flyout opens, then
   move the mouse from the "Move to" button toward the flyout (crossing the small gap). Expected:
   the flyout stays open. Move the mouse away from both the button and the flyout entirely.
   Expected: after a beat, the flyout closes but the main right-click menu stays open. Click
   anywhere else in the window. Expected: both the main menu and (if still open) the flyout close.

- [ ] **Step 5: Commit**

```bash
git add todo.html
git commit -m "feat: add \"Move to\" island flyout to tab right-click menu"
```
