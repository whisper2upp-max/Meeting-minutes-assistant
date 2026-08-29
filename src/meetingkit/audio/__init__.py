"""录音入口：按平台选择实现。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

from .base import TrackSpec, mix_tracks_to_mono, read_wav_mono, write_wav_mono

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"


def get_recorder(system_source: str = "", microphone: str = ""):
    """返回平台对应的录音器（统一 start(out_dir)/stop()->List[TrackSpec] 接口）。"""
    if IS_WINDOWS:
        from .windows_rec import WindowsRecorder
        return WindowsRecorder(system_source, microphone)
    if IS_MACOS:
        from .macos_rec import MacRecorder
        return MacRecorder(system_source, microphone)
    raise RuntimeError(f"暂不支持的平台：{sys.platform}（仅支持 Windows / macOS）")


def list_devices() -> dict:
    """供界面展示的设备列表：{'microphones': [...], 'system_sources': [...]}。"""
    if IS_WINDOWS:
        from .windows_rec import list_mic_names
        mics = list_mic_names()
        return {"microphones": mics, "system_sources": []}  # Windows 用默认输出内录，无需选择
    if IS_MACOS:
        from .macos_rec import list_microphones, list_loopback_sources
        return {"microphones": list_microphones(),
                "system_sources": list_loopback_sources()}
    return {"microphones": [], "system_sources": []}


def mix_to_session_audio(specs: List[TrackSpec], out_wav: Path) -> float:
    """录音轨道混合为提交转写用的单声道 WAV，返回时长（秒）。"""
    return mix_tracks_to_mono(specs, out_wav)
