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
