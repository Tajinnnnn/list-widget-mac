from datetime import date, datetime, timezone
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
