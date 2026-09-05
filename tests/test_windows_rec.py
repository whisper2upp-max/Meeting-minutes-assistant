import queue
import sys
import threading
import wave
from types import SimpleNamespace

import numpy as np
import pytest

from meetingkit.audio.windows_rec import (
    WindowsMicMonitor,
    WindowsRecorder,
    _convert_monitor_chunk,
    microphone_device_summary,
)


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


def test_live_mic_toggle_writes_silence_without_shifting_system_audio(monkeypatch):
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", SimpleNamespace(
        paContinue=0, paComplete=1))
    recorder = WindowsRecorder()
    mic_queue = queue.SimpleQueue()
    system_queue = queue.SimpleQueue()
    mic_callback = recorder._make_callback(mic_queue, "mic")
    system_callback = recorder._make_callback(system_queue, "system")
    pcm = np.array([1200, -900, 450, -300], dtype=np.int16).tobytes()

    recorder.set_mic_enabled(False)
    mic_callback(pcm, 4, {}, 0)
    system_callback(pcm, 4, {}, 0)

    assert recorder.mic_enabled is False
    assert mic_queue.get() == bytes(len(pcm))
    assert system_queue.get() == pcm

    recorder.set_mic_enabled(True)
    mic_callback(pcm, 4, {}, 0)
    assert recorder.mic_enabled is True
    assert mic_queue.get() == pcm


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

    summary = microphone_device_summary()

    assert summary == {
        "microphones": ["Microphone Array", "USB Headset"],
        "default_microphone": "Microphone Array",
    }
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


def test_monitor_pcm_downmixes_resamples_and_duplicates_output_channels():
    stereo = np.array([[1000, 3000], [3000, 5000]], dtype=np.int16)

    converted = _convert_monitor_chunk(
        stereo.tobytes(), input_channels=2, input_rate=24000,
        output_channels=2, output_rate=48000,
    )
    output = np.frombuffer(converted, dtype=np.int16).reshape(-1, 2)

    assert output.shape == (4, 2)
    assert output[:, 0].tolist() == [2000, 3000, 4000, 4000]
    assert output[:, 1].tolist() == output[:, 0].tolist()


class _MonitorStream(_FakeStream):
    def __init__(self, events, written=None, wrote=None):
        super().__init__(events)
        self.written = written
        self.wrote = wrote

    def write(self, data, exception_on_underflow=True):
        self.events.append("stream.write")
        self.written.append(data)
        self.wrote.set()


class _MonitorInputStream(_FakeStream):
    def __init__(self, events, chunks):
        super().__init__(events)
        self.chunks = chunks
        self.stopped = threading.Event()

    def read(self, frame_count, exception_on_overflow=True):
        while not self.stopped.is_set():
            try:
                return self.chunks.get(timeout=0.05)
            except queue.Empty:
                pass
        return b""

    def stop_stream(self):
        self.stopped.set()
        super().stop_stream()


class _MonitorAudio:
    def __init__(self):
        self.events = []
        self.open_calls = []
        self.chunks = queue.Queue()
        self.written = []
        self.wrote = threading.Event()
        self.devices = [
            {"name": "Laptop Microphone", "index": 5, "hostApi": 2,
             "defaultSampleRate": 24000, "maxInputChannels": 2},
        ]
        self.output = {
            "name": "USB Headphones", "index": 12, "hostApi": 2,
            "defaultSampleRate": 48000, "maxOutputChannels": 2,
        }

    def get_host_api_info_by_type(self, host_type):
        assert host_type == 13
        # 模拟 host 默认索引陈旧；全局默认输出仍正确跟随当前 USB 耳机。
        return {"index": 2, "defaultInputDevice": 5, "defaultOutputDevice": 99}

    def get_device_info_generator(self):
        return iter(self.devices)

    def get_device_info_by_index(self, index):
        assert index == 12
        return self.output

    def get_default_output_device_info(self):
        return self.output

    def open(self, **kwargs):
        self.open_calls.append(kwargs)
        if kwargs.get("output"):
            return _MonitorStream(self.events, self.written, self.wrote)
        return _MonitorInputStream(self.events, self.chunks)

    def terminate(self):
        self.events.append("audio.terminate")


def test_mic_monitor_routes_selected_input_to_current_default_output(monkeypatch):
    audio = _MonitorAudio()
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", SimpleNamespace(
        PyAudio=lambda: audio, paWASAPI=13, paInt16=8,
        paContinue=0, paComplete=1,
    ))
    monitor = WindowsMicMonitor()

    monitor.start()
    samples = np.array([[1000, 3000], [3000, 5000]], dtype=np.int16)
    audio.chunks.put(samples.tobytes())
    assert audio.wrote.wait(timeout=1)

    assert monitor.active is True
    assert monitor.input_name == "Laptop Microphone"
    assert monitor.output_name == "USB Headphones"
    assert audio.open_calls[0] == {
        "format": 8, "channels": 2, "rate": 48000, "output": True,
        "output_device_index": 12, "frames_per_buffer": 1024,
    }
    assert audio.open_calls[1]["input_device_index"] == 5
    assert "stream_callback" not in audio.open_calls[1]
    assert np.frombuffer(audio.written[0], dtype=np.int16).reshape(-1, 2)[:, 0].tolist() == [7000, 10500, 14000, 14000]
    assert monitor.level > 0

    monitor.stop()
    assert monitor.active is False
    assert audio.events[-3:] == ["stream.stop", "stream.close", "audio.terminate"]
