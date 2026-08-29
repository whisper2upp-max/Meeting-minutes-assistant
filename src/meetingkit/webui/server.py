"""pywebview 桌面窗口后端：把录音/管线能力以 JS API 暴露给本地前端（index.html）。

前端通过轮询 get_status() 驱动界面；耗时操作（录音、转写、纪要）在独立线程执行。
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import webview

from .. import audio as audio_mod
from .. import pipeline as pipeline_mod
from ..config import Config, load_config, save_config

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
        self.devices = {"microphones": [], "system_sources": []}
        self.cfg: Config = load_config()
        self.prev_output_id: Optional[int] = None  # 录音前默认输出设备（macOS 录后还原）

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
            "is_windows": IS_WINDOWS,
            "loopback_ready": loopback_ready,
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
            "attendees": "\n".join(c.attendees),
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
            c.attendees = [l.strip() for l in str(data.get("attendees", "")).splitlines() if l.strip()]
            out = str(data.get("output_dir", "")).strip()
            if out:
                c.output_dir = out
            save_config(c)
            _state.log(f"设置已保存（端点：{c.resolved_api_host()}）")
            return {"ok": True}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    # ---------- 录音 ----------

    def start_recording(self, title: str = "", system_source: str = "", microphone: str = "") -> dict:
        if _state.busy():
            return {"ok": False, "error": "当前有任务进行中"}
        if IS_MACOS:
            from ..audio import mac_setup
            if not mac_setup.blackhole_installed():
                return {"ok": False, "need_setup": True,
                        "error": "首次使用需要安装录音驱动（开源 BlackHole，仅此一次）"}
        cfg = _state.cfg
        cfg.system_source = "" if system_source.startswith("（") else system_source
        cfg.microphone = "" if microphone.startswith("（") else microphone
        title = (title or "").strip()
        _state.set(phase="recording", stage="recording", detail="",
                   error=None, result=None, started_at=datetime.now())
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
            if IS_MACOS:
                from ..audio import mac_setup
                prev_output = mac_setup.prepare_for_recording(log=_state.log)
                _state.set(prev_output_id=prev_output)
            rec = audio_mod.get_recorder(cfg.system_source, cfg.microphone)
            try:
                rec.start(session)
            except Exception as exc:
                raise RuntimeError(f"启动录音失败：{exc}")
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

    def process_file(self, path: str) -> dict:
        if _state.busy():
            return {"ok": False, "error": "当前有任务进行中"}
        p = Path(path).expanduser()
        if not p.exists():
            return {"ok": False, "error": f"文件不存在：{p}"}
        _state.set(phase="processing", stage="prepare", detail=str(p.name),
                   error=None, result=None)
        _spawn(self._process_worker, None, p)
        return {"ok": True}

    # ---------- 管线 ----------

    def _process_worker(self, rec, import_path: Optional[Path]) -> None:
        try:
            cfg = _state.cfg
            if not cfg.effective_api_key():
                raise RuntimeError("未配置百炼 API Key，请先在“设置”中填写。")
            title = ""
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
                from .audio.base import read_wav_mono as _read
                _x, _ = _read(audio_path)
                if float(_np.sqrt(_np.mean(_np.square(_x)))) < 1e-4:
                    raise RuntimeError(
                        "录音全程静音：最常见原因是麦克风权限未授予。"
                        "请到 系统设置 → 隐私与安全性 → 麦克风，勾选“会议纪要助手”后重试。")
                audio_path = audio_path
            minutes = pipeline_mod.run_pipeline(
                audio_path, cfg, session_dir=session, title=title,
                started_at=_state.started_at,
                progress=lambda s, d: _state.log(f"{s}｜{d}" if d else s))
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
        _state.set(phase="idle", stage="", detail="", error=None, result=None,
                   session_dir=None, started_at=None)
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
        _reveal(_state.cfg.resolved_output_dir())
        return {"ok": True}

    def reveal(self, path: str) -> dict:
        p = Path(path)
        _reveal(p.parent if p.is_file() else p, select=p if p.is_file() else None)
        return {"ok": True}

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


def _reveal(d: Path, select: Optional[Path] = None) -> None:
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(select or d)])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", "/select," + str(select or d)])
        else:
            subprocess.Popen(["xdg-open", str(d)])
    except Exception as exc:
        _state.log(f"打开目录失败：{exc}")


def _run_autotest(api: "Api", seconds: int, audio: str) -> None:
    """隐藏自动验收（MEETINGKIT_AUTOTEST=秒数）：自动录音→播放测试音频→停止→跑完管线→退出。"""
    import json as _json
    import time as _t
    result = {"phase": "error", "error": None, "session": None, "minutes": None}
    try:
        _t.sleep(2.5)  # 等窗口起来
        r = api.start_recording("自动验收", "", "")
        if not r.get("ok"):
            raise RuntimeError(r.get("error", "启动失败"))
        _t.sleep(2)
        player = None
        if audio:
            import subprocess as _sp
            player = _sp.Popen(["afplay", audio])
        _t.sleep(seconds)
        api.stop_recording()
        for _ in range(240):  # 等管线完成（含云端转写），最多 4 分钟
            _t.sleep(1)
            st = api.get_status()
            if st["phase"] in ("done", "error"):
                break
        result = {"phase": st["phase"], "error": st.get("error"),
                  "session": st.get("session_dir"),
                  "minutes": (st.get("result") or {}).get("minutes")}
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


def main() -> None:
    global _window
    api = Api()
    try:
        _state.log("正在启动界面…")
        _window = webview.create_window(
            "会议纪要助手",
            url=str(_INDEX_HTML),
            js_api=api,
            width=1100, height=780,
            min_size=(960, 680),
            background_color="#f4f5f7",
        )
        autotest = os.environ.get("MEETINGKIT_AUTOTEST")
        if autotest:
            _spawn(_run_autotest, api, int(autotest),
                   os.environ.get("MEETINGKIT_AUTOTEST_AUDIO", ""))
        webview.start()
    except Exception:
        # webview 起不来（极端环境）时由上层回退到 Tkinter 简版界面
        raise
