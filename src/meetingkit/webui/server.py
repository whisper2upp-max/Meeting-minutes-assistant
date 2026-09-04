"""pywebview 桌面窗口后端：把录音/管线能力以 JS API 暴露给本地前端（index.html）。

前端通过轮询 get_status() 驱动界面；耗时操作（录音、转写、纪要）在独立线程执行。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import webview

from .. import __version__
from .. import audio as audio_mod
from .. import pipeline as pipeline_mod
from ..cloud import llm as llm_mod
from ..cloud import transcribe as transcribe_mod
from ..config import Config, load_config, save_config
from ..prompt import (DEFAULT_DETAIL_LEVEL, detail_level_info,
                      normalize_detail_level)

IS_WINDOWS = sys.platform == "win32"
IS_MACOS = sys.platform == "darwin"

_INDEX_HTML = Path(__file__).with_name("index.html")


class UiState:
    """跨线程共享的界面状态。"""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.phase = "idle"        # idle | recording | processing | done | error
        self.stage = ""
        self.detail = ""
        self.error: Optional[str] = None
        self.result: Optional[dict] = None   # {"minutes": str, "session": str, "transcript": str}
        self.logs: deque = deque(maxlen=400)
        self.recorder = None
        self.session_dir: Optional[Path] = None
        self.started_at: Optional[datetime] = None
        self.meeting_title = ""
        self.meeting_detail_level = DEFAULT_DETAIL_LEVEL
        self.devices = {"microphones": [], "system_sources": [],
                        "default_microphone": ""}
        self.mic_monitor = None
        self.cfg: Config = load_config()
        self.prev_output_id: Optional[int] = None  # 录音前默认输出设备（macOS 录后还原）
        self.meeting_attendees: List[str] = []     # 本场会议的参会人（会议维度，非全局）

    # ---- 线程安全的小工具 ----
    def log(self, msg: str) -> None:
        with self.lock:
            self.logs.append((datetime.now().strftime("%H:%M:%S"), str(msg)))

    def set(self, **kw) -> None:
        with self.lock:
            for k, v in kw.items():
                setattr(self, k, v)

    def busy(self) -> bool:
        with self.lock:
            return self.phase in ("recording", "processing")

    def rec_duration(self) -> float:
        with self.lock:
            rec = self.recorder
        if rec is None:
            return 0.0
        try:
            return max(w.duration for w in getattr(rec, "_writers", []))
        except Exception:
            return (datetime.now() - (self.started_at or datetime.now())).total_seconds()

    def snapshot(self) -> dict:
        with self.lock:
            logs = list(self.logs)
            cfg = self.cfg
            phase, stage, detail = self.phase, self.stage, self.detail
            error, result = self.error, self.result
            devices = dict(self.devices)
            session = self.session_dir
            mic_monitor = self.mic_monitor
        mic_test_active = bool(mic_monitor and mic_monitor.active)
        mic_test_error = mic_monitor.last_error if mic_monitor else None
        host_label = cfg.resolved_api_host()
        host_label = ("官方端点" if host_label.endswith("dashscope.aliyuncs.com")
                      else host_label.replace("https://", ""))
        loopback_ready = True
        if IS_MACOS:
            from ..audio import mac_setup
            loopback_ready = mac_setup.blackhole_installed()
        return {
            "phase": phase, "stage": stage, "detail": detail,
            "error": error, "result": result,
            "elapsed": self.rec_duration() if phase == "recording" else 0.0,
            "logs": logs, "devices": devices,
            "session_dir": str(session) if session else "",
            "meeting_detail_level": self.meeting_detail_level,
            "is_windows": IS_WINDOWS,
            "mic_test_active": mic_test_active,
            "mic_test_error": mic_test_error,
            "mic_test_input": mic_monitor.input_name if mic_monitor else "",
            "mic_test_output": mic_monitor.output_name if mic_monitor else "",
            "mic_test_level": float(getattr(mic_monitor, "level", 0.0)) if mic_monitor else 0.0,
            "loopback_ready": loopback_ready,
            "version": __version__,
            "config": {
                "has_key": bool(cfg.effective_api_key()),
                "host_label": host_label,
                "transcribe_model": cfg.transcribe_model,
                "llm_model": cfg.llm_model,
                "output_dir": str(cfg.resolved_output_dir()),
                "attendees": list(cfg.attendees),
            },
        }


_state = UiState()
_window: Optional[webview.Window] = None


def _spawn(fn, *args) -> None:
    threading.Thread(target=fn, args=args, daemon=True).start()


class Api:
    """暴露给 JS 的方法（pywebview 自动驼峰化：get_status -> get_status）。"""

    # ---------- 状态 / 配置 ----------

    def get_status(self) -> dict:
        return _state.snapshot()

    def refresh_devices(self) -> dict:
        try:
            devs = audio_mod.list_devices()
        except Exception as exc:
            _state.log(f"设备列表获取失败：{exc}")
            devs = {"microphones": [], "system_sources": []}
        _state.set(devices=devs)
        return {"ok": True, "devices": devs}

    def get_config(self) -> dict:
        c = _state.cfg
        return {
            "api_key": c.api_key,
            "api_host": c.api_host,
            "transcribe_model": c.transcribe_model,
            "llm_model": c.llm_model,
            "attendees": list(c.attendees),
            "output_dir": str(c.resolved_output_dir()),
            "system_source": c.system_source,
            "microphone": c.microphone,
        }

    def save_config(self, data: dict) -> dict:
        try:
            c = _state.cfg
            c.api_key = str(data.get("api_key", "")).strip()
            c.api_host = str(data.get("api_host", "")).strip()
            c.transcribe_model = str(data.get("transcribe_model", c.transcribe_model)).strip() or c.transcribe_model
            c.llm_model = str(data.get("llm_model", c.llm_model)).strip() or c.llm_model
            raw_attendees = data.get("attendees", c.attendees)
            if isinstance(raw_attendees, str):
                raw_attendees = re.split(r"[\n,，;；]+", raw_attendees)
            if isinstance(raw_attendees, list):
                c.attendees = pipeline_mod.clean_attendees(raw_attendees)
            out = str(data.get("output_dir", "")).strip()
            if out:
                c.output_dir = out
            save_config(c)
            _state.log(f"设置已保存（端点：{c.resolved_api_host()}）")
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ---------- 录音 ----------

    def start_mic_test(self, microphone: str = "") -> dict:
        if not IS_WINDOWS:
            return {"ok": False, "error": "麦克风实时测试目前仅在 Windows 版本提供"}
        if _state.busy():
            return {"ok": False, "error": "录音或处理进行中，暂时不能测试麦克风"}
        self.stop_mic_test()
        monitor = None
        try:
            monitor = audio_mod.get_mic_monitor(microphone)
            monitor.start()
            with _state.lock:
                if _state.phase in ("recording", "processing"):
                    monitor.stop()
                    return {"ok": False, "error": "当前有任务进行中"}
                _state.mic_monitor = monitor
            _state.log(
                f"麦克风测试已开始：{monitor.input_name} → {monitor.output_name}"
            )
            return {"ok": True, "input": monitor.input_name,
                    "output": monitor.output_name}
        except Exception as exc:
            if monitor is not None:
                monitor.stop()
            _state.log(f"麦克风测试失败：{exc}")
            return {"ok": False, "error": f"启动麦克风测试失败：{exc}"}

    def stop_mic_test(self) -> dict:
        with _state.lock:
            monitor, _state.mic_monitor = _state.mic_monitor, None
        if monitor is None:
            return {"ok": True}
        try:
            monitor.stop()
            _state.log("麦克风测试已停止")
            return {"ok": True}
        except Exception as exc:
            _state.log(f"停止麦克风测试失败：{exc}")
            return {"ok": False, "error": f"停止麦克风测试失败：{exc}"}

    def start_recording(self, title: str = "", system_source: str = "", microphone: str = "",
                        attendees: str = "", detail_level: str = DEFAULT_DETAIL_LEVEL) -> dict:
        if _state.busy():
            return {"ok": False, "error": "当前有任务进行中"}
        self.stop_mic_test()
        if IS_MACOS:
            from ..audio import mac_setup
            if not mac_setup.blackhole_installed():
                return {"ok": False, "need_setup": True,
                        "error": "首次使用需要安装录音驱动（开源 BlackHole，仅此一次）"}
        cfg = _state.cfg
        cfg.system_source = "" if system_source.startswith("（") else system_source
        cfg.microphone = "" if microphone.startswith("（") else microphone
        meeting_attendees = pipeline_mod.clean_attendees(
            re.split(r"[\n,，;；]+", attendees) if isinstance(attendees, str) else attendees
        )
        title = (title or "").strip()
        _state.set(phase="recording", stage="recording", detail="",
                   error=None, result=None, started_at=datetime.now(),
                   meeting_title=title, meeting_attendees=meeting_attendees,
                   meeting_detail_level=normalize_detail_level(detail_level))
        _spawn(self._record_worker, title)
        return {"ok": True}

    def setup_loopback(self) -> dict:
        """首次使用：安装内置 BlackHole 驱动（弹管理员密码框）。"""
        if not IS_MACOS:
            return {"ok": True, "error": None}
        from ..audio import mac_setup
        ok, msg = mac_setup.install_blackhole()
        _state.log(f"驱动安装：{msg}")
        return {"ok": ok, "error": None if ok else msg}

    def _record_worker(self, title: str) -> None:
        prev_output = None
        try:
            cfg = _state.cfg
            session = pipeline_mod.new_session_dir(cfg.resolved_output_dir(), title)
            _state.set(session_dir=session)
            _state.log(f"会话目录：{session}")
            if IS_MACOS and not os.environ.get("MEETINGKIT_AUTOTEST_RAW"):
                from ..audio import mac_setup
                prev_output = mac_setup.prepare_for_recording(log=_state.log)
                _state.set(prev_output_id=prev_output)
            rec = audio_mod.get_recorder(cfg.system_source, cfg.microphone)
            try:
                rec.start(session)
            except Exception as exc:
                raise RuntimeError(f"启动录音失败：{exc}")
            if IS_WINDOWS:
                _state.log("会议内声已启用：Windows 默认输出设备（WASAPI 自动内录）")
            for msg in getattr(rec, "last_errors", []):
                _state.log(f"⚠️ {msg}")
            _state.set(recorder=rec)
        except Exception as exc:
            if prev_output is not None:
                from ..audio import mac_setup
                mac_setup.restore_output(prev_output, log=_state.log)
            _state.set(phase="error", error=f"{exc}", stage="", detail="")
            _state.log(f"错误：{exc}")

    def stop_recording(self) -> dict:
        with _state.lock:
            rec = _state.recorder
            if _state.phase != "recording" or rec is None:
                return {"ok": False, "error": "当前没有在录音"}
            _state.recorder = None
        _state.set(phase="processing", stage="finalize", detail="正在停止录音并混音…")
        _spawn(self._process_worker, rec, None)
        return {"ok": True}

    # ---------- 导入模式 ----------

    def pick_audio_file(self) -> str:
        if _window is None:
            return ""
        try:
            paths = _window.create_file_dialog(
                webview.OPEN_DIALOG, allow_multiple=False,
                file_types=("音视频文件 (*.wav;*.mp3;*.m4a;*.aac;*.flac;*.ogg;*.opus;*.wma;*.amr;*.mp4;*.mov)",
                            "所有文件 (*.*)"))
            if paths:
                return paths if isinstance(paths, str) else paths[0]
        except Exception as exc:
            _state.log(f"选择文件失败：{exc}")
        return ""

    def process_file(self, path: str, attendees: str = "",
                     detail_level: str = DEFAULT_DETAIL_LEVEL) -> dict:
        if _state.busy():
            return {"ok": False, "error": "当前有任务进行中"}
        self.stop_mic_test()
        p = Path(path).expanduser()
        if not p.exists():
            return {"ok": False, "error": f"文件不存在：{p}"}
        meeting_attendees = pipeline_mod.clean_attendees(
            re.split(r"[\n,，;；]+", attendees) if isinstance(attendees, str) else attendees
        )
        _state.set(meeting_attendees=meeting_attendees,
                   meeting_title="",
                   meeting_detail_level=normalize_detail_level(detail_level),
                   phase="processing", stage="prepare", detail=str(p.name),
                   error=None, result=None)
        _spawn(self._process_worker, None, p)
        return {"ok": True}

    # ---------- 管线 ----------

    @staticmethod
    def _pipeline_progress(stage: str, detail: str) -> None:
        """同时更新结构化阶段与日志，避免界面永远停留在“准备”。"""
        _state.set(stage=stage, detail=detail)
        _state.log(f"{stage}｜{detail}" if detail else stage)

    def _process_worker(self, rec, import_path: Optional[Path]) -> None:
        try:
            cfg = _state.cfg
            if not cfg.effective_api_key():
                raise RuntimeError("未配置百炼 API Key，请先在“设置”中填写。")
            title = _state.meeting_title
            if import_path is not None:
                _state.log(f"导入文件：{import_path}")
                session = pipeline_mod.new_session_dir(cfg.resolved_output_dir(), "")
                _state.set(session_dir=session, started_at=datetime.now())
                audio_path = import_path
            else:
                session = _state.session_dir
                specs = rec.stop()
                if IS_MACOS:
                    from ..audio import mac_setup
                    mac_setup.restore_output(_state.prev_output_id, log=_state.log)
                    _state.set(prev_output_id=None)
                total = sum(s.path.stat().st_size for s in specs) / 1e6
                _state.log(f"录音结束：{len(specs)} 轨，共 {total:.1f} MB")
                audio_path = session / pipeline_mod.AUDIO_WAV
                dur = audio_mod.mix_to_session_audio(specs, audio_path)
                _state.log(f"已混为单声道 16kHz：{dur / 60:.1f} 分钟")
                # 全程静音守卫：避免把无声文件送去云端白跑一趟
                import numpy as _np
                _x, _ = audio_mod.read_wav_mono(audio_path)
                if float(_np.sqrt(_np.mean(_np.square(_x)))) < 1e-4:
                    raise RuntimeError(
                        "录音全程静音：最常见原因是麦克风权限未授予。"
                        "请到 系统设置 → 隐私与安全性 → 麦克风，勾选“会议纪要助手”后重试。")
                audio_path = audio_path
            minutes = pipeline_mod.run_pipeline(
                audio_path, cfg, session_dir=session, title=title,
                started_at=_state.started_at, attendees=_state.meeting_attendees,
                detail_level=_state.meeting_detail_level,
                progress=self._pipeline_progress)
            _state.set(phase="done",
                       result={"minutes": str(minutes),
                               "transcript": str(session / pipeline_mod.TRANSCRIPT_MD),
                               "session": str(session)})
            _state.log(f"完成：{minutes}")
        except Exception as exc:
            detail = str(exc) or repr(exc)
            _state.set(phase="error", error=detail)
            _state.log(f"错误：{detail}")

    def reset(self) -> dict:
        if _state.busy():
            return {"ok": False, "error": "当前有任务进行中"}
        self.stop_mic_test()
        _state.set(phase="idle", stage="", detail="", error=None, result=None,
                   session_dir=None, started_at=None, meeting_title="",
                   meeting_attendees=[], meeting_detail_level=DEFAULT_DETAIL_LEVEL)
        return {"ok": True}

    # ---------- 文件 / 目录 ----------

    def pick_folder(self) -> str:
        if _window is None:
            return ""
        try:
            paths = _window.create_file_dialog(webview.FOLDER_DIALOG)
            if paths:
                return paths if isinstance(paths, str) else paths[0]
        except Exception as exc:
            _state.log(f"选择目录失败：{exc}")
        return ""

    def open_output_dir(self) -> dict:
        try:
            output = _state.cfg.resolved_output_dir().resolve()
            _reveal(output)
            _state.log(f"已打开输出目录：{output}")
            return {"ok": True, "path": str(output)}
        except Exception as exc:
            _state.log(f"打开输出目录失败：{exc}")
            return {"ok": False, "error": f"打开输出目录失败：{exc}"}

    def reveal(self, path: str) -> dict:
        try:
            p = Path(path).expanduser().resolve()
            _reveal(p.parent if p.is_file() else p, select=p if p.is_file() else None)
            return {"ok": True}
        except Exception as exc:
            _state.log(f"打开目录失败：{exc}")
            return {"ok": False, "error": f"打开目录失败：{exc}"}

    def open_file(self, path: str) -> dict:
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", path])
            elif sys.platform == "win32":
                subprocess.Popen(["cmd", "/c", "start", "", path], shell=False)
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception as exc:
            _state.log(f"打开文件失败：{exc}")
        return {"ok": True}

    # ---------- 纪要：查看 / 编辑 / 导出 / 历史会话 ----------

    def _safe_minutes_path(self, path: str) -> Path:
        p = Path(path).expanduser().resolve()
        root = _state.cfg.resolved_output_dir().resolve()
        if root not in p.parents:
            raise RuntimeError("只能访问输出目录内的纪要文件")
        return p

    def get_minutes(self, path: str) -> dict:
        try:
            p = self._safe_minutes_path(path)
            transcript = p.parent / pipeline_mod.TRANSCRIPT_MD
            metadata = pipeline_mod.load_session_metadata(p.parent)
            detail = detail_level_info(metadata["detail_level"])
            history_dir = p.parent / pipeline_mod.MINUTES_HISTORY_DIR
            history_count = len(list(history_dir.glob("*.md"))) if history_dir.exists() else 0
            return {
                "ok": True,
                "content": p.read_text(encoding="utf-8"),
                "session": str(p.parent),
                "session_name": p.parent.name,
                "transcript": str(transcript) if transcript.exists() else "",
                "mtime": datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M"),
                "detail_level": detail["value"],
                "detail_label": detail["label"],
                "minutes_model": metadata["minutes_model"],
                "attendees": metadata["attendees"],
                "history_count": history_count,
            }
        except Exception as exc:
            return {"ok": False, "error": f"{exc}"}

    def _speaker_context(
        self,
        minutes: Path,
    ) -> tuple[list[dict], dict[str, str], list[str]]:
        """读取一场会议可映射的说话人、样例发言和已保存映射。"""
        session = minutes.parent
        transcript_json = session / pipeline_mod.TRANSCRIPT_JSON
        transcript_md = session / pipeline_mod.TRANSCRIPT_MD
        sentences: list[dict] = []
        if transcript_json.exists():
            payload = json.loads(transcript_json.read_text(encoding="utf-8"))
            sentences = payload.get("sentences", []) if isinstance(payload, dict) else []

        samples: dict[int, list[str]] = {}
        for sentence in sentences:
            if not isinstance(sentence, dict):
                continue
            try:
                speaker_id = int(sentence.get("speaker_id", -1))
            except (TypeError, ValueError):
                continue
            text = " ".join(str(sentence.get("text", "")).split())
            if speaker_id < 0 or not text:
                continue
            bucket = samples.setdefault(speaker_id + 1, [])
            if len(bucket) < 2:
                bucket.append(text)

        # 极少数旧会话可能只保留 transcript.md，仍允许用户完成姓名匹配。
        if not samples and transcript_md.exists():
            content = transcript_md.read_text(encoding="utf-8")
            pattern = re.compile(r"\*\*说话人(\d+)\*\*[：:]\s*([^\n]+)")
            for number_text, text in pattern.findall(content):
                number = int(number_text)
                bucket = samples.setdefault(number, [])
                if len(bucket) < 2:
                    bucket.append(" ".join(text.split()))

        mapping_path = session / pipeline_mod.SPEAKER_MAP_JSON
        mapping: dict[str, str] = {}
        stored_candidates: list[str] = []
        if mapping_path.exists():
            stored = json.loads(mapping_path.read_text(encoding="utf-8"))
            raw_mapping = stored.get("speakers", {}) if isinstance(stored, dict) else {}
            if isinstance(raw_mapping, dict):
                mapping = {
                    str(key): str(value).strip()
                    for key, value in raw_mapping.items()
                    if str(value).strip()
                }
            raw_candidates = stored.get("candidates", []) if isinstance(stored, dict) else []
            if isinstance(raw_candidates, list):
                for value in raw_candidates:
                    name = " ".join(str(value).split())
                    if name and name not in stored_candidates:
                        stored_candidates.append(name)

        speakers = [
            {
                "number": number,
                "label": f"说话人{number}",
                "sample": " / ".join(parts)[:180],
            }
            for number, parts in sorted(samples.items())
        ]
        return speakers, mapping, stored_candidates

    def get_speaker_mapping(self, path: str) -> dict:
        try:
            minutes = self._safe_minutes_path(path)
            if minutes.name != pipeline_mod.MINUTES_MD or not minutes.is_file():
                raise RuntimeError("会议纪要文件不存在")
            speakers, mapping, stored_candidates = self._speaker_context(minutes)
            metadata = pipeline_mod.load_session_metadata(minutes.parent)
            candidates = []
            with _state.lock:
                active_session = _state.session_dir.resolve() if _state.session_dir else None
                attendee_candidates = (
                    list(_state.meeting_attendees)
                    if active_session == minutes.parent.resolve()
                    else []
                )
            for name in [
                *metadata["attendees"],
                *stored_candidates,
                *attendee_candidates,
                *_state.cfg.attendees,
                *mapping.values(),
            ]:
                clean = " ".join(str(name).split())
                if clean and clean not in candidates:
                    candidates.append(clean)
            return {
                "ok": True,
                "speakers": speakers,
                "mapping": mapping,
                "candidates": candidates,
            }
        except Exception as exc:
            return {"ok": False, "error": f"读取说话人信息失败：{exc}"}

    def save_speaker_mapping(self, path: str, mapping: dict) -> dict:
        """保存用户确认的姓名映射，并据原始 JSON 重新生成可读转写稿。"""
        try:
            minutes = self._safe_minutes_path(path)
            if minutes.name != pipeline_mod.MINUTES_MD or not minutes.is_file():
                raise RuntimeError("会议纪要文件不存在")
            speakers, _, stored_candidates = self._speaker_context(minutes)
            valid_numbers = {item["number"] for item in speakers}
            if not valid_numbers:
                raise RuntimeError("这场会议没有可匹配的说话人标签")
            if not isinstance(mapping, dict):
                raise RuntimeError("说话人映射格式无效")

            cleaned: dict[str, str] = {}
            for key, value in mapping.items():
                try:
                    number = int(key)
                except (TypeError, ValueError):
                    raise RuntimeError(f"无效的说话人编号：{key}") from None
                if number not in valid_numbers:
                    raise RuntimeError(f"转写稿中不存在说话人{number}")
                name = " ".join(str(value).split())
                if len(name) > 40:
                    raise RuntimeError(f"说话人{number}的姓名过长")
                if name:
                    cleaned[str(number)] = name

            mapping_path = minutes.parent / pipeline_mod.SPEAKER_MAP_JSON
            metadata = pipeline_mod.load_session_metadata(minutes.parent)
            candidates = pipeline_mod.clean_attendees([
                *metadata["attendees"], *stored_candidates, *cleaned.values(),
            ])
            mapping_payload = {
                "version": 1,
                "speakers": cleaned,
                "candidates": candidates,
            }
            mapping_path.write_text(
                json.dumps(mapping_payload, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            pipeline_mod.save_session_metadata(minutes.parent, attendees=candidates)

            transcript_json = minutes.parent / pipeline_mod.TRANSCRIPT_JSON
            transcript_md = minutes.parent / pipeline_mod.TRANSCRIPT_MD
            if transcript_json.exists():
                payload = json.loads(transcript_json.read_text(encoding="utf-8"))
                sentences = payload.get("sentences", []) if isinstance(payload, dict) else []
                names_by_id = {int(number) - 1: name for number, name in cleaned.items()}
                transcript_md.write_text(
                    transcribe_mod.format_transcript_md(sentences, names_by_id),
                    encoding="utf-8",
                )

            _state.log(
                f"说话人匹配已保存：{len(cleaned)}/{len(valid_numbers)} 位参会人"
            )
            return {
                "ok": True,
                "mapping": cleaned,
                "transcript": str(transcript_md) if transcript_md.exists() else "",
            }
        except Exception as exc:
            return {"ok": False, "error": f"保存说话人匹配失败：{exc}"}

    def regenerate_minutes(self, path: str,
                           detail_level: str = DEFAULT_DETAIL_LEVEL) -> dict:
        """基于已保存转写异步重新生成纪要，不重复上传和转写。"""
        try:
            if _state.busy():
                return {"ok": False, "error": "当前有任务进行中，请稍后再试"}
            minutes = self._safe_minutes_path(path)
            if minutes.name != pipeline_mod.MINUTES_MD or not minutes.is_file():
                raise RuntimeError("会议纪要文件不存在")
            transcript = minutes.parent / pipeline_mod.TRANSCRIPT_MD
            if not transcript.is_file():
                raise RuntimeError("这场会议缺少完整转写，无法重新生成纪要")
            if not _state.cfg.effective_api_key():
                raise RuntimeError("未配置百炼 API Key，请先在“设置”中填写")

            level = normalize_detail_level(detail_level)
            info = detail_level_info(level)
            _state.set(
                phase="processing",
                stage="minutes",
                detail=f"正在重新生成{info['label']}纪要…",
                error=None,
                result=None,
                session_dir=minutes.parent,
                meeting_detail_level=level,
            )
            _state.log(f"纪要重生成｜目标详细程度：{info['label']}（不重复上传和转写）")
            _spawn(self._regenerate_minutes_worker, minutes, level)
            return {"ok": True, "detail_level": level, "detail_label": info["label"]}
        except Exception as exc:
            return {"ok": False, "error": f"无法重新生成纪要：{exc}"}

    def _regenerate_minutes_worker(self, minutes: Path, detail_level: str) -> None:
        try:
            cfg = _state.cfg
            metadata = pipeline_mod.load_session_metadata(minutes.parent)
            transcript = minutes.parent / pipeline_mod.TRANSCRIPT_MD
            _, mapping, stored_candidates = self._speaker_context(minutes)
            attendees = pipeline_mod.clean_attendees([
                *metadata["attendees"],
                *stored_candidates,
                *mapping.values(),
            ])
            try:
                started_at = datetime.fromisoformat(metadata["started_at"])
            except (TypeError, ValueError):
                started_at = datetime.fromtimestamp(minutes.stat().st_mtime)

            generated = llm_mod.generate_minutes(
                transcript.read_text(encoding="utf-8"),
                api_key=cfg.effective_api_key(),
                model=cfg.llm_model,
                attendees=attendees,
                meeting_title=metadata["title"],
                started_at=started_at,
                detail_level=detail_level,
                base_url=cfg.llm_base_url(),
                progress=self._pipeline_progress,
            )

            history_dir = minutes.parent / pipeline_mod.MINUTES_HISTORY_DIR
            history_dir.mkdir(exist_ok=True)
            old_info = detail_level_info(metadata["detail_level"])
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = history_dir / f"会议纪要_{old_info['label']}_{stamp}.md"
            index = 1
            while backup.exists():
                backup = history_dir / f"会议纪要_{old_info['label']}_{stamp}_{index}.md"
                index += 1
            shutil.copy2(minutes, backup)

            temporary = minutes.parent / ".会议纪要.md.tmp"
            temporary.write_text(generated, encoding="utf-8")
            temporary.replace(minutes)
            model = llm_mod.resolve_minutes_model(cfg.llm_model, detail_level)
            pipeline_mod.save_session_metadata(
                minutes.parent,
                attendees=attendees,
                detail_level=detail_level,
                minutes_model=model,
            )
            (minutes.parent / "done.flag").write_text("ok", encoding="utf-8")
            _state.set(
                phase="done",
                stage="minutes",
                detail=f"{detail_level_info(detail_level)['label']}纪要已生成",
                result={
                    "minutes": str(minutes),
                    "transcript": str(transcript),
                    "session": str(minutes.parent),
                },
            )
            _state.log(f"纪要重生成完成：{minutes.name}（旧版已保存到 {backup.name}）")
        except Exception as exc:
            detail = str(exc) or repr(exc)
            _state.set(phase="error", stage="minutes", error=detail)
            _state.log(f"错误：{detail}")

    def save_minutes(self, path: str, content: str) -> dict:
        try:
            p = self._safe_minutes_path(path)
            p.write_text(content, encoding="utf-8")
            _state.log(f"纪要已保存：{p.name}")
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": f"{exc}"}

    def export_minutes(self, path: str) -> dict:
        """导出纪要到用户选择的目录（同名冲突时自动加时间后缀）。"""
        try:
            src = self._safe_minutes_path(path)
            dest_dir = self.pick_folder()
            if not dest_dir:
                return {"ok": False, "error": "未选择导出目录"}
            dest_dir = Path(dest_dir).expanduser()
            dest = dest_dir / src.name
            if dest.exists():
                stamp = datetime.now().strftime("%H%M%S")
                dest = dest_dir / f"{src.stem}_{stamp}{src.suffix}"
            shutil.copy2(src, dest)
            _state.log(f"纪要已导出：{dest}")
            return {"ok": True, "dest": str(dest)}
        except Exception as exc:
            return {"ok": False, "error": f"{exc}"}

    def delete_session(self, path: str) -> dict:
        """永久删除一场会议的完整目录；只允许删除输出根目录的直接子目录。"""
        try:
            if _state.busy():
                return {"ok": False, "error": "录音或处理进行中，暂时不能删除会议"}
            minutes = self._safe_minutes_path(path)
            root = _state.cfg.resolved_output_dir().resolve()
            session = minutes.parent.resolve()
            if minutes.name != pipeline_mod.MINUTES_MD:
                raise RuntimeError("只能通过会议纪要文件删除会议")
            if session == root or session.parent != root:
                raise RuntimeError("只能删除输出目录内的单个会议文件夹")
            if not minutes.is_file() or not session.is_dir():
                raise RuntimeError("会议记录不存在或已被移除")

            shutil.rmtree(session)
            with _state.lock:
                active_session = _state.session_dir.resolve() if _state.session_dir else None
                if active_session == session:
                    _state.phase = "idle"
                    _state.stage = ""
                    _state.detail = ""
                    _state.error = None
                    _state.result = None
                    _state.session_dir = None
                    _state.started_at = None
                    _state.meeting_title = ""
                    _state.meeting_attendees = []
                    _state.meeting_detail_level = DEFAULT_DETAIL_LEVEL
            _state.log(f"已永久删除会议文件夹：{session.name}")
            return {"ok": True, "deleted": str(session)}
        except Exception as exc:
            return {"ok": False, "error": f"{exc}"}

    def list_sessions(self) -> dict:
        """输出目录里最近有纪要的会议，供首页展示。"""
        out = []
        try:
            root = _state.cfg.resolved_output_dir()
            for d in root.iterdir():
                if not d.is_dir():
                    continue
                m = d / pipeline_mod.MINUTES_MD
                if not m.exists():
                    continue
                st = m.stat()
                transcript = d / pipeline_mod.TRANSCRIPT_MD
                metadata = pipeline_mod.load_session_metadata(d)
                detail = detail_level_info(metadata["detail_level"])
                out.append({"name": d.name,
                            "minutes": str(m),
                            "transcript": str(transcript) if transcript.exists() else "",
                            "detail_level": detail["value"],
                            "detail_label": detail["label"],
                            "mtime": datetime.fromtimestamp(st.st_mtime).strftime("%m-%d %H:%M"),
                            "mtime_ts": st.st_mtime,
                            "size_kb": max(1, st.st_size // 1024)})
            out.sort(key=lambda x: x["mtime_ts"], reverse=True)
        except Exception:
            pass
        return {"ok": True, "sessions": out}


def _reveal(d: Path, select: Optional[Path] = None) -> None:
    d = Path(d).expanduser()
    if not d.exists():
        raise FileNotFoundError(f"目录不存在：{d}")
    if sys.platform == "darwin":
        if select is not None:
            subprocess.Popen(["open", "-R", str(select or d)])
        else:
            subprocess.Popen(["open", str(d)])
    elif sys.platform == "win32":
        if select is not None:
            subprocess.Popen(["explorer.exe", f"/select,{select}"])
        else:
            # /select,目录 会打开其父级（常见表现就是只看到 Documents）；
            # 打开目录本身必须把目录作为普通参数传给 Explorer。
            subprocess.Popen(["explorer.exe", str(d)])
    else:
        subprocess.Popen(["xdg-open", str(d)])


def _run_autotest(api: "Api", seconds: int, audio: str) -> None:
    """隐藏自动验收（MEETINGKIT_AUTOTEST=秒数）：自动录音→播放测试音频→停止→跑完管线→退出。"""
    import json as _json
    import time as _t
    result = {"phase": "error", "error": None, "session": None, "minutes": None,
              "diag": {}}
    player = None
    try:
        _t.sleep(2.5)  # 等窗口起来
        if IS_MACOS:
            try:
                from ..audio import mac_setup
                result["diag"]["default_out_before"] = mac_setup.get_default_output()["name"]
            except Exception as exc:
                result["diag"]["default_out_before"] = f"err:{exc}"
        r = api.start_recording("自动验收", "", "", "")
        if not r.get("ok"):
            raise RuntimeError(r.get("error", "启动失败"))
        if audio:
            # 等待录音 worker 完成输出设备切换（默认输出变为聚合设备）后再播放，
            # 否则 afplay 可能撞上切换窗口、把声音播到旧设备或直接卡死
            if IS_MACOS:
                from ..audio import mac_setup
                for _ in range(20):
                    try:
                        if mac_setup.get_default_output()["uid"] == mac_setup.AGG_UID:
                            break
                    except Exception:
                        pass
                    _t.sleep(1)
        _t.sleep(1)
        if audio:
            import subprocess as _sp
            player = _sp.Popen(["afplay", audio])
        _t.sleep(seconds)
        api.stop_recording()
        if player is not None:
            try:
                player.wait(timeout=5)
            except Exception:
                player.terminate()
            result["diag"]["afplay_rc"] = player.returncode
        for _ in range(240):  # 等管线完成（含云端转写），最多 4 分钟
            _t.sleep(1)
            st = api.get_status()
            if st["phase"] in ("done", "error"):
                break
        result.update({"phase": st["phase"], "error": st.get("error"),
                       "session": st.get("session_dir"),
                       "minutes": (st.get("result") or {}).get("minutes")})
    except Exception as exc:
        result["error"] = f"{exc}"
    finally:
        if player and player.poll() is None:
            player.terminate()
        Path("/tmp/mk_autotest_result.json").write_text(
            _json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        _t.sleep(1)
        if _window is not None:
            _window.destroy()


def _on_closing() -> bool:
    """录音/处理进行中关闭窗口时拦截确认，避免静默丢弃已录内容。"""
    allowed = True
    if _state.busy():
        try:
            allowed = bool(_window.evaluate_js(
                "confirm('录音或处理正在进行中，确定放弃并退出？（已录制的原始轨道会保留在会话目录）')"))
        except Exception:
            allowed = True
    if allowed:
        Api().stop_mic_test()
    return allowed


def main() -> None:
    global _window
    api = Api()
    try:
        _state.log("正在启动界面…")
        _window = webview.create_window(
            "会议纪要助手",
            url=str(_INDEX_HTML),
            js_api=api,
            width=1280, height=840,
            min_size=(1040, 720),
            background_color="#f3f6fc",
        )
        autotest = os.environ.get("MEETINGKIT_AUTOTEST")
        if not autotest and Path("/tmp/mk_autotest").exists():
            # 经 `open` 启动时环境变量传不进来，用标记文件（内容：秒数<TAB>音频路径）。
            # 用 `open` 启动时音频权限才归属 app 自身；从终端直启会归属终端宿主而被置零。
            try:
                parts = Path("/tmp/mk_autotest").read_text(encoding="utf-8").split("\t")
                autotest = parts[0].strip()
                if len(parts) > 1:
                    os.environ["MEETINGKIT_AUTOTEST_AUDIO"] = parts[1].strip()
                for extra in parts[2:]:
                    extra = extra.strip()
                    if extra == "raw":
                        os.environ["MEETINGKIT_AUTOTEST_RAW"] = "1"  # 诊断：跳过聚合设备切换
                    elif extra.startswith("exp"):
                        os.environ["MEETINGKIT_AGG_EXP"] = extra[3:]  # 聚合配方实验
            except Exception:
                autotest = None
            try:
                Path("/tmp/mk_autotest").unlink()
            except OSError:
                pass
        if autotest:
            _spawn(_run_autotest, api, int(autotest),
                   os.environ.get("MEETINGKIT_AUTOTEST_AUDIO", ""))
        _window.events.closing += _on_closing
        webview.start()
    except Exception:
        # webview 起不来（极端环境）时由上层回退到 Tkinter 简版界面
        raise
