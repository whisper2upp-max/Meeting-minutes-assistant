from meetingkit.cloud.llm import resolve_minutes_model
from meetingkit.prompt import (DEFAULT_DETAIL_LEVEL, SYSTEM_PROMPT,
                               build_minutes_prompt, detail_level_info,
                               normalize_detail_level)


def test_messages_structure_and_attendees():
    msgs = build_minutes_prompt("转写内容", attendees=["张三"],
                                meeting_title="周会", started_at=None)
    assert [m["role"] for m in msgs] == ["system", "user"]
    assert "不" in SYSTEM_PROMPT  # 约束性系统提示存在
    user = msgs[1]["content"]
    assert "张三" in user
    assert "周会" in user
    assert "转写内容" in user
    assert "待办事项" in user and "会议决议" in user


def test_without_attendees_keeps_speaker_labels():
    msgs = build_minutes_prompt("转写内容")
    assert "说话人N" in msgs[1]["content"]
    assert "映射为真实姓名" not in msgs[1]["content"]  # 未提供名单时不应有映射指令
    assert "（未提供" in msgs[1]["content"]  # 标题缺省占位


def test_minutes_detail_levels_use_distinct_structures():
    brief = build_minutes_prompt("转写", detail_level="brief")[1]["content"]
    standard = build_minutes_prompt("转写", detail_level="standard")[1]["content"]
    detailed = build_minutes_prompt("转写", detail_level="detailed")[1]["content"]

    assert "纪要详细程度：简要" in brief
    assert "## 会议主题" in brief
    assert "纪要详细程度：标准" in standard
    assert "## 议题讨论" in standard
    assert "纪要详细程度：详细" in detailed
    assert "## 决策记录" in detailed
    assert "讨论过程与主要观点" in detailed


def test_detail_level_falls_back_and_detailed_upgrades_default_model():
    assert normalize_detail_level("unknown") == DEFAULT_DETAIL_LEVEL
    assert detail_level_info("standard")["label"] == "标准"
    assert resolve_minutes_model("qwen-flash", "detailed") == "qwen-plus"
    assert resolve_minutes_model("qwen-max", "detailed") == "qwen-max"
    assert resolve_minutes_model("qwen-flash", "standard") == "qwen-flash"
