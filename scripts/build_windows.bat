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
  --collect-all dashscope ^
  --add-data "src\meetingkit\webui\index.html;meetingkit\webui" ^
  --add-data "src\meetingkit\webui\styles.css;meetingkit\webui" ^
  --add-data "src\meetingkit\webui\app.js;meetingkit\webui" ^
  --add-data "src\meetingkit\webui\workspace.js;meetingkit\webui" ^
  --add-data "src\meetingkit\webui\workspace.css;meetingkit\webui" ^
  --hidden-import meetingkit.audio.windows_rec ^
  --hidden-import pyaudiowpatch ^
  --hidden-import truststore._windows ^
  --hidden-import webview.platforms.winforms ^
  --hidden-import webview.platforms.edgechromium ^
  --version-file assets\version_info.txt ^
  --icon assets\app.ico ^
  run_app.py

if errorlevel 1 exit /b 1
.venv\Scripts\python scripts\check_frozen_runtime.py "dist\会议纪要助手.exe"
if errorlevel 1 exit /b 1
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" (
  "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" scripts\windows_installer.iss
  if errorlevel 1 exit /b 1
) else (
  echo 安装 Inno Setup 6 后可生成 Setup 安装包。
)

echo 打包完成：dist\会议纪要助手.exe
echo 分发提示：未签名，用户首次运行 SmartScreen 选“更多信息-仍要运行”；详见 docs\使用说明-Windows.md
