import copy
import os
import random
import re
import string
import time
from datetime import date, datetime, timedelta, timezone
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


def _due_to_display(due_iso: str, all_day: bool = False) -> str:
    dt = datetime.fromisoformat(due_iso.replace("Z", "+00:00")).astimezone()
    if all_day:
        return dt.strftime("%Y-%m-%d")
    return dt.strftime("%Y-%m-%d %H:%M")


def _display_to_due(display: str) -> str:
    fmt = "%Y-%m-%d %H:%M" if " " in display else "%Y-%m-%d"
    naive_local = datetime.strptime(display, fmt)
    aware_local = naive_local.astimezone()
    return aware_local.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


_WEEKDAY_ABBR = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"]
_OCCURRENCE_LABEL = {1: "1st", 2: "2nd", 3: "3rd", 4: "4th", -1: "last"}
_OCCURRENCE_VALUE = {v: k for k, v in _OCCURRENCE_LABEL.items()}


def _repeat_suffix(item: dict) -> str:
    repeat = item.get("repeat")
    if repeat == "weekly" and item.get("repeatDays"):
        indices = [int(x) for x in item["repeatDays"].split(",")]
        return ":" + ",".join(_WEEKDAY_ABBR[i] for i in indices)
    if repeat == "monthly" and item.get("repeatWeekday") is not None and item.get("repeatOccurrence") is not None:
        occurrence = _OCCURRENCE_LABEL[item["repeatOccurrence"]]
        weekday = _WEEKDAY_ABBR[item["repeatWeekday"]]
        return f":{occurrence}-{weekday}"
    return ""


def _format_item_line(item: dict, source_list_name: str | None = None) -> str:
    box = "x" if item.get("done") else " "
    parts = [item.get("text", "")]
    if item.get("pinned"):
        parts.append("📌")
    due = item.get("due")
    if due:
        parts.append(f"📅 {_due_to_display(due, item.get('dueAllDay'))}")
    repeat = item.get("repeat")
    if repeat:
        parts.append(f"🔁 {repeat}{_repeat_suffix(item)}")
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
        if lst.get("syncToVault") is False:
            continue
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


_ITEM_LINE_RE = re.compile(r"^- \[([ xX])\]\s+(?P<rest>.+?)\s*<!--id:(?P<id>[A-Za-z0-9]+)-->\s*$")
_LIST_HEADING_RE = re.compile(r"^### (?P<name>.+?)(?:\s*<!--id:(?P<id>[A-Za-z0-9]+)-->)?\s*$")
_PINNED_RE = re.compile(r"\s*📌\s*")
_DUE_RE = re.compile(r"\s*📅\s*(\d{4}-\d{2}-\d{2})(?:\s+(\d{2}:\d{2}))?\s*")
_REPEAT_RE = re.compile(r"\s*🔁\s*(daily|weekly|monthly)(?::([A-Za-z0-9,\-]+))?\s*")


def _parse_repeat_suffix(repeat: str, suffix: str | None) -> tuple[str | None, int | None, int | None]:
    """Returns (repeatDays, repeatWeekday, repeatOccurrence) decoded from a
    `weekly:Mon,Wed,Fri` / `monthly:2nd-Tue` suffix. Falls back to all-None
    (legacy/bare tag, or an unrecognized suffix) rather than raising."""
    if not suffix:
        return None, None, None
    if repeat == "weekly":
        abbrs = suffix.split(",")
        if all(a in _WEEKDAY_ABBR for a in abbrs):
            indices = sorted(_WEEKDAY_ABBR.index(a) for a in abbrs)
            return ",".join(str(i) for i in indices), None, None
        return None, None, None
    if repeat == "monthly":
        occurrence_str, _, weekday_str = suffix.partition("-")
        if occurrence_str in _OCCURRENCE_VALUE and weekday_str in _WEEKDAY_ABBR:
            return None, _WEEKDAY_ABBR.index(weekday_str), _OCCURRENCE_VALUE[occurrence_str]
        return None, None, None
    return None, None, None


