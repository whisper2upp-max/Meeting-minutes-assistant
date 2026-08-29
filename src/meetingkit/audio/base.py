"""录音公共层：轨道写入、重采样、归一化、混单声道（说话人分离要求单声道）。"""

from __future__ import annotations

import threading
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

# 说话人分离只支持单声道；16kHz/16bit 足够语音识别且体积可控（约 115MB/小时）
TARGET_SAMPLE_RATE = 16000
# 归一化目标响度（dBFS）。两轨（内录/麦克风）先各自归一再混合，
# 避免麦克风增益过大把内录的远端说话人压没，从而破坏说话人分离。
_TARGET_RMS_DBFS = -20.0
_PEAK_LIMIT = 0.98


class WavTrackWriter:
    """线程安全地把 PCM 块顺序追加写入单声道 WAV 文件（多声道输入自动平均降混）。"""

    def __init__(self, path: Path, sample_rate: int, channels: int = 1):
        self.path = path
        self.sample_rate = sample_rate
        self.channels = max(1, int(channels))
        self._frames = 0
        self._lock = threading.Lock()
        self._closed = False
        self._fh = wave.open(str(path), "wb")
        self._fh.setnchannels(1)
        self._fh.setsampwidth(2)
        self._fh.setframerate(sample_rate)

    def write(self, pcm: bytes) -> None:
        if self._closed or not pcm:
            return
        if self.channels > 1:
            x = np.frombuffer(pcm, dtype=np.int16)
            usable = (len(x) // self.channels) * self.channels
            if usable == 0:
                return
            pcm = (x[:usable].reshape(-1, self.channels).astype(np.int32)
                   .mean(axis=1).astype(np.int16).tobytes())
        with self._lock:
            self._fh.writeframes(pcm)
            self._frames += len(pcm) // 2

    @property
    def duration(self) -> float:
        return self._frames / self.sample_rate

    def close(self) -> None:
        with self._lock:
            if not self._closed:
                self._fh.close()
                self._closed = True


def read_wav_mono(path: Path) -> Tuple[np.ndarray, int]:
    """读 WAV 为 float32 单声道（多声道取平均），返回 (samples, sample_rate)。"""
    with wave.open(str(path), "rb") as fh:
        n_channels = fh.getnchannels()
        sample_rate = fh.getframerate()
        sampwidth = fh.getsampwidth()
        if sampwidth != 2:
            raise ValueError(f"仅支持 16-bit PCM WAV（{path} 为 {sampwidth * 8}-bit）")
        raw = fh.readframes(fh.getnframes())
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    if n_channels > 1:
        x = x.reshape(-1, n_channels).mean(axis=1)
    return x, sample_rate


def write_wav_mono(path: Path, x: np.ndarray, sample_rate: int) -> None:
    """把 float 单声道写成 16-bit WAV。"""
    y = np.clip(x, -1.0, 1.0)
    y = (y * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(sample_rate)
        fh.writeframes(y.tobytes())


def resample(x: np.ndarray, sr_from: int, sr_to: int) -> np.ndarray:
    """线性插值重采样（语音场景足够，且无额外依赖）。"""
    if sr_from == sr_to or len(x) == 0:
        return x
    n_out = max(1, int(round(len(x) * sr_to / sr_from)))
    idx = np.linspace(0.0, len(x) - 1, n_out, dtype=np.float64)
    return np.interp(idx, np.arange(len(x), dtype=np.float64), x).astype(np.float32)


def rms_normalize(x: np.ndarray, target_dbfs: float = _TARGET_RMS_DBFS) -> np.ndarray:
    """把轨道整体响度归一到目标 dBFS，并限制峰值，避免混合后削波。"""
    if len(x) == 0:
        return x
    rms = float(np.sqrt(np.mean(np.square(x))))
    if rms < 1e-8:  # 静音轨道（比如没开麦克风），不放大底噪
        return x
    target = 10 ** (target_dbfs / 20.0)
    y = x * (target / rms)
    peak = float(np.max(np.abs(y)))
    if peak > _PEAK_LIMIT:
        y = y * (_PEAK_LIMIT / peak)
    return y


@dataclass
class TrackSpec:
    path: Path
    sample_rate: int
    label: str = ""


def mix_tracks_to_mono(tracks: List[TrackSpec], out_path: Path,
                        target_rate: int = TARGET_SAMPLE_RATE) -> float:
    """多条单声道轨 -> 重采样 -> 各自响度归一 -> 平均混合 -> 写 16k 单声道 WAV。
    返回混合后时长（秒）。"""
    if not tracks:
        raise ValueError("没有任何录音轨道")
    normalized: List[np.ndarray] = []
    for t in tracks:
        x, sr = read_wav_mono(t.path)
        x = resample(x, sr, target_rate)
        normalized.append(rms_normalize(x))

    # 独立音频设备的回调不会保证收到完全相同的帧数；即使同时启停，
    # 两轨也常有几毫秒差异。按最长轨建缓冲区，较短轨尾部自然补零，
    # 既避免 NumPy 广播错误，也不截掉任一轨末尾的有效语音。
    max_len = max(len(x) for x in normalized)
    mixed = np.zeros(max_len, dtype=np.float32)
    for x in normalized:
        mixed[:len(x)] += x
    mixed /= len(normalized)
    write_wav_mono(out_path, mixed, target_rate)
    return len(mixed) / target_rate
