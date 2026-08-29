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
