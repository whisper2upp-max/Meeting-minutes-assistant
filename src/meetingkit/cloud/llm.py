"""qwen-flash（百炼 OpenAI 兼容端点）生成会议纪要。"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional

from openai import OpenAI, APIConnectionError, APIStatusError, RateLimitError

from ..prompt import build_minutes_prompt
from ..tls import certificate_error_help, is_certificate_verification_error

Progress = Callable[[str, str], None]

_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
_MAX_RETRIES = 3
_RETRY_BACKOFF_SEC = 3


def generate_minutes(
    transcript_md: str,
    *,
    api_key: str,
    model: str = "qwen-flash",
    attendees: Optional[List[str]] = None,
    meeting_title: str = "",
    started_at: Optional[datetime] = None,
    base_url: str = "",
    progress: Optional[Progress] = None,
) -> str:
    attendees = [a.strip() for a in (attendees or []) if a.strip()]
    messages = build_minutes_prompt(
        transcript_md, attendees=attendees, meeting_title=meeting_title,
        started_at=started_at,
    )

    endpoint = (base_url or "").strip() or _DEFAULT_BASE_URL
    client = OpenAI(api_key=api_key, base_url=endpoint)
    if progress:
        progress("minutes", f"调用 {model} 生成会议纪要…（转写稿约 {len(transcript_md)} 字符）")

    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            resp = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0.3,
                max_tokens=8192,
            )
            content = (resp.choices[0].message.content or "").strip()
            if not content:
                raise RuntimeError("模型返回了空内容")
            return _strip_code_fence(content)
        except (APIConnectionError, APIStatusError, RateLimitError, RuntimeError) as exc:
            last_exc = exc
            if is_certificate_verification_error(exc):
                raise RuntimeError(f"生成会议纪要失败：{certificate_error_help()}") from exc
            if attempt < _MAX_RETRIES:
                if progress:
                    progress("minutes", f"调用失败（{exc}），{_RETRY_BACKOFF_SEC * attempt}s 后重试 {attempt + 1}/{_MAX_RETRIES}…")
                time.sleep(_RETRY_BACKOFF_SEC * attempt)
    raise RuntimeError(f"生成会议纪要失败（已重试 {_MAX_RETRIES} 次）：{last_exc}")


def _strip_code_fence(text: str) -> str:
    """模型偶尔会把整份纪要包进 ```markdown 围栏，剥掉。"""
    if text.startswith("```"):
        first_nl = text.find("\n")
        if first_nl != -1:
            text = text[first_nl + 1:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    return text.strip() + "\n"
