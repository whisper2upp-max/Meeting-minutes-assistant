"""macOS 录音：sounddevice（PortAudio）采集 BlackHole（系统声音）与麦克风。

系统内录依赖一次性配置（详见 docs/使用说明-macOS.md）：
安装 BlackHole 2ch 后，在"音频 MIDI 设置"里建一个"多输出设备"
（耳机 + BlackHole）并设为系统输出，程序录制 BlackHole 输入即可拿到会议声音。
"""

from __future__ import annotations

import queue
import threading
import time
from pathlib import Path
from typing import List, Optional, Tuple

import sounddevice as sd

from .base import WavTrackWriter, TrackSpec

_LOOPBACK_KEYWORDS = ("blackhole", "loopback", "soundflower", "aggregate", "录屏")


def list_microphones() -> List[str]:
    return [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0]


def list_loopback_sources() -> List[str]:
    """可当作"系统声音"录制的虚拟输入设备。"""
    names = []
    for d in sd.query_devices():
        if d["max_input_channels"] > 0 and any(
                k in d["name"].lower() for k in _LOOPBACK_KEYWORDS):
            names.append(d["name"])
    return names


def _resolve_device(name: str) -> Optional[int]:
    if not name:
        return None
    for i, d in enumerate(sd.query_devices()):
        if d["name"] == name:
            return i
    return None


class MacRecorder:
    """同时录制系统声音（BlackHole）与麦克风两条单声道轨。"""

    def __init__(self, system_source: str = "", microphone: str = ""):
        self._system_name = system_source
        self._mic_name = microphone
        self._streams: List[sd.InputStream] = []
        self._writers: List[WavTrackWriter] = []
        self._specs: List[TrackSpec] = []
        self._errors: List[str] = []
        self._stopped = threading.Event()

    def _make_callback(self, writer: WavTrackWriter):
        def _cb(indata, frames, time_info, status) -> None:
            if status:
                self._errors.append(str(status))
            writer.write(indata.tobytes())
        return _cb

    def _open(self, device: Optional[int], label: str, out_dir: Path) -> Optional[WavTrackWriter]:
        # sounddevice.query_devices(None) 返回全部设备列表，而不是默认设备。
        # 麦克风配置留空时 device 正是 None，因此必须显式指定 input，
        # 才会解析为系统默认输入设备并取得它的采样率。
        dev = sd.query_devices(device, "input")
        rate = int(dev["default_samplerate"])
        writer = WavTrackWriter(out_dir / f"track_{label}.wav", rate)
        stream = None
        try:
            stream = sd.InputStream(
                device=device,
                channels=1,
                samplerate=rate,
                dtype="int16",
                callback=self._make_callback(writer),
            )
            stream.start()
        except Exception:
            # 授权等待期间可能连续失败；每次失败都要释放 WAV/PortAudio
            # 资源，否则重试会遗留空轨文件和未关闭的文件句柄。
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            writer.close()
            raise
        self._streams.append(stream)
        self._writers.append(writer)
        self._specs.append(TrackSpec(writer.path, rate, label))
        return writer

    def start(self, out_dir: Path) -> None:
        out_dir.mkdir(parents=True, exist_ok=True)
        sys_idx = _resolve_device(self._system_name)
        if sys_idx is None:  # 未显式选择时自动找 BlackHole 类设备
            candidates = list_loopback_sources()
            if candidates:
                sys_idx = _resolve_device(candidates[0])
        if sys_idx is not None:
            try:
                self._open(sys_idx, "system", out_dir)
            except Exception as exc:
                self._errors.append(f"系统声音源打开失败：{exc}")
        else:
            self._errors.append("未找到系统声音源（BlackHole）。"
                                "本次将只录麦克风；如需内录请参见使用说明配置 BlackHole。")
        # 麦克风是必需轨道；首次使用时 macOS 授权弹窗可能还悬在屏幕上，
        # 这里留出约 13 秒重试窗口等用户点「允许」，而不是立刻失败
        mic_err: Exception | None = None
        for attempt in range(6):
            try:
                self._open(_resolve_device(self._mic_name), "mic", out_dir)
                mic_err = None
                break
            except Exception as exc:
                mic_err = exc
                if attempt < 5:
                    self._errors.append(
                        f"等待麦克风就绪/授权（第 {attempt + 1}/6 次，若屏幕上有授权弹窗请点「好」）…")
                    time.sleep(2.5)
        if mic_err is not None:
            self.stop()
            raise RuntimeError(
                f"麦克风无法打开：{mic_err}。请到 系统设置 → 隐私与安全性 → 麦克风，"
                f"勾选“会议纪要助手”后【完全退出并重新打开】本程序再试。"
            ) from mic_err
        if not self._streams:
            self.stop()
            raise RuntimeError("没有任何可用录音设备（请检查麦克风权限与设备连接）")

    def stop(self) -> List[TrackSpec]:
        """停止全部流并返回轨道描述。幂等。"""
        if self._stopped.is_set():
            return self._specs
        self._stopped.set()
        for s in self._streams:
            try:
                s.stop()
                s.close()
            except Exception:
                pass
        for w in self._writers:
            w.close()
        return self._specs

    @property
    def last_errors(self) -> List[str]:
        return list(self._errors)
