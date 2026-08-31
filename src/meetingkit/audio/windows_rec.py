"""Windows 录音：pyaudiowpatch 的 WASAPI loopback 内录系统声音 + 普通输入流录麦克风。

WASAPI loopback 由系统自带，免驱动、免管理员权限；默认输出设备即可内录。
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from .base import WavTrackWriter, TrackSpec

_BLOCK_FRAMES = 2048
_MONITOR_FRAMES = 1024
_MONITOR_GAIN = 3.5
_QUEUE_STOP = object()


def _unique_microphone_names(devices: List[dict]) -> List[str]:
    names: List[str] = []
    seen = set()
    for device in devices:
        name = str(device.get("name", "")).strip()
        key = name.casefold()
        if name and key not in seen:
            names.append(name)
            seen.add(key)
    return names


def microphone_device_summary() -> dict:
    """返回真实 WASAPI 麦克风列表和当前 Windows 默认麦克风名称。"""
    import pyaudiowpatch as pyaudio

    p = pyaudio.PyAudio()
    try:
        host, devices = _wasapi_input_devices(p)
        default_index = int(host.get("defaultInputDevice", -1))
        default = next(
            (device for device in devices
             if int(device.get("index", -1)) == default_index),
            None,
        )
        return {
            "microphones": _unique_microphone_names(devices),
            "default_microphone": str(default.get("name", "")).strip() if default else "",
        }
    finally:
        p.terminate()


def list_microphones() -> List[str]:
    """可选的麦克风设备名列表（仅真实 WASAPI 输入，按名称去重）。"""
    return microphone_device_summary()["microphones"]


def _wasapi_input_devices(p) -> Tuple[dict, List[dict]]:
    """返回 WASAPI 主机信息和真实的麦克风端点。

    PyAudioWPatch 会同时暴露 MME、DirectSound、WASAPI 以及 loopback
    端点。如果全部放入麦克风列表，同一物理设备会重复出现，
    还可能选中输出回环或旧的 Sound Mapper 端点。
    """
    import pyaudiowpatch as pyaudio

    try:
        host = p.get_host_api_info_by_type(pyaudio.paWASAPI)
    except OSError as exc:
        raise RuntimeError(
            "未检测到 Windows WASAPI 音频主机，无法录制麦克风。"
        ) from exc

    host_index = int(host["index"])
    devices = []
    for device in p.get_device_info_generator():
        if int(device.get("hostApi", -1)) != host_index:
            continue
        if int(device.get("maxInputChannels", 0)) <= 0:
            continue
        if bool(device.get("isLoopbackDevice", False)):
            continue
        if not str(device.get("name", "")).strip():
            continue
        devices.append(device)
    return host, devices


def list_mic_names() -> List[str]:
    return list_microphones()


def _resolve_microphone(p, microphone: str = "") -> Tuple[dict, dict]:
    """按界面选择解析 WASAPI 麦克风；空字符串表示当前系统默认。"""
    host, devices = _wasapi_input_devices(p)
    default_index = int(host.get("defaultInputDevice", -1))
    if microphone:
        matches = [device for device in devices if device["name"] == microphone]
        if not matches:
            raise RuntimeError(
                f"未找到已选麦克风“{microphone}”。"
                "设备可能已拔出，请刷新设备后重新选择。"
            )
        device = next(
            (item for item in matches if int(item["index"]) == default_index),
            matches[0],
        )
        return host, device

    device = next(
        (item for item in devices if int(item["index"]) == default_index),
        None,
    )
    if device is None:
        raise RuntimeError(
            "未检测到 Windows 默认麦克风。"
            "请先在 Windows 设置 → 系统 → 声音 中选择默认输入设备。"
        )
    return host, device


def _default_output_device(p, host: dict) -> dict:
    """解析当前 WASAPI 默认播放端点，用于把测试声音送到耳机/扬声器。"""
    # PortAudio 的全局默认输出会跟随 Windows 当前选择（插入耳机后通常会
    # 自动切换），优先使用它。旧版只读取 WASAPI host 的默认索引，在部分
    # 驱动上该索引不会随 Windows 的通讯/多媒体默认端点同步，测试流虽然
    # 成功启动，声音却会被送往没有在使用的端点。
    device = None
    try:
        candidate = p.get_default_output_device_info()
        if int(candidate.get("maxOutputChannels", 0)) > 0:
            device = candidate
    except Exception:
        pass
    if device is not None:
        return device

    default_index = int(host.get("defaultOutputDevice", -1))
    if default_index < 0:
        raise RuntimeError(
            "未检测到 Windows 默认播放设备。请先连接扬声器或耳机并设为默认输出。"
        )
    try:
        device = p.get_device_info_by_index(default_index)
    except Exception as exc:
        raise RuntimeError(
            "无法读取 Windows 默认播放设备，请在声音设置中重新选择输出设备。"
        ) from exc
    if int(device.get("maxOutputChannels", 0)) <= 0:
        raise RuntimeError("Windows 默认播放端点不可用，请重新选择扬声器或耳机。")
    return device


def _convert_monitor_chunk(data: bytes, input_channels: int, input_rate: int,
                           output_channels: int, output_rate: int,
                           gain: float = 1.0) -> bytes:
    """把麦克风 PCM 安全转换为默认播放设备的声道数与采样率。"""
    samples = np.frombuffer(data, dtype=np.int16)
    usable = samples.size - (samples.size % input_channels)
    if usable <= 0:
        return b""
    frames = samples[:usable].reshape(-1, input_channels).astype(np.float32)
    mono = frames.mean(axis=1)
    if input_rate != output_rate and mono.size > 1:
        frame_count = max(1, int(round(mono.size * output_rate / input_rate)))
        source_positions = np.arange(frame_count, dtype=np.float64) * input_rate / output_rate
        source_positions = np.minimum(source_positions, mono.size - 1)
        mono = np.interp(source_positions, np.arange(mono.size), mono)
    converted = np.clip(np.rint(mono * max(0.0, float(gain))), -32768, 32767).astype(np.int16)
    if output_channels > 1:
        converted = np.repeat(converted[:, None], output_channels, axis=1).reshape(-1)
    return converted.tobytes()


def _monitor_level(data: bytes, channels: int) -> float:
    """返回适合界面音量条的 0..1 麦克风电平。"""
    samples = np.frombuffer(data, dtype=np.int16)
    usable = samples.size - (samples.size % max(1, channels))
    if usable <= 0:
        return 0.0
    frames = samples[:usable].reshape(-1, max(1, channels)).astype(np.float32)
    mono = frames.mean(axis=1)
    rms = float(np.sqrt(np.mean(np.square(mono)))) if mono.size else 0.0
    # 约 -35 dBFS 开始可见，正常说话在音量条中段，避免低电平看起来始终为 0。
    return min(1.0, rms / 6000.0)


class WindowsMicMonitor:
    """将选中麦克风低延迟回放到当前 Windows 默认扬声器/耳机。"""

    def __init__(self, microphone: str = ""):
        self._microphone = microphone
        self._pa = None
        self._input_stream = None
        self._output_stream = None
        self._worker: Optional[threading.Thread] = None
        self._stopped = threading.Event()
        self._active = threading.Event()
        self._cleanup_lock = threading.Lock()
        self._error: Optional[str] = None
        self._level = 0.0
        self._input_channels = 1
        self._input_rate = 48000
        self._output_channels = 2
        self._output_rate = 48000
        self.input_name = ""
        self.output_name = ""

    def _playback_loop(self) -> None:
        try:
            while not self._stopped.is_set():
                input_stream = self._input_stream
                if input_stream is None:
                    return
                try:
                    data = input_stream.read(
                        _MONITOR_FRAMES,
                        exception_on_overflow=False,
                    )
                except Exception:
                    if self._stopped.is_set():
                        return
                    raise
                self._level = _monitor_level(data, self._input_channels)
                converted = _convert_monitor_chunk(
                    data,
                    self._input_channels,
                    self._input_rate,
                    self._output_channels,
                    self._output_rate,
                    gain=_MONITOR_GAIN,
                )
                if converted and self._output_stream is not None:
                    self._output_stream.write(converted, exception_on_underflow=False)
        except Exception as exc:
            self._error = f"麦克风测试播放中断：{exc}"
            self._stopped.set()
        finally:
            self._level = 0.0
            self._active.clear()

    def start(self) -> None:
        import pyaudiowpatch as pyaudio

        if self.active:
            return
        self._stopped.clear()
        self._error = None
        self._pa = pyaudio.PyAudio()
        try:
            host, mic = _resolve_microphone(self._pa, self._microphone)
            output = _default_output_device(self._pa, host)
            self._input_channels = min(2, int(mic.get("maxInputChannels", 1)) or 1)
            self._input_rate = int(mic["defaultSampleRate"])
            self._output_channels = min(2, int(output.get("maxOutputChannels", 2)) or 2)
            self._output_rate = int(output["defaultSampleRate"])
            self.input_name = str(mic.get("name", "麦克风"))
            self.output_name = str(output.get("name", "默认播放设备"))

            self._output_stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=self._output_channels,
                rate=self._output_rate,
                output=True,
                output_device_index=int(output["index"]),
                frames_per_buffer=_MONITOR_FRAMES,
            )
            self._input_stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=self._input_channels,
                rate=self._input_rate,
                input=True,
                input_device_index=int(mic["index"]),
                frames_per_buffer=_MONITOR_FRAMES,
            )
            self._active.set()
            self._worker = threading.Thread(target=self._playback_loop, daemon=True)
            self._worker.start()
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        with self._cleanup_lock:
            self._stopped.set()
            self._active.clear()
            self._level = 0.0

            input_stream = self._input_stream
            if input_stream is not None:
                try:
                    input_stream.stop_stream()
                except Exception:
                    pass

            worker, self._worker = self._worker, None
            if worker is not None and worker is not threading.current_thread():
                worker.join(timeout=2)

            self._input_stream = None
            if input_stream is not None:
                try:
                    input_stream.close()
                except Exception:
                    pass

            output_stream, self._output_stream = self._output_stream, None
            if output_stream is not None:
                try:
                    output_stream.stop_stream()
                except Exception:
                    pass
                try:
                    output_stream.close()
                except Exception:
                    pass

            if self._pa is not None:
                try:
                    self._pa.terminate()
                except Exception:
                    pass
                self._pa = None

    @property
    def active(self) -> bool:
        return self._active.is_set() and not self._stopped.is_set()

    @property
    def last_error(self) -> Optional[str]:
        return self._error

    @property
    def level(self) -> float:
        return self._level if self.active else 0.0


class WindowsRecorder:
    """系统声音（默认输出 loopback）+ 麦克风，两条单声道轨。"""

    def __init__(self, system_source: str = "", microphone: str = ""):
        self._system_name = system_source
        self._mic_name = microphone
        self._pa = None
        self._streams = []
        self._writers: List[WavTrackWriter] = []
        self._specs: List[TrackSpec] = []
        self._queues: List[queue.SimpleQueue] = []
        self._threads: List[threading.Thread] = []
        self._stopped = threading.Event()
        self._open_error: Optional[str] = None

    def _make_callback(self, audio_queue: queue.SimpleQueue):
        import pyaudiowpatch as pyaudio

        def _callback(in_data, frame_count, time_info, status_flags):
            if status_flags and not self._stopped.is_set():
                self._open_error = f"录音流状态异常：{status_flags}"
            if self._stopped.is_set():
                return in_data, pyaudio.paComplete
            audio_queue.put(in_data)
            return in_data, pyaudio.paContinue

        return _callback

    @staticmethod
    def _writer_loop(audio_queue: queue.SimpleQueue,
                     writer: WavTrackWriter) -> None:
        while True:
            data = audio_queue.get()
            if data is _QUEUE_STOP:
                return
            writer.write(data)

    def _register_stream(self, stream, writer: WavTrackWriter,
                         spec: TrackSpec,
                         audio_queue: queue.SimpleQueue) -> None:
        self._streams.append(stream)
        self._writers.append(writer)
        self._specs.append(spec)
        self._queues.append(audio_queue)
        thread = threading.Thread(
            target=self._writer_loop,
            args=(audio_queue, writer),
            daemon=True,
        )
        self._threads.append(thread)
        thread.start()

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
        audio_queue = queue.SimpleQueue()
        # PyAudioWPatch 把 WASAPI loopback 暴露为可直接读取的虚拟输入设备。
        # 只需打开它的 input_device_index；PyAudio 的 Stream 构造器没有
        # ``as_loopback`` 参数（该参数属于其他音频库的接口）。
        try:
            stream = self._pa.open(
                format=pyaudio.paInt16, channels=channels, rate=rate, input=True,
                input_device_index=int(dev["index"]),
                frames_per_buffer=_BLOCK_FRAMES,
                stream_callback=self._make_callback(audio_queue),
            )
        except Exception:
            writer.close()
            raise
        self._register_stream(
            stream, writer, TrackSpec(writer.path, rate, "system"), audio_queue)

    def _open_mic(self, out_dir: Path) -> None:
        import pyaudiowpatch as pyaudio

        _, dev = _resolve_microphone(self._pa, self._mic_name)

        dev_idx = int(dev["index"])
        rate = int(dev["defaultSampleRate"])
        # 某些 Windows 麦克风阵列的 WASAPI 混音格式只接受双声道。
        # 按设备支持的声道打开，WavTrackWriter 再安全降混为单声道。
        channels = min(2, int(dev.get("maxInputChannels", 1)) or 1)
        writer = WavTrackWriter(out_dir / "track_mic.wav", rate, channels)
        audio_queue = queue.SimpleQueue()
        try:
            stream = self._pa.open(
                format=pyaudio.paInt16, channels=channels, rate=rate, input=True,
                input_device_index=dev_idx,
                frames_per_buffer=_BLOCK_FRAMES,
                stream_callback=self._make_callback(audio_queue),
            )
        except Exception:
            writer.close()
            raise
        self._register_stream(
            stream, writer, TrackSpec(writer.path, rate, "mic"), audio_queue)

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

    def stop(self) -> List[TrackSpec]:
        if self._stopped.is_set():
            return self._specs
        self._stopped.set()
        self._cleanup()
        return self._specs

    def _cleanup(self) -> None:
        # PyAudio 的回调运行在原生音频线程中。必须先停止并关闭全部流，
        # 确认不会再产生回调，再结束 Python 写盘线程；不能在另一个线程
        # 阻塞于 stream.read() 时关闭同一个原生流。
        streams, self._streams = self._streams, []
        for stream in streams:
            try:
                stream.stop_stream()
            except Exception:
                pass
            try:
                stream.close()
            except Exception:
                pass

        queues, self._queues = self._queues, []
        for audio_queue in queues:
            audio_queue.put(_QUEUE_STOP)

        threads, self._threads = self._threads, []
        for thread in threads:
            thread.join()

        writers, self._writers = self._writers, []
        for writer in writers:
            writer.close()
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None

    @property
    def last_errors(self) -> List[str]:
        return [self._open_error] if self._open_error else []
