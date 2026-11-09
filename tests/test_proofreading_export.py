import json
from meetingkit.webui.server import Api


def test_export_requires_saved_decisions(tmp_path, monkeypatch):
    minutes = tmp_path / '会议纪要.md'
    minutes.write_text('API说明', encoding='utf-8')
    review = tmp_path / 'proofreading.json'
    review.write_text(json.dumps({'uncertain': [{'term': 'API'}]}), encoding='utf-8')
    api = Api()
    monkeypatch.setattr(api, '_safe_minutes_path', lambda path: minutes)
    destination = tmp_path / 'export'
    destination.mkdir()
    monkeypatch.setattr(api, 'pick_folder', lambda: str(destination))
    assert not api.export_minutes(str(minutes))['ok']
    assert api.save_minutes(str(minutes), 'API说明', {'API': 'confirmed'})['ok']
    assert api.get_minutes(str(minutes))['proofreading']['uncertain'][0]['decision'] == 'confirmed'
    assert api.export_minutes(str(minutes))['ok']
    assert api.save_minutes(str(minutes), 'API说明', {'API': 'pending'})['ok']
    assert not api.export_minutes(str(minutes))['ok']
