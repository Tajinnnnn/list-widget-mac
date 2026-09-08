"""Tests for vault_sync.merge_docs — the device-to-device document merge.

Distinct from merge(), which merges a device document against the
markdown-parsed shape from today's daily note using a single note_mtime.
merge_docs merges two full device documents using the per-item updatedAt
each one carries, has none of merge()'s vault-specific tombstone
exclusions, and covers settings/islands/trash as well as lists.

See docs/superpowers/specs/2026-09-08-iphone-pwa-sync-design.md.
"""

import copy
from datetime import datetime, timedelta, timezone

import vault_sync


def _iso(minutes_ago=0):
    # Tombstone assertions need timestamps inside purge_old_tombstones'
    # 3-day cutoff of the real clock, so these are relative, not hardcoded.
    dt = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


OLD = _iso(120)
MID = _iso(60)
NEW = _iso(1)


def _item(_id="i1", text="task", **overrides):
    item = {
        "_id": _id,
        "text": text,
        "done": False,
        "due": None,
        "dueAllDay": False,
        "notified": False,
        "pinned": False,
        "repeat": None,
        "repeatDays": None,
        "repeatWeekday": None,
        "repeatOccurrence": None,
        "completedAt": None,
        "updatedAt": MID,
        "type": "task",
        "note": None,
        "parentId": None,
        "subtasksCollapsed": False,
    }
    item.update(overrides)
    return item


def _list(id="l1", name="Tasks", items=None, **overrides):
    lst = {
        "id": id,
        "name": name,
        "items": items if items is not None else [],
        "color": None,
        "syncToVault": True,
        "islandId": None,
        "updatedAt": MID,
    }
    lst.update(overrides)
    return lst


def _doc(lists=None, **overrides):
    doc = {
        "lists": lists if lists is not None else [_list()],
        "active": "l1",
        "settings": {
            "retention": "endOfDay",
            "vibrancy": False,
            "calendarView": "day",
            "trashRetention": "7d",
            "updatedAt": MID,
        },
        "tombstones": [],
        "islands": [],
        "trash": [],
        "migratedDefaultListName": True,
    }
    doc.update(overrides)
    return doc


def _items_by_id(doc):
    out = {}
    for lst in doc["lists"]:
        for item in lst["items"]:
            out[item["_id"]] = (lst["id"], item)
    return out


def _without_active(doc):
    d = copy.deepcopy(doc)
    d.pop("active", None)
    return d


# --- core properties -------------------------------------------------------


def test_idempotent_on_identical_documents():
    doc = _doc(lists=[_list(items=[_item()])])
    assert vault_sync.merge_docs(doc, copy.deepcopy(doc)) == doc


def test_merging_a_document_with_itself_changes_nothing():
    doc = _doc(lists=[_list(items=[_item("a"), _item("b")])])
    assert vault_sync.merge_docs(doc, doc) == doc


def test_symmetric_ignoring_active():
    a = _doc(lists=[_list(items=[_item("a", "from a", updatedAt=NEW)])])
    b = _doc(
        lists=[_list(items=[_item("b", "from b", updatedAt=OLD)])],
        active="l1",
    )
    ab = vault_sync.merge_docs(a, b)
    ba = vault_sync.merge_docs(b, a)
    assert _without_active(ab) == _without_active(ba)


def test_does_not_mutate_either_input():
    a = _doc(lists=[_list(items=[_item("a", updatedAt=OLD)])])
    b = _doc(lists=[_list(items=[_item("a", "renamed", updatedAt=NEW)])])
    a_before, b_before = copy.deepcopy(a), copy.deepcopy(b)
    vault_sync.merge_docs(a, b)
    assert a == a_before
    assert b == b_before


# --- item-level last-write-wins -------------------------------------------


def test_newer_edit_on_b_wins():
    a = _doc(lists=[_list(items=[_item("x", "old text", updatedAt=OLD)])])
    b = _doc(lists=[_list(items=[_item("x", "new text", updatedAt=NEW)])])
    merged = vault_sync.merge_docs(a, b)
    assert _items_by_id(merged)["x"][1]["text"] == "new text"


