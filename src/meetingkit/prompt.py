"""纪要生成的提示词模板。"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

SYSTEM_PROMPT = (
    "你是一名专业的会议纪要撰写助手。你的任务是阅读会议转写稿，"
    "产出一份准确、简洁、结构清晰的中文会议纪要（Markdown 格式）。\n"
    "必须遵守：\n"
    "1. 只依据转写稿内容，绝不编造未提及的信息；不确定的内容标注“待确认”。\n"
    "2. 待办事项必须有负责人（若转写稿中明确）与期限（若提及），缺少的写“未明确”。\n"
    "3. 转写稿来自语音识别，可能存在同音错别字，理解时结合上下文合理纠正。\n"
    "4. 直接输出 Markdown 正文，不要输出额外解释或代码块围栏。"
)

_TEMPLATE = """# 会议纪要{{title_line}}

## 基本信息
- 时间：{{started_at}}
- 参会人：{{attendees_line}}

## 会议主题
（一两句话概括本次会议讨论的核心内容）

## 讨论要点
（按议题分小节，概括各方观点与关键信息，注明发言人）

## 会议决议
（明确达成一致的事项；没有则写“本次会议未形成明确决议”）

## 待办事项
| 事项 | 负责人 | 期限 |
|---|---|---|
（没有则写“无”）

## 风险与待确认
（分歧点、悬而未决的问题、需要后续确认的事项；没有则写“无”）
"""


def build_minutes_prompt(
    transcript_md: str,
    attendees: Optional[List[str]] = None,
    meeting_title: str = "",
    started_at: Optional[datetime] = None,
) -> List[dict]:
    """返回 OpenAI 格式的 messages 列表。"""
    time_str = (started_at or datetime.now()).strftime("%Y-%m-%d %H:%M")
    title_str = meeting_title.strip() or "（未提供，请根据内容概括）"
    if attendees:
        attendees_line = "、".join(attendees)
        speaker_note = (
            f"参会人名单如下，请结合转写稿中各说话人的称呼与发言内容，"
            f"将“说话人N”映射为真实姓名；把握不足的映射请在该参会人后标注“（？）”。\n"
            f"参会人：{attendees_line}\n"
            f"纪要“基本信息-参会人”一栏直接使用该名单。"
        )
    else:
        attendees_line = "（未知，见转写稿说话人）"
        speaker_note = "未提供参会人名单，请保留“说话人N”的称呼。"

    user_prompt = (
        f"{speaker_note}\n\n"
        f"会议开始时间：{time_str}\n"
        f"会议标题（用户填写，供参考）：{title_str}\n"
        f"以下是带说话人标签与时间戳的会议转写稿，请生成会议纪要：\n\n"
        f"---转写稿开始---\n{transcript_md}\n---转写稿结束---\n\n"
        f"请严格按以下结构输出（章节顺序不可变，括号内为填写说明，不需要保留）：\n"
        f"{_TEMPLATE}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
