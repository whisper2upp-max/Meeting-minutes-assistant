@echo off
rem 打包 Windows exe（在 Windows 开发机上执行）
cd /d "%~dp0.."

if not exist .venv\Scripts\python.exe (
  echo 请先创建虚拟环境：python -m venv .venv ^&^& .venv\Scripts\pip install -r requirements.txt pyinstaller
  exit /b 1
)

.venv\Scripts\pyinstaller --noconfirm --clean --windowed --onefile ^
  --name "会议纪要助手" ^
  --paths src ^
  --add-data "src\meetingkit\webui\index.html;meetingkit\webui" ^
  --add-data "src\meetingkit\webui\styles.css;meetingkit\webui" ^
  --add-data "src\meetingkit\webui\app.js;meetingkit\webui" ^
  --hidden-import meetingkit.audio.windows_rec ^
  --hidden-import pyaudiowpatch ^
  --hidden-import truststore._windows ^
  --hidden-import webview.platforms.winforms ^
  --hidden-import webview.platforms.edgechromium ^
  --version-file assets\version_info.txt ^
  --icon assets\app.ico ^
  run_app.py

echo 打包完成：dist\会议纪要助手.exe
echo 分发提示：未签名，用户首次运行 SmartScreen 选“更多信息-仍要运行”；详见 docs\使用说明-Windows.md
