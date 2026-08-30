import sys

import meetingkit

from meetingkit.tls import (certificate_error_help,
                            enable_windows_system_trust,
                            is_certificate_verification_error)


def test_system_trust_is_only_injected_on_windows():
    calls = []

    assert enable_windows_system_trust(
        platform_name="darwin", injector=lambda: calls.append("called")
    ) is False
    assert calls == []

    assert enable_windows_system_trust(
        platform_name="win32", injector=lambda: calls.append("called")
    ) is True
    assert calls == ["called"]


def test_application_bootstrap_activates_native_trust_on_windows():
    assert meetingkit.WINDOWS_SYSTEM_TRUST_ACTIVE is (sys.platform == "win32")


def test_system_trust_injection_failure_is_actionable():
    def fail():
        raise OSError("CryptoAPI unavailable")

    try:
        enable_windows_system_trust(platform_name="win32", injector=fail)
        assert False, "注入失败时应抛出明确异常"
    except RuntimeError as exc:
        assert "Windows 系统证书库" in str(exc)
        assert "CryptoAPI unavailable" in str(exc)


def test_certificate_error_is_found_in_nested_exception_chain():
    try:
        try:
            raise OSError("[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer certificate")
        except OSError as inner:
            raise RuntimeError("request failed") from inner
    except RuntimeError as outer:
        assert is_certificate_verification_error(outer)

    assert not is_certificate_verification_error(RuntimeError("connection timed out"))
    assert "不要关闭证书校验" in certificate_error_help()