def test_newer_edit_on_a_wins():
    a = _doc(lists=[_list(items=[_item("x", "new text", updatedAt=NEW)])])
    b = _doc(lists=[_list(items=[_item("x", "old text", updatedAt=OLD)])])
    merged = vault_sync.merge_docs(a, b)
    assert _items_by_id(merged)["x"][1]["text"] == "new text"


def test_item_only_on_b_is_added():
    a = _doc(lists=[_list(items=[_item("x")])])
    b = _doc(lists=[_list(items=[_item("x"), _item("y", "phone task")])])
    merged = vault_sync.merge_docs(a, b)
    assert set(_items_by_id(merged)) == {"x", "y"}


def test_done_flag_from_newer_side_wins():
    a = _doc(lists=[_list(items=[_item("x", done=False, updatedAt=OLD)])])
    b = _doc(lists=[_list(items=[_item("x", done=True, updatedAt=NEW)])])
    merged = vault_sync.merge_docs(a, b)
    assert _items_by_id(merged)["x"][1]["done"] is True


def test_equal_timestamps_break_deterministically_both_orders():
    a = _doc(lists=[_list(items=[_item("x", "alpha", updatedAt=MID)])])
    b = _doc(lists=[_list(items=[_item("x", "beta", updatedAt=MID)])])
    ab = _items_by_id(vault_sync.merge_docs(a, b))["x"][1]["text"]
    ba = _items_by_id(vault_sync.merge_docs(b, a))["x"][1]["text"]
    assert ab == ba


# --- tombstones ------------------------------------------------------------


def test_tombstone_newer_than_item_deletes_it():
    a = _doc(lists=[_list(items=[_item("x", updatedAt=OLD)])])
    b = _doc(lists=[_list()], tombstones=[{"_id": "x", "updatedAt": NEW}])
    merged = vault_sync.merge_docs(a, b)
    assert "x" not in _items_by_id(merged)


def test_edit_newer_than_tombstone_resurrects_item():
    a = _doc(lists=[_list(items=[_item("x", "edited on mac", updatedAt=NEW)])])
    b = _doc(lists=[_list()], tombstones=[{"_id": "x", "updatedAt": OLD}])
    merged = vault_sync.merge_docs(a, b)
    assert _items_by_id(merged)["x"][1]["text"] == "edited on mac"


def test_stale_device_does_not_resurrect_deleted_item():
    # The phone was dark for a while and still carries an item the Mac has
    # since deleted. Its stale copy must not bring the item back.
    a = _doc(lists=[_list()], tombstones=[{"_id": "x", "updatedAt": NEW}])
    b = _doc(lists=[_list(items=[_item("x", updatedAt=OLD)])])
    merged = vault_sync.merge_docs(a, b)
    assert "x" not in _items_by_id(merged)


def test_tombstones_are_unioned_keeping_the_newer_timestamp():
    a = _doc(tombstones=[{"_id": "x", "updatedAt": OLD}])
    b = _doc(tombstones=[{"_id": "x", "updatedAt": NEW}, {"_id": "y", "updatedAt": MID}])
    merged = vault_sync.merge_docs(a, b)
    by_id = {t["_id"]: t["updatedAt"] for t in merged["tombstones"]}
    assert by_id == {"x": NEW, "y": MID}


def test_expired_tombstones_are_purged():
    ancient = (datetime.now(timezone.utc) - timedelta(days=5)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )
    a = _doc(tombstones=[{"_id": "x", "updatedAt": ancient}])
    merged = vault_sync.merge_docs(a, _doc())
    assert merged["tombstones"] == []


# --- the vault-exclusion inversion ----------------------------------------


