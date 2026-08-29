import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="仅 macOS")


def test_blackhole_installed():
    from meetingkit.audio import mac_setup
    assert mac_setup.blackhole_installed(), "本机应已安装 BlackHole（开发机）"


def test_bundled_driver_available():
    from meetingkit.audio import mac_setup
    p = mac_setup.bundled_driver_path()
    assert p is not None and p.exists(), "assets/ 应内置驱动（打包与开发态至少命中其一）"
    assert (p / "Contents" / "Info.plist").exists()


def test_list_devices_has_output():
    from meetingkit.audio import mac_setup
    devs = mac_setup.list_devices()
    assert any(d["outputs"] > 0 for d in devs), "至少应有一个输出设备"


def test_constants_fourcc():
    from meetingkit.audio import mac_setup as m
    assert m.kAudioHardwarePropertyDevices == 0x64657623      # 'dev#'
    assert m.kAudioHardwarePropertyDefaultOutputDevice == 0x644F7574  # 'dOut'
    assert m.SCOPE_GLOBAL == 0x676C6F62                       # 'glob'
