from datetime import datetime

import numpy as np

from meetingkit.audio.base import TrackSpec, write_wav_mono
from meetingkit.config import Config
from meetingkit.webui import server


class _RecordedTracks:
    def __init__(self, specs):
        self._specs = specs

    def stop(self):
        return self._specs


def test_recording_process_reaches_pipeline_after_silence_check(tmp_path, monkeypatch):
    """覆盖录音停止后的混音、静音检查和管线调用，防止包内相对导入写错。"""
    sample_rate = 48000
    system_path = tmp_path / "track_system.wav"
    mic_path = tmp_path / "track_mic.wav"
    write_wav_mono(system_path, np.zeros(sample_rate, dtype=np.float32), sample_rate)
    write_wav_mono(
        mic_path,
        np.full(sample_rate + 512, 0.1, dtype=np.float32),
        sample_rate,
    )
    recorder = _RecordedTracks([
        TrackSpec(system_path, sample_rate, "system"),
        TrackSpec(mic_path, sample_rate, "mic"),
    ])

    pipeline_calls = []

    def fake_run_pipeline(audio_path, cfg, **kwargs):
        pipeline_calls.append((audio_path, cfg, kwargs))
        return "0.0 分钟"

    monkeypatch.setattr(server, "IS_MACOS", False)
    monkeypatch.setattr(server.pipeline_mod, "run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(server._state, "cfg", Config(api_key="sk-test"))
    monkeypatch.setattr(server._state, "session_dir", tmp_path)
    monkeypatch.setattr(server._state, "started_at", datetime(2026, 8, 29))
    monkeypatch.setattr(server._state, "phase", "processing")
    monkeypatch.setattr(server._state, "error", None)
    monkeypatch.setattr(server._state, "result", None)

    server.Api()._process_worker(recorder, None)

    assert server._state.phase == "done"
    assert server._state.error is None
    assert len(pipeline_calls) == 1
    assert pipeline_calls[0][0] == tmp_path / server.pipeline_mod.AUDIO_WAV
    assert pipeline_calls[0][0].exists()


def test_minutes_metadata_and_recent_sessions(tmp_path, monkeypatch):
    """纪要工作区需要历史记录、原始转写与文件时间等完整元数据。"""
    session = tmp_path / "2026-08-29_0900_产品同步"
    session.mkdir()
    minutes = session / server.pipeline_mod.MINUTES_MD
    transcript = session / server.pipeline_mod.TRANSCRIPT_MD
    minutes.write_text("# 产品同步\n\n- 下一步", encoding="utf-8")
    transcript.write_text("完整转写", encoding="utf-8")
    monkeypatch.setattr(server._state, "cfg", Config(output_dir=str(tmp_path)))

    detail = server.Api().get_minutes(str(minutes))
    recent = server.Api().list_sessions()

    assert detail["ok"] is True
    assert detail["session_name"] == session.name
    assert detail["transcript"] == str(transcript)
    assert detail["mtime"].startswith("20")
    assert recent["sessions"][0]["minutes"] == str(minutes)
    assert recent["sessions"][0]["transcript"] == str(transcript)


def test_status_includes_application_version():
    assert server.Api().get_status()["version"] == server.__version__


def test_delete_session_removes_the_complete_meeting_folder(tmp_path, monkeypatch):
    output = tmp_path / "output"
    session = output / "2026-08-30_0900_删除测试"
    session.mkdir(parents=True)
    minutes = session / server.pipeline_mod.MINUTES_MD
    minutes.write_text("# 删除测试", encoding="utf-8")
    (session / server.pipeline_mod.TRANSCRIPT_MD).write_text("转写", encoding="utf-8")
    (session / "audio.wav").write_bytes(b"RIFF-test")
    (session / "transcript.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(server._state, "cfg", Config(output_dir=str(output)))
    monkeypatch.setattr(server._state, "phase", "idle")
    monkeypatch.setattr(server._state, "session_dir", None)

    result = server.Api().delete_session(str(minutes))

    assert result["ok"] is True
    assert result["deleted"] == str(session)
    assert not session.exists()


def test_delete_session_rejects_nested_or_external_directories(tmp_path, monkeypatch):
    output = tmp_path / "output"
    nested = output / "group" / "meeting"
    nested.mkdir(parents=True)
    minutes = nested / server.pipeline_mod.MINUTES_MD
    minutes.write_text("# 不应删除", encoding="utf-8")
    monkeypatch.setattr(server._state, "cfg", Config(output_dir=str(output)))
    monkeypatch.setattr(server._state, "phase", "idle")

    result = server.Api().delete_session(str(minutes))

    assert result["ok"] is False
    assert "单个会议文件夹" in result["error"]
    assert nested.exists()


def test_list_sessions_returns_more_than_thirty_records(tmp_path, monkeypatch):
    for index in range(35):
        session = tmp_path / f"2026-08-30_{index:04d}"
        session.mkdir()
        (session / server.pipeline_mod.MINUTES_MD).write_text(f"# 会议 {index}", encoding="utf-8")
    monkeypatch.setattr(server._state, "cfg", Config(output_dir=str(tmp_path)))

    result = server.Api().list_sessions()

    assert len(result["sessions"]) == 35
