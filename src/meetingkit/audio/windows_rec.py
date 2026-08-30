"""Windows 录音：pyaudiowpatch 的 WASAPI loopback 内录系统声音 + 普通输入流录麦克风。

WASAPI loopback 由系统自带，免驱动、免管理员权限；默认输出设备即可内录。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import List, Optional

from .base import WavTrackWriter, TrackSpec

_BLOCK_FRAMES = 2048


def list_microphones() -> List[str]:
    """可选的麦克风设备名列表。"""
    return [d["name"] for d in _list_input_devices()]


def _list_input_devices() -> List[dict]:
    import pyaudiowpatch as pyaudio
    p = pyaudio.PyAudio()
    try:
        return [d for d in p.get_device_info_generator() if d.get("maxInputChannels", 0) > 0]
    finally:
        p.terminate()


def list_mic_names() -> List[str]:
    return list_microphones()


class WindowsRecorder:
    """系统声音（默认输出 loopback）+ 麦克风，两条单声道轨。"""

    def __init__(self, system_source: str = "", microphone: str = ""):
        self._system_name = system_source
        self._mic_name = microphone
        self._pa = None
        self._streams = []
        self._writers: List[WavTrackWriter] = []
        self._specs: List[TrackSpec] = []
        self._threads: List[threading.Thread] = []
        self._stopped = threading.Event()
        self._open_error: Optional[str] = None

    def _reader_loop(self, stream, writer: WavTrackWriter) -> None:
        while not self._stopped.is_set():
            try:
                data = stream.read(_BLOCK_FRAMES, exception_on_overflow=False)
                writer.write(data[0] if isinstance(data, tuple) else data)
            except OSError as exc:
                if not self._stopped.is_set():
                    self._open_error = f"录音流中断：{exc}"
                break

    def _open_loopback(self, out_dir: Path) -> None:
        import pyaudiowpatch as pyaudio
        dev = None
        if self._system_name:
            for d in self._pa.get_loopback_device_info_generator():
                if d["name"] == self._system_name:
                    dev = d
                    break
        if dev is None:  # 默认输出的 loopback
            try:
                dev = self._pa.get_default_wasapi_loopback()
            except OSError:
                pass
        if dev is None:
            raise RuntimeError(
                "未检测到 Windows 默认输出设备的 WASAPI 回环，无法录制会议内声。"
                "请先在 Windows 声音设置中选择并启用默认输出设备。"
            )
        rate = int(dev["defaultSampleRate"])
        # loopback 流按设备混合格式（通常 2 声道）打开，写入时自动降混单声道
        channels = min(2, int(dev.get("maxInputChannels", 2)) or 2)
        writer = WavTrackWriter(out_dir / "track_system.wav", rate, channels)
        # PyAudioWPatch 把 WASAPI loopback 暴露为可直接读取的虚拟输入设备。
        # 只需打开它的 input_device_index；PyAudio 的 Stream 构造器没有
        # ``as_loopback`` 参数（该参数属于其他音频库的接口）。
        stream = self._pa.open(
            format=pyaudio.paInt16, channels=channels, rate=rate, input=True,
            input_device_index=int(dev["index"]),
            frames_per_buffer=_BLOCK_FRAMES,
        )
        self._streams.append(stream)
        self._writers.append(writer)
        self._specs.append(TrackSpec(writer.path, rate, "system"))
        self._threads.append(threading.Thread(target=self._reader_loop,
                                              args=(stream, writer), daemon=True))

    def _open_mic(self, out_dir: Path) -> None:
        import pyaudiowpatch as pyaudio
        dev_idx = None
        default = self._pa.get_default_input_device_info()
        if self._mic_name:
            for d in _list_input_devices():
                if d["name"] == self._mic_name:
                    dev_idx = int(d["index"])
                    break
        if dev_idx is None and not self._mic_name:
            dev_idx = int(default["index"])
        if dev_idx is None:
            return
        rate = int(self._pa.get_device_info_by_index(dev_idx)["defaultSampleRate"])
        writer = WavTrackWriter(out_dir / "track_mic.wav", rate)
        stream = self._pa.open(
            format=pyaudio.paInt16, channels=1, rate=rate, input=True,
            input_device_index=dev_idx,
            frames_per_buffer=_BLOCK_FRAMES,
        )
        self._streams.append(stream)
        self._writers.append(writer)
        self._specs.append(TrackSpec(writer.path, rate, "mic"))
        self._threads.append(threading.Thread(target=self._reader_loop,
                                              args=(stream, writer), daemon=True))

    def start(self, out_dir: Path) -> None:
        import pyaudiowpatch as pyaudio
        out_dir.mkdir(parents=True, exist_ok=True)
        self._pa = pyaudio.PyAudio()
        try:
            self._open_loopback(out_dir)
            self._open_mic(out_dir)
        except Exception:
            self._cleanup()
            raise
        if not self._streams:
            self._cleanup()
            raise RuntimeError("没有可用的录音设备（loopback 与麦克风都打开失败）")
        for t in self._threads:
            t.start()

    def stop(self) -> List[TrackSpec]:
        if self._stopped.is_set():
            return self._specs
        self._stopped.set()
        for s in self._streams:
            try:
                s.stop_stream()
                s.close()
            except Exception:
                pass
        for t in self._threads:
            t.join(timeout=3)
        self._cleanup()
        return self._specs

    def _cleanup(self) -> None:
        for w in self._writers:
            w.close()
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None

    @property
    def last_errors(self) -> List[str]:
        return [self._open_error] if self._open_error else []
