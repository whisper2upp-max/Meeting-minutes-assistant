# 会议纪要助手

Teams 会议（也适用于任何会议软件）**内录 + 麦克风录音 → 百炼 fun-asr 转写（自动区分说话人）→ qwen-flash 生成结构化会议纪要**。Windows / macOS 双平台，可打包分发给同事。网络请求只指向 `dashscope.aliyuncs.com`（或公司专属网关）。

**零手工配置**：macOS 录音驱动（BlackHole）已内置，首次点录音自动安装（一次管理员密码）；录音时自动创建"多输出设备"边听边录、结束自动还原；换耳机自动适配。Windows 使用系统自带 WASAPI 内录，天然零配置。

## 快速开始（开发机）

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt   # Windows 下会额外安装 pyaudiowpatch
.venv/bin/python -m pytest                  # 单元测试
.venv/bin/python -m meetingkit              # 启动图形界面（需 src 在 PYTHONPATH）
```

启动 GUI 的等价方式：`PYTHONPATH=src .venv/bin/python src/meetingkit/__main__.py`

## 云链路冒烟（首次部署务必执行）

```bash
.venv/bin/python scripts/smoke_test.py --file 一段真实录音.wav --key sk-xxx
# 公司专属网关（ws-*.maas.aliyuncs.com）加：--host https://ws-xxx.cn-beijing.maas.aliyuncs.com
```

验证：临时存储上传、fun-asr 转写（说话人分离）、qwen-flash 纪要生成全链路。

> 专属网关：在 GUI「设置 → API 网关」或 `~/.meetingkit/config.toml` 的 `[api] host` 填写即可，官方端点留空。本机代理（Clash 等）对 `aliyuncs.com` 的干扰已自动绕过。

## 打包分发

```bash
scripts/build_macos.sh        # 产出 dist/会议纪要助手.app
scripts/build_windows.bat     # Windows 机器上执行，产出 dist/会议纪要助手.exe
```

用户文档见 [docs/使用说明-macOS.md](docs/使用说明-macOS.md) 与 [docs/使用说明-Windows.md](docs/使用说明-Windows.md)。

## 目录结构

```
src/meetingkit/
  entry.py          # 统一入口：pywebview 新版界面优先，异常回退 Tkinter 简版
  config.py         # ~/.meetingkit/config.toml 读写（API Key、网关、模型、参会人）
  audio/            # 录音：Windows WASAPI loopback / macOS sounddevice(BlackHole)，混单声道
  cloud/transcribe.py  # fun-asr：OssUtils 临时存储上传 -> 异步转写(diarization) -> 轮询解析
  cloud/llm.py         # qwen-flash：compatible-mode OpenAI 端点，带重试
  pipeline.py      # 音频->转写->纪要 串联，每步落盘可断点续跑
  prompt.py        # 纪要提示词模板
  webui/           # 新版界面：pywebview + 单文件 HTML/CSS/JS（步骤条/录音按钮/设置弹窗/日志）
  gui/app.py       # Tkinter 简版界面（webview 不可用时的兜底）
tests/             # 纯逻辑单测（不联网）
scripts/           # 冒烟脚本 + 双平台打包脚本
```

## 设计要点

- 说话人分离要求**单声道**：内录轨与麦克风轨各自 RMS 归一后混合，避免一轨压过另一轨破坏分离效果
- 断点续跑：会话目录依次产出 `audio.wav → transcript.json → transcript.md → 会议纪要.md`，重跑自动跳过已完成步骤
- API Key 只存本机 `~/.meetingkit/config.toml`（权限 600），不进安装包
- 成本参考：fun-asr ≈ 0.79 元/小时，qwen-flash 每场 < 1 分钱
