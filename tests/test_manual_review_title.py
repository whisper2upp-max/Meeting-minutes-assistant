import json

from meetingkit import pipeline
from meetingkit.config import Config
from meetingkit.webui import server


def setup_meeting(tmp_path, monkeypatch):
    monkeypatch.setattr(server._state, "cfg", Config(output_dir=str(tmp_path)))
    session = tmp_path / "2026-11-11_1000"
    session.mkdir()
    minutes = session / "会议纪要.md"
    minutes.write_text("# 原标题\n\nAFC 讨论。再次确认 AFC。", encoding="utf-8")
    pipeline.save_session_metadata(session, title="原标题", attendees=["李四"], detail_level="detailed")
    return server.Api(), minutes


def test_title_persists_in_document_and_history_without_moving_files(tmp_path, monkeypatch):
    api, minutes = setup_meeting(tmp_path, monkeypatch)
    content = "# 项目周会\n\nAFC 讨论。"
    assert api.save_minutes(str(minutes), content, {}, "项目周会")["ok"]
    assert api.get_minutes(str(minutes))["session_name"] == "项目周会"
    assert api.list_sessions()["sessions"][0]["title"] == "项目周会"
    meta = pipeline.load_session_metadata(minutes.parent)
    assert meta["attendees"] == ["李四"]
    assert meta["detail_level"] == "detailed"
    assert minutes.read_text(encoding="utf-8") == content
    for title in (" ", "x" * 121, "两行\n标题"):
        assert not api.save_minutes(str(minutes), "must not overwrite", {}, title)["ok"]
        assert minutes.read_text(encoding="utf-8") == content


def test_manual_terms_persist_and_block_export_until_resolved(tmp_path, monkeypatch):
    api, minutes = setup_meeting(tmp_path, monkeypatch)
    content = minutes.read_text(encoding="utf-8")
    decisions = {"AFC": {"decision": "pending", "source": "manual"}}
    assert api.save_minutes(str(minutes), content, decisions)["ok"]
    review = api.get_minutes(str(minutes))["proofreading"]
    assert review["uncertain"][0]["source"] == "manual"
    assert api.list_sessions()["sessions"][0]["pending_terms"] == 1
    assert not api.export_minutes(str(minutes))["ok"]
    # Repeated autosave must not duplicate a manually added task.
    assert api.save_minutes(str(minutes), content, decisions)["ok"]
    assert len(api.get_minutes(str(minutes))["proofreading"]["uncertain"]) == 1
    decisions["AFC"].update(decision="replaced", replacement="AFRC")
    assert api.save_minutes(str(minutes), content.replace("AFC", "AFRC"), decisions)["ok"]
    assert api.list_sessions()["sessions"][0]["pending_terms"] == 0
    assert api.get_minutes(str(minutes))["proofreading"]["uncertain"][0]["replacement"] == "AFRC"
    destination = tmp_path / "export"
    destination.mkdir()
    monkeypatch.setattr(api, "pick_folder", lambda: str(destination))
    assert api.export_minutes(str(minutes))["ok"]
    assert "AFRC" in (destination / minutes.name).read_text(encoding="utf-8")


def test_manual_and_ai_terms_coexist_and_can_be_confirmed(tmp_path, monkeypatch):
    api, minutes = setup_meeting(tmp_path, monkeypatch)
    review_path = minutes.parent / "proofreading.json"
    review_path.write_text(json.dumps({"status": "done", "uncertain": [{"term": "项目", "reason": "AI 提示"}]}), encoding="utf-8")
    decisions = {"项目": "confirmed", "AFC": {"source": "manual", "decision": "confirmed"}}
    assert api.save_minutes(str(minutes), "AFC 项目", decisions)["ok"]
    items = api.get_minutes(str(minutes))["proofreading"]["uncertain"]
    assert len(items) == 2
    assert all(x["decision"] == "confirmed" for x in items)
    assert items[0]["reason"] == "AI 提示"
