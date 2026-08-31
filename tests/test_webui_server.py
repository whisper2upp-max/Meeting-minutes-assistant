import json
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


def test_speaker_mapping_uses_samples_and_regenerates_transcript(tmp_path, monkeypatch):
    session = tmp_path / "2026-08-31_0900_复盘会"
    session.mkdir()
    minutes = session / server.pipeline_mod.MINUTES_MD
    transcript_json = session / server.pipeline_mod.TRANSCRIPT_JSON
    transcript_md = session / server.pipeline_mod.TRANSCRIPT_MD
    minutes.write_text("# 复盘会\n\n- 说话人1确认上线\n- 说话人2负责验收\n", encoding="utf-8")
    transcript_json.write_text(json.dumps({
        "sentences": [
            {"begin_ms": 0, "end_ms": 1000, "text": "我来确认上线。", "speaker_id": 0},
            {"begin_ms": 1200, "end_ms": 2200, "text": "我负责验收。", "speaker_id": 1},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    transcript_md.write_text("旧转写", encoding="utf-8")
    monkeypatch.setattr(server._state, "cfg", Config(output_dir=str(tmp_path)))
    monkeypatch.setattr(server._state, "meeting_attendees", ["张三", "李四"])
    monkeypatch.setattr(server._state, "session_dir", session)

    detail = server.Api().get_speaker_mapping(str(minutes))
    saved = server.Api().save_speaker_mapping(str(minutes), {"1": "张三", "2": "李四"})

    assert detail["ok"] is True
    assert detail["speakers"] == [
        {"number": 1, "label": "说话人1", "sample": "我来确认上线。"},
        {"number": 2, "label": "说话人2", "sample": "我负责验收。"},
    ]
    assert detail["candidates"] == ["张三", "李四"]
    assert saved["ok"] is True
    assert saved["mapping"] == {"1": "张三", "2": "李四"}
    assert "**张三**" in transcript_md.read_text(encoding="utf-8")
    assert "**李四**" in transcript_md.read_text(encoding="utf-8")
    stored = json.loads((session / server.pipeline_mod.SPEAKER_MAP_JSON).read_text(encoding="utf-8"))
    assert stored["speakers"] == {"1": "张三", "2": "李四"}
    # 后端不重写用户纪要正文；前端仅替换仍存在的“说话人N”标签后再正常保存。
    assert "说话人1" in minutes.read_text(encoding="utf-8")


def test_speaker_mapping_rejects_unknown_speaker(tmp_path, monkeypatch):
    session = tmp_path / "2026-08-31_1000"
    session.mkdir()
    minutes = session / server.pipeline_mod.MINUTES_MD
    minutes.write_text("# 测试", encoding="utf-8")
    (session / server.pipeline_mod.TRANSCRIPT_JSON).write_text(json.dumps({
        "sentences": [{"begin_ms": 0, "end_ms": 1, "text": "你好", "speaker_id": 0}],
    }), encoding="utf-8")
    monkeypatch.setattr(server._state, "cfg", Config(output_dir=str(tmp_path)))

    result = server.Api().save_speaker_mapping(str(minutes), {"3": "不存在"})

    assert result["ok"] is False
    assert "不存在说话人3" in result["error"]


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


def test_windows_reveal_opens_directory_itself_instead_of_selecting_parent(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(server.sys, "platform", "win32")
    monkeypatch.setattr(server.subprocess, "Popen", lambda args: calls.append(args))

    server._reveal(tmp_path)

    assert calls == [["explorer.exe", str(tmp_path)]]


def test_windows_reveal_selects_a_file_when_requested(tmp_path, monkeypatch):
    minutes = tmp_path / "会议纪要.md"
    minutes.write_text("# 测试", encoding="utf-8")
    calls = []
    monkeypatch.setattr(server.sys, "platform", "win32")
    monkeypatch.setattr(server.subprocess, "Popen", lambda args: calls.append(args))

    server._reveal(tmp_path, select=minutes)

    assert calls == [["explorer.exe", f"/select,{minutes}"]]


def test_open_output_dir_uses_the_configured_custom_path(tmp_path, monkeypatch):
    custom = tmp_path / "Company Meetings"
    opened = []
    monkeypatch.setattr(server._state, "cfg", Config(output_dir=str(custom)))
    monkeypatch.setattr(server, "_reveal", lambda path, select=None: opened.append(path))

    result = server.Api().open_output_dir()

    assert result == {"ok": True, "path": str(custom.resolve())}
    assert opened == [custom.resolve()]


class _FakeMicMonitor:
    def __init__(self):
        self.active = False
        self.last_error = None
        self.input_name = "USB Headset Mic"
        self.output_name = "USB Headset"
        self.level = 0.42
        self.stopped = False

    def start(self):
        self.active = True

    def stop(self):
        self.active = False
        self.stopped = True


def test_mic_test_lifecycle_is_exposed_in_status(monkeypatch):
    monitor = _FakeMicMonitor()
    monkeypatch.setattr(server, "IS_WINDOWS", True)
    monkeypatch.setattr(server._state, "phase", "idle")
    monkeypatch.setattr(server._state, "mic_monitor", None)
    monkeypatch.setattr(server.audio_mod, "get_mic_monitor", lambda microphone: monitor)

    started = server.Api().start_mic_test("USB Headset Mic")
    status = server.Api().get_status()
    stopped = server.Api().stop_mic_test()

    assert started == {"ok": True, "input": "USB Headset Mic", "output": "USB Headset"}
    assert status["mic_test_active"] is True
    assert status["mic_test_input"] == "USB Headset Mic"
    assert status["mic_test_output"] == "USB Headset"
    assert status["mic_test_level"] == 0.42
    assert stopped["ok"] is True
    assert monitor.stopped is True
