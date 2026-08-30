"""TLS 启动配置与证书错误识别。"""

from __future__ import annotations

import sys
from typing import Callable, Optional


_CERTIFICATE_ERROR_MARKERS = (
    "certificate_verify_failed",
    "certificate verify failed",
    "unable to get local issuer certificate",
    "self-signed certificate in certificate chain",
)


def enable_windows_system_trust(
    *,
    platform_name: Optional[str] = None,
    injector: Optional[Callable[[], None]] = None,
) -> bool:
    """让 Windows 版通过 CryptoAPI 使用系统信任证书库。

    必须在 requests、urllib3、httpx 和 DashScope SDK 导入前调用。应用自身拥有
    Python 进程，因此这里使用 truststore 的全局注入模式是有意为之。
    """
    current_platform = platform_name or sys.platform
    if current_platform != "win32":
        return False

    if injector is None:
        try:
            from truststore import inject_into_ssl
        except ImportError as exc:  # 打包遗漏依赖时给出明确根因
            raise RuntimeError(
                "Windows 系统证书组件缺失，请重新安装官方发布包。"
            ) from exc
        injector = inject_into_ssl

    try:
        injector()
    except Exception as exc:
        raise RuntimeError(f"无法启用 Windows 系统证书库：{exc}") from exc
    return True


def is_certificate_verification_error(exc: BaseException) -> bool:
    """检查异常及其 cause/context 链是否属于 TLS 证书校验失败。"""
    pending = [exc]
    visited: set[int] = set()
    while pending:
        current = pending.pop()
        marker = id(current)
        if marker in visited:
            continue
        visited.add(marker)
        detail = str(current).lower()
        if any(token in detail for token in _CERTIFICATE_ERROR_MARKERS):
            return True
        for nested in (current.__cause__, current.__context__):
            if nested is not None:
                pending.append(nested)
    return False


def certificate_error_help() -> str:
    return (
        "HTTPS 证书校验失败。Windows 版会读取系统信任证书库，请确认公司根证书"
        "已安装；如果 PowerShell 中 curl.exe 可以访问该地址但程序仍失败，请更新或"
        "重新安装最新版。不要关闭证书校验。"
    )
