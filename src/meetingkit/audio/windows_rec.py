"""Windows 录音：pyaudiowpatch 的 WASAPI loopback 内录系统声音 + 普通输入流录麦克风。

WASAPI loopback 由系统自带，免驱动、免管理员权限；默认输出设备即可内录。
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import List, Optional, Tuple

from .base import WavTrackWriter, TrackSpec

_BLOCK_FRAMES = 2048
_QUEUE_STOP = object()


def list_microphones() -> List[str]:
    """可选的麦克风设备名列表（仅真实 WASAPI 输入，按名称去重）。"""
    names: List[str] = []
    seen = set()
    for device in _list_input_devices():
        name = str(device.get("name", "")).strip()
        key = name.casefold()
        if name and key not in seen:
            names.append(name)
            seen.add(key)
    return names


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


def _list_input_devices() -> List[dict]:
    import pyaudiowpatch as pyaudio
    p = pyaudio.PyAudio()
    try:
        _, devices = _wasapi_input_devices(p)
        return devices
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

        host, devices = _wasapi_input_devices(self._pa)
        default_index = int(host.get("defaultInputDevice", -1))
        dev = None
        if self._mic_name:
            matches = [d for d in devices if d["name"] == self._mic_name]
            if matches:
                # 极少数驱动会在同一 WASAPI 主机下重复同名端点；
                # 同名时优先使用 Windows 默认输入。
                dev = next(
                    (d for d in matches if int(d["index"]) == default_index),
                    matches[0],
                )
            else:
                raise RuntimeError(
                    f"未找到已选麦克风“{self._mic_name}”。"
                    "设备可能已拔出，请刷新设备后重新选择。"
                )
        else:
            dev = next(
                (d for d in devices if int(d["index"]) == default_index),
                None,
            )
            if dev is None:
                raise RuntimeError(
                    "未检测到 Windows 默认麦克风。"
                    "请先在 Windows 设置 → 系统 → 声音 中选择默认输入设备。"
                )

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
