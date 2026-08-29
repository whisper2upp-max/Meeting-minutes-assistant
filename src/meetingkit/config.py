"""配置读写：~/.meetingkit/config.toml（可用环境变量 MEETINGKIT_HOME 重定向，便于测试）。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

import tomli_w

ENV_API_KEY = "DASHSCOPE_API_KEY"
ENV_HOME = "MEETINGKIT_HOME"

_DEFAULT_OUTPUT_DIR_NAME = "会议纪要"
# 官方公共端点；公司若提供专属网关（如 ws-xxx.cn-beijing.maas.aliyuncs.com）则覆盖
_DEFAULT_API_HOST = "https://dashscope.aliyuncs.com"


def config_dir() -> Path:
    base = os.environ.get(ENV_HOME)
    root = Path(base) if base else Path.home() / ".meetingkit"
    root.mkdir(parents=True, exist_ok=True)
    return root


def config_file() -> Path:
    return config_dir() / "config.toml"


def default_output_dir() -> Path:
    docs = Path.home() / "Documents"
    base = docs if docs.exists() else Path.home()
    out = base / _DEFAULT_OUTPUT_DIR_NAME
    out.mkdir(parents=True, exist_ok=True)
    return out


@dataclass
class Config:
    api_key: str = ""
    # API 网关主机（带 https://，不带路径）；空 = 官方 dashscope.aliyuncs.com
    api_host: str = ""
    transcribe_model: str = "fun-asr"
    llm_model: str = "qwen-flash"
    sample_rate: int = 16000
    system_source: str = ""      # 设备名；空 = 自动（Win 默认输出 loopback / Mac 取 BlackHole）
    microphone: str = ""         # 设备名；空 = 系统默认麦克风
    diarization: bool = True
    disfluency_removal: bool = True
    attendees: List[str] = field(default_factory=list)
    output_dir: str = ""

    def resolved_output_dir(self) -> Path:
        if self.output_dir:
            p = Path(os.path.expanduser(self.output_dir))
        else:
            p = default_output_dir()
        p.mkdir(parents=True, exist_ok=True)
        return p

    def effective_api_key(self) -> str:
        return self.api_key or os.environ.get(ENV_API_KEY, "")

    def resolved_api_host(self) -> str:
        host = (self.api_host or "").strip().rstrip("/")
        # 容错：用户可能粘贴了带 /api/v1 或 /compatible-mode/v1 的完整地址
        for suffix in ("/compatible-mode/v1", "/compatible-mode", "/api/v1", "/api"):
            if host.endswith(suffix):
                host = host[: -len(suffix)]
        return host or _DEFAULT_API_HOST

    def dashscope_base_url(self) -> str:
        return self.resolved_api_host() + "/api/v1"

    def llm_base_url(self) -> str:
        return self.resolved_api_host() + "/compatible-mode/v1"


# TOML 键名与 Config 属性名不一致的字段（其余字段与属性同名）
_KEY_ALIASES = {("api", "key"): "api_key", ("api", "host"): "api_host",
                ("output", "dir"): "output_dir"}


def load_config() -> Config:
    cfg = Config()
    path = config_file()
    if path.exists():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:  # 配置损坏时退回默认值，而不是让程序无法启动
            raise RuntimeError(f"配置文件解析失败（{path}）：{exc}") from exc
        for section, values in data.items():
            if not isinstance(values, dict):
                continue
            for k, v in values.items():
                attr = _KEY_ALIASES.get((section, k), k)
                if hasattr(cfg, attr):
                    setattr(cfg, attr, v)
    if not cfg.api_key:
        cfg.api_key = os.environ.get(ENV_API_KEY, "")
    return cfg


def save_config(cfg: Config) -> Path:
    # 与 config.example.toml 相同的分区结构，保证手工编辑与程序写入互相兼容
    data = {
        "api": {"key": cfg.api_key, "host": cfg.api_host},
        "models": {"transcribe_model": cfg.transcribe_model,
                   "llm_model": cfg.llm_model},
        "recording": {"sample_rate": cfg.sample_rate,
                      "system_source": cfg.system_source,
                      "microphone": cfg.microphone},
        "transcription": {"diarization": cfg.diarization,
                          "disfluency_removal": cfg.disfluency_removal},
        "minutes": {"attendees": cfg.attendees},
        "output": {"dir": str(cfg.resolved_output_dir())},
    }
    path = config_file()
    path.write_bytes(tomli_w.dumps(data).encode("utf-8"))
    try:  # 尽力收紧权限（Windows 上 chmod 语义有限，忽略失败）
        path.chmod(0o600)
    except OSError:
        pass
    return path
