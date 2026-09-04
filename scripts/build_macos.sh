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
  --add-data "src/meetingkit/webui/styles.css:meetingkit/webui/" \
  --add-data "src/meetingkit/webui/app.js:meetingkit/webui/" \
  --add-data "assets/BlackHole2ch-0.7.1.pkg:meetingkit/assets/" \
  --hidden-import meetingkit.audio.macos_rec \
  --hidden-import webview.platforms.cocoa \
  --icon assets/app.icns \
  --osx-bundle-identifier com.meetingkit.app \
  run_app.py

APP="dist/会议纪要助手.app"
# 关键：没有 NSMicrophoneUsageDescription 的 app 请求麦克风时会被 macOS 直接
# 静默拒绝（不弹授权框、不出现在隐私列表），必须注入声明后重新 ad-hoc 签名
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString 0.1.7" \
  "$APP/Contents/Info.plist" 2>/dev/null || \
/usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string 0.1.7" \
  "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion 0.1.7" \
  "$APP/Contents/Info.plist" 2>/dev/null || \
/usr/libexec/PlistBuddy -c "Add :CFBundleVersion string 0.1.7" \
  "$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :NSMicrophoneUsageDescription 会议声音录制需要访问麦克风，用于录入您自己的发言" \
  "$APP/Contents/Info.plist" 2>/dev/null || \
/usr/libexec/PlistBuddy -c "Add :NSMicrophoneUsageDescription string 会议声音录制需要访问麦克风，用于录入您自己的发言" \
  "$APP/Contents/Info.plist"
codesign --force --deep --sign - "$APP" >/dev/null 2>&1
zip -q -r -y "dist/会议纪要助手-macOS.zip" "$APP"

echo "打包完成：dist/会议纪要助手.app、dist/会议纪要助手-macOS.zip"
echo "分发提示：未签名，用户首次需右键->打开；详见 docs/使用说明-macOS.md"
