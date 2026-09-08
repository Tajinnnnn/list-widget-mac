"""Tests for sync_api.handle — the sync server's request logic.

Kept as a pure function over a store so the auth, dispatch, validation and
merge behaviour is testable without HTTP or Postgres. api/state.py is a
thin adapter over this; sync_store.py is the Postgres store.
"""

import copy
import json

import sync_api
import vault_sync

SECRET = "test-secret"
TS = "2026-09-08T12:00:00.000Z"
NEWER = "2026-09-08T13:00:00.000Z"


def _item(_id="i1", text="task", updatedAt=TS, **kw):
    item = {
        "_id": _id, "text": text, "done": False, "due": None, "dueAllDay": False,
        "notified": False, "pinned": False, "repeat": None, "repeatDays": None,
        "repeatWeekday": None, "repeatOccurrence": None, "completedAt": None,
        "updatedAt": updatedAt, "type": "task", "note": None, "parentId": None,
        "subtasksCollapsed": False,
    }
    item.update(kw)
    return item


def _doc(items=None, active="l1", **kw):
    doc = {
        "lists": [{
            "id": "l1", "name": "Tasks", "color": None, "syncToVault": True,
            "islandId": None, "updatedAt": TS,
            "items": items if items is not None else [_item()],
        }],
        "active": active,
        "settings": {"retention": "endOfDay", "vibrancy": False,
                     "calendarView": "day", "trashRetention": "7d", "updatedAt": TS},
        "tombstones": [], "islands": [], "trash": [],
        "migratedDefaultListName": True,
    }
    doc.update(kw)
    return doc


def _auth(secret=SECRET):
    return {"authorization": f"Bearer {secret}"}


def _call(method, headers=None, body=None, store=None, secret=SECRET):
    if store is None:
        store = sync_api.InMemoryStore()
    return sync_api.handle(
        method,
        headers if headers is not None else _auth(),
        body,
        store,
        secret,
    )


# --- auth ------------------------------------------------------------------


def test_missing_authorization_header_is_rejected():
    status, payload = _call("GET", headers={})
    assert status == 401
    assert "doc" not in payload


def test_wrong_secret_is_rejected():
    status, _ = _call("GET", headers=_auth("nope"))
    assert status == 401


def test_non_bearer_scheme_is_rejected():
    status, _ = _call("GET", headers={"authorization": SECRET})
    assert status == 401


def test_header_name_is_matched_case_insensitively():
    status, _ = _call("GET", headers={"Authorization": f"Bearer {SECRET}"})
    assert status == 200


def test_server_with_no_secret_configured_refuses_everything():
    # A missing INGEST-style secret must fail closed, not open.
    status, _ = _call("GET", secret="")
    assert status == 503


def test_auth_is_checked_before_the_body_is_parsed():
    # A malformed body on an unauthenticated request must still be a 401,
    # so a probe cannot tell a bad secret from a bad payload.
    status, _ = _call("POST", headers={}, body=b"{{{not json")
    assert status == 401


# --- GET -------------------------------------------------------------------


def test_get_on_empty_database_returns_null_doc_at_version_zero():
    status, payload = _call("GET")
    assert status == 200
    assert payload["doc"] is None
    assert payload["version"] == 0


def test_get_returns_the_stored_document():
    store = sync_api.InMemoryStore(_doc(), version=3)
    status, payload = _call("GET", store=store)
    assert status == 200
    assert payload["version"] == 3
    assert payload["doc"]["lists"][0]["items"][0]["_id"] == "i1"


# --- POST ------------------------------------------------------------------


def test_first_post_stores_the_document():
    store = sync_api.InMemoryStore()
    status, payload = _call("POST", body=json.dumps({"doc": _doc()}).encode(), store=store)
    assert status == 200
    assert payload["version"] == 1
    assert payload["doc"]["lists"][0]["items"][0]["_id"] == "i1"


def test_post_merges_against_the_stored_document():
    store = sync_api.InMemoryStore(_doc(items=[_item("i1", "from mac")]))
    incoming = _doc(items=[_item("i1", "from mac"), _item("i2", "from phone")])
    status, payload = _call("POST", body=json.dumps({"doc": incoming}).encode(), store=store)
    assert status == 200
    ids = {i["_id"] for i in payload["doc"]["lists"][0]["items"]}
    assert ids == {"i1", "i2"}


