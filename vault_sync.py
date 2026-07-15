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
