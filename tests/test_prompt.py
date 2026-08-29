from meetingkit.prompt import SYSTEM_PROMPT, build_minutes_prompt


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