def _parse_item_line(line: str) -> dict | None:
    match = _ITEM_LINE_RE.match(line.strip())
    if not match:
        return None
    rest = match.group("rest")

    pinned = bool(_PINNED_RE.search(rest))
    rest = _PINNED_RE.sub(" ", rest)

    due = None
    due_all_day = False
    due_match = _DUE_RE.search(rest)
    if due_match:
        date_str, time_str = due_match.group(1), due_match.group(2)
        if time_str:
            due = _display_to_due(f"{date_str} {time_str}")
        else:
            due = _display_to_due(date_str)
            due_all_day = True
        rest = _DUE_RE.sub(" ", rest)

    repeat = None
    repeat_days = repeat_weekday = repeat_occurrence = None
    repeat_match = _REPEAT_RE.search(rest)
    if repeat_match:
        repeat = repeat_match.group(1)
        repeat_days, repeat_weekday, repeat_occurrence = _parse_repeat_suffix(repeat, repeat_match.group(2))
        rest = _REPEAT_RE.sub(" ", rest)

    text = " ".join(rest.split()).strip()

    return {
        "id": match.group("id"),
        "text": text,
        "done": match.group(1).lower() == "x",
        "due": due,
        "dueAllDay": due_all_day,
        "pinned": pinned,
        "repeat": repeat,
        "repeatDays": repeat_days,
        "repeatWeekday": repeat_weekday,
        "repeatOccurrence": repeat_occurrence,
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


def _gen_id() -> str:
    ts = format(int(time.time() * 1000), "x")
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
    return f"{ts}{suffix}"


def _mtime_to_iso(mtime: float) -> str:
    dt = datetime.fromtimestamp(mtime, tz=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _render_key(d: dict) -> tuple:
    return (
        d.get("text", ""),
        bool(d.get("done")),
        d.get("due"),
        bool(d.get("dueAllDay")),
        bool(d.get("pinned")),
        d.get("repeat"),
        d.get("repeatDays"),
        d.get("repeatWeekday"),
        d.get("repeatOccurrence"),
    )


def _remote_to_item(r_item: dict, item_id: str, updated_at: str) -> dict:
    return {
        "_id": item_id,
        "text": r_item.get("text", ""),
        "done": bool(r_item.get("done")),
        "due": r_item.get("due"),
        "dueAllDay": bool(r_item.get("dueAllDay")),
        "notified": False,
        "pinned": bool(r_item.get("pinned")),
        "repeat": r_item.get("repeat"),
        "repeatDays": r_item.get("repeatDays"),
        "repeatWeekday": r_item.get("repeatWeekday"),
        "repeatOccurrence": r_item.get("repeatOccurrence"),
        "completedAt": updated_at if r_item.get("done") else None,
        "updatedAt": updated_at,
    }


def _apply_remote_to_item(local_item: dict, r_item: dict, updated_at: str) -> None:
    was_done = local_item.get("done")
    local_item["text"] = r_item.get("text", "")
    local_item["done"] = bool(r_item.get("done"))
    local_item["due"] = r_item.get("due")
    local_item["dueAllDay"] = bool(r_item.get("dueAllDay"))
    local_item["pinned"] = bool(r_item.get("pinned"))
    local_item["repeat"] = r_item.get("repeat")
    local_item["repeatDays"] = r_item.get("repeatDays")
    local_item["repeatWeekday"] = r_item.get("repeatWeekday")
    local_item["repeatOccurrence"] = r_item.get("repeatOccurrence")
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
    """Merge local widget state with parsed remote state from today's note.

    Uses last-write-wins (LWW) semantics: local is the source of truth for items
    it already knows about. Remote changes are applied only if note_mtime (the
    note file's modification time) is newer than the item's updatedAt timestamp.

    Since individual note-typed edits carry no per-item timestamp, note_mtime
    serves as the effective "when did this change" timestamp for all items in
    the remote snapshot.

    Maintains tombstones for deleted items to prevent re-creating recently-deleted
    items if they reappear in the note before the tombstone expires (3 days).
    """
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

            # New item: no prior local record and not tombstoned. Add it to local state.
            if existing is None and tombstone is None:
                new_item = _remote_to_item(r_item, item_id, note_mtime)
                target_list["items"].append(new_item)
                local_items_by_id[item_id] = (target_list, new_item)
                continue

            # Existing item: remote wins only if note_mtime is newer than local updatedAt.
            if existing is not None:
                _, local_item = existing
                if _render_key(local_item) == _render_key(r_item):
                    continue
                if note_mtime > local_item.get("updatedAt", ""):
                    _apply_remote_to_item(local_item, r_item, note_mtime)
                continue

            # Tombstoned item: resurrect only if note_mtime is newer than the tombstone.
            if note_mtime > tombstone.get("updatedAt", ""):
                new_item = _remote_to_item(r_item, item_id, note_mtime)
                target_list["items"].append(new_item)
                local_items_by_id[item_id] = (target_list, new_item)
                del tombstones_by_id[item_id]

    # Items missing from remote: tombstone them if note_mtime is newer than their updatedAt.
    # This handles items deleted in the note; gated by timestamp to prevent re-deletion
    # if they were modified locally after the note was last written.
    #
    # Lists with syncToVault=False are never written to the note by
    # render_tasks_section, so they can never appear in `remote` — without
    # this guard, every item in an excluded list would look "deleted in the
    # note" on the very next pull and get wiped out.
    for item_id, (lst, item) in list(local_items_by_id.items()):
        if item_id in seen_remote_item_ids:
            continue
        if lst.get("syncToVault") is False:
            continue
        if note_mtime > item.get("updatedAt", ""):
            lst["items"] = [it for it in lst["items"] if it["_id"] != item_id]
            tombstones_by_id[item_id] = {"_id": item_id, "updatedAt": note_mtime}

    result["tombstones"] = purge_old_tombstones(list(tombstones_by_id.values()))
    return result


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
