import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="仅 macOS")


def test_blackhole_installed():
    from meetingkit.audio import mac_setup
    if not mac_setup.blackhole_installed():
        pytest.skip("当前机器未安装 BlackHole；CI 只验证内置安装包")
    assert mac_setup.blackhole_installed()


def test_bundled_pkg_available():
    from meetingkit.audio import mac_setup
    p = mac_setup.bundled_pkg_path()
    assert p is not None and p.exists(), "assets/ 应内置驱动安装包（打包与开发态至少命中其一）"
    assert p.stat().st_size > 50_000, "pkg 应为完整的安装包（约 100KB）"


def test_list_devices_has_output():
    from meetingkit.audio import mac_setup
    devs = mac_setup.list_devices()
    if not any(d["outputs"] > 0 for d in devs):
        pytest.skip("当前环境没有可枚举的输出设备（常见于无声卡 CI）")
    assert any(d["outputs"] > 0 for d in devs), "至少应有一个输出设备"


def test_constants_fourcc():
    from meetingkit.audio import mac_setup as m
    assert m.kAudioHardwarePropertyDevices == 0x64657623      # 'dev#'
    assert m.kAudioHardwarePropertyDefaultOutputDevice == 0x644F7574  # 'dOut'
    assert m.SCOPE_GLOBAL == 0x676C6F62                       # 'glob'
