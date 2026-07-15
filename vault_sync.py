import os
import re
from datetime import date, datetime, timezone
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
