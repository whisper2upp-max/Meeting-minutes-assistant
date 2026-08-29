"""meetingkit —— 会议录音转写与纪要生成工具（百炼 fun-asr + qwen-flash）。"""

import os

__version__ = "0.1.0"


def _bypass_proxy_for_aliyun() -> None:
    """对阿里云域名绕过本机代理。

    公司网络对百炼是直连认证的；而本机系统代理（Clash 等，macOS 上 Python 的
    requests/httpx 会读取、curl 不会）可能拦截到 *.maas.aliyuncs.com 的连接，
    表现为 SSL UNEXPECTED_EOF。百炼转写的上传与结果下载也都在 aliyuncs.com
    域内，统一绕过。
    """
    domain = "aliyuncs.com"
    for var in ("NO_PROXY", "no_proxy"):
        cur = os.environ.get(var, "")
        if domain not in cur:
            os.environ[var] = f"{cur},{domain}" if cur else domain


_bypass_proxy_for_aliyun()
