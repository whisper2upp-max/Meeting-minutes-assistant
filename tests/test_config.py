import os
from pathlib import Path

from meetingkit.config import Config, load_config, save_config


def test_defaults_and_env_home(tmp_path, monkeypatch):
    monkeypatch.setenv("MEETINGKIT_HOME", str(tmp_path))
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    cfg = load_config()
    assert cfg.transcribe_model == "fun-asr"
    assert cfg.llm_model == "qwen-flash"
    assert cfg.api_key == ""
    assert not (tmp_path / "config.toml").exists()


def test_env_api_key_fallback(tmp_path, monkeypatch):
    monkeypatch.setenv("MEETINGKIT_HOME", str(tmp_path))
    monkeypatch.setenv("DASHSCOPE_API_KEY", "sk-env-key")
    cfg = load_config()
    assert cfg.effective_api_key() == "sk-env-key"


def test_save_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("MEETINGKIT_HOME", str(tmp_path))
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    cfg = Config(api_key="sk-test", attendees=["张三", "李四"], output_dir=str(tmp_path / "out"))
    save_config(cfg)
    loaded = load_config()
    assert loaded.api_key == "sk-test"
    assert loaded.attendees == ["张三", "李四"]
    assert loaded.resolved_output_dir() == Path(tmp_path / "out")


def test_corrupt_config_raises_with_path(tmp_path, monkeypatch):
    monkeypatch.setenv("MEETINGKIT_HOME", str(tmp_path))
    (tmp_path / "config.toml").write_text("not [ valid toml ==", encoding="utf-8")
    try:
        load_config()
        assert False, "应抛出异常"
    except RuntimeError as e:
        assert "config.toml" in str(e)


def test_api_host_url_derivation(tmp_path, monkeypatch):
    monkeypatch.setenv("MEETINGKIT_HOME", str(tmp_path))
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    # 缺省 -> 官方端点
    cfg = Config()
    assert cfg.resolved_api_host() == "https://dashscope.aliyuncs.com"
    assert cfg.llm_base_url().endswith("/compatible-mode/v1")
    assert cfg.dashscope_base_url().endswith("/api/v1")
    # 专属网关，且容错各种粘贴格式
    for pasted in ("https://ws-x.cn-beijing.maas.aliyuncs.com",
                   "https://ws-x.cn-beijing.maas.aliyuncs.com/",
                   "https://ws-x.cn-beijing.maas.aliyuncs.com/api/v1",
                   "https://ws-x.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"):
        cfg = Config(api_host=pasted)
        assert cfg.resolved_api_host() == "https://ws-x.cn-beijing.maas.aliyuncs.com", pasted
        assert cfg.dashscope_base_url() == "https://ws-x.cn-beijing.maas.aliyuncs.com/api/v1"
        assert cfg.llm_base_url() == "https://ws-x.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