def test_note_typed_items_do_delete_across_devices():
    # merge() deliberately skips type == "note" from tombstoning because
    # render_tasks_section omits notes from the markdown round trip. For
    # device sync that exclusion is wrong: a deleted note must delete.
    a = _doc(lists=[_list(items=[_item("n", type="note", updatedAt=OLD)])])
    b = _doc(lists=[_list()], tombstones=[{"_id": "n", "updatedAt": NEW}])
    merged = vault_sync.merge_docs(a, b)
    assert "n" not in _items_by_id(merged)


def test_items_in_non_vault_lists_do_delete_across_devices():
    # Same inversion for syncToVault: false lists.
    a = _doc(lists=[_list(syncToVault=False, items=[_item("x", updatedAt=OLD)])])
    b = _doc(
        lists=[_list(syncToVault=False)],
        tombstones=[{"_id": "x", "updatedAt": NEW}],
    )
    merged = vault_sync.merge_docs(a, b)
    assert "x" not in _items_by_id(merged)


# --- cross-list moves ------------------------------------------------------


def test_cross_list_move_follows_the_newer_copy_without_duplicating():
    moved = _item("x", updatedAt=NEW)
    a = _doc(lists=[_list("l1", items=[_item("x", updatedAt=OLD)]), _list("l2", "Other")])
    b = _doc(lists=[_list("l1"), _list("l2", "Other", items=[moved])])
    merged = vault_sync.merge_docs(a, b)
    by_id = _items_by_id(merged)
    assert by_id["x"][0] == "l2"
    assert sum(len(l["items"]) for l in merged["lists"]) == 1


# --- lists -----------------------------------------------------------------


def test_list_rename_uses_newer_list_timestamp():
    a = _doc(lists=[_list("l1", "Old name", updatedAt=OLD)])
    b = _doc(lists=[_list("l1", "New name", updatedAt=NEW)])
    merged = vault_sync.merge_docs(a, b)
    assert merged["lists"][0]["name"] == "New name"


def test_list_color_from_newer_side_wins():
    a = _doc(lists=[_list("l1", color=None, updatedAt=OLD)])
    b = _doc(lists=[_list("l1", color="#ff0000", updatedAt=NEW)])
    merged = vault_sync.merge_docs(a, b)
    assert merged["lists"][0]["color"] == "#ff0000"


def test_new_list_from_b_is_added():
    a = _doc(lists=[_list("l1")])
    b = _doc(lists=[_list("l1"), _list("l2", "Phone list")])
    merged = vault_sync.merge_docs(a, b)
    assert {l["id"] for l in merged["lists"]} == {"l1", "l2"}


def test_item_order_follows_the_newer_list():
    a = _doc(
        lists=[
            _list("l1", items=[_item("x"), _item("y")], updatedAt=OLD)
        ]
    )
    b = _doc(
        lists=[
            _list("l1", items=[_item("y"), _item("x")], updatedAt=NEW)
        ]
    )
    merged = vault_sync.merge_docs(a, b)
    assert [i["_id"] for i in merged["lists"][0]["items"]] == ["y", "x"]


# --- settings, islands, trash, active -------------------------------------


def test_settings_replaced_wholesale_by_newer_side():
    a = _doc()
    a["settings"] = {**a["settings"], "retention": "never", "updatedAt": OLD}
    b = _doc()
    b["settings"] = {**b["settings"], "retention": "4h", "updatedAt": NEW}
    merged = vault_sync.merge_docs(a, b)
    assert merged["settings"]["retention"] == "4h"


def test_islands_unioned_with_per_island_last_write_wins():
    a = _doc(islands=[{"id": "s1", "name": "Old", "color": None, "collapsed": False, "updatedAt": OLD}])
    b = _doc(
        islands=[
            {"id": "s1", "name": "New", "color": None, "collapsed": False, "updatedAt": NEW},
            {"id": "s2", "name": "Second", "color": None, "collapsed": False, "updatedAt": MID},
        ]
    )
    merged = vault_sync.merge_docs(a, b)
    by_id = {i["id"]: i["name"] for i in merged["islands"]}
    assert by_id == {"s1": "New", "s2": "Second"}


