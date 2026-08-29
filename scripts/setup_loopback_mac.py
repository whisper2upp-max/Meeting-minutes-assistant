#!/usr/bin/env python
"""（可选的）手动配置入口——正常使用无需运行本脚本，程序会在录音时自动完成配置。

  .venv/bin/python scripts/setup_loopback_mac.py            # 持久切换到内录输出
  .venv/bin/python scripts/setup_loopback_mac.py --restore  # 切回普通输出
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from meetingkit.audio import mac_setup


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--restore", action="store_true", help="恢复为普通输出（停止内录）")
    args = ap.parse_args()
    if args.restore:
        for d in mac_setup.list_devices():
            if d["uid"] != mac_setup.AGG_UID and "blackhole" not in d["uid"].lower() and d["outputs"] > 0:
                mac_setup.set_default_output(d["id"])
                print(f"✓ 已恢复默认输出为“{d['name']}”")
                return
        print("未找到可恢复的普通输出设备")
        return
    if not mac_setup.blackhole_installed():
        ok, msg = mac_setup.install_blackhole()
        print(msg)
        if not ok:
            sys.exit(1)
    mac_setup.prepare_for_recording(log=print)
    print("✓ 内录输出已生效（保持到手动 --restore）")


if __name__ == "__main__":
    main()
