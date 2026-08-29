"""Tkinter 主界面：录音（内录+麦克风）、导入文件、状态日志、设置。"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, scrolledtext, ttk
from pathlib import Path
from typing import Optional

from .. import audio as audio_mod
from .. import pipeline as pipeline_mod
from ..config import Config, load_config, save_config

_IS_MAC = sys.platform == "darwin"
_POLL_MS = 120


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("会议纪要助手（百炼 fun-asr + qwen-flash）")
        self.geometry("760x560")
        self.minsize(680, 480)

        self.cfg: Config = load_config()
        self.event_q: "queue.Queue[tuple]" = queue.Queue()
        self.recorder = None
        self.session_dir: Optional[Path] = None
        self.rec_started_at: Optional[datetime] = None
        self.worker: Optional[threading.Thread] = None
        self.busy = False

        self._build_ui()
        self._refresh_devices(first=True)
        self.after(_POLL_MS, self._poll_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------------- UI ----------------

    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}

        top = ttk.Frame(self)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="会议标题（可选）").pack(side="left")
        self.title_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.title_var, width=28).pack(side="left", padx=6)

        dev = ttk.LabelFrame(self, text="录音设备")
        dev.pack(fill="x", **pad)
        if _IS_MAC:
            ttk.Label(dev, text="系统声音").grid(row=0, column=0, padx=6, pady=4, sticky="w")
            self.sys_var = tk.StringVar()
            self.sys_box = ttk.Combobox(dev, textvariable=self.sys_var, width=38,
                                        values=self._sys_choices())
            self.sys_box.grid(row=0, column=1, padx=4, pady=4, sticky="w")
        else:
            ttk.Label(dev, text="系统声音：默认输出设备（自动内录）").grid(
                row=0, column=0, columnspan=2, padx=6, pady=4, sticky="w")
        ttk.Label(dev, text="麦克风").grid(row=1, column=0, padx=6, pady=4, sticky="w")
        self.mic_var = tk.StringVar()
        self.mic_box = ttk.Combobox(dev, textvariable=self.mic_var, width=38)
        self.mic_box.grid(row=1, column=1, padx=4, pady=4, sticky="w")
        ttk.Button(dev, text="刷新设备", command=self._refresh_devices,
                   width=10).grid(row=1, column=2, padx=6, pady=4)
        dev.columnconfigure(1, weight=1)

        act = ttk.Frame(self)
        act.pack(fill="x", **pad)
        self.record_btn = ttk.Button(act, text="●  开始录音", command=self._toggle_record)
        self.record_btn.pack(side="left", padx=(8, 4), ipadx=10, ipady=4)
        self.import_btn = ttk.Button(act, text="导入音频/视频文件…", command=self._import_file)
        self.import_btn.pack(side="left", padx=4, ipadx=6, ipady=4)
        self.state_var = tk.StringVar(value="就绪")
        ttk.Label(act, textvariable=self.state_var).pack(side="right", padx=10)

        bar = ttk.Frame(self)
        bar.pack(fill="x", **pad)
        self.progress = ttk.Progressbar(bar, mode="indeterminate", length=420)
        self.progress.pack(side="left", padx=8)
        ttk.Button(bar, text="设置…", command=self._open_settings).pack(side="right", padx=4)
        ttk.Button(bar, text="打开输出目录", command=self._open_output_dir).pack(side="right", padx=4)

        self.log = scrolledtext.ScrolledText(self, height=16, state="disabled",
                                             font=("Menlo" if _IS_MAC else "Consolas", 11))
        self.log.pack(fill="both", expand=True, **pad)

    def _sys_choices(self):
        try:
            return ["（自动检测 BlackHole）"] + audio_mod.list_devices()["system_sources"]
        except Exception:
            return ["（自动检测 BlackHole）"]

    def _refresh_devices(self, first: bool = False) -> None:
        def _do():
            try:
                devs = audio_mod.list_devices()
            except Exception as exc:
                if not first:
                    messagebox.showerror("设备列表", f"获取设备失败：{exc}")
                return
            mics = ["（系统默认）"] + devs["microphones"]
            self.mic_box["values"] = mics
            if self.cfg.microphone and self.cfg.microphone in mics:
                self.mic_var.set(self.cfg.microphone)
            else:
                self.mic_var.set(mics[0])
            if _IS_MAC:
                syslist = self._sys_choices()
                if self.cfg.system_source and self.cfg.system_source in syslist:
                    self.sys_var.set(self.cfg.system_source)
                else:
                    self.sys_var.set(syslist[0])
            self._log(f"设备已刷新：麦克风 {len(mics) - 1} 个"
                      + (f"，系统声音源 {len(syslist) - 1} 个" if _IS_MAC else ""))
        self.after(0, _do)

    # ---------------- 事件泵（工作线程 -> UI） ----------------

    def _emit(self, *event) -> None:
        self.event_q.put(event)

    def _poll_events(self) -> None:
        try:
            while True:
                ev = self.event_q.get_nowait()
                kind = ev[0]
                if kind == "log":
                    self._log(ev[1])
                elif kind == "stage":
                    self.state_var.set(ev[1])
                elif kind == "error":
                    self._set_busy(False)
                    self.progress.stop()
                    self._log(f"错误：{ev[1]}")
                    self.state_var.set("失败")
                    messagebox.showerror("出错了", ev[1])
                elif kind == "done":
                    self._set_busy(False)
                    self.progress.stop()
                    self.state_var.set("完成 ✔")
                    self._log(f"完成：{ev[1]}")
                    if messagebox.askyesno("完成", "纪要已生成，是否打开所在文件夹？"):
                        self._reveal(Path(ev[1]))
        except queue.Empty:
            pass
        if self.rec_started_at and self.busy and self.recorder is not None:
            try:
                dur = max(w.duration for w in getattr(self.recorder, "_writers", []))
                self.state_var.set(f"录音中… {int(dur)} 秒")
            except Exception:
                pass
        self.after(_POLL_MS, self._poll_events)

    def _log(self, text: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        self.log.configure(state="normal")
        self.log.insert("end", f"[{stamp}] {text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_busy(self, busy: bool) -> None:
        self.busy = busy
        state = "disabled" if busy else "normal"
        self.import_btn.configure(state=state)
        if busy:
            self.record_btn.configure(text="■  停止并生成纪要")
        else:
            self.record_btn.configure(text="●  开始录音")
            self.recorder = None
            self.rec_started_at = None

    # ---------------- 录音 ----------------

    def _toggle_record(self) -> None:
        if self.busy and self.recorder is not None:  # 正在录音 -> 停止
            rec = self.recorder
            self.recorder = None
            self.record_btn.configure(state="disabled")
            self._start_worker(self._finish_recording, rec)
            return
        if self.busy:
            return
        self._start_worker(self._do_record)

    def _selected(self, var, default_if_auto: str = "") -> str:
        v = var.get()
        return default_if_auto if v.startswith("（") else v

    def _do_record(self) -> None:
        cfg = self.cfg
        cfg.system_source = self._selected(self.sys_var) if _IS_MAC else ""
        cfg.microphone = self._selected(self.mic_var)
        title = self.title_var.get().strip()
        self.session_dir = pipeline_mod.new_session_dir(cfg.resolved_output_dir(), title)
        self._emit("log", f"会话目录：{self.session_dir}")
        rec = audio_mod.get_recorder(cfg.system_source, cfg.microphone)
        try:
            rec.start(self.session_dir)
        except Exception as exc:
            self._emit("error", f"启动录音失败：{exc}")
            return
        for msg in getattr(rec, "last_errors", []):
            self._emit("log", f"⚠️ {msg}")
        self.recorder = rec
        self.rec_started_at = datetime.now()
        self._emit("stage", "录音中…")

    def _finish_recording(self, rec) -> None:
        self._emit("stage", "正在停止录音并混音…")
        specs = rec.stop()
        total = sum(s.path.stat().st_size for s in specs) / 1e6
        self._emit("log", f"录音结束：{len(specs)} 轨，共 {total:.1f} MB")
        audio_path = self.session_dir / pipeline_mod.AUDIO_WAV
        duration = audio_mod.mix_to_session_audio(specs, audio_path)
        self._emit("log", f"已混为单声道 {audio_mod.TARGET_SAMPLE_RATE}Hz：{duration / 60:.1f} 分钟")
        self._run_pipeline(audio_path)

    # ---------------- 导入模式 ----------------

    def _import_file(self) -> None:
        if self.busy:
            return
        path = filedialog.askopenfilename(
            title="选择会议录音",
            filetypes=[("音视频", "*.wav *.mp3 *.m4a *.aac *.flac *.ogg *.opus *.wma *.amr *.mp4 *.mov"),
                       ("所有文件", "*.*")])
        if not path:
            return
        self._start_worker(self._import_worker, Path(path))

    def _import_worker(self, path: Path) -> None:
        self.session_dir = pipeline_mod.new_session_dir(self.cfg.resolved_output_dir(),
                                                        self.title_var.get().strip())
        self._emit("log", f"导入文件：{path}")
        self._run_pipeline(path)

    # ---------------- 管线 ----------------

    def _run_pipeline(self, audio_path: Path) -> None:
        self._emit("stage", "处理中…")
        self.after(0, self.progress.start, 24)
        try:
            minutes = pipeline_mod.run_pipeline(
                audio_path, self.cfg,
                session_dir=self.session_dir,
                title=self.title_var.get().strip(),
                started_at=self.rec_started_at,
                progress=lambda s, d: self._emit("log", f"{s}: {d}" if d else s),
            )
            self._emit("log", f"转写稿：{self.session_dir / pipeline_mod.TRANSCRIPT_MD}")
            self._emit("done", str(minutes))
        except Exception as exc:
            detail = "".join(traceback.format_exception_only(type(exc), exc)).strip()
            self._emit("error", f"{detail}\n\n会话目录保留在 {self.session_dir}，修复后可重跑续传。")

    def _start_worker(self, fn, *args) -> None:
        self._set_busy(True)

        def _wrap():
            try:
                fn(*args)
            except Exception as exc:
                self._emit("error", f"{exc}")
        self.worker = threading.Thread(target=_wrap, daemon=True)
        self.worker.start()

    # ---------------- 设置 ----------------

    def _open_settings(self) -> None:
        SettingsDialog(self, self.cfg)

    def _open_output_dir(self) -> None:
        self._reveal_dir(self.cfg.resolved_output_dir())

    def _reveal(self, path: Path) -> None:
        self._reveal_dir(path.parent if path.is_file() else path, select=path)

    def _reveal_dir(self, d: Path, select: Optional[Path] = None) -> None:
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", "-R", str(select or d)])
            elif sys.platform == "win32":
                subprocess.Popen(["explorer", "/select," + str(select or d)])
            else:
                subprocess.Popen(["xdg-open", str(d)])
        except Exception as exc:
            self._log(f"打开目录失败：{exc}")

    def _on_close(self) -> None:
        if self.busy and self.recorder is not None:
            if not messagebox.askyesno("退出", "正在录音，确定放弃本次录音并退出？"):
                return
            try:
                self.recorder.stop()
            except Exception:
                pass
        elif self.busy:
            if not messagebox.askyesno("退出", "正在处理音频，退出会中断本次任务（已完成的步骤会保留）。确定退出？"):
                return
        self.destroy()


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent: App, cfg: Config):
        super().__init__(parent)
        self.title("设置")
        self.geometry("560x480")
        self.parent_app = parent
        self.cfg = cfg
        self.transient(parent)
        self.grab_set()

        frm = ttk.Frame(self)
        frm.pack(fill="both", expand=True, padx=12, pady=10)

        ttk.Label(frm, text="百炼 API Key").grid(row=0, column=0, sticky="w", pady=4)
        self.key_var = tk.StringVar(value=cfg.api_key)
        self.key_entry = ttk.Entry(frm, textvariable=self.key_var, width=52, show="*")
        self.key_entry.grid(row=0, column=1, pady=4, sticky="we")
        self.show_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(frm, text="显示", variable=self.show_var,
                        command=self._toggle_show).grid(row=0, column=2, padx=4)

        ttk.Label(frm, text="API 网关（公司专属时填写）").grid(row=1, column=0, sticky="w", pady=4)
        self.host_var = tk.StringVar(value=cfg.api_host)
        ttk.Entry(frm, textvariable=self.host_var, width=52).grid(row=1, column=1, columnspan=2, pady=4, sticky="we")

        ttk.Label(frm, text="转写模型").grid(row=2, column=0, sticky="w", pady=4)
        self.tm_var = tk.StringVar(value=cfg.transcribe_model)
        ttk.Combobox(frm, textvariable=self.tm_var, width=24,
                     values=["fun-asr", "paraformer-v2"]).grid(row=2, column=1, sticky="w", pady=4)

        ttk.Label(frm, text="纪要模型").grid(row=3, column=0, sticky="w", pady=4)
        self.lm_var = tk.StringVar(value=cfg.llm_model)
        ttk.Combobox(frm, textvariable=self.lm_var, width=24,
                     values=["qwen-flash", "qwen-plus", "qwen-max"]).grid(row=3, column=1, sticky="w", pady=4)

        ttk.Label(frm, text="参会人（每行一个，可选；\n用于把说话人映射为姓名）").grid(
            row=4, column=0, sticky="nw", pady=4)
        self.att_text = tk.Text(frm, width=40, height=6)
        self.att_text.insert("1.0", "\n".join(cfg.attendees))
        self.att_text.grid(row=4, column=1, columnspan=2, sticky="we", pady=4)

        ttk.Label(frm, text="输出目录").grid(row=5, column=0, sticky="w", pady=4)
        self.out_var = tk.StringVar(value=str(cfg.resolved_output_dir()))
        ttk.Entry(frm, textvariable=self.out_var, width=44).grid(row=5, column=1, sticky="we", pady=4)
        ttk.Button(frm, text="浏览…", command=self._browse).grid(row=5, column=2, padx=4)

        btns = ttk.Frame(self)
        btns.pack(fill="x", padx=12, pady=8)
        ttk.Button(btns, text="保存", command=self._save).pack(side="right", padx=4)
        ttk.Button(btns, text="取消", command=self.destroy).pack(side="right", padx=4)
        frm.columnconfigure(1, weight=1)

    def _toggle_show(self) -> None:
        self.key_entry.configure(show="" if self.show_var.get() else "*")

    def _browse(self) -> None:
        d = filedialog.askdirectory(initialdir=self.out_var.get() or str(Path.home()))
        if d:
            self.out_var.set(d)

    def _save(self) -> None:
        cfg = self.cfg
        cfg.api_key = self.key_var.get().strip()
        cfg.api_host = self.host_var.get().strip()
        cfg.transcribe_model = self.tm_var.get().strip() or cfg.transcribe_model
        cfg.llm_model = self.lm_var.get().strip() or cfg.llm_model
        cfg.attendees = [l.strip() for l in
                         self.att_text.get("1.0", "end").splitlines() if l.strip()]
        cfg.output_dir = self.out_var.get().strip()
        try:
            path = save_config(cfg)
        except Exception as exc:
            messagebox.showerror("保存失败", str(exc), parent=self)
            return
        self.parent_app._log(f"设置已保存：{path}")
        self.destroy()


def main() -> None:
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