def test_trash_unioned_by_id():
    a = _doc(trash=[{"_id": "t1", "kind": "item", "deletedAt": OLD, "listId": "l1", "listName": "Tasks", "payload": {}}])
    b = _doc(trash=[{"_id": "t2", "kind": "item", "deletedAt": NEW, "listId": "l1", "listName": "Tasks", "payload": {}}])
    merged = vault_sync.merge_docs(a, b)
    assert {t["_id"] for t in merged["trash"]} == {"t1", "t2"}


def test_trash_removal_wins_over_a_stale_present_entry():
    # A restore or manual purge sets removedAt rather than splicing, and the
    # marked entry has to survive the merge — dropping it would let the
    # device that still holds the entry simply re-add it. The client filters
    # removedAt out of the Trash view; trashRetention purges it for good.
    entry = {"_id": "t1", "kind": "item", "deletedAt": OLD, "listId": "l1", "listName": "Tasks", "payload": {}}
    a = _doc(trash=[entry])
    b = _doc(trash=[{**entry, "removedAt": NEW}])
    merged = vault_sync.merge_docs(a, b)
    assert [t["_id"] for t in merged["trash"]] == ["t1"]
    assert merged["trash"][0]["removedAt"] == NEW


def test_trash_removal_wins_in_either_argument_order():
    entry = {"_id": "t1", "kind": "item", "deletedAt": OLD, "listId": "l1", "listName": "Tasks", "payload": {}}
    a = _doc(trash=[entry])
    b = _doc(trash=[{**entry, "removedAt": NEW}])
    assert vault_sync.merge_docs(a, b)["trash"] == vault_sync.merge_docs(b, a)["trash"]


def test_active_tab_is_taken_from_the_first_document():
    a = _doc(lists=[_list("l1"), _list("l2", "Other")], active="l1")
    b = _doc(lists=[_list("l1"), _list("l2", "Other")], active="l2")
    assert vault_sync.merge_docs(a, b)["active"] == "l1"


def test_migration_flag_is_sticky_if_either_side_ran_it():
    a = _doc(migratedDefaultListName=False)
    b = _doc(migratedDefaultListName=True)
    assert vault_sync.merge_docs(a, b)["migratedDefaultListName"] is True
    assert vault_sync.merge_docs(b, a)["migratedDefaultListName"] is True


# --- randomized property checks -------------------------------------------
#
# The hand-built pairs above each pin one rule. These generate messy
# multi-list documents with overlapping ids, divergent timestamps and
# tombstones, because that is the shape real device divergence takes and
# it is where an order-dependent tie-break would actually show up.


def _random_doc(rng, item_ids, list_ids):
    stamps = [OLD, MID, NEW]
    chosen_lists = rng.sample(list_ids, rng.randint(1, len(list_ids)))

    # Each item id lives in at most ONE list. A real document can never
    # have the same _id in two lists, and generating that state would make
    # these properties fail on an input the app cannot produce.
    pool = item_ids[:]
    rng.shuffle(pool)
    assignment = {list_id: [] for list_id in chosen_lists}
    for item_id in pool:
        if rng.random() < 0.25:
            continue  # this document simply doesn't know about the item
        assignment[rng.choice(chosen_lists)].append(item_id)

    lists = []
    for list_id in chosen_lists:
        chosen = assignment[list_id]
        lists.append(
            _list(
                list_id,
                name=rng.choice(["Tasks", "Work", "Home"]),
                items=[
                    _item(
                        i,
                        text=rng.choice(["a", "b", "c"]),
                        done=rng.choice([True, False]),
                        type=rng.choice(["task", "note"]),
                        updatedAt=rng.choice(stamps),
                    )
                    for i in chosen
                ],
                color=rng.choice([None, "#ff0000"]),
                syncToVault=rng.choice([True, False]),
                updatedAt=rng.choice(stamps),
            )
        )
    used = {i["_id"] for l in lists for i in l["items"]}
    tombs = [
        {"_id": i, "updatedAt": rng.choice(stamps)}
        for i in item_ids
        if i not in used and rng.random() < 0.4
    ]
    rng.shuffle(tombs)
    doc = _doc(lists=lists, tombstones=tombs, active=lists[0]["id"])
    doc["settings"] = {**doc["settings"], "updatedAt": rng.choice(stamps)}
    doc["listsUpdatedAt"] = rng.choice(stamps)
    return doc


