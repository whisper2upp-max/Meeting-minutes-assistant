import json
from datetime import datetime
from pathlib import Path

import numpy as np

from meetingkit.audio.base import write_wav_mono
from meetingkit.config import Config
from meetingkit.pipeline import (AUDIO_WAV, MINUTES_MD, TRANSCRIPT_JSON,
                                 TRANSCRIPT_MD, new_session_dir, prepare_audio,
                                 run_pipeline)


def _make_wav(path: Path, seconds: float = 1.0, sr: int = 48000):
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    write_wav_mono(path, (0.3 * np.sin(2 * np.pi * 300 * t)).astype(np.float32), sr)


def _fake_transcribe(audio_path, *, api_key, model, diarization,
                     disfluency_removal, base_url="", progress=None, _counter=[0]):
    _counter[0] += 1
    return {"sentences": [
        {"begin_ms": 0, "end_ms": 1500, "text": "大家好。", "speaker_id": 0},
        {"begin_ms": 1600, "end_ms": 3000, "text": "今天同步进度。", "speaker_id": 1},
        {"begin_ms": 3100, "end_ms": 4000, "text": "好的。", "speaker_id": 1},
    ], "raw": {}}


def _fake_minutes(transcript_md, *, api_key, model, attendees,
                  meeting_title, started_at, base_url="", progress=None, _counter=[0]):
    _counter[0] += 1
    return f"# 会议纪要\n\n来自：{transcript_md[:20]}…\n"


def test_prepare_audio_converts_to_16k_mono(tmp_path):
    src = tmp_path / "src.wav"
    _make_wav(src, sr=48000)
    out = prepare_audio(src, tmp_path / "session")
    import wave
    with wave.open(str(out), "rb") as fh:
        assert fh.getframerate() == 16000
        assert fh.getnchannels() == 1


def test_prepare_audio_copies_non_wav(tmp_path):
    src = tmp_path / "rec.mp3"
    src.write_bytes(b"\x00" * 64)
    out = prepare_audio(src, tmp_path / "session")
    assert out.read_bytes() == src.read_bytes()


def test_session_dir_unique_and_sanitized(tmp_path):
    a = new_session_dir(tmp_path, '周会/同步:进度')
    b = new_session_dir(tmp_path, "周会同步进度")
    assert a.exists() and b.exists()
    assert "/" not in a.name and ":" not in a.name


def test_run_pipeline_full_and_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("MEETINGKIT_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    cfg = Config(api_key="sk-test", attendees=["张三"],
                 output_dir=str(tmp_path / "out"))
    src = tmp_path / "meeting.wav"
    _make_wav(src, sr=44100)

    t_counter = [0]
    m_counter = [0]

    def t_fn(*a, **k):
        t_counter[0] += 1
        return _fake_transcribe(*a, **k)

    def m_fn(*a, **k):
        m_counter[0] += 1
        return _fake_minutes(*a, **k)

    session = new_session_dir(cfg.resolved_output_dir(), "测试会")
    minutes = run_pipeline(src, cfg, session_dir=session, title="测试会",
                           transcribe_fn=t_fn, minutes_fn=m_fn)
    assert minutes.exists()
    assert (session / AUDIO_WAV).exists()
    assert (session / TRANSCRIPT_JSON).exists()
    assert (session / TRANSCRIPT_MD).exists()
    tmd = (session / TRANSCRIPT_MD).read_text(encoding="utf-8")
    assert "说话人1" in tmd and "说话人2" in tmd
    # 同一说话人连续发言被合并
    assert tmd.count("说话人2") == 1

    # 第二次运行：全部命中缓存，云端调用不增加
    run_pipeline(src, cfg, session_dir=session, title="测试会",
                 transcribe_fn=t_fn, minutes_fn=m_fn)
    assert t_counter[0] == 1
    assert m_counter[0] == 1


def test_run_pipeline_requires_api_key(tmp_path, monkeypatch):
    monkeypatch.setenv("MEETINGKIT_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    cfg = Config(output_dir=str(tmp_path / "out"))
    src = tmp_path / "m.wav"
    _make_wav(src)
    try:
        run_pipeline(src, cfg, session_dir=tmp_path / "s",
                     transcribe_fn=_fake_transcribe, minutes_fn=_fake_minutes)
        assert False, "缺少 API Key 应报错"
    except RuntimeError as e:
        assert "API Key" in str(e)