def test_post_returns_the_merged_document_not_the_one_sent():
    # The client replaces its local state with this, so it has to include
    # what the other device contributed.
    store = sync_api.InMemoryStore(_doc(items=[_item("i1"), _item("i9", "only on server")]))
    incoming = _doc(items=[_item("i1")])
    _, payload = _call("POST", body=json.dumps({"doc": incoming}).encode(), store=store)
    assert "i9" in {i["_id"] for i in payload["doc"]["lists"][0]["items"]}


def test_post_keeps_the_pushing_clients_active_tab():
    # `active` is per-device. The pusher must not get its selected tab
    # replaced by whatever the other device was looking at.
    stored = _doc(active="l1")
    stored["lists"].append({
        "id": "l2", "name": "Other", "color": None, "syncToVault": True,
        "islandId": None, "updatedAt": TS, "items": [],
    })
    store = sync_api.InMemoryStore(stored)
    incoming = copy.deepcopy(stored)
    incoming["active"] = "l2"
    _, payload = _call("POST", body=json.dumps({"doc": incoming}).encode(), store=store)
    assert payload["doc"]["active"] == "l2"


def test_version_increments_only_when_the_document_actually_changes():
    doc = _doc()
    canonical = vault_sync.merge_docs(doc, doc)
    store = sync_api.InMemoryStore(canonical, version=7)
    _, payload = _call("POST", body=json.dumps({"doc": canonical}).encode(), store=store)
    assert payload["version"] == 7


def test_newer_edit_from_the_client_wins():
    store = sync_api.InMemoryStore(_doc(items=[_item("i1", "stale", updatedAt=TS)]))
    incoming = _doc(items=[_item("i1", "fresh", updatedAt=NEWER)])
    _, payload = _call("POST", body=json.dumps({"doc": incoming}).encode(), store=store)
    assert payload["doc"]["lists"][0]["items"][0]["text"] == "fresh"


def test_stale_client_does_not_resurrect_a_server_side_deletion():
    stored = _doc(items=[])
    stored["tombstones"] = [{"_id": "i1", "updatedAt": NEWER}]
    store = sync_api.InMemoryStore(stored)
    incoming = _doc(items=[_item("i1", updatedAt=TS)])
    _, payload = _call("POST", body=json.dumps({"doc": incoming}).encode(), store=store)
    assert payload["doc"]["lists"][0]["items"] == []


# --- validation ------------------------------------------------------------


def test_malformed_json_is_a_400():
    status, _ = _call("POST", body=b"{not json")
    assert status == 400


def test_empty_body_is_a_400():
    status, _ = _call("POST", body=b"")
    assert status == 400


def test_missing_doc_key_is_a_400():
    status, _ = _call("POST", body=json.dumps({"nope": 1}).encode())
    assert status == 400


def test_doc_that_is_not_an_object_is_a_400():
    status, _ = _call("POST", body=json.dumps({"doc": [1, 2]}).encode())
    assert status == 400


def test_doc_without_a_lists_array_is_a_400():
    # Guards against storing a document shape the client cannot load,
    # which would brick both devices at once.
    status, _ = _call("POST", body=json.dumps({"doc": {"settings": {}}}).encode())
    assert status == 400


def test_a_rejected_document_does_not_touch_the_store():
    store = sync_api.InMemoryStore(_doc(), version=4)
    _call("POST", body=b"{bad", store=store)
    doc, version = store.read()
    assert version == 4
    assert doc["lists"][0]["items"][0]["_id"] == "i1"


# --- dispatch --------------------------------------------------------------


def test_unsupported_method_is_a_405():
    status, _ = _call("DELETE")
    assert status == 405


def test_options_preflight_is_allowed_without_auth():
    status, _ = _call("OPTIONS", headers={})
    assert status == 204


# --- concurrency -----------------------------------------------------------


def test_two_clients_pushing_in_either_order_converge():
    mac = _doc(items=[_item("i1", "mac", updatedAt=NEWER)])
    phone = _doc(items=[_item("i1", "phone", updatedAt=TS), _item("i2", "phone only")])

    a = sync_api.InMemoryStore()
    _call("POST", body=json.dumps({"doc": mac}).encode(), store=a)
    _, first = _call("POST", body=json.dumps({"doc": phone}).encode(), store=a)

    b = sync_api.InMemoryStore()
    _call("POST", body=json.dumps({"doc": phone}).encode(), store=b)
    _, second = _call("POST", body=json.dumps({"doc": mac}).encode(), store=b)

    def shape(payload):
        d = copy.deepcopy(payload["doc"])
        d.pop("active", None)
        return d

    assert shape(first) == shape(second)
