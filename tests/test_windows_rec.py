import sys
import wave
from types import SimpleNamespace

import numpy as np
import pytest

from meetingkit.audio.windows_rec import WindowsRecorder, list_microphones


class _FakeStream:
    def __init__(self, events):
        self.events = events

    def stop_stream(self):
        self.events.append("stream.stop")

    def close(self):
        self.events.append("stream.close")


class _FakeAudio:
    def __init__(self, device=None, devices=None, default_input=-1):
        self.device = device
        self.devices = list(devices or [])
        self.default_input = default_input
        self.open_calls = []
        self.callbacks = []
        self.events = []

    def get_host_api_info_by_type(self, host_type):
        assert host_type == 13
        return {"index": 2, "defaultInputDevice": self.default_input}

    def get_device_info_generator(self):
        return iter(self.devices)

    def get_loopback_device_info_generator(self):
        return iter(())

    def get_default_wasapi_loopback(self):
        if self.device is None:
            raise OSError("no default output")
        return self.device

    def open(self, *, format, channels, rate, input, input_device_index,
             frames_per_buffer, stream_callback):
        self.open_calls.append({
            "format": format,
            "channels": channels,
            "rate": rate,
            "input": input,
            "input_device_index": input_device_index,
            "frames_per_buffer": frames_per_buffer,
        })
        self.callbacks.append(stream_callback)
        return _FakeStream(self.events)

    def terminate(self):
        self.events.append("audio.terminate")


def test_default_wasapi_loopback_opens_system_track(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", SimpleNamespace(
        paInt16=8, paContinue=0, paComplete=1))
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


def test_callback_capture_stops_stream_before_closing_wav(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", SimpleNamespace(
        paInt16=8, paContinue=0, paComplete=1))
    audio = _FakeAudio({
        "name": "Speakers (Company Laptop)",
        "index": 17,
        "defaultSampleRate": 48000,
        "maxInputChannels": 2,
    })
    recorder = WindowsRecorder()
    recorder._pa = audio
    recorder._open_loopback(tmp_path)

    stereo = np.array([[1000, 3000], [2000, 4000]], dtype=np.int16)
    assert audio.callbacks[0](stereo.tobytes(), 2, {}, 0)[1] == 0

    recorder.stop()

    assert audio.events == ["stream.stop", "stream.close", "audio.terminate"]
    with wave.open(str(tmp_path / "track_system.wav"), "rb") as wav:
        samples = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    assert samples.tolist() == [2000, 3000]


def test_missing_default_output_fails_before_mic_only_recording(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", SimpleNamespace(
        paInt16=8, paContinue=0, paComplete=1))
    recorder = WindowsRecorder()
    recorder._pa = _FakeAudio()

    with pytest.raises(RuntimeError, match="无法录制会议内声"):
        recorder._open_loopback(tmp_path)


def test_microphone_list_only_contains_unique_real_wasapi_inputs(monkeypatch):
    devices = [
        {"name": "Microsoft Sound Mapper - Input", "index": 0,
         "hostApi": 0, "maxInputChannels": 2},
        {"name": "Microphone Array", "index": 4,
         "hostApi": 1, "maxInputChannels": 2},
        {"name": "Microphone Array", "index": 8,
         "hostApi": 2, "maxInputChannels": 2},
        {"name": "USB Headset", "index": 9,
         "hostApi": 2, "maxInputChannels": 1},
        {"name": "USB Headset", "index": 10,
         "hostApi": 2, "maxInputChannels": 1},
        {"name": "Speakers [Loopback]", "index": 11,
         "hostApi": 2, "maxInputChannels": 2, "isLoopbackDevice": True},
        {"name": "Speakers", "index": 12,
         "hostApi": 2, "maxInputChannels": 0},
    ]
    audio = _FakeAudio(devices=devices, default_input=8)
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", SimpleNamespace(
        PyAudio=lambda: audio, paWASAPI=13))

    assert list_microphones() == ["Microphone Array", "USB Headset"]
    assert audio.events == ["audio.terminate"]


def test_default_mic_uses_wasapi_default_and_supported_channels(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", SimpleNamespace(
        paInt16=8, paContinue=0, paComplete=1, paWASAPI=13))
    devices = [
        {"name": "Legacy default", "index": 1,
         "hostApi": 0, "defaultSampleRate": 44100, "maxInputChannels": 1},
        {"name": "Microphone Array", "index": 8,
         "hostApi": 2, "defaultSampleRate": 48000, "maxInputChannels": 2},
    ]
    audio = _FakeAudio(devices=devices, default_input=8)
    recorder = WindowsRecorder()
    recorder._pa = audio

    recorder._open_mic(tmp_path)

    assert [spec.label for spec in recorder._specs] == ["mic"]
    assert audio.open_calls == [{
        "format": 8,
        "channels": 2,
        "rate": 48000,
        "input": True,
        "input_device_index": 8,
        "frames_per_buffer": 2048,
    }]
    recorder._cleanup()


def test_named_mic_ignores_legacy_duplicate(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", SimpleNamespace(
        paInt16=8, paContinue=0, paComplete=1, paWASAPI=13))
    devices = [
        {"name": "USB Microphone", "index": 3,
         "hostApi": 0, "defaultSampleRate": 44100, "maxInputChannels": 1},
        {"name": "USB Microphone", "index": 14,
         "hostApi": 2, "defaultSampleRate": 48000, "maxInputChannels": 1},
    ]
    audio = _FakeAudio(devices=devices, default_input=14)
    recorder = WindowsRecorder(microphone="USB Microphone")
    recorder._pa = audio

    recorder._open_mic(tmp_path)

    assert audio.open_calls[0]["input_device_index"] == 14
    recorder._cleanup()


def test_missing_named_mic_reports_actionable_error(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", SimpleNamespace(
        paInt16=8, paContinue=0, paComplete=1, paWASAPI=13))
    audio = _FakeAudio(devices=[], default_input=-1)
    recorder = WindowsRecorder(microphone="Disconnected microphone")
    recorder._pa = audio

    with pytest.raises(RuntimeError, match="设备可能已拔出"):
        recorder._open_mic(tmp_path)
