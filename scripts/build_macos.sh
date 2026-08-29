#!/usr/bin/env bash
# 打包 macOS .app（在 macOS 开发机上执行）
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -x .venv/bin/python ]; then
  echo "请先创建虚拟环境：python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pyinstaller"
  exit 1
fi

.venv/bin/pyinstaller --noconfirm --clean --windowed \
  --name "会议纪要助手" \
  --paths src \
  --add-data "src/meetingkit/webui/index.html:meetingkit/webui/" \
  --add-data "assets/BlackHole2ch-0.7.1.pkg:meetingkit/assets/" \
  --hidden-import meetingkit.audio.macos_rec \
  --hidden-import webview.platforms.cocoa \
  --icon assets/app.icns \
  --osx-bundle-identifier com.meetingkit.app \
  run_app.py

echo "打包完成：dist/会议纪要助手.app"
echo "分发提示：未签名，用户首次需右键->打开；详见 docs/使用说明-macOS.md"
