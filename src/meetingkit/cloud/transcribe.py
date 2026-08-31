"""百炼录音文件转写（fun-asr）：本地文件上传临时存储 -> 异步转写 -> 轮询 -> 解析结果。

支持公司专属网关（ws-*.maas.aliyuncs.com）：通过 base_url 参数覆盖官方端点，
在首次 import dashscope 之前设置 DASHSCOPE_HTTP_BASE_URL 生效。
依赖的 SDK 能力（dashscope>=1.27）：
- dashscope.utils.oss_utils.OssUtils.upload  本地文件 -> oss:// 临时 URL（48 小时有效）
- dashscope.audio.asr.transcription.Transcription.async_call / fetch
  注：oss:// URL 需要请求头 X-DashScope-OssResourceResolve: enable，转写接口不会自动添加。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Callable, List, Mapping, Optional

import requests

from ..tls import certificate_error_help, is_certificate_verification_error

Progress = Callable[[str, str], None]

_POLL_INTERVAL_SEC = 5
_POLL_TIMEOUT_SEC = 60 * 60  # 服务端最长支持 12 小时音频，留足裕量

# 惰性加载：必须在设置 DASHSCOPE_HTTP_BASE_URL 之后才能 import dashscope
_sdk_cache = None


def _sdk(base_url: str = ""):
    global _sdk_cache
    if _sdk_cache is None:
        url = (base_url or "").strip().rstrip("/")
        if url:
            os.environ["DASHSCOPE_HTTP_BASE_URL"] = url
        from dashscope.audio.asr.transcription import Transcription
        from dashscope.common.error import DashScopeException
        from dashscope.utils.oss_utils import OssUtils
        _sdk_cache = {"Transcription": Transcription,
                      "OssUtils": OssUtils,
                      "DashScopeException": DashScopeException}
    return _sdk_cache


# 常见云端转写错误码 -> 可操作的中文提示
_ASR_ERROR_HINTS = {
    "ASR_RESPONSE_HAVE_NO_WORDS": (
        "音频中没有识别到语音内容。常见原因：录音太短、全程无人说话、"
        "或内录未生效（日志里“录音结束”应为 2 轨）。请确认设备后重试。"),
    "FILE_DOWNLOAD_FAILED": "云端下载音频文件失败，请重试（临时存储链接 48 小时有效）。",
    "AUDIO_TRANSCODE_FAILED": "音频解码失败，请换 WAV/MP3 等常见格式重试。",
    "FILE_TOO_LARGE": "音频文件过大，请拆分后重试。",
}


def _friendly_task_error(output) -> str:
    raw = json.dumps(output or {}, ensure_ascii=False)
    for code, hint in _ASR_ERROR_HINTS.items():
        if code in raw:
            return hint + f"（错误码 {code}）"
    return f"云端转写失败：{raw[:300]}"


class TranscribeError(RuntimeError):
    pass


def _network_error(prefix: str, exc: BaseException) -> TranscribeError:
    if is_certificate_verification_error(exc):
        return TranscribeError(f"{prefix}：{certificate_error_help()}")
    return TranscribeError(f"{prefix}：{exc}")


def _log(progress: Optional[Progress], stage: str, detail: str = "") -> None:
    if progress:
        progress(stage, detail)


def upload_audio(file_path: Path, *, api_key: str, model: str, base_url: str = "",
                 progress: Optional[Progress] = None) -> str:
    """上传本地音频到百炼临时存储，返回 oss:// URL（48 小时内有效）。"""
    sdk = _sdk(base_url)
    _log(progress, "upload", f"上传音频到临时存储：{file_path.name} "
                             f"({file_path.stat().st_size / 1e6:.1f} MB)")
    try:
        oss_url, _ = sdk["OssUtils"].upload(model=model, file_path=str(file_path),
                                            api_key=api_key)
    except sdk["DashScopeException"] as exc:
        if is_certificate_verification_error(exc):
            raise _network_error("音频上传失败", exc) from exc
        raise TranscribeError(
            f"音频上传失败：{exc}\n请检查 API Key、网络与网关地址（默认 dashscope.aliyuncs.com，"
            f"公司专属网关在“设置”中填写）。"
        ) from exc
    except Exception as exc:
        raise _network_error("音频上传失败", exc) from exc
    if not oss_url or not oss_url.startswith("oss://"):
        raise TranscribeError(f"音频上传返回异常 URL：{oss_url!r}")
    return oss_url


