"""(C) An older widget snapshot must not clobber a shared task edit."""
import json
import backup


def test_stale_widget_save_preserves_external_edit(tmp_path, monkeypatch):
    path=tmp_path/'backup.json'
    monkeypatch.setattr(backup,'BACKUP_PATH',path)
    monkeypatch.setattr(backup.vault_sync,'sync_push',lambda *args:None)
    stale={'lists':[{'id':'l','name':'Tasks','items':[{'_id':'a','text':'Old','updatedAt':'2026-01-01T00:00:00Z'}]}]}
    current={'lists':[{'id':'l','name':'Tasks','items':[{'_id':'a','text':'New','updatedAt':'2026-01-02T00:00:00Z'},{'_id':'b','text':'Added','updatedAt':'2026-01-02T00:00:00Z'}]}]}
    path.write_text(json.dumps(current))
    assert backup.write_backup(json.dumps(stale))
    items=json.loads(path.read_text())['lists'][0]['items']
    assert {x['_id']:x['text'] for x in items}=={'a':'New','b':'Added'}
