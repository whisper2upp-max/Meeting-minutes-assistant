import json
from types import SimpleNamespace

from meetingkit.cloud.llm import proofread_minutes


def test_review_preserves_uncertain_terms_and_numbers():
    payload = {"corrections": [
        {"original": "以经", "replacement": "已经"},
        {"original": "营收10万", "replacement": "营收20万"},
        {"original": "爱批爱", "replacement": "API"},
    ], "uncertain": [
        {"term": "爱批爱", "reason": "可能为英文缩写，请确认"},
        {"term": "不存在", "reason": "模型误报"},
        {"term": "爱批爱", "reason": "重复"},
    ]}
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(
        create=lambda **kwargs: SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(payload)))])
    )))
    result = proofread_minutes(client, "test", "以经完成爱批爱，营收10万。爱批爱以经测试。")
    assert result == "已经完成爱批爱，营收10万。爱批爱已经测试。"
    assert len(result.review["uncertain"]) == 1
    assert result.review["corrections"] == [{"original": "以经", "replacement": "已经"}]
