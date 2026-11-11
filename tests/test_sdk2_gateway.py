"""Exercise real SDK request building with offline HTTP responses."""
import json

import requests

from meetingkit.cloud import transcribe
from meetingkit.config import load_config


def test_saved_credentials_and_gateway_survive_sdk_upgrade(tmp_path, monkeypatch):
    monkeypatch.setenv("MEETINGKIT_HOME", str(tmp_path))
    config = tmp_path / "config.toml"
    original = '[api]\nkey = "sk-existing-test"\nhost = "https://company.example"\n[output]\ndir = "saved-meetings"\n'
    config.write_text(original, encoding="utf-8")
    cfg = load_config()
    audio = tmp_path / "sample.wav"
    audio.write_bytes(b"offline-test")
    seen = []

    def request(self, method, url, **kwargs):
        seen.append((method.upper(), url, kwargs))
        if url.endswith("/uploads"):
            payload = {"output": {
                "oss_access_key_id": "test", "signature": "test", "policy": "test",
                "upload_dir": "test", "x_oss_object_acl": "private",
                "x_oss_forbid_overwrite": "true", "upload_host": "https://storage.example"}}
        elif url == "https://storage.example":
            payload = {}
        elif url.endswith("/services/audio/asr/transcription"):
            payload = {"output": {"task_id": "test-task", "task_status": "PENDING"}}
        elif url.endswith("/tasks/test-task"):
            payload = {"output": {"task_id": "test-task", "task_status": "SUCCEEDED",
                                  "results": [{"transcription_url": "https://result.example"}]}}
        elif url == "https://result.example":
            payload = {"transcripts": [{"sentences": [{"text": "测试成功", "speaker_id": 0}]}]}
        else:
            raise AssertionError(f"Unexpected SDK endpoint: {url}")
        response = requests.Response()
        response.status_code = 200
        response.headers["content-type"] = "application/json"
        response._content = json.dumps(payload).encode()
        return response

    monkeypatch.setattr(requests.Session, "request", request)
    monkeypatch.setattr(transcribe.time, "sleep", lambda _: None)
    # Same running application can switch between gateways without cached endpoints.
    for host in (cfg.dashscope_base_url(), "https://other.example/api/v1"):
        result = transcribe.transcribe_file(audio, api_key=cfg.effective_api_key(), base_url=host)
        assert result["sentences"][0]["text"] == "测试成功"
        calls = [c for c in seen if c[1].startswith(host)]
        assert len(calls) == 3  # policy, submit, poll
        for _, _, options in calls:
            assert options["headers"]["Authorization"] == "Bearer sk-existing-test"
        submit = calls[1][2]
        assert submit["headers"]["X-DashScope-OssResourceResolve"] == "enable"
    assert config.read_text(encoding="utf-8") == original