def test_symmetry_holds_over_randomized_documents():
    import random

    item_ids = ["i1", "i2", "i3", "i4", "i5"]
    list_ids = ["l1", "l2", "l3"]
    for seed in range(300):
        rng = random.Random(seed)
        a = _random_doc(rng, item_ids, list_ids)
        b = _random_doc(rng, item_ids, list_ids)
        ab = vault_sync.merge_docs(a, b)
        ba = vault_sync.merge_docs(b, a)
        assert _without_active(ab) == _without_active(ba), f"asymmetric at seed {seed}"


def _canonical(doc):
    # merge_docs returns a canonical form: tombstones, islands and trash are
    # sorted by id so the result never depends on argument order. A document
    # straight off a client is not canonical — it appends tombstones in
    # deletion order — so idempotence is stated against the canonical form.
    d = copy.deepcopy(doc)
    d["tombstones"] = sorted(d.get("tombstones") or [], key=lambda t: t["_id"])
    return d


def test_idempotence_holds_over_randomized_documents():
    import random

    item_ids = ["i1", "i2", "i3", "i4", "i5"]
    list_ids = ["l1", "l2", "l3"]
    for seed in range(300):
        rng = random.Random(seed)
        doc = _random_doc(rng, item_ids, list_ids)
        merged = vault_sync.merge_docs(doc, doc)
        assert merged == _canonical(doc), f"not idempotent at seed {seed}"
        # And canonical output is a genuine fixed point.
        assert vault_sync.merge_docs(merged, merged) == merged, f"seed {seed}"


def test_merging_is_stable_when_reapplied_to_its_own_result():
    # A client pushes, gets the merged document back, and pushes again on
    # the next save. That second round trip must not keep changing things.
    import random

    item_ids = ["i1", "i2", "i3", "i4"]
    list_ids = ["l1", "l2"]
    for seed in range(200):
        rng = random.Random(seed)
        a = _random_doc(rng, item_ids, list_ids)
        b = _random_doc(rng, item_ids, list_ids)
        once = vault_sync.merge_docs(a, b)
        twice = vault_sync.merge_docs(once, b)
        assert twice == once, f"unstable at seed {seed}"


def test_no_item_is_ever_duplicated_across_lists():
    import random

    item_ids = ["i1", "i2", "i3", "i4", "i5"]
    list_ids = ["l1", "l2", "l3"]
    for seed in range(300):
        rng = random.Random(seed)
        a = _random_doc(rng, item_ids, list_ids)
        b = _random_doc(rng, item_ids, list_ids)
        merged = vault_sync.merge_docs(a, b)
        seen = [i["_id"] for l in merged["lists"] for i in l["items"]]
        assert len(seen) == len(set(seen)), f"duplicate at seed {seed}"


def test_no_tombstoned_item_survives_with_an_older_timestamp():
    import random

    item_ids = ["i1", "i2", "i3", "i4", "i5"]
    list_ids = ["l1", "l2"]
    for seed in range(300):
        rng = random.Random(seed)
        a = _random_doc(rng, item_ids, list_ids)
        b = _random_doc(rng, item_ids, list_ids)
        merged = vault_sync.merge_docs(a, b)
        tombs = {t["_id"]: t["updatedAt"] for t in merged["tombstones"]}
        for lst in merged["lists"]:
            for item in lst["items"]:
                if item["_id"] in tombs:
                    assert tombs[item["_id"]] <= item["updatedAt"], f"seed {seed}"
