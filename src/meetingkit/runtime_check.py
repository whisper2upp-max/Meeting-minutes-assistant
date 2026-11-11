"""Offline smoke check executed inside the shipped application, without opening UI."""

import json
import sys
import traceback
from pathlib import Path


def main(args: list[str]) -> int:
    if len(args) != 1:
        return 2
    report = {"ok": False, "frozen": bool(getattr(sys, "frozen", False))}
    try:
        from . import __version__
        from .cloud.transcribe import _sdk
        from importlib.metadata import version

        sdk = _sdk()
        for owner, method in (("OssUtils", "upload"),
                              ("Transcription", "async_call"),
                              ("Transcription", "fetch")):
            if not callable(getattr(sdk[owner], method, None)):
                raise RuntimeError(f"Missing SDK method: {owner}.{method}")
        if not issubclass(sdk["DashScopeException"], Exception):
            raise RuntimeError("Invalid SDK exception type")
        report.update(ok=True, version=__version__, dashscope=version("dashscope"))
    except Exception:
        report["error"] = traceback.format_exc()
    Path(args[0]).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
