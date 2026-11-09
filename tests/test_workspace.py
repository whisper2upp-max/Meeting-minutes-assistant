import json
import urllib.request
import urllib.error
import wave

import pytest

from meetingkit.config import Config
from meetingkit.workspace import read_workspace, update_workspace
from meetingkit.webui import server, media


@pytest.fixture
def meeting(tmp_path, monkeypatch):
    monkeypatch.setenv('MEETINGKIT_HOME', str(tmp_path / 'config'))
    monkeypatch.setattr(server._state, 'cfg', Config(output_dir=str(tmp_path)))
    folder = tmp_path / '2026-11-09_1000'
    folder.mkdir()
    minutes = folder / '会议纪要.md'
    minutes.write_text('飞书妙季讨论。', encoding='utf-8')
    (folder / 'transcript.json').write_text(json.dumps({'sentences': [
        {'text': '统一会议记录', 'begin_ms': 1000, 'end_ms': 4000, 'speaker_id': 0},
        {'text': '好的', 'begin_ms': 4500, 'end_ms': 6000, 'speaker_id': 1}]}), encoding='utf-8')
    (folder / 'proofreading.json').write_text(json.dumps({'status': 'done', 'uncertain': [{'term': '飞书妙季'}]}), encoding='utf-8')
    with wave.open(str(folder / 'audio.wav'), 'wb') as f:
        f.setnchannels(1); f.setsampwidth(2); f.setframerate(16000)
        f.writeframes(bytes(16000*2*8))
    return minutes


def test_preferences_and_dictionary_persist_and_validate(tmp_path, monkeypatch):
    monkeypatch.setenv('MEETINGKIT_HOME', str(tmp_path))
    update_workspace({'font_size': 17, 'reduce_motion': True, 'terms': [{'from': '错词', 'to': '准确词'}]})
    assert read_workspace()['terms'] == [{'from': '错词', 'to': '准确词'}]
    assert read_workspace()['font_size'] == 17
    with pytest.raises(ValueError): update_workspace({'font_size': 100})
    with pytest.raises(ValueError): update_workspace({'terms': [{'from': '', 'to': 'x'}]})
    assert read_workspace()['font_size'] == 17
    update_workspace({'terms': []})
    assert read_workspace()['terms'] == []


def test_segments_and_mapping_use_real_timestamps(meeting):
    api = server.Api()
    assert api.save_speaker_mapping(str(meeting), {'1': '林悦'})['ok']
    r = api.get_meeting_segments(str(meeting))
    assert r['segments'][0] == {'number': 1, 'speaker': '林悦', 'begin': 1.0, 'end': 4.0, 'text': '统一会议记录'}
    with urllib.request.urlopen(urllib.request.Request(r['audio_url'], headers={'Range': 'bytes=44-63'})) as response:
        assert response.status == 206
        assert response.headers['Content-Length'] == '20'
        assert response.read() == bytes(20)
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(r['audio_url'] + '/../../config.json')
    assert exc.value.code == 404


def test_media_range_and_deleted_audio(meeting):
    audio = meeting.parent / 'audio.wav'
    url = media.register(audio)
    data = audio.read_bytes()
    with urllib.request.urlopen(urllib.request.Request(url, headers={'Range': 'bytes=-12'})) as response:
        assert response.read() == data[-12:]
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(urllib.request.Request(url, headers={'Range': 'bytes=999999-'}))
    assert exc.value.code == 416
    audio.unlink()
    assert server.Api().get_meeting_segments(str(meeting))['audio_url'] == ''
    with pytest.raises(urllib.error.HTTPError) as exc:
        urllib.request.urlopen(url)
    assert exc.value.code == 404


def test_video_disguised_as_audio_wav_has_correct_mime(tmp_path):
    p = tmp_path / 'audio.wav'
    p.write_bytes(b'\x00\x00\x00\x18ftypmp42' + bytes(30))
    assert media.media_type(p) == 'video/mp4'


def test_sessions_count_saved_decisions_and_workspace_scope(meeting, tmp_path):
    api = server.Api()
    assert api.list_sessions()['sessions'][0]['pending_terms'] == 1
    assert api.save_minutes(str(meeting), '飞书妙记讨论。', {'飞书妙季': {'decision': 'replaced', 'replacement': '飞书妙记'}})['ok']
    session = api.list_sessions()['sessions'][0]
    assert session['pending_terms'] == 0
    assert session['total_terms'] == 1
    assert session['duration_seconds'] == 6
    assert api.get_minutes(str(meeting))['proofreading']['uncertain'][0]['replacement'] == '飞书妙记'
    assert not api.save_workspace({'last_minutes': str(tmp_path.parent / 'outside.md')})['ok']
    assert api.save_workspace({'last_minutes': str(meeting)})['ok']
    assert api.get_workspace()['last_minutes'] == str(meeting)


def test_dictionary_reference_reaches_generation_without_unrelated_terms(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from meetingkit.cloud import llm
    monkeypatch.setenv('MEETINGKIT_HOME', str(tmp_path))
    update_workspace({'terms': [{'from': '飞书妙季', 'to': '飞书妙记'}, {'from': '不相关', 'to': '无关名称'}]})
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='# 会议纪要'))])
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    monkeypatch.setattr(llm, 'OpenAI', lambda **kwargs: client)
    monkeypatch.setattr(llm, 'proofread_minutes', lambda client, model, text: text)
    llm.generate_minutes('通过飞书妙季整理会议。', api_key='test')
    messages = json.dumps(calls[0]['messages'], ensure_ascii=False)
    assert '飞书妙记' in messages
    assert '无关名称' not in messages
