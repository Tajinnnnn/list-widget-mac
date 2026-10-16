# (C) Deleted list identities must survive stale clients and trash expiry.
import copy
from vault_sync import merge_docs, merge


def test_deleted_empty_list_stays_deleted():
    stale = {'lists': [{'id': 'keep', 'name': 'Keep', 'items': []}, {'id': 'gone', 'name': 'New list', 'items': []}], 'active': 'gone'}
    deleted = copy.deepcopy(stale)
    deleted['lists'].pop()
    deleted['listTombstones'] = [{'id': 'gone', 'updatedAt': '2026-01-01T00:00:00Z'}]
    for a,b in [(deleted,stale),(stale,deleted)]:
        result = merge_docs(a,b)
        assert [l['id'] for l in result['lists']] == ['keep']
        assert result['active'] == 'keep'
        assert result['listTombstones'] == deleted['listTombstones']
        assert merge_docs(result,stale)['lists'] == result['lists']


def test_explicit_restore_beats_list_deletion():
    deleted = {'lists': [], 'listTombstones': [{'id':'gone','updatedAt':'2026-01-01T00:00:00Z'}]}
    restored = {'lists':[{'id':'gone','name':'Restored','items':[], 'restoredAt':'2026-01-02T00:00:00Z'}]}
    for a,b in [(deleted,restored),(restored,deleted)]:
        assert len(merge_docs(a,b)['lists']) == 1


def test_old_vault_heading_cannot_recreate_deleted_list():
    local = {'lists': [], 'listTombstones':[{'id':'gone','updatedAt':'2026-01-01T00:00:00Z'}]}
    remote = {'lists':[{'id':'gone','name':'New list','items':[]}]}
    assert merge(local,remote,'2026-01-02T00:00:00Z')['lists'] == []
