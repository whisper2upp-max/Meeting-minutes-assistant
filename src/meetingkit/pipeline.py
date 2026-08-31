"""处理管线：音频 -> （单声道化）-> 转写 -> 纪要，每步落盘、断点续跑。

会话目录结构：
  {output_dir}/{时间戳}{标题}/
    audio.wav          提交转写的 16k 单声道音频（导入模式下为原始文件的副本）
    transcript.json    归一化转写结果（带 speaker_id）
    transcript.md      带时间戳/说话人标签的可读转写稿
    speaker_map.json   用户后期确认的说话人与参会人姓名映射
    会议纪要.md         最终纪要
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from .audio.base import read_wav_mono, resample, rms_normalize, write_wav_mono, TARGET_SAMPLE_RATE
from .cloud import transcribe as transcribe_mod
from .cloud import llm as llm_mod
from .config import Config

Progress = Callable[[str, str], None]

AUDIO_WAV = "audio.wav"
TRANSCRIPT_JSON = "transcript.json"
TRANSCRIPT_MD = "transcript.md"
SPEAKER_MAP_JSON = "speaker_map.json"
MINUTES_MD = "会议纪要.md"


def new_session_dir(output_dir: Path, title: str = "") -> Path:
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
    safe = "".join(c for c in title.strip() if c not in '/\\:*?"<>|')[:40].strip()
    name = f"{stamp}{safe}" if safe else stamp
    d = output_dir / name
    i = 1
    while d.exists():  # 同一分钟内重复创建时避免覆盖
        d = output_dir / f"{name}_{i}"
        i += 1
    d.mkdir(parents=True)
    return d


def prepare_audio(input_path: Path, session_dir: Path, progress: Optional[Progress] = None) -> Path:
    """把输入音频规整为 16k 单声道 WAV（说话人分离的要求），非 WAV 原样复制交给云端解码。"""
    session_dir.mkdir(parents=True, exist_ok=True)
    out = session_dir / AUDIO_WAV
    if out.exists():
        return out
    if input_path.suffix.lower() == ".wav":
        x, sr = read_wav_mono(input_path)
        x = resample(x, sr, TARGET_SAMPLE_RATE)
        x = rms_normalize(x)
        write_wav_mono(out, x, TARGET_SAMPLE_RATE)
        if progress:
            progress("prepare", f"已转为 {TARGET_SAMPLE_RATE}Hz 单声道（{len(x) / TARGET_SAMPLE_RATE / 60:.1f} 分钟）")
    else:
        shutil.copy2(input_path, out)
        if progress:
            progress("prepare", f"导入文件按原格式提交（{input_path.suffix}，云端解码）")
    return out


def run_pipeline(
    input_path: Path,
    cfg: Config,
    *,
    session_dir: Optional[Path] = None,
    title: str = "",
    started_at: Optional[datetime] = None,
    progress: Optional[Progress] = None,
    transcribe_fn=transcribe_mod.transcribe_file,
    minutes_fn=llm_mod.generate_minutes,
    attendees: Optional[list] = None,
) -> Path:
    """完整处理一个音频文件，返回纪要文件路径。已完成的步骤自动跳过。

    attendees 为 None 时回退到全局配置里的名单；非 None 时（含空列表）以传入值为准。
    """
    api_key = cfg.effective_api_key()
    if not api_key:
        raise RuntimeError("未配置百炼 API Key：请先在“设置”中填写（或设置环境变量 DASHSCOPE_API_KEY）。")

    session_dir = session_dir or new_session_dir(cfg.resolved_output_dir(), title)
    started_at = started_at or datetime.now()
    meeting_attendees = attendees if attendees is not None else cfg.attendees

    audio_path = prepare_audio(input_path, session_dir, progress)

    tjson = session_dir / TRANSCRIPT_JSON
    tmd = session_dir / TRANSCRIPT_MD
    if not tjson.exists():
        result = transcribe_fn(
            audio_path,
            api_key=api_key,
            model=cfg.transcribe_model,
            diarization=cfg.diarization,
            disfluency_removal=cfg.disfluency_removal,
            base_url=cfg.dashscope_base_url(),
            progress=progress,
        )
        tjson.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        if progress:
            progress("transcribe", "发现已有转写结果，跳过转写。")
        result = json.loads(tjson.read_text(encoding="utf-8"))

    if not tmd.exists():
        tmd.write_text(transcribe_mod.format_transcript_md(result["sentences"]),
                       encoding="utf-8")

    minutes_path = session_dir / MINUTES_MD
    if not minutes_path.exists():
        transcript_md = tmd.read_text(encoding="utf-8")
        minutes = minutes_fn(
            transcript_md,
            api_key=api_key,
            model=cfg.llm_model,
            attendees=meeting_attendees,
            meeting_title=title,
            started_at=started_at,
            base_url=cfg.llm_base_url(),
            progress=progress,
        )
        minutes_path.write_text(minutes, encoding="utf-8")
    elif progress:
        progress("minutes", "发现已有纪要，跳过生成。")

    clean_candidates = []
    for attendee in meeting_attendees:
        name = " ".join(str(attendee).split())
        if name and name not in clean_candidates:
            clean_candidates.append(name)
    if clean_candidates:
        mapping_path = session_dir / SPEAKER_MAP_JSON
        mapping_payload = {"version": 1, "speakers": {}}
        if mapping_path.exists():
            stored = json.loads(mapping_path.read_text(encoding="utf-8"))
            if isinstance(stored, dict):
                mapping_payload.update(stored)
        mapping_payload["candidates"] = clean_candidates
        mapping_path.write_text(
            json.dumps(mapping_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    (session_dir / "done.flag").write_text("ok", encoding="utf-8")
    return minutes_path
