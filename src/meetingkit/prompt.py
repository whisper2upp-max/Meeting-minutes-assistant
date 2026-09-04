"""纪要生成的提示词模板与详细程度定义。"""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

SYSTEM_PROMPT = (
    "你是一名专业的会议纪要撰写助手。你的任务是阅读会议转写稿，"
    "按用户指定的详细程度产出准确、结构清晰的中文会议纪要（Markdown 格式）。\n"
    "必须遵守：\n"
    "1. 只依据转写稿内容，绝不编造未提及的信息；不确定的内容标注“待确认”。\n"
    "2. 待办事项必须有负责人（若转写稿中明确）与期限（若提及），缺少的写“未明确”。\n"
    "3. 转写稿来自语音识别，可能存在同音错别字，理解时结合上下文合理纠正。\n"
    "4. 直接输出 Markdown 正文，不要输出额外解释或代码块围栏。"
)

DEFAULT_DETAIL_LEVEL = "brief"

DETAIL_LEVELS = {
    "brief": {
        "label": "简要",
        "description": "结论优先，快速浏览",
        "instruction": (
            "采用简要模式：高度压缩重复表达，优先保留主题、结论、责任人、期限和风险。"
            "讨论要点只记录影响结论的信息，每个议题通常使用 2—4 条要点。"
        ),
    },
    "standard": {
        "label": "标准",
        "description": "兼顾背景、观点与结论",
        "instruction": (
            "采用标准模式：除结论和行动项外，保留每个议题的必要背景、主要观点、"
            "关键事实以及讨论后形成的结论。合并重复发言，但不要遗漏有实质差异的意见。"
        ),
    },
    "detailed": {
        "label": "详细",
        "description": "完整保留讨论脉络",
        "instruction": (
            "采用详细模式：在不逐字复述的前提下，完整保留议题背景、讨论过程、各方观点、"
            "关键数据、分歧、决策依据、影响范围和后续安排。信息缺失时明确写“未提及”或“待确认”，"
            "不得为了显得详细而补写转写稿中不存在的内容。"
        ),
    },
}

_BRIEF_TEMPLATE = """# 会议纪要{{title_line}}

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

_STANDARD_TEMPLATE = """# 会议纪要{{title_line}}

## 基本信息
- 时间：{{started_at}}
- 参会人：{{attendees_line}}

## 会议摘要
（用 3—5 条要点概括会议目标、进展、核心结论和下一步）

## 议题讨论
（按议题分三级标题；每个议题依次记录必要背景、主要观点、关键事实和讨论结论，并注明发言人）

## 会议决议
（逐条记录明确达成一致的事项及适用范围；没有则写“本次会议未形成明确决议”）

## 待办事项
| 事项 | 负责人 | 期限 | 备注 |
|---|---|---|---|
（没有则写“无”）

## 风险与待确认
（记录风险、依赖、分歧和需要后续确认的问题；没有则写“无”）
"""

_DETAILED_TEMPLATE = """# 会议纪要{{title_line}}

## 基本信息
- 时间：{{started_at}}
- 参会人：{{attendees_line}}

## 执行摘要
（完整概括会议目标、讨论范围、主要结论、重要分歧和下一步）

## 议题与讨论记录
（按议题分三级标题，并根据转写稿实际内容使用以下小项）
- 背景与目标：
- 讨论过程与主要观点：（注明发言人，不合并存在实质差异的意见）
- 关键事实与数据：
- 分歧与待确认：
- 议题结论：

## 决策记录
| 决策 | 决策依据 | 影响范围 | 确认人 |
|---|---|---|---|
（没有则写“本次会议未形成明确决议”）

## 待办事项
| 事项 | 负责人 | 期限 | 优先级/依赖 |
|---|---|---|---|
（没有则写“无”）

## 风险、依赖与待确认
（分别列出会议中明确提到的风险、外部依赖、未决问题和所需确认人；没有则写“无”）

## 后续跟进
（仅记录会议中提出的复盘、汇报、检查点或下次会议安排；未提及则写“未提及”）
"""

_TEMPLATES = {
    "brief": _BRIEF_TEMPLATE,
    "standard": _STANDARD_TEMPLATE,
    "detailed": _DETAILED_TEMPLATE,
}


def normalize_detail_level(value: str) -> str:
    """把外部传入的详细程度收敛到稳定枚举；旧会话默认视为简要。"""
    level = str(value or "").strip().lower()
    return level if level in DETAIL_LEVELS else DEFAULT_DETAIL_LEVEL


def detail_level_info(value: str) -> dict:
    level = normalize_detail_level(value)
    return {"value": level, **DETAIL_LEVELS[level]}


def build_minutes_prompt(
    transcript_md: str,
    attendees: Optional[List[str]] = None,
    meeting_title: str = "",
    started_at: Optional[datetime] = None,
    detail_level: str = DEFAULT_DETAIL_LEVEL,
) -> List[dict]:
    """返回 OpenAI 格式的 messages 列表。"""
    detail_level = normalize_detail_level(detail_level)
    detail = DETAIL_LEVELS[detail_level]
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
        f"纪要详细程度：{detail['label']}。{detail['instruction']}\n"
        f"以下是带说话人标签与时间戳的会议转写稿，请生成会议纪要：\n\n"
        f"---转写稿开始---\n{transcript_md}\n---转写稿结束---\n\n"
        f"请严格按以下结构输出（章节顺序不可变，括号内为填写说明，不需要保留）：\n"
        f"{_TEMPLATES[detail_level]}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]
