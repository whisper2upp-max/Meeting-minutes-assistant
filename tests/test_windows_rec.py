import sys
from types import SimpleNamespace

import pytest

from meetingkit.audio.windows_rec import WindowsRecorder


class _FakeStream:
    pass


class _FakeAudio:
    def __init__(self, device=None):
        self.device = device
        self.open_calls = []

    def get_loopback_device_info_generator(self):
        return iter(())

    def get_default_wasapi_loopback(self):
        if self.device is None:
            raise OSError("no default output")
        return self.device

    def open(self, *, format, channels, rate, input, input_device_index,
             frames_per_buffer):
        self.open_calls.append({
            "format": format,
            "channels": channels,
            "rate": rate,
            "input": input,
            "input_device_index": input_device_index,
            "frames_per_buffer": frames_per_buffer,
        })
        return _FakeStream()


def test_default_wasapi_loopback_opens_system_track(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", SimpleNamespace(paInt16=8))
    audio = _FakeAudio({
        "name": "Speakers (Company Laptop)",
        "index": 17,
        "defaultSampleRate": 48000,
        "maxInputChannels": 2,
    })
    recorder = WindowsRecorder()
    recorder._pa = audio

    recorder._open_loopback(tmp_path)

    assert [spec.label for spec in recorder._specs] == ["system"]
    assert audio.open_calls == [{
        "format": 8,
        "channels": 2,
        "rate": 48000,
        "input": True,
        "input_device_index": 17,
        "frames_per_buffer": 2048,
    }]
    recorder._cleanup()


def test_missing_default_output_fails_before_mic_only_recording(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", SimpleNamespace(paInt16=8))
    recorder = WindowsRecorder()
    recorder._pa = _FakeAudio()

    with pytest.raises(RuntimeError, match="无法录制会议内声"):
        recorder._open_loopback(tmp_path)
