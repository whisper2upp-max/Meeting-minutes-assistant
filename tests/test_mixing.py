import math
import wave
from pathlib import Path

import numpy as np

from meetingkit.audio.base import (
    TARGET_SAMPLE_RATE, WavTrackWriter, mix_tracks_to_mono, read_wav_mono,
    resample, rms_normalize, write_wav_mono,
)


def _sin(seconds: float, sr: int, freq: float = 440.0, amp: float = 0.5) -> np.ndarray:
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def test_resample_changes_length_proportionally():
    x = _sin(2.0, 48000)
    y = resample(x, 48000, 16000)
    assert abs(len(y) - 32000) <= 2
    y2 = resample(x, 48000, 48000)
    assert len(y2) == len(x)


def test_rms_normalize_hits_target_and_caps_peak():
    x = _sin(1.0, 16000, amp=0.01)
    y = rms_normalize(x, target_dbfs=-20.0)
    rms = float(np.sqrt(np.mean(np.square(y))))
    assert abs(20 * math.log10(rms) - (-20.0)) < 0.5
    assert float(np.max(np.abs(y))) <= 0.98


def test_rms_normalize_keeps_silent_track():
    x = np.zeros(1600, dtype=np.float32)
    assert np.array_equal(rms_normalize(x), x)


def test_wav_writer_downmixes_stereo():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.wav"
        w = WavTrackWriter(p, 48000, channels=2)
        # 2 声道交错：左 10000、右 -10000 -> 平均为 0
        inter = np.array([10000, -10000] * 100, dtype=np.int16)
        w.write(inter.tobytes())
        w.close()
        x, sr = read_wav_mono(p)
        assert sr == 48000
        assert len(x) == 100
        assert float(np.max(np.abs(x))) < 0.01


def test_wav_roundtrip_mono():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "t.wav"
        x = _sin(1.0, 16000)
        write_wav_mono(p, x, 16000)
        y, sr = read_wav_mono(p)
        assert sr == 16000
        assert len(y) == len(x)
        assert float(np.max(np.abs(y - x))) < 0.01


def test_mix_tracks_normalizes_and_averages():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        d = Path(d)
        loud = d / "loud.wav"
        quiet = d / "quiet.wav"
        write_wav_mono(loud, _sin(2.0, 48000, amp=0.9), 48000)   # 大声的“远端”
        write_wav_mono(quiet, _sin(2.0, 44100, amp=0.02), 44100)  # 小声的“麦克风”
        out = d / "mixed.wav"
        dur = mix_tracks_to_mono(
            [type("S", (), {"path": loud, "sample_rate": 48000, "label": "system"})(),
             type("S", (), {"path": quiet, "sample_rate": 44100, "label": "mic"})()],
            out)
        assert abs(dur - 2.0) < 0.1
        with wave.open(str(out), "rb") as fh:
            assert fh.getnchannels() == 1
            assert fh.getframerate() == TARGET_SAMPLE_RATE
        x, _ = read_wav_mono(out)
        # 两轨各自归一后平均，能量应明显高于直接混合“小声轨”的水平
        rms = float(np.sqrt(np.mean(np.square(x))))
        assert rms > 0.02
