"""macOS 录音：sounddevice（PortAudio）采集 BlackHole（系统声音）与麦克风。

系统内录依赖一次性配置（详见 docs/使用说明-macOS.md）：
安装 BlackHole 2ch 后，在"音频 MIDI 设置"里建一个"多输出设备"
（耳机 + BlackHole）并设为系统输出，程序录制 BlackHole 输入即可拿到会议声音。
"""

from __future__ import annotations

import queue
import threading
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
        dev = sd.query_devices(device)
        rate = int(dev["default_samplerate"])
        writer = WavTrackWriter(out_dir / f"track_{label}.wav", rate)
        stream = sd.InputStream(
            device=device,
            channels=1,
            samplerate=rate,
            dtype="int16",
            callback=self._make_callback(writer),
        )
        stream.start()
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
        try:
            self._open(_resolve_device(self._mic_name), "mic", out_dir)
        except Exception as exc:
            # 麦克风是必需轨道：失败立即终止，不能默默继续录（无麦克风授权时
            # 系统还会把其它输入轨一并静默置零，继续录只会得到全静音文件）
            self.stop()
            raise RuntimeError(
                "麦克风无法打开（常见原因：未授权或被拒绝）。请到 "
                "系统设置 → 隐私与安全性 → 麦克风，勾选“会议纪要助手”后重试。"
            ) from exc
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