def transcribe_file(
    file_path: Path,
    *,
    api_key: str,
    model: str = "fun-asr",
    diarization: bool = True,
    disfluency_removal: bool = True,
    speaker_count: Optional[int] = None,
    base_url: str = "",
    progress: Optional[Progress] = None,
) -> dict:
    """转写本地音频文件，返回归一化结果 dict：
    {"sentences": [{"begin_ms", "end_ms", "text", "speaker_id"}], "raw": {...}}
    """
    sdk = _sdk(base_url)
    oss_url = upload_audio(file_path, api_key=api_key, model=model,
                           base_url=base_url, progress=progress)

    params: dict = {}
    if diarization:
        params["diarization_enabled"] = True
        if speaker_count:
            params["speaker_count"] = speaker_count
    if disfluency_removal:
        params["disfluency_removal_enabled"] = True

    _log(progress, "submit", f"提交转写任务（模型 {model}，说话人分离={'开' if diarization else '关'}）")
    try:
        task = sdk["Transcription"].async_call(
            model=model,
            file_urls=[oss_url],
            api_key=api_key,
            headers={"X-DashScope-OssResourceResolve": "enable"},
            **params,
        )
    except Exception as exc:
        raise _network_error("转写任务提交失败", exc) from exc

    task_id = _extract(task, "output", "task_id") or ""
    if task.status_code != 200 or not task_id:
        raise TranscribeError(
            f"转写任务提交失败：HTTP {task.status_code} "
            f"code={getattr(task, 'code', '')} message={getattr(task, 'message', '')}"
        )

    _log(progress, "transcribe", f"任务已提交（id={task_id}），等待云端转写…")
    started = time.monotonic()
    while True:
        status = _extract(task, "output", "task_status") or ""
        if status == "SUCCEEDED":
            break
        if status == "FAILED":
            raise TranscribeError(_friendly_task_error(_extract(task, "output")))
        if time.monotonic() - started > _POLL_TIMEOUT_SEC:
            raise TranscribeError("转写超时（超过 60 分钟未完成）。")
        time.sleep(_POLL_INTERVAL_SEC)
        try:
            task = sdk["Transcription"].fetch(task, api_key=api_key)
        except sdk["DashScopeException"] as exc:
            raise _network_error("查询转写任务失败", exc) from exc
        _log(progress, "transcribe",
             f"云端处理中… 已等待 {int(time.monotonic() - started)} 秒（状态 {status or 'PENDING'}）")

    result_url = ""
    results = _extract(task, "output", "results") or []
    if results and isinstance(results[0], dict):
        result_url = results[0].get("transcription_url", "")
    if not result_url:
        raise TranscribeError(f"转写成功但未返回结果 URL：{json.dumps(_extract(task, 'output') or {}, ensure_ascii=False)[:500]}")

    _log(progress, "transcribe", "下载转写结果…")
    try:
        detail = requests.get(result_url, timeout=120).json()
    except Exception as exc:
        raise _network_error("下载转写结果失败", exc) from exc

    sentences = _parse_sentences(detail)
    if not sentences:
        preview = json.dumps(detail, ensure_ascii=False)[:500]
        raise TranscribeError(f"转写结果中没有识别到任何语音内容。原始返回（截断）：{preview}")
    _log(progress, "transcribe", f"转写完成，共 {len(sentences)} 段。")
    return {"sentences": sentences, "raw": detail}


def _extract(obj, *keys):
    """兼容 DashScopeResponse 的 output（可能是对象或 dict）。"""
    cur = obj
    for k in keys:
        if cur is None:
            return None
        if isinstance(cur, dict):
            cur = cur.get(k)
        else:
            cur = getattr(cur, k, None)
    return cur


def _parse_sentences(detail: dict) -> List[dict]:
    sentences: List[dict] = []
    for transcript in detail.get("transcripts", []) or []:
        for s in transcript.get("sentences", []) or []:
            if not isinstance(s, dict) or not s.get("text"):
                continue
            sentences.append({
                "begin_ms": int(s.get("begin_time", 0) or 0),
                "end_ms": int(s.get("end_time", 0) or 0),
                "text": str(s.get("text", "")).strip(),
                # 说话人分离关闭时字段缺失，统一成 -1
                "speaker_id": int(s["speaker_id"]) if s.get("speaker_id") is not None else -1,
            })
    sentences.sort(key=lambda x: x["begin_ms"])
    return sentences


def format_transcript_md(
    sentences: List[dict],
    speaker_names: Optional[Mapping[int, str]] = None,
) -> str:
    """把转写结果排版为 Markdown，可使用用户确认后的说话人姓名。"""
    speaker_names = speaker_names or {}
    has_speaker = any(s["speaker_id"] >= 0 for s in sentences)
    lines: List[str] = []
    last_speaker = None
    for s in sentences:
        ts = _fmt_ts(s["begin_ms"])
        if has_speaker:
            spk = s["speaker_id"]
            if spk == last_speaker:  # 同一说话人连续发言合并展示
                lines[-1] = lines[-1].rstrip() + s["text"]
                continue
            last_speaker = spk
            label = speaker_names.get(spk) or f"说话人{spk + 1}"
            lines.append(f"`[{ts}]` **{label}**：{s['text']}")
        else:
            lines.append(f"`[{ts}]` {s['text']}")
    return "\n\n".join(lines) + "\n"


def _fmt_ts(ms: int) -> str:
    sec = ms // 1000
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"
