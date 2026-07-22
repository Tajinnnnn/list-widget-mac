import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import vault_sync


def _recent_iso(minutes_ago=0):
    # Tombstone-related merge tests need timestamps within purge_old_tombstones'
    # 3-day cutoff of the real clock, not hardcoded dates that age out.
    dt = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


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


def test_format_item_line_weekly_with_days():
    line = vault_sync._format_item_line(_item(repeat="weekly", repeatDays="1,3,5"))
    assert "🔁 weekly:Mon,Wed,Fri" in line


def test_format_item_line_monthly_with_occurrence():
    line = vault_sync._format_item_line(_item(repeat="monthly", repeatWeekday=2, repeatOccurrence=2))
    assert "🔁 monthly:2nd-Tue" in line


def test_weekly_days_roundtrip_through_line():
    line = vault_sync._format_item_line(_item(repeat="weekly", repeatDays="1,3,5"))
    note = f"## Tasks\n### Tasks <!--id:list1-->\n{line}\n"
    parsed = vault_sync.parse_tasks_section(note)
    item = parsed["lists"][0]["items"][0]
    assert item["repeat"] == "weekly"
    assert item["repeatDays"] == "1,3,5"


def test_monthly_occurrence_roundtrip_through_line():
    line = vault_sync._format_item_line(_item(repeat="monthly", repeatWeekday=2, repeatOccurrence=2))
    note = f"## Tasks\n### Tasks <!--id:list1-->\n{line}\n"
    parsed = vault_sync.parse_tasks_section(note)
    item = parsed["lists"][0]["items"][0]
    assert item["repeat"] == "monthly"
    assert item["repeatWeekday"] == 2
    assert item["repeatOccurrence"] == 2


def test_bare_repeat_tag_still_parses_with_no_days():
    note = "## Tasks\n### Tasks <!--id:list1-->\n- [ ] Gym 🔁 weekly <!--id:abc123-->\n"
    parsed = vault_sync.parse_tasks_section(note)
    item = parsed["lists"][0]["items"][0]
    assert item["repeat"] == "weekly"
    assert item["repeatDays"] is None
    assert item["repeatWeekday"] is None
    assert item["repeatOccurrence"] is None


def test_format_item_line_with_due_contains_marker():
    line = vault_sync._format_item_line(_item(due="2026-08-01T04:59:00.000Z"))
    assert "📅 " in line
    assert line.endswith("<!--id:abc123-->")


def test_format_item_line_all_day_due_has_no_time():
    line = vault_sync._format_item_line(_item(due="2026-08-01T04:59:00.000Z", dueAllDay=True))
    assert re.search(r"📅 \d{4}-\d{2}-\d{2} <!--", line)


def test_all_day_due_roundtrip_through_line():
    line = vault_sync._format_item_line(_item(due="2026-08-01T04:59:00.000Z", dueAllDay=True))
    note = f"## Tasks\n### Tasks <!--id:list1-->\n{line}\n"
    parsed = vault_sync.parse_tasks_section(note)
    item = parsed["lists"][0]["items"][0]
    assert item["dueAllDay"] is True
    assert item["due"] is not None


def test_timed_due_roundtrip_still_not_all_day():
    original = "2026-08-01T04:59:00.000Z"
    line = vault_sync._format_item_line(_item(due=original, dueAllDay=False))
    note = f"## Tasks\n### Tasks <!--id:list1-->\n{line}\n"
    parsed = vault_sync.parse_tasks_section(note)
    item = parsed["lists"][0]["items"][0]
    assert item["dueAllDay"] is False
    assert item["due"] == original


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


def test_render_tasks_section_excludes_list_with_sync_off():
    state = {
        "lists": [
            {"id": "list1", "name": "Tasks", "items": [_item()]},
            {"id": "list2", "name": "Private", "syncToVault": False,
             "items": [_item(_id="def456", text="Secret")]},
        ]
    }
    section = vault_sync.render_tasks_section(state)
    assert "### Tasks <!--id:list1-->" in section
    assert "Private" not in section
    assert "Secret" not in section


def test_render_tasks_section_includes_list_with_sync_on():
    state = {
        "lists": [
            {"id": "list1", "name": "Tasks", "syncToVault": True, "items": [_item()]},
        ]
    }
    section = vault_sync.render_tasks_section(state)
    assert "### Tasks <!--id:list1-->" in section


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
        "due": None, "dueAllDay": False, "pinned": False, "repeat": None,
        "repeatDays": None, "repeatWeekday": None, "repeatOccurrence": None,
    }
    assert gym == {
        "id": "def456", "text": "Gym", "done": True,
        "due": None, "dueAllDay": False, "pinned": True, "repeat": "daily",
        "repeatDays": None, "repeatWeekday": None, "repeatOccurrence": None,
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
    note_mtime = _recent_iso()
    merged = vault_sync.merge(local, remote, note_mtime)
    assert merged["lists"][0]["items"] == []
    assert merged["tombstones"] == [{"_id": "a1", "updatedAt": note_mtime}]


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
    tombstone_time = _recent_iso()
    note_mtime = _recent_iso(minutes_ago=10)
    local["tombstones"] = [{"_id": "a1", "updatedAt": tombstone_time}]
    remote = _remote_list([
        {"id": "a1", "text": "Stale leftover line", "done": False, "due": None,
         "pinned": False, "repeat": None},
    ])
    merged = vault_sync.merge(local, remote, note_mtime)
    assert merged["lists"][0]["items"] == []
    assert merged["tombstones"] == [{"_id": "a1", "updatedAt": tombstone_time}]


def test_merge_leaves_sync_off_list_untouched_when_absent_from_remote():
    # A syncToVault=False list is never written to the note by
    # render_tasks_section, so it can never appear in `remote` — merge must
    # not mistake that absence for the items having been deleted in the note.
    local = _local_state(syncToVault=False)
    remote = {"lists": []}
    merged = vault_sync.merge(local, remote, _recent_iso())
    assert merged["lists"][0]["items"] == local["lists"][0]["items"]
    assert merged["tombstones"] == []


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
    from datetime import timedelta
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
