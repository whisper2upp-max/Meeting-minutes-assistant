"""macOS 内录自动配置：BlackHole 驱动安装 + 录音时自动切换"多输出设备"。

设计目标：用户零手工步骤——
- 首次点录音：若检测不到 BlackHole，由界面引导一键安装（内置驱动 + 管理员密码框）
- 每次开始录音：自动按"当前输出设备 + BlackHole"重建多输出设备并切换（换耳机无需重配）
- 录音结束：自动还原为原来的输出设备，不留系统痕迹

实现说明：直接用 ctypes 调 CoreAudio 系统库（常量值为 10.13+ 系统头文件的固定值，
已在真机核对），CF 对象构造用 pyobjc 的 Foundation（pywebview 在 macOS 已依赖）。
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
from pathlib import Path

AGG_UID = "meetingkit-multi-output"
AGG_NAME = "会议内录输出"

# ---- CoreAudio 常量（FourCC，真机核对）----
kAudioObjectSystemObject = 0x1
kAudioObjectPropertyName = 0x6C6E616D            # 'lnam'
kAudioDevicePropertyDeviceUID = 0x75696420       # 'uid '
kAudioDevicePropertyStreamConfiguration = 0x736C6179  # 'slay'
kAudioHardwarePropertyDevices = 0x64657623       # 'dev#'
kAudioHardwarePropertyDefaultOutputDevice = 0x644F7574  # 'dOut'
SCOPE_GLOBAL = 0x676C6F62                        # 'glob'
SCOPE_INPUT = 0x696E7074                         # 'inpt'
SCOPE_OUTPUT = 0x6F757470                        # 'outp'

_LIB = ctypes.cdll.LoadLibrary(
    "/System/Library/Frameworks/CoreAudio.framework/CoreAudio")


class _Addr(ctypes.Structure):
    _fields_ = [("sel", ctypes.c_uint32),
                ("scope", ctypes.c_uint32),
                ("elem", ctypes.c_uint32)]


def _addr(selector: int, scope: int = SCOPE_GLOBAL) -> _Addr:
    return _Addr(selector, scope, 0)


# ---------------- 基础属性读写 ----------------

def _get_u32(obj_id: int, selector: int) -> int:
    addr = _addr(selector)
    val = ctypes.c_uint32(0)
    size = ctypes.c_uint32(4)
    err = _LIB.AudioObjectGetPropertyData(obj_id, ctypes.byref(addr), 0, None,
                                          ctypes.byref(size), ctypes.byref(val))
    if err != 0:
        raise RuntimeError(f"读 UInt32 属性失败 sel=0x{selector:x} err={err}")
    return val.value


def _get_cfstr(obj_id: int, selector: int) -> str:
    import objc
    addr = _addr(selector)
    ref = ctypes.c_void_p()
    size = ctypes.c_uint32(ctypes.sizeof(ref))
    err = _LIB.AudioObjectGetPropertyData(obj_id, ctypes.byref(addr), 0, None,
                                          ctypes.byref(size), ctypes.byref(ref))
    if err != 0 or not ref.value:
        raise RuntimeError(f"读 CFString 属性失败 sel=0x{selector:x} err={err}")
    return str(objc.objc_object(c_void_p=ref.value))


def _channels(obj_id: int, scope: int) -> int:
    addr = _addr(kAudioDevicePropertyStreamConfiguration, scope)
    size = ctypes.c_uint32(0)
    err = _LIB.AudioObjectGetPropertyDataSize(obj_id, ctypes.byref(addr), 0, None,
                                              ctypes.byref(size))
    if err != 0:
        return 0
    n = size.value // 4
    if n == 0:
        return 0
    buf = (ctypes.c_uint32 * n)()
    err = _LIB.AudioObjectGetPropertyData(obj_id, ctypes.byref(addr), 0, None,
                                          ctypes.byref(size), buf)
    return 0 if err != 0 else sum(buf)


def list_devices() -> list[dict]:
    addr = _addr(kAudioHardwarePropertyDevices)
    size = ctypes.c_uint32(0)
    err = _LIB.AudioObjectGetPropertyDataSize(kAudioObjectSystemObject,
                                              ctypes.byref(addr), 0, None,
                                              ctypes.byref(size))
    if err != 0:
        raise RuntimeError(f"枚举音频设备失败 err={err}")
    n = size.value // 4
    ids = (ctypes.c_uint32 * n)()
    _LIB.AudioObjectGetPropertyData(kAudioObjectSystemObject, ctypes.byref(addr),
                                    0, None, ctypes.byref(size), ids)
    out = []
    for dev_id in ids:
        try:
            out.append({
                "id": dev_id,
                "uid": _get_cfstr(dev_id, kAudioDevicePropertyDeviceUID),
                "name": _get_cfstr(dev_id, kAudioObjectPropertyName),
                "inputs": _channels(dev_id, SCOPE_INPUT),
                "outputs": _channels(dev_id, SCOPE_OUTPUT),
            })
        except Exception:
            continue
    return out


def get_default_output() -> dict | None:
    dev_id = _get_u32(kAudioObjectSystemObject, kAudioHardwarePropertyDefaultOutputDevice)
    for d in list_devices():
        if d["id"] == dev_id:
            return d
    return None


def set_default_output(dev_id: int) -> None:
    addr = _addr(kAudioHardwarePropertyDefaultOutputDevice)
    val = ctypes.c_uint32(dev_id)
    size = ctypes.c_uint32(4)
    err = _LIB.AudioObjectSetPropertyData(kAudioObjectSystemObject,
                                          ctypes.byref(addr), 0, None, size,
                                          ctypes.byref(val))
    if err != 0:
        raise RuntimeError(f"设置默认输出设备失败 err={err}")


# ---------------- BlackHole 驱动 ----------------

def blackhole_installed() -> bool:
    return Path("/Library/Audio/Plug-Ins/HAL/BlackHole2ch.driver").exists()


def bundled_driver_path() -> Path | None:
    """内置驱动位置：打包后在 _MEIPASS/meetingkit/assets/，开发态在项目 assets/。"""
    candidates = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        candidates.append(Path(meipass) / "meetingkit" / "assets" / "BlackHole2ch.driver")
    root = Path(__file__).resolve().parents[3]  # src/meetingkit/audio/ -> 项目根
    candidates.append(root / "assets" / "BlackHole2ch.driver")
    for c in candidates:
        if c.exists():
            return c
    return None


def install_blackhole() -> tuple[bool, str]:
    """把内置驱动装入系统（弹一次管理员密码框），成功后重启音频服务。"""
    if blackhole_installed():
        return True, "BlackHole 已安装"
    src = bundled_driver_path()
    if src is None:
        return False, "安装包内未找到驱动文件，请手动安装：brew install blackhole-2ch"
    script = (
        f"mkdir -p /Library/Audio/Plug-Ins/HAL && "
        f"rm -rf /Library/Audio/Plug-Ins/HAL/BlackHole2ch.driver && "
        f"cp -R '{src}' /Library/Audio/Plug-Ins/HAL/ && "
        f"killall coreaudiod"
    )  # 路径用 shell 单引号：避免与 AppleScript 的双引号字符串冲突
    try:
        subprocess.run(
            ["osascript", "-e",
             f'do shell script "{script}" with administrator privileges'],
            capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return False, "安装超时（密码框 2 分钟无操作）"
    if not blackhole_installed():
        return False, "驱动安装失败，请重试或手动安装：brew install blackhole-2ch"
    _rescan_portaudio()
    return True, "驱动安装完成"


def _rescan_portaudio() -> None:
    """coreaudiod 重启后让 PortAudio 重新枚举设备。"""
    try:
        import sounddevice as sd
        sd._terminate()
        sd._initialize()
    except Exception:
        pass


# ---------------- 录音前后的输出设备管理 ----------------

def prepare_for_recording(log=print) -> int | None:
    """录音前调用：确保"当前输出 + BlackHole"多输出设备为默认输出。

    返回录音前默认输出设备的 id（供 restore_output 还原），无需还原时返回 None。
    """
    devs = list_devices()
    bh = next((d for d in devs if "blackhole" in d["uid"].lower()), None)
    if bh is None:
        raise RuntimeError("BlackHole 驱动未安装")
    default = get_default_output()
    if default is None:
        raise RuntimeError("无法确定当前默认输出设备")
    if default["uid"] == AGG_UID:
        log("系统输出已是“会议内录输出”（内录生效中）")
        return None  # 已是聚合设备：本次未切换，录音后无需还原

    # 删除旧聚合（子设备可能已过期），按当前输出重建
    for d in devs:
        if d["uid"] == AGG_UID:
            _LIB.AudioHardwareDestroyAggregateDevice(d["id"])

    from Foundation import (NSArray, CFDictionaryCreate, CFStringCreateWithCString,
                            kCFBooleanFalse, kCFStringEncodingUTF8)

    def _s(x: str):
        return CFStringCreateWithCString(None, x.encode("utf-8"), kCFStringEncodingUTF8)

    import objc
    keys = [_s(k) for k in ("uid", "name", "main", "private", "stacked", "subdevices")]
    vals = [_s(AGG_UID), _s(AGG_NAME), _s(default["uid"]),
            kCFBooleanFalse, kCFBooleanFalse,
            NSArray.arrayWithArray_([
                CFDictionaryCreate(None, [_s("uid")], [_s(default["uid"])], 1, None, None),
                CFDictionaryCreate(None, [_s("uid")], [_s(bh["uid"])], 1, None, None),
            ])]
    desc = CFDictionaryCreate(None, keys, vals, len(keys), None, None)
    out_id = ctypes.c_uint32(0)
    _LIB.AudioHardwareCreateAggregateDevice(
        ctypes.c_void_p(objc.pyobjc_id(desc)), ctypes.byref(out_id))
    if out_id.value == 0:
        raise RuntimeError("创建多输出设备失败")
    prev_id = default["id"]
    set_default_output(out_id.value)
    log(f"已切换到“{AGG_NAME}”（{default['name']} + BlackHole），"
        f"录音期间系统音量条可能暂时失效")
    return prev_id


def restore_output(prev_id: int | None, log=print) -> None:
    """录音结束后还原默认输出设备。"""
    if prev_id is None:
        return
    try:
        devs = {d["id"]: d for d in list_devices()}
        if prev_id in devs:
            set_default_output(prev_id)
            log(f"已还原输出设备为“{devs[prev_id]['name']}”")
    except Exception as exc:
        log(f"还原输出设备失败：{exc}")
