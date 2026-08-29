# 项目进度档案（progress.md）

> 更新：2026-08-29 深夜（终版）。状态：**全链路闭环，可用**。

## 一、用户需求

1. Teams 会议录音（戴耳机，**内录系统声音 + 麦克风**）→ fun-asr 转写（说话人分离）→ qwen-flash 生成纪要，全部走百炼 API（公司禁其它 AI）
2. Windows / macOS 双平台；双击即用的 .app / .exe；界面要好看
3. **零配置**：一次性安装、驱动内置、打开就能用、不跑脚本

## 二、最终状态：全部达成

| 环节 | 状态 | 证据 |
|---|---|---|
| 云链路（上传/转写/纪要/说话人分离） | ✅ | TTS 双音色会话正确分出说话人1/2；官方端点与专属网关均验证 |
| GUI + 打包（app/zip/GitHub Actions exe） | ✅ | 26 项测试；app 带图标、内置驱动、麦克风声明 |
| 驱动内置自动安装（一次密码） | ✅ | 真机从零删除→重装→设备出现全链路 |
| 麦克风轨 | ✅ | 用户 22:01 真机验收（Codex 修复 `query_devices(None,"input")` 等） |
| **内录轨（BlackHole）** | ✅ | 2239 会话：播放的测试音频从系统轨进来，转写含两句测试音频，说话人分离正常 |
| 录音自动切多输出设备/结束还原 | ✅ | 2239 会话后默认输出自动还原为扬声器 |
| Windows | ✅ 代码完成 | WASAPI 内录免驱动；exe 由 GitHub Actions 构建，待同事实机验证 |

## 三、本次会话最后修复的两个关键问题

1. **内录全零（多输出设备坏设备）**：程序创建聚合设备时带了 `private=false` 键且未开 `stacked`，导致声音只进扬声器不进 BlackHole（或设备不可播）。正确配方：`stacked=true` 且**不带 private 键**；切换默认输出后等 1.5s 稳定。真机实证（2239）。
2. **验证方法修正**：从终端直启 app 时音频权限归属终端宿主（被系统置零），必须用 `open` 启动才归属 app——此前多次"自动验收失败"因此误判。自动验收改用 `open` + 标记文件驱动。

## 四、已知注意事项（非缺陷）

- app 为 ad-hoc 签名：**每次重新打包后首次录音可能要求重新授权麦克风**（点一次"好"即可）；正式分发建议申请 Developer ID 签名公证
- 录音期间系统音量条可能失效（多输出模式），用耳机自身音量；结束自动恢复
- 同事 Mac 分发：`dist/会议纪要助手-macOS.zip`；首次点录音弹一次驱动安装密码框 + 一次麦克风授权
- Windows：GitHub 仓库 Actions → build-app → 下载 `meetingkit-windows-exe`

## 五、关键文件

- `src/meetingkit/`：audio（录音+macOS 自动配置）/ cloud（转写+LLM）/ webui（界面）/ pipeline
- `scripts/`：build_macos.sh、build_windows.bat、smoke_test.py、setup_loopback_mac.py（手动兜底）
- `docs/`：使用说明×2、开发计划；`工作交接/`：Codex 交接文档
- `~/.meetingkit/config.toml`：API Key 与网关（不入库）
