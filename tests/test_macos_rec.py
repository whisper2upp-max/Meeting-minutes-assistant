import numpy as np
import pytest

from meetingkit.audio.macos_rec import MacRecorder


class _FakeInputStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.started = False
        self.closed = False

    def start(self):
        self.started = True

    def stop(self):
        pass

    def close(self):
        self.closed = True


def test_open_default_microphone_queries_default_input(tmp_path, monkeypatch):
    """空麦克风配置应解析系统默认输入，不能把全部设备列表当单个设备。"""
    query_calls = []
    streams = []

    def fake_query_devices(device=None, kind=None):
        query_calls.append((device, kind))
        if kind != "input":
            raise AssertionError("查询默认设备时必须明确指定 input")
        return {"name": "系统默认麦克风", "default_samplerate": 48000}

    def fake_input_stream(**kwargs):
        stream = _FakeInputStream(**kwargs)
        streams.append(stream)
        return stream

    monkeypatch.setattr("meetingkit.audio.macos_rec.sd.query_devices", fake_query_devices)
    monkeypatch.setattr("meetingkit.audio.macos_rec.sd.InputStream", fake_input_stream)

    recorder = MacRecorder()
    writer = recorder._open(None, "mic", tmp_path)

    assert query_calls == [(None, "input")]
    assert streams[0].kwargs["device"] is None
    assert streams[0].kwargs["samplerate"] == 48000
    assert streams[0].started
    assert writer.sample_rate == 48000
    recorder.stop()
    assert streams[0].closed


def test_failed_stream_start_releases_retry_resources(tmp_path, monkeypatch):
    class FailingInputStream(_FakeInputStream):
        def start(self):
            raise RuntimeError("permission pending")

    monkeypatch.setattr(
        "meetingkit.audio.macos_rec.sd.query_devices",
        lambda device, kind: {"name": "系统默认麦克风", "default_samplerate": 48000},
    )
    stream = FailingInputStream()
    monkeypatch.setattr(
        "meetingkit.audio.macos_rec.sd.InputStream", lambda **kwargs: stream
    )

    recorder = MacRecorder()
    with pytest.raises(RuntimeError, match="permission pending"):
        recorder._open(None, "mic", tmp_path)

    assert stream.closed
    assert recorder._streams == []
    assert recorder._writers == []


def test_live_mic_toggle_writes_silence_and_keeps_system_callback_live():
    class Writer:
        def __init__(self):
            self.chunks = []

        def write(self, data):
            self.chunks.append(data)

    recorder = MacRecorder()
    mic_writer = Writer()
    system_writer = Writer()
    mic_callback = recorder._make_callback(mic_writer, "mic")
    system_callback = recorder._make_callback(system_writer, "system")
    pcm = np.array([1300, -700, 200], dtype=np.int16)

    recorder.set_mic_enabled(False)
    mic_callback(pcm, len(pcm), {}, None)
    system_callback(pcm, len(pcm), {}, None)

    assert recorder.mic_enabled is False
    assert mic_writer.chunks == [bytes(pcm.nbytes)]
    assert system_writer.chunks == [pcm.tobytes()]

    recorder.set_mic_enabled(True)
    mic_callback(pcm, len(pcm), {}, None)
    assert recorder.mic_enabled is True
    assert mic_writer.chunks[-1] == pcm.tobytes()
