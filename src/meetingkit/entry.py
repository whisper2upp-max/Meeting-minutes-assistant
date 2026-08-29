"""统一入口：优先启动 pywebview 新版界面，异常时回退 Tkinter 简版界面。"""

from __future__ import annotations

import sys


def run() -> None:
    try:
        from .webui.server import main as web_main
        web_main()
    except Exception as exc:  # webview 不可用时兜底（同事机器环境各异）
        print(f"新版界面启动失败（{exc}），回退到简版界面", file=sys.stderr)
        from .gui.app import main as tk_main
        tk_main()
