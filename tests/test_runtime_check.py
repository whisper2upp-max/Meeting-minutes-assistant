import json

from meetingkit.runtime_check import main


def test_real_transcription_sdk_loads_without_network(tmp_path):
    report = tmp_path / "check.json"
    assert main([str(report)]) == 0
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["ok"]
    assert data["dashscope"] == "1.27.2"


def test_missing_sdk_fails_check_with_diagnostic(tmp_path, monkeypatch):
    from meetingkit.cloud import transcribe

    def missing():
        raise ModuleNotFoundError("No module named 'dashscope'")

    monkeypatch.setattr(transcribe, "_sdk", missing)
    report = tmp_path / "check.json"
    assert main([str(report)]) == 1
    data = json.loads(report.read_text(encoding="utf-8"))
    assert not data["ok"]
    assert "No module named 'dashscope'" in data["error"]
