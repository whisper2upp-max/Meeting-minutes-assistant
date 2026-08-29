#!/usr/bin/env python
"""云链路冒烟测试：验证 百炼上传/转写/LLM 全链路可用。

用法：
  .venv/bin/python scripts/smoke_test.py --file 某个真实录音.wav [--key sk-xxx]

不提供 --file 时会合成一段 6 秒的测试音频（无人声，仅验证接口连通与任务流程，
转写结果可能为空——这是预期行为；请以 --file 传入真实语音做完整验证）。
"""

from __future__ import annotations

import argparse
import sys
import tempfile
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import numpy as np

from meetingkit.cloud.llm import generate_minutes
from meetingkit.cloud.transcribe import transcribe_file, format_transcript_md, TranscribeError


def make_test_wav(path: Path, seconds: float = 6.0, sr: int = 16000) -> None:
    t = np.linspace(0, seconds, int(sr * seconds), endpoint=False)
    # 交替的两段不同音色（440/220Hz + 噪声），模拟“两个说话人”
    x = np.where((t % 3) < 1.5, np.sin(2 * np.pi * 440 * t), np.sin(2 * np.pi * 220 * t))
    x = (x * 0.3 + np.random.default_rng(42).normal(0, 0.05, len(t))).astype(np.float32)
    y = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as fh:
        fh.setnchannels(1)
        fh.setsampwidth(2)
        fh.setframerate(sr)
        fh.writeframes(y.tobytes())


def progress(stage: str, detail: str) -> None:
    print(f"[{stage}] {detail}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="真实语音文件（wav/mp3/m4a 等）")
    ap.add_argument("--key", help="百炼 API Key（缺省读 DASHSCOPE_API_KEY 或配置文件）")
    ap.add_argument("--host", default="", help="API 网关主机（公司专属网关，如 https://ws-xxx.cn-beijing.maas.aliyuncs.com）")
    ap.add_argument("--model", default="fun-asr")
    args = ap.parse_args()

    from meetingkit.config import load_config
    cfg = load_config()
    if args.host:
        cfg.api_host = args.host
    api_key = args.key or cfg.effective_api_key()
    if not api_key:
        print("缺少百炼 API Key：用 --key 提供，或设置 DASHSCOPE_API_KEY，或在配置文件中填写。")
        return 2
    print(f"网关：{cfg.resolved_api_host()}")

    if args.file:
        audio = Path(args.file).expanduser()
        if not audio.exists():
            print(f"文件不存在：{audio}")
            return 2
    else:
        audio = Path(tempfile.mkstemp(suffix=".wav")[1])
        make_test_wav(audio)
        print(f"（未提供 --file，使用合成音频 {audio} 验证接口连通性）")

    try:
        result = transcribe_file(audio, api_key=api_key, model=args.model,
                                 diarization=True, base_url=cfg.dashscope_base_url(),
                                 progress=progress)
    except TranscribeError as exc:
        print(f"转写失败：{exc}")
        return 1
    finally:
        if not args.file and audio.exists():
            audio.unlink()

    md = format_transcript_md(result["sentences"])
    print("\n===== 转写稿（前 600 字）=====")
    print(md[:600])

    print("\n===== 调用 qwen-flash 生成纪要（样例转写稿）=====")
    sample = ("`[00:00:03]` **说话人1**：大家好，今天主要同步一下新版上线的进度。\n"
              "`[00:00:12]` **说话人2**：服务端本周五可以提测，但压测环境还没好。\n"
              "`[00:00:30]` **说话人1**：那提测时间定下周一吧，小李负责跟进压测环境，周五前给我结果。\n"
              "`[00:01:02]` **说话人2**：好的。另外客户端有个登录闪退的遗留 bug，需要这次一起修掉。\n"
              "`[00:01:20]` **说话人1**：可以，安排小王这周修完。散会前确认下，会议纪要我来发。")
    minutes = generate_minutes(sample, api_key=api_key,
                               attendees=["张三", "李四", "小王"],
                               base_url=cfg.llm_base_url(), progress=progress)
    print(minutes)
    print("\n冒烟测试通过 ✔  （上传、转写、说话人分离参数、LLM 全链路可用）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
