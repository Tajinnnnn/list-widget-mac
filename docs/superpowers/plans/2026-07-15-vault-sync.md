# List Widget ↔ Obsidian Vault Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two-way sync between the List widget's tasks and today's Obsidian daily note, scoped to a `## Tasks` section, per `docs/superpowers/specs/2026-07-15-vault-sync-design.md`.

**Architecture:** A new pure-function module `vault_sync.py` renders widget state to markdown and parses it back, plus an item-level last-write-wins `merge()`. `app.py` wires this in at three points: every local save (push), a ~20s background poll (pull), and once at launch (reconcile). `todo.html` gains an `updatedAt`/`tombstones` schema so merges can tell what changed since the last sync.

**Tech Stack:** Python 3.12, pytest, pywebview/PyObjC (existing), vanilla JS (existing).

## Global Constraints

- Vault root is a hardcoded constant: `VAULT_ROOT = Path("/Users/tajin/Documents/Coding/Obsidian/Tajin Brain")` in `vault_sync.py` — single-user, single-machine app, matches the existing hardcoded-path style of `LOCK_PATH`/`BACKUP_PATH` in `app.py`.
- Only *today's* daily note is ever touched (`01 Journals/daily/YYYY-MM-DD.md`, "today" = local date). Older notes are never read or written by sync.
- All sync code must swallow exceptions and no-op on failure (matches `write_backup`/`read_backup`'s existing `try/except Exception: pass` style) — a sync hiccup must never crash the widget or block the UI.
- Two corrections vs. the design doc, found while making it concrete (flagged to Tajin already, noted here for the record):
  - List headings (`### <name>`) also carry a `<!--id:...-->` comment, same as items — the spec's merge strategy says lists merge "the same way, by list id," but its markdown example omitted the id comment on `###` lines. Fixed here.
  - Due dates render with time-of-day (`📅 YYYY-MM-DD HH:MM`, local time), not just the date — the widget stores due times to the minute, and date-only rendering would silently truncate them on every note round-trip.

---

## Task 1: Test scaffolding

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/__init__.py` (empty)

**Interfaces:**
- Produces: a working `uv run pytest` command for all later tasks.

- [ ] **Step 1: Add pytest as a dev dependency**

Run: `cd "/Users/tajin/Documents/Coding/Obsidian/Tajin Brain/03 Projects/build4fun/Projects/list-widget-mac" && uv add --dev pytest`

Expected: `pyproject.toml`'s `[dependency-groups] dev` list now includes `pytest>=...`, and `uv.lock` is updated.

- [ ] **Step 2: Configure pytest's import path**

Add this to `pyproject.toml` (a new top-level table, order doesn't matter relative to `[project]`/`[dependency-groups]`):

```toml
[tool.pytest.ini_options]
pythonpath = ["."]
```

This lets `tests/test_vault_sync.py` do `import vault_sync` without installing the project as a package.

- [ ] **Step 3: Create the tests package**

Create `tests/__init__.py` with empty content (0 bytes).

- [ ] **Step 4: Verify pytest runs with zero tests**

Run: `uv run pytest -v`
Expected: `no tests ran` (or similar), exit code 0 or 5 — no import errors, no collection errors.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock tests/__init__.py
git commit -m "test: add pytest scaffolding"
```

---

## Task 2: `vault_sync.py` — paths, note creation, section read/write helpers

**Files:**
- Create: `vault_sync.py`
- Test: `tests/test_vault_sync.py`

**Interfaces:**
- Produces: `today_note_path(vault_root: Path) -> Path`, `ensure_note_exists(vault_root: Path, path: Path) -> None`, `_section_bounds(text: str, heading: str) -> tuple[int, int] | None`, `_extract_section(text: str, heading: str) -> str | None`, `_upsert_section(text: str, heading: str, body: str) -> str`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_vault_sync.py`:

```python
from datetime import date
from pathlib import Path

import vault_sync


def test_today_note_path(tmp_path):
    expected = tmp_path / "01 Journals" / "daily" / f"{date.today().isoformat()}.md"
    assert vault_sync.today_note_path(tmp_path) == expected


def test_ensure_note_exists_creates_from_template(tmp_path):
    template_dir = tmp_path / "01 Journals"
    template_dir.mkdir(parents=True)
    (template_dir / "_daily-template.md").write_text("# {{date}}\n\n## Notes\n")

    path = vault_sync.today_note_path(tmp_path)
    vault_sync.ensure_note_exists(tmp_path, path)

    assert path.exists()
    content = path.read_text()
    assert content.startswith(f"# {date.today().isoformat()}")
    assert "## Notes" in content


def test_ensure_note_exists_noop_if_already_present(tmp_path):
    path = vault_sync.today_note_path(tmp_path)
    path.parent.mkdir(parents=True)
    path.write_text("# existing content\n")

    vault_sync.ensure_note_exists(tmp_path, path)

    assert path.read_text() == "# existing content\n"


def test_extract_section_missing_heading_returns_none():
    assert vault_sync._extract_section("# Title\n\n## Other\nstuff\n", "## Tasks") is None


def test_extract_section_returns_body_up_to_next_heading():
    text = "# Title\n\n## Tasks\nline one\nline two\n\n## Other\nstuff\n"
    assert vault_sync._extract_section(text, "## Tasks") == "line one\nline two"


def test_extract_section_to_eof_when_last_section():
    text = "# Title\n\n## Tasks\nline one\nline two\n"
    assert vault_sync._extract_section(text, "## Tasks") == "line one\nline two"


def test_upsert_section_appends_when_missing():
    text = "# Title\n\n## Notes\nfreeform\n"
    result = vault_sync._upsert_section(text, "## Tasks", "- [ ] a task")
    assert result == "# Title\n\n## Notes\nfreeform\n\n## Tasks\n- [ ] a task\n"


def test_upsert_section_replaces_existing_body_only():
    text = "# Title\n\n## Tasks\nold line\n\n## Reflection\nkeep me\n"
    result = vault_sync._upsert_section(text, "## Tasks", "new line")
    assert result == "# Title\n\n## Tasks\nnew line\n\n## Reflection\nkeep me\n"


def test_upsert_section_preserves_content_before_heading():
    text = "# Title\n\n## Intent\nuntouched\n\n## Tasks\nold\n"
    result = vault_sync._upsert_section(text, "## Tasks", "new")
    assert "## Intent\nuntouched" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_vault_sync.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'vault_sync'` (file doesn't exist yet).

- [ ] **Step 3: Write `vault_sync.py`**

Create `vault_sync.py`:

```python
from datetime import date
from pathlib import Path

VAULT_ROOT = Path("/Users/tajin/Documents/Coding/Obsidian/Tajin Brain")


def today_note_path(vault_root: Path) -> Path:
    return vault_root / "01 Journals" / "daily" / f"{date.today().isoformat()}.md"


def ensure_note_exists(vault_root: Path, path: Path) -> None:
    if path.exists():
        return
    template_path = vault_root / "01 Journals" / "_daily-template.md"
    template = template_path.read_text() if template_path.exists() else "# {{date}}\n"
    content = template.replace("{{date}}", date.today().isoformat())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _section_bounds(text: str, heading: str) -> tuple[int, int] | None:
    lines = text.split("\n")
    start_line = None
    for i, line in enumerate(lines):
        if line.strip() == heading:
            start_line = i
            break
    if start_line is None:
        return None
    end_line = len(lines)
    for i in range(start_line + 1, len(lines)):
        if lines[i].startswith("## "):
            end_line = i
            break
    return start_line, end_line


def _extract_section(text: str, heading: str) -> str | None:
    bounds = _section_bounds(text, heading)
    if bounds is None:
        return None
    start, end = bounds
    lines = text.split("\n")
    return "\n".join(lines[start + 1 : end]).strip("\n")


def _upsert_section(text: str, heading: str, body: str) -> str:
    bounds = _section_bounds(text, heading)
    lines = text.split("\n")
    if bounds is None:
        suffix = "\n\n" if text.strip() else ""
        return text.rstrip("\n") + suffix + heading + "\n" + body.rstrip("\n") + "\n"
    start, end = bounds
    new_lines = lines[: start + 1] + [body.rstrip("\n"), ""] + lines[end:]
    return "\n".join(new_lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_vault_sync.py -v`
Expected: all 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add vault_sync.py tests/test_vault_sync.py
git commit -m "feat: add vault note path/section helpers for sync"
```

---

## Task 3: `vault_sync.py` — render state to markdown

**Files:**
- Modify: `vault_sync.py`
- Test: `tests/test_vault_sync.py`

**Interfaces:**
- Consumes: nothing new from Task 2.
- Produces: `render_tasks_section(state: dict) -> str`, `_due_to_display(due_iso: str) -> str`, `_display_to_due(display: str) -> str`, `_format_item_line(item: dict, source_list_name: str | None = None) -> str`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_vault_sync.py`:

```python
from datetime import datetime, timezone


def _item(**overrides):
    base = {
        "_id": "abc123",
        "text": "Get haircut",
        "done": False,
        "due": None,
        "notified": False,
        "pinned": False,
        "repeat": None,
        "completedAt": None,
    }
    base.update(overrides)
    return base


def test_due_display_roundtrip():
    original = "2026-08-01T04:59:00.000Z"
    display = vault_sync._due_to_display(original)
    assert vault_sync._display_to_due(display) == original


def test_format_item_line_plain():
    line = vault_sync._format_item_line(_item())
    assert line == "- [ ] Get haircut <!--id:abc123-->"


def test_format_item_line_done():
    line = vault_sync._format_item_line(_item(done=True))
    assert line.startswith("- [x] Get haircut")


def test_format_item_line_pinned_and_repeat():
    line = vault_sync._format_item_line(_item(text="Gym", pinned=True, repeat="daily"))
    assert line == "- [ ] Gym 📌 🔁 daily <!--id:abc123-->"


def test_format_item_line_with_due_contains_marker():
    line = vault_sync._format_item_line(_item(due="2026-08-01T04:59:00.000Z"))
    assert "📅 " in line
    assert line.endswith("<!--id:abc123-->")


def test_format_item_line_with_source_list():
    line = vault_sync._format_item_line(_item(), source_list_name="Tasks")
    assert line == "- [ ] Get haircut (Tasks) <!--id:abc123-->"


def test_render_tasks_section_groups_by_list():
    state = {
        "lists": [
            {"id": "list1", "name": "Tasks", "items": [_item()]},
            {"id": "list2", "name": "Build4fun", "items": [_item(_id="def456", text="Ship it")]},
        ]
    }
    section = vault_sync.render_tasks_section(state)
    assert "### Tasks <!--id:list1-->" in section
    assert "### Build4fun <!--id:list2-->" in section
    assert "- [ ] Get haircut <!--id:abc123-->" in section
    assert "- [ ] Ship it <!--id:def456-->" in section
    assert "### Completed today" in section


def test_render_tasks_section_completed_today_rollup():
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    state = {
        "lists": [
            {
                "id": "list1",
                "name": "Tasks",
                "items": [_item(text="Done today", done=True, completedAt=now_iso)],
            }
        ]
    }
    section = vault_sync.render_tasks_section(state)
    completed_block = section.split("### Completed today")[1]
    assert "Done today (Tasks)" in completed_block


def test_render_tasks_section_no_completions_today_shows_placeholder():
    state = {"lists": [{"id": "list1", "name": "Tasks", "items": [_item()]}]}
    section = vault_sync.render_tasks_section(state)
    completed_block = section.split("### Completed today")[1]
    assert "Nothing yet" in completed_block
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_vault_sync.py -v -k "render or format or due_display"`
Expected: FAIL — `AttributeError: module 'vault_sync' has no attribute 'render_tasks_section'` (and similar for the others).

- [ ] **Step 3: Implement rendering in `vault_sync.py`**

Add to `vault_sync.py` (imports first, then the new functions — insert near the top and after `_upsert_section` respectively):

Add to the imports at the top:

```python
from datetime import date, datetime, timezone
```

(replace the existing `from datetime import date` line with this one)

Append these functions to the end of `vault_sync.py`:

```python
def _due_to_display(due_iso: str) -> str:
    dt = datetime.fromisoformat(due_iso.replace("Z", "+00:00")).astimezone()
    return dt.strftime("%Y-%m-%d %H:%M")


def _display_to_due(display: str) -> str:
    naive_local = datetime.strptime(display, "%Y-%m-%d %H:%M")
    aware_local = naive_local.astimezone()
    return aware_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _format_item_line(item: dict, source_list_name: str | None = None) -> str:
    box = "x" if item.get("done") else " "
    parts = [item.get("text", "")]
    if item.get("pinned"):
        parts.append("📌")
    due = item.get("due")
    if due:
        parts.append(f"📅 {_due_to_display(due)}")
    repeat = item.get("repeat")
    if repeat:
        parts.append(f"🔁 {repeat}")
    if source_list_name:
        parts.append(f"({source_list_name})")
    body = " ".join(parts)
    return f"- [{box}] {body} <!--id:{item.get('_id', '')}-->"


def _to_local_date_str(iso_str: str) -> str:
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00")).astimezone()
    return dt.date().isoformat()


def render_tasks_section(state: dict) -> str:
    today_str = date.today().isoformat()
    lines: list[str] = []
    completed_today: list[tuple[dict, str]] = []

    for lst in state.get("lists", []):
        lines.append(f"### {lst.get('name', '')} <!--id:{lst.get('id', '')}-->")
        for item in lst.get("items", []):
            lines.append(_format_item_line(item))
            completed_at = item.get("completedAt")
            if item.get("done") and completed_at and _to_local_date_str(completed_at) == today_str:
                completed_today.append((item, lst.get("name", "")))
        lines.append("")

    lines.append("### Completed today")
    if completed_today:
        for item, list_name in completed_today:
            lines.append(_format_item_line(item, source_list_name=list_name))
    else:
        lines.append("*Nothing yet.*")

    return "\n".join(lines).rstrip("\n") + "\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_vault_sync.py -v`
Expected: all tests PASS (17 total so far).

- [ ] **Step 5: Commit**

```bash
git add vault_sync.py tests/test_vault_sync.py
git commit -m "feat: render widget state to Tasks section markdown"
```

---

## Task 4: `vault_sync.py` — parse markdown back to state

**Files:**
- Modify: `vault_sync.py`
- Test: `tests/test_vault_sync.py`

**Interfaces:**
- Consumes: `_extract_section` (Task 2), `_display_to_due` (Task 3).
- Produces: `parse_tasks_section(note_text: str) -> dict` returning `{"lists": [{"id": str | None, "name": str, "items": [{"id": str, "text": str, "done": bool, "due": str | None, "pinned": bool, "repeat": str | None}]}]}`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_vault_sync.py`:

```python
def test_parse_tasks_section_missing_heading_returns_empty():
    assert vault_sync.parse_tasks_section("# Title\n\n## Other\n") == {"lists": []}


def test_parse_tasks_section_basic_roundtrip():
    note = (
        "# Title\n\n"
        "## Tasks\n"
        "### Tasks <!--id:list1-->\n"
        "- [ ] Get haircut <!--id:abc123-->\n"
        "- [x] Gym 📌 🔁 daily <!--id:def456-->\n"
        "\n"
        "### Completed today\n"
        "- [x] Gym (Tasks) 📌 🔁 daily <!--id:def456-->\n"
    )
    parsed = vault_sync.parse_tasks_section(note)
    assert len(parsed["lists"]) == 1
    lst = parsed["lists"][0]
    assert lst["id"] == "list1"
    assert lst["name"] == "Tasks"
    assert len(lst["items"]) == 2
    haircut, gym = lst["items"]
    assert haircut == {
        "id": "abc123", "text": "Get haircut", "done": False,
        "due": None, "pinned": False, "repeat": None,
    }
    assert gym == {
        "id": "def456", "text": "Gym", "done": True,
        "due": None, "pinned": True, "repeat": "daily",
    }


def test_parse_tasks_section_ignores_completed_today_as_a_list():
    note = (
        "## Tasks\n"
        "### Tasks <!--id:list1-->\n"
        "- [ ] a <!--id:x1-->\n"
        "\n"
        "### Completed today\n"
        "- [x] something (Tasks) <!--id:x2-->\n"
    )
    parsed = vault_sync.parse_tasks_section(note)
    names = [l["name"] for l in parsed["lists"]]
    assert names == ["Tasks"]


def test_parse_tasks_section_due_roundtrips_through_render():
    due_iso = "2026-08-01T04:59:00.000Z"
    state = {"lists": [{"id": "list1", "name": "Tasks", "items": [
        {"_id": "abc123", "text": "Renew card", "done": False, "due": due_iso,
         "notified": False, "pinned": False, "repeat": None, "completedAt": None},
    ]}]}
    note = "## Tasks\n" + vault_sync.render_tasks_section(state)
    parsed = vault_sync.parse_tasks_section(note)
    assert parsed["lists"][0]["items"][0]["due"] == due_iso


def test_parse_tasks_section_list_with_no_id_comment():
    note = "## Tasks\n### Hand-typed list\n- [ ] a task <!--id:x1-->\n"
    parsed = vault_sync.parse_tasks_section(note)
    assert parsed["lists"][0]["id"] is None
    assert parsed["lists"][0]["name"] == "Hand-typed list"


def test_parse_tasks_section_item_with_no_id_comment_is_skipped():
    # A line typed by hand with no id comment doesn't match _ITEM_LINE_RE
    # (which requires the id comment) — it's surfaced separately by the
    # merge step (Task 6) as a brand-new item, not here.
    note = "## Tasks\n### Tasks <!--id:list1-->\n- [ ] hand typed, no id yet\n"
    parsed = vault_sync.parse_tasks_section(note)
    assert parsed["lists"][0]["items"] == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_vault_sync.py -v -k parse_tasks_section`
Expected: FAIL — `AttributeError: module 'vault_sync' has no attribute 'parse_tasks_section'`.

- [ ] **Step 3: Implement parsing in `vault_sync.py`**

Add to the imports at the top of `vault_sync.py`:

```python
import re
```

Append to the end of `vault_sync.py`:

```python
_ITEM_LINE_RE = re.compile(r"^- \[([ xX])\]\s+(?P<rest>.+?)\s*<!--id:(?P<id>[A-Za-z0-9]+)-->\s*$")
_LIST_HEADING_RE = re.compile(r"^### (?P<name>.+?)(?:\s*<!--id:(?P<id>[A-Za-z0-9]+)-->)?\s*$")
_PINNED_RE = re.compile(r"\s*📌\s*")
_DUE_RE = re.compile(r"\s*📅\s*(\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2})\s*")
_REPEAT_RE = re.compile(r"\s*🔁\s*(daily|weekly|monthly)\s*")


def _parse_item_line(line: str) -> dict | None:
    match = _ITEM_LINE_RE.match(line.strip())
    if not match:
        return None
    rest = match.group("rest")

    pinned = bool(_PINNED_RE.search(rest))
    rest = _PINNED_RE.sub(" ", rest)

    due = None
    due_match = _DUE_RE.search(rest)
    if due_match:
        due = _display_to_due(due_match.group(1))
        rest = _DUE_RE.sub(" ", rest)

    repeat = None
    repeat_match = _REPEAT_RE.search(rest)
    if repeat_match:
        repeat = repeat_match.group(1)
        rest = _REPEAT_RE.sub(" ", rest)

    text = " ".join(rest.split()).strip()

    return {
        "id": match.group("id"),
        "text": text,
        "done": match.group(1).lower() == "x",
        "due": due,
        "pinned": pinned,
        "repeat": repeat,
    }


def parse_tasks_section(note_text: str) -> dict:
    section = _extract_section(note_text, "## Tasks")
    if section is None:
        return {"lists": []}

    lists: list[dict] = []
    current: dict | None = None

    for line in section.split("\n"):
        heading_match = _LIST_HEADING_RE.match(line.strip())
        if heading_match:
            name = heading_match.group("name").strip()
            if name == "Completed today":
                current = None
                continue
            current = {"id": heading_match.group("id"), "name": name, "items": []}
            lists.append(current)
            continue
        if current is None:
            continue
        item = _parse_item_line(line)
        if item is not None:
            current["items"].append(item)

    return {"lists": lists}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_vault_sync.py -v`
Expected: all tests PASS (23 total so far).

- [ ] **Step 5: Commit**

```bash
git add vault_sync.py tests/test_vault_sync.py
git commit -m "feat: parse Tasks section markdown back into state"
```

---

## Task 5: `vault_sync.py` — write the section to disk

**Files:**
- Modify: `vault_sync.py`
- Test: `tests/test_vault_sync.py`

**Interfaces:**
- Consumes: `today_note_path`, `ensure_note_exists`, `_upsert_section`, `render_tasks_section` (Tasks 2–3).
- Produces: `write_tasks_section(vault_root: Path, state: dict) -> None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_vault_sync.py`:

```python
def test_write_tasks_section_creates_note_and_writes_body(tmp_path):
    state = {"lists": [{"id": "list1", "name": "Tasks", "items": [_item()]}]}
    vault_sync.write_tasks_section(tmp_path, state)

    path = vault_sync.today_note_path(tmp_path)
    assert path.exists()
    content = path.read_text()
    assert "## Tasks" in content
    assert "- [ ] Get haircut <!--id:abc123-->" in content


def test_write_tasks_section_is_idempotent_noop(tmp_path):
    state = {"lists": [{"id": "list1", "name": "Tasks", "items": [_item()]}]}
    vault_sync.write_tasks_section(tmp_path, state)
    path = vault_sync.today_note_path(tmp_path)
    first_mtime = path.stat().st_mtime_ns

    vault_sync.write_tasks_section(tmp_path, state)
    assert path.stat().st_mtime_ns == first_mtime


def test_write_tasks_section_preserves_rest_of_note(tmp_path):
    journals = tmp_path / "01 Journals"
    journals.mkdir()
    (journals / "_daily-template.md").write_text(
        "# {{date}}\n\n## Intent\nmy own words\n"
    )
    state = {"lists": [{"id": "list1", "name": "Tasks", "items": [_item()]}]}
    vault_sync.write_tasks_section(tmp_path, state)

    content = vault_sync.today_note_path(tmp_path).read_text()
    assert "## Intent\nmy own words" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_vault_sync.py -v -k write_tasks_section`
Expected: FAIL — `AttributeError: module 'vault_sync' has no attribute 'write_tasks_section'`.

- [ ] **Step 3: Implement `write_tasks_section`**

Add to the imports at the top of `vault_sync.py`:

```python
import os
```

Append to the end of `vault_sync.py`:

```python
def write_tasks_section(vault_root: Path, state: dict) -> None:
    path = today_note_path(vault_root)
    ensure_note_exists(vault_root, path)
    text = path.read_text()
    new_text = _upsert_section(text, "## Tasks", render_tasks_section(state))
    if new_text == text:
        return
    tmp_path = path.with_suffix(".md.tmp")
    tmp_path.write_text(new_text)
    os.replace(tmp_path, path)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_vault_sync.py -v`
Expected: all tests PASS (26 total so far).

- [ ] **Step 5: Commit**

```bash
git add vault_sync.py tests/test_vault_sync.py
git commit -m "feat: write Tasks section to today's note atomically"
```

---

## Task 6: `vault_sync.py` — merge and tombstones

**Files:**
- Modify: `vault_sync.py`
- Test: `tests/test_vault_sync.py`

**Interfaces:**
- Consumes: output shape of `parse_tasks_section` (Task 4).
- Produces: `merge(local: dict, remote: dict, note_mtime: str) -> dict`, `purge_old_tombstones(tombstones: list[dict], now: datetime | None = None) -> list[dict]`, `_mtime_to_iso(mtime: float) -> str`, `_gen_id() -> str`.

**Local state shape this consumes/produces** (matches `backup.json`, as written by `todo.html`):
```python
{
  "lists": [{"id": str, "name": str, "color": str | None, "items": [
      {"_id": str, "text": str, "done": bool, "due": str | None, "notified": bool,
       "pinned": bool, "repeat": str | None, "completedAt": str | None, "updatedAt": str}
  ]}],
  "active": str,
  "settings": {...},
  "tombstones": [{"_id": str, "updatedAt": str}],
}
```

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_vault_sync.py`:

```python
import copy


def _local_state(**list_overrides):
    lst = {
        "id": "list1", "name": "Tasks", "color": None,
        "items": [
            {"_id": "a1", "text": "Existing task", "done": False, "due": None,
             "notified": False, "pinned": False, "repeat": None, "completedAt": None,
             "updatedAt": "2026-07-14T10:00:00.000Z"},
        ],
    }
    lst.update(list_overrides)
    return {"lists": [lst], "active": "list1", "settings": {}, "tombstones": []}


def _remote_list(items):
    return {"lists": [{"id": "list1", "name": "Tasks", "items": items}]}


def test_merge_no_changes_returns_equivalent_state():
    local = _local_state()
    remote = {"lists": [{"id": "list1", "name": "Tasks", "items": [
        {"id": "a1", "text": "Existing task", "done": False, "due": None,
         "pinned": False, "repeat": None},
    ]}]}
    merged = vault_sync.merge(local, remote, "2026-07-14T09:00:00.000Z")
    assert merged["lists"][0]["items"][0]["text"] == "Existing task"
    assert merged["lists"][0]["items"][0]["updatedAt"] == "2026-07-14T10:00:00.000Z"


def test_merge_remote_edit_newer_than_local_wins():
    local = _local_state()
    remote = _remote_list([
        {"id": "a1", "text": "Edited in Obsidian", "done": False, "due": None,
         "pinned": False, "repeat": None},
    ])
    merged = vault_sync.merge(local, remote, "2026-07-15T09:00:00.000Z")
    item = merged["lists"][0]["items"][0]
    assert item["text"] == "Edited in Obsidian"
    assert item["updatedAt"] == "2026-07-15T09:00:00.000Z"


def test_merge_local_edit_newer_than_remote_wins():
    local = _local_state()
    local["lists"][0]["items"][0]["updatedAt"] = "2026-07-16T09:00:00.000Z"
    remote = _remote_list([
        {"id": "a1", "text": "Stale note edit", "done": False, "due": None,
         "pinned": False, "repeat": None},
    ])
    merged = vault_sync.merge(local, remote, "2026-07-15T09:00:00.000Z")
    item = merged["lists"][0]["items"][0]
    assert item["text"] == "Existing task"


def test_merge_new_item_added_in_note():
    local = _local_state()
    remote = _remote_list([
        {"id": "a1", "text": "Existing task", "done": False, "due": None,
         "pinned": False, "repeat": None},
        {"id": "b2", "text": "Added in Obsidian", "done": False, "due": None,
         "pinned": False, "repeat": None},
    ])
    merged = vault_sync.merge(local, remote, "2026-07-15T09:00:00.000Z")
    ids = {it["_id"] for it in merged["lists"][0]["items"]}
    assert ids == {"a1", "b2"}
    new_item = next(it for it in merged["lists"][0]["items"] if it["_id"] == "b2")
    assert new_item["updatedAt"] == "2026-07-15T09:00:00.000Z"


def test_merge_item_added_in_note_without_id_gets_minted_id():
    local = _local_state()
    remote = _remote_list([
        {"id": "a1", "text": "Existing task", "done": False, "due": None,
         "pinned": False, "repeat": None},
        {"id": None, "text": "Hand typed", "done": False, "due": None,
         "pinned": False, "repeat": None},
    ])
    merged = vault_sync.merge(local, remote, "2026-07-15T09:00:00.000Z")
    assert len(merged["lists"][0]["items"]) == 2
    hand_typed = next(it for it in merged["lists"][0]["items"] if it["text"] == "Hand typed")
    assert hand_typed["_id"]


def test_merge_item_deleted_in_note_becomes_tombstone():
    local = _local_state()
    remote = _remote_list([])
    merged = vault_sync.merge(local, remote, "2026-07-15T09:00:00.000Z")
    assert merged["lists"][0]["items"] == []
    assert merged["tombstones"] == [{"_id": "a1", "updatedAt": "2026-07-15T09:00:00.000Z"}]


def test_merge_deletion_older_than_local_edit_does_not_stick():
    local = _local_state()
    local["lists"][0]["items"][0]["updatedAt"] = "2026-07-16T09:00:00.000Z"
    remote = _remote_list([])
    merged = vault_sync.merge(local, remote, "2026-07-15T09:00:00.000Z")
    assert len(merged["lists"][0]["items"]) == 1
    assert merged["tombstones"] == []


def test_merge_resurrects_item_edited_after_tombstone():
    local = _local_state()
    local["lists"][0]["items"] = []
    local["tombstones"] = [{"_id": "a1", "updatedAt": "2026-07-14T09:00:00.000Z"}]
    remote = _remote_list([
        {"id": "a1", "text": "Back again", "done": False, "due": None,
         "pinned": False, "repeat": None},
    ])
    merged = vault_sync.merge(local, remote, "2026-07-15T09:00:00.000Z")
    assert len(merged["lists"][0]["items"]) == 1
    assert merged["lists"][0]["items"][0]["text"] == "Back again"
    assert merged["tombstones"] == []


def test_merge_tombstone_newer_than_note_edit_stays_deleted():
    local = _local_state()
    local["lists"][0]["items"] = []
    local["tombstones"] = [{"_id": "a1", "updatedAt": "2026-07-16T09:00:00.000Z"}]
    remote = _remote_list([
        {"id": "a1", "text": "Stale leftover line", "done": False, "due": None,
         "pinned": False, "repeat": None},
    ])
    merged = vault_sync.merge(local, remote, "2026-07-15T09:00:00.000Z")
    assert merged["lists"][0]["items"] == []
    assert merged["tombstones"] == [{"_id": "a1", "updatedAt": "2026-07-16T09:00:00.000Z"}]


def test_merge_new_list_from_note_gets_added():
    local = _local_state()
    remote = {"lists": [
        {"id": "list1", "name": "Tasks", "items": [
            {"id": "a1", "text": "Existing task", "done": False, "due": None,
             "pinned": False, "repeat": None},
        ]},
        {"id": None, "name": "New From Note", "items": [
            {"id": None, "text": "Fresh", "done": False, "due": None,
             "pinned": False, "repeat": None},
        ]},
    ]}
    merged = vault_sync.merge(local, remote, "2026-07-15T09:00:00.000Z")
    names = {l["name"] for l in merged["lists"]}
    assert names == {"Tasks", "New From Note"}


def test_purge_old_tombstones_drops_entries_older_than_3_days():
    from datetime import datetime, timedelta, timezone
    now = datetime(2026, 7, 15, tzinfo=timezone.utc)
    tombstones = [
        {"_id": "old", "updatedAt": (now - timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%S.000Z")},
        {"_id": "recent", "updatedAt": (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z")},
    ]
    kept = vault_sync.purge_old_tombstones(tombstones, now=now)
    assert [t["_id"] for t in kept] == ["recent"]


def test_mtime_to_iso_format_matches_js_toisostring():
    iso = vault_sync._mtime_to_iso(1752566400.123)
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$", iso)
```

Add `import re` near the top of `tests/test_vault_sync.py` if not already present from a prior task (it isn't — this is the first test file use of `re`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_vault_sync.py -v -k "merge or purge_old_tombstones or mtime_to_iso"`
Expected: FAIL — `AttributeError: module 'vault_sync' has no attribute 'merge'`.

- [ ] **Step 3: Implement merge in `vault_sync.py`**

Add to the imports at the top of `vault_sync.py`:

```python
import copy
import random
import string
import time
from datetime import timedelta
```

(merge this with the existing `from datetime import date, datetime, timezone` line into one `from datetime import date, datetime, timedelta, timezone`)

Append to the end of `vault_sync.py`:

```python
def _gen_id() -> str:
    ts = format(int(time.time() * 1000), "x")
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{ts}{suffix}"


def _mtime_to_iso(mtime: float) -> str:
    dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _render_key(d: dict) -> tuple:
    return (d.get("text", ""), bool(d.get("done")), d.get("due"), bool(d.get("pinned")), d.get("repeat"))


def _remote_to_item(r_item: dict, item_id: str, updated_at: str) -> dict:
    return {
        "_id": item_id,
        "text": r_item.get("text", ""),
        "done": bool(r_item.get("done")),
        "due": r_item.get("due"),
        "notified": False,
        "pinned": bool(r_item.get("pinned")),
        "repeat": r_item.get("repeat"),
        "completedAt": updated_at if r_item.get("done") else None,
        "updatedAt": updated_at,
    }


def _apply_remote_to_item(local_item: dict, r_item: dict, updated_at: str) -> None:
    was_done = local_item.get("done")
    local_item["text"] = r_item.get("text", "")
    local_item["done"] = bool(r_item.get("done"))
    local_item["due"] = r_item.get("due")
    local_item["pinned"] = bool(r_item.get("pinned"))
    local_item["repeat"] = r_item.get("repeat")
    local_item["updatedAt"] = updated_at
    if local_item["done"] and not was_done:
        local_item["completedAt"] = updated_at
    elif not local_item["done"]:
        local_item["completedAt"] = None


def purge_old_tombstones(tombstones: list[dict], now: datetime | None = None) -> list[dict]:
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=3)
    kept = []
    for t in tombstones:
        updated = datetime.fromisoformat(t["updatedAt"].replace("Z", "+00:00"))
        if updated >= cutoff:
            kept.append(t)
    return kept


def merge(local: dict, remote: dict, note_mtime: str) -> dict:
    result = copy.deepcopy(local)
    result.setdefault("tombstones", [])
    tombstones_by_id = {t["_id"]: t for t in result["tombstones"]}

    local_lists_by_id = {}
    local_items_by_id = {}
    for lst in result.get("lists", []):
        local_lists_by_id[lst["id"]] = lst
        for item in lst.get("items", []):
            local_items_by_id[item["_id"]] = (lst, item)

    seen_remote_item_ids = set()

    for r_list in remote.get("lists", []):
        list_id = r_list.get("id") or _gen_id()
        target_list = local_lists_by_id.get(list_id)
        if target_list is None:
            target_list = {"id": list_id, "name": r_list["name"], "color": None, "items": []}
            result["lists"].append(target_list)
            local_lists_by_id[list_id] = target_list
        else:
            target_list["name"] = r_list["name"]

        for r_item in r_list.get("items", []):
            item_id = r_item.get("id") or _gen_id()
            seen_remote_item_ids.add(item_id)
            existing = local_items_by_id.get(item_id)
            tombstone = tombstones_by_id.get(item_id)

            if existing is None and tombstone is None:
                new_item = _remote_to_item(r_item, item_id, note_mtime)
                target_list["items"].append(new_item)
                local_items_by_id[item_id] = (target_list, new_item)
                continue

            if existing is not None:
                _, local_item = existing
                if _render_key(local_item) == _render_key(r_item):
                    continue
                if note_mtime > local_item.get("updatedAt", ""):
                    _apply_remote_to_item(local_item, r_item, note_mtime)
                continue

            if note_mtime > tombstone.get("updatedAt", ""):
                new_item = _remote_to_item(r_item, item_id, note_mtime)
                target_list["items"].append(new_item)
                local_items_by_id[item_id] = (target_list, new_item)
                del tombstones_by_id[item_id]

    for item_id, (lst, item) in list(local_items_by_id.items()):
        if item_id in seen_remote_item_ids:
            continue
        if note_mtime > item.get("updatedAt", ""):
            lst["items"] = [it for it in lst["items"] if it["_id"] != item_id]
            tombstones_by_id[item_id] = {"_id": item_id, "updatedAt": note_mtime}

    result["tombstones"] = purge_old_tombstones(list(tombstones_by_id.values()))
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_vault_sync.py -v`
Expected: all tests PASS (39 total so far).

- [ ] **Step 5: Commit**

```bash
git add vault_sync.py tests/test_vault_sync.py
git commit -m "feat: item-level last-write-wins merge with tombstones"
```

---

## Task 7: `vault_sync.py` — top-level push/pull entry points

**Files:**
- Modify: `vault_sync.py`
- Test: `tests/test_vault_sync.py`

**Interfaces:**
- Consumes: everything from Tasks 2–6.
- Produces: `sync_push(state: dict, vault_root: Path = VAULT_ROOT) -> None`, `sync_pull_and_merge(local_state: dict, vault_root: Path = VAULT_ROOT) -> dict | None`. These are what `app.py` calls; both take an optional `vault_root` override so tests don't touch the real vault.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_vault_sync.py`:

```python
def test_sync_push_writes_note(tmp_path):
    state = {"lists": [{"id": "list1", "name": "Tasks", "items": [_item()]}]}
    vault_sync.sync_push(state, vault_root=tmp_path)
    content = vault_sync.today_note_path(tmp_path).read_text()
    assert "Get haircut" in content


def test_sync_pull_and_merge_returns_none_when_note_missing(tmp_path):
    local = _local_state()
    assert vault_sync.sync_pull_and_merge(local, vault_root=tmp_path) is None


def test_sync_pull_and_merge_returns_none_when_note_matches_local(tmp_path):
    local = _local_state()
    vault_sync.sync_push(local, vault_root=tmp_path)
    assert vault_sync.sync_pull_and_merge(local, vault_root=tmp_path) is None


def test_sync_pull_and_merge_returns_merged_state_on_external_edit(tmp_path):
    local = _local_state()
    vault_sync.sync_push(local, vault_root=tmp_path)

    path = vault_sync.today_note_path(tmp_path)
    text = path.read_text()
    edited = text.replace("Existing task", "Edited by hand")
    path.write_text(edited)

    merged = vault_sync.sync_pull_and_merge(local, vault_root=tmp_path)
    assert merged is not None
    assert merged["lists"][0]["items"][0]["text"] == "Edited by hand"


def test_sync_pull_and_merge_self_heals_note_missing_tasks_heading(tmp_path):
    journals = tmp_path / "01 Journals" / "daily"
    journals.mkdir(parents=True)
    vault_sync.today_note_path(tmp_path).write_text("# No tasks section here\n")

    local = _local_state()
    result = vault_sync.sync_pull_and_merge(local, vault_root=tmp_path)
    assert result is None
    content = vault_sync.today_note_path(tmp_path).read_text()
    assert "## Tasks" in content
    assert "Existing task" in content
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_vault_sync.py -v -k "sync_push or sync_pull_and_merge"`
Expected: FAIL — `AttributeError: module 'vault_sync' has no attribute 'sync_push'`.

- [ ] **Step 3: Implement the entry points**

Append to the end of `vault_sync.py`:

```python
def sync_push(state: dict, vault_root: Path = VAULT_ROOT) -> None:
    try:
        write_tasks_section(vault_root, state)
    except Exception:
        pass


def sync_pull_and_merge(local_state: dict, vault_root: Path = VAULT_ROOT) -> dict | None:
    try:
        path = today_note_path(vault_root)
        if not path.exists():
            return None
        note_text = path.read_text()
        current_section = _extract_section(note_text, "## Tasks")
        rendered = render_tasks_section(local_state)
        if current_section is None:
            write_tasks_section(vault_root, local_state)
            return None
        if current_section.strip() == rendered.strip():
            return None
        remote = parse_tasks_section(note_text)
        note_mtime = _mtime_to_iso(path.stat().st_mtime)
        merged = merge(local_state, remote, note_mtime)
        write_tasks_section(vault_root, merged)
        return merged
    except Exception:
        return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_vault_sync.py -v`
Expected: all tests PASS (44 total so far).

- [ ] **Step 5: Commit**

```bash
git add vault_sync.py tests/test_vault_sync.py
git commit -m "feat: add sync_push/sync_pull_and_merge entry points"
```

---

## Task 8: `todo.html` — `updatedAt`/`tombstones` schema and stamping

**Files:**
- Modify: `todo.html:664-674` (`normalizeItems`), `todo.html:776-816` (`load`), `todo.html:818-829` (`save`), `todo.html:837-855` (`recoverFromBackupIfNewer`)

**Interfaces:**
- Produces: `state.tombstones: Array<{_id, updatedAt}>`, `item.updatedAt: string`, and the invariant that `save()` always stamps `updatedAt` on anything that changed since the last save and tombstones anything deleted — this is what `vault_sync.merge()` (Task 6) depends on when it later reads `backup.json`.

This task has no automated test — it's browser/pywebview-only JS with no test runner in this project (matches the design doc's "Testing" section, which calls out these paths as manual-only). Verification is a manual run of the app at the end of the step.

- [ ] **Step 1: Add `updatedAt` default to `normalizeItems`**

In `todo.html`, find this block (around line 664):

```javascript
  function normalizeItems(items) {
    (items || []).forEach(it => {
      if (it.due === undefined) it.due = null;
      if (it.notified === undefined) it.notified = false;
      if (it.pinned === undefined) it.pinned = false;
      if (it.repeat === undefined) it.repeat = null;
      if (it.completedAt === undefined) it.completedAt = null;
      if (!it._id) it._id = uid();
    });
    return items || [];
  }
```

Replace it with:

```javascript
  function normalizeItems(items) {
    (items || []).forEach(it => {
      if (it.due === undefined) it.due = null;
      if (it.notified === undefined) it.notified = false;
      if (it.pinned === undefined) it.pinned = false;
      if (it.repeat === undefined) it.repeat = null;
      if (it.completedAt === undefined) it.completedAt = null;
      if (it.updatedAt === undefined) it.updatedAt = new Date().toISOString();
      if (!it._id) it._id = uid();
    });
    return items || [];
  }
```

- [ ] **Step 2: Default `state.tombstones` in `load()`**

In `todo.html`, find the end of the `load()` function (around line 803-816):

```javascript
    if (!result.settings) result.settings = {};
    if (!result.settings.retention) result.settings.retention = "endOfDay";
    if (result.settings.vibrancy === undefined) result.settings.vibrancy = false;
    if (!result.settings.calendarView) result.settings.calendarView = "day";
```

Add immediately after those four lines (still inside `load()`, before the migration comment/block that follows):

```javascript
    if (!Array.isArray(result.tombstones)) result.tombstones = [];
```

- [ ] **Step 3: Add the diff-and-stamp helpers**

In `todo.html`, find this line (around line 656):

```javascript
  let state = load();
```

Replace it with:

```javascript
  let state = load();
  let lastItemFields = snapshotItemFields(state);

  function snapshotItemFields(s) {
    const map = new Map();
    (s.lists || []).forEach(l => {
      (l.items || []).forEach(it => {
        map.set(it._id, { text: it.text, done: it.done, due: it.due, pinned: it.pinned, repeat: it.repeat });
      });
    });
    return map;
  }

  function fieldsEqual(a, b) {
    return a.text === b.text && a.done === b.done && a.due === b.due
      && a.pinned === b.pinned && a.repeat === b.repeat;
  }

  function stampUpdatedAtAndTombstones() {
    const now = new Date().toISOString();
    const currentIds = new Set();
    state.lists.forEach(l => {
      l.items.forEach(it => {
        currentIds.add(it._id);
        const prev = lastItemFields.get(it._id);
        const cur = { text: it.text, done: it.done, due: it.due, pinned: it.pinned, repeat: it.repeat };
        if (!prev || !fieldsEqual(prev, cur)) {
          it.updatedAt = now;
        }
      });
    });
    if (!Array.isArray(state.tombstones)) state.tombstones = [];
    const tombstoneIds = new Set(state.tombstones.map(t => t._id));
    lastItemFields.forEach((_, id) => {
      if (!currentIds.has(id) && !tombstoneIds.has(id)) {
        state.tombstones.push({ _id: id, updatedAt: now });
      }
    });
    lastItemFields = snapshotItemFields(state);
  }
```

This runs *before* `function uid()` in the file, which is fine — `uid` isn't called here. (`snapshotItemFields` is declared as a function statement so it's hoisted and usable from the `let lastItemFields = snapshotItemFields(state);` line above it in the same block regardless of source order, but it's placed after for readability.)

- [ ] **Step 4: Call the stamp helper from `save()`**

In `todo.html`, find `function save()` (around line 818):

```javascript
  function save() {
    const json = JSON.stringify(state);
    localStorage.setItem(KEY, json);
    // Belt-and-suspenders backup: written to a plain file with an
    // explicit fsync on the Python side, independent of whatever
    // WebKit's own (opaque, asynchronous) localStorage persistence is
    // doing. Fire-and-forget — don't block saves on it.
    if (window.pywebview && window.pywebview.api && window.pywebview.api.save_backup) {
      window.pywebview.api.save_backup(json).catch(() => {});
    }
  }
```

Replace it with:

```javascript
  function save() {
    stampUpdatedAtAndTombstones();
    const json = JSON.stringify(state);
    localStorage.setItem(KEY, json);
    // Belt-and-suspenders backup: written to a plain file with an
    // explicit fsync on the Python side, independent of whatever
    // WebKit's own (opaque, asynchronous) localStorage persistence is
    // doing. Fire-and-forget — don't block saves on it.
    if (window.pywebview && window.pywebview.api && window.pywebview.api.save_backup) {
      window.pywebview.api.save_backup(json).catch(() => {});
    }
  }
```

- [ ] **Step 5: Reset the snapshot baseline when state is replaced wholesale**

In `todo.html`, find `recoverFromBackupIfNewer()` (around line 837-855):

```javascript
      if (countAllItems(backup) > countAllItems(state)) {
        state = backup;
        state.lists.forEach(l => {
          normalizeItems(l.items);
          if (l.color === undefined) l.color = null;
        });
        save();
        renderTabs();
        renderList();
      }
```

Replace it with:

```javascript
      if (countAllItems(backup) > countAllItems(state)) {
        state = backup;
        state.lists.forEach(l => {
          normalizeItems(l.items);
          if (l.color === undefined) l.color = null;
        });
        if (!Array.isArray(state.tombstones)) state.tombstones = [];
        lastItemFields = snapshotItemFields(state);
        save();
        renderTabs();
        renderList();
      }
```

- [ ] **Step 6: Manual verification**

Run: `cd "/Users/tajin/Documents/Coding/Obsidian/Tajin Brain/03 Projects/build4fun/Projects/list-widget-mac" && .venv/bin/python app.py`

- Add a task, confirm it still appears and behaves normally (checking off, deleting, pinning all still work).
- Quit the app (tray Quit), then inspect `~/Library/Application Support/List/backup.json` — confirm items now carry an `updatedAt` field and `tombstones: []` is present at the top level.

- [ ] **Step 7: Commit**

```bash
git add todo.html
git commit -m "feat: track per-item updatedAt and tombstones for sync merge"
```

---

## Task 9: `todo.html` — apply externally-merged state

**Files:**
- Modify: `todo.html` (new function, placed near `window.__checkDueTasks` around line 1924)

**Interfaces:**
- Consumes: `save()`, `renderTabs()`, `renderList()`, `snapshotItemFields()` (Task 8).
- Produces: `window.__applySyncedState(jsonStateString: string) -> void`, called by `app.py` (Task 11) via `evaluate_js`.

- [ ] **Step 1: Add the function**

In `todo.html`, find this block (around line 1922-1942):

```javascript
  // Called periodically from Python (even while the window is hidden in the
  // tray) to find due tasks and hand back native-notification payloads.
  window.__checkDueTasks = function () {
```

Insert immediately *before* that comment and function:

```javascript
  // Called from Python (vault_sync poll loop / launch reconcile) after it
  // has merged today's note against backup.json. `jsonStateString` is the
  // full merged state, already reconciled — just adopt it, same as
  // recoverFromBackupIfNewer does for the backup-is-newer case.
  window.__applySyncedState = function (jsonStateString) {
    let merged;
    try {
      merged = JSON.parse(jsonStateString);
    } catch {
      return;
    }
    if (!merged || !Array.isArray(merged.lists)) return;

    state = merged;
    state.lists.forEach(l => {
      normalizeItems(l.items);
      if (l.color === undefined) l.color = null;
    });
    if (!Array.isArray(state.tombstones)) state.tombstones = [];
    lastItemFields = snapshotItemFields(state);
    save();
    if (!document.querySelector(".due-edit")) {
      renderTabs();
      renderList();
    }
  };

```

- [ ] **Step 2: Manual verification**

`window.__applySyncedState` has no caller yet — that's wired up in Task 11 — so there's nothing to exercise end-to-end here. This step only confirms Task 9's edit didn't break page load (a JS syntax error in this block would stop the whole script from running, and no tasks would render at all).

Run: `cd "/Users/tajin/Documents/Coding/Obsidian/Tajin Brain/03 Projects/build4fun/Projects/list-widget-mac" && .venv/bin/python app.py`

Confirm the window opens and your existing tasks still show up. Quit the app. Real functional verification of this function happens in Task 11 Steps 4-5.

- [ ] **Step 3: Commit**

```bash
git add todo.html
git commit -m "feat: add window.__applySyncedState for pull-side sync updates"
```

---

## Task 10: `app.py` — push wiring

**Files:**
- Modify: `app.py:1-9` (imports), `app.py:59-76` (`write_backup`)

**Interfaces:**
- Consumes: `vault_sync.sync_push` (Task 7).
- Produces: every call to `write_backup` now also mirrors state into today's note.

- [ ] **Step 1: Import `vault_sync`**

In `app.py`, find the import block (lines 1-16):

```python
import fcntl
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import AppKit
import pystray
import webview
import WebKit
from PIL import Image
from PyObjCTools import AppHelper
```

Replace it with:

```python
import fcntl
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import AppKit
import pystray
import webview
import WebKit
from PIL import Image
from PyObjCTools import AppHelper

import vault_sync
```

- [ ] **Step 2: Hook `sync_push` into `write_backup`**

In `app.py`, find `write_backup` (lines 59-76):

```python
def write_backup(data):
    # A Python-owned fallback, independent of WKWebView's localStorage
    # entirely — written with an explicit flush + fsync so it's actually
    # durable on disk the moment this returns, unlike localStorage's
    # opaque, asynchronous persistence (see quit_app). Write to a temp
    # file and atomically rename over the real one so a mid-write kill
    # can never leave behind a corrupt/partial backup — worst case, the
    # previous good backup just doesn't get updated this time.
    try:
        BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = BACKUP_PATH.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, BACKUP_PATH)
    except Exception:
        pass
```

Replace it with:

```python
def write_backup(data):
    # A Python-owned fallback, independent of WKWebView's localStorage
    # entirely — written with an explicit flush + fsync so it's actually
    # durable on disk the moment this returns, unlike localStorage's
    # opaque, asynchronous persistence (see quit_app). Write to a temp
    # file and atomically rename over the real one so a mid-write kill
    # can never leave behind a corrupt/partial backup — worst case, the
    # previous good backup just doesn't get updated this time.
    try:
        BACKUP_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = BACKUP_PATH.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, BACKUP_PATH)
    except Exception:
        pass
    try:
        vault_sync.sync_push(json.loads(data))
    except Exception:
        pass
```

- [ ] **Step 3: Manual verification**

Run: `cd "/Users/tajin/Documents/Coding/Obsidian/Tajin Brain/03 Projects/build4fun/Projects/list-widget-mac" && .venv/bin/python app.py`

- Add a task titled "push wiring test".
- Check `/Users/tajin/Documents/Coding/Obsidian/Tajin Brain/01 Journals/daily/<today>.md` — confirm it now exists (or was updated) with a `## Tasks` section containing "push wiring test".
- Quit the app.

- [ ] **Step 4: Commit**

```bash
git add app.py
git commit -m "feat: push widget state to today's note on every save"
```

---

## Task 11: `app.py` — pull + launch reconcile wiring

**Files:**
- Modify: `app.py:24-25` (constants), `app.py:431-443` (near `notification_loop`), `app.py:483` (thread startup)

**Interfaces:**
- Consumes: `vault_sync.sync_pull_and_merge` (Task 7), `window.__applySyncedState` (Task 9).
- Produces: `vault_sync_loop()`, `_run_vault_sync_cycle()` — started as a daemon thread, mirroring `notification_loop`'s existing pattern.

- [ ] **Step 1: Add the poll interval constant**

In `app.py`, find:

```python
WINDOW_WIDTH = 360
WINDOW_HEIGHT = 540
SCREEN_MARGIN = 12
CHECK_INTERVAL_SECONDS = 20
```

Replace it with:

```python
WINDOW_WIDTH = 360
WINDOW_HEIGHT = 540
SCREEN_MARGIN = 12
CHECK_INTERVAL_SECONDS = 20
VAULT_SYNC_INTERVAL_SECONDS = 20
```

- [ ] **Step 2: Add the sync loop functions**

In `app.py`, find `notification_loop` (lines 431-442):

```python
def notification_loop():
    window.events.loaded.wait(timeout=15)
    while not stop_event.is_set():
        if stop_event.wait(CHECK_INTERVAL_SECONDS):
            break
        try:
            result = window.evaluate_js("window.__checkDueTasks()")
            due_items = json.loads(result) if result else []
        except Exception:
            due_items = []
        for item in due_items:
            notify(f"Due now — {item.get('list', APP_TITLE)}", item.get("text", ""))
```

Insert immediately after it (still before `if __name__ == "__main__":`):

```python


def _run_vault_sync_cycle():
    local_raw = read_backup()
    if not local_raw:
        return
    try:
        local_state = json.loads(local_raw)
    except Exception:
        return
    merged = vault_sync.sync_pull_and_merge(local_state)
    if merged is None:
        return
    write_backup(json.dumps(merged))
    try:
        window.evaluate_js(f"window.__applySyncedState({json.dumps(json.dumps(merged))})")
    except Exception:
        pass


def vault_sync_loop():
    window.events.loaded.wait(timeout=15)
    _run_vault_sync_cycle()
    while not stop_event.is_set():
        if stop_event.wait(VAULT_SYNC_INTERVAL_SECONDS):
            break
        _run_vault_sync_cycle()
```

- [ ] **Step 3: Start the thread**

In `app.py`, find:

```python
    setup_tray()
    threading.Thread(target=notification_loop, daemon=True).start()
```

Replace it with:

```python
    setup_tray()
    threading.Thread(target=notification_loop, daemon=True).start()
    threading.Thread(target=vault_sync_loop, daemon=True).start()
```

- [ ] **Step 4: Manual verification — pull path**

Run: `cd "/Users/tajin/Documents/Coding/Obsidian/Tajin Brain/03 Projects/build4fun/Projects/list-widget-mac" && .venv/bin/python app.py`

- With the app running (and today's note already containing a `## Tasks` section from Task 10's test), open today's note in a text editor and edit a task's text under `### Tasks`, keeping its `<!--id:...-->` comment intact. Save the file.
- Wait up to ~20 seconds. Open the widget — confirm the task's text updated to match your edit.
- Add a brand new `- [ ] a note-only task` line (no id comment) under the same `###` heading, save. Wait ~20s, open the widget — confirm the new task now appears there too, and check the note — it should now have gained an `<!--id:...-->` comment on that line the next time the widget saves.
- Quit the app.

- [ ] **Step 5: Manual verification — launch reconcile**

- With the app fully quit, edit today's note again (change a task's `[ ]` to `[x]` under `### Tasks`).
- Relaunch: `.venv/bin/python app.py`
- Immediately open the widget (within the first few seconds) — confirm the task already shows checked, without waiting a full poll cycle.
- Quit the app.

- [ ] **Step 6: Commit**

```bash
git add app.py
git commit -m "feat: poll today's note for edits and reconcile on launch"
```

---

## Task 12: End-to-end pass, README update, final commit

**Files:**
- Modify: `README.md`

**Interfaces:** None — this task documents and does a final sanity pass over Tasks 1–11.

- [ ] **Step 1: Run the full test suite**

Run: `cd "/Users/tajin/Documents/Coding/Obsidian/Tajin Brain/03 Projects/build4fun/Projects/list-widget-mac" && uv run pytest -v`
Expected: all tests PASS, no skips, no errors.

- [ ] **Step 2: Document the feature in README**

In `README.md`, find the `## Project layout` section's bullet list (the one starting with `- \`todo.html\` — the entire UI/logic...`) and add a new bullet after the `list.spec` bullet:

```markdown
- `vault_sync.py` — two-way sync between the widget's tasks and today's
  Obsidian daily note (`## Tasks` section only). Widget saves push
  instantly; a background poll (and a check on launch) pulls in edits made
  in the note, merged item-by-item with last-write-wins. See
  `docs/superpowers/specs/2026-07-15-vault-sync-design.md` for the full
  design.
```

- [ ] **Step 3: Full manual regression pass**

Run: `.venv/bin/python app.py`

Walk through, confirming each still works (these are pre-existing features that touched code paths in this plan — Tasks 8/9 modified `save()`, `load()`, `recoverFromBackupIfNewer`):
- Add, edit, pin, delete a task.
- Check a task off and confirm it moves to the Completed view.
- Set a due date/time and repeat on a task.
- Switch tabs/lists.
- Quit and relaunch — confirm all tasks persisted.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document vault sync in README"
```

---

## Deployment note (not part of this plan)

`/Applications/List.app` is a separately-built PyInstaller bundle (see `list.spec`) — these code changes won't reach the *running* installed app until it's rebuilt (`uv run pyinstaller list.spec --noconfirm`) and reinstalled. That's a deploy step, out of scope here; flag it to Tajin once this plan is fully executed and reviewed.
