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
