#!/usr/bin/env python
"""一键配置 macOS 内录：创建“多输出设备”（当前输出 + BlackHole 2ch）并设为系统默认输出。

用法（先接好耳机，再执行）：
  .venv/bin/python scripts/setup_loopback_mac.py            # 创建/更新并切换到多输出
  .venv/bin/python scripts/setup_loopback_mac.py --restore  # 恢复为普通输出

可重复执行：每次按“当前默认输出设备”重建（换了耳机后重跑一次即可）。
"""

from __future__ import annotations

import argparse
import ctypes
import sys

import objc
import CoreAudio as CA
from Foundation import NSArray, CFDictionaryCreate, CFNumberCreate, \
    CFStringCreateWithCString, kCFBooleanFalse, kCFBooleanTrue, \
    kCFNumberSInt32Type, kCFStringEncodingUTF8

_LIB = ctypes.cdll.LoadLibrary(
    "/System/Library/Frameworks/CoreAudio.framework/CoreAudio")

AGG_UID = "meetingkit-multi-output"
AGG_NAME = "会议内录输出"

_kErrBase = 0x10000  # 'what' offset in OSStatus，用于构造属性不存在的错误码


class Addr(ctypes.Structure):
    _fields_ = [("sel", ctypes.c_uint32),
                ("scope", ctypes.c_uint32),
                ("elem", ctypes.c_uint32)]


def _addr(selector: int, scope: int = CA.kAudioObjectPropertyScopeGlobal) -> Addr:
    return Addr(selector, scope, 0)


def _cf_id(cfobj) -> ctypes.c_void_p:
    return ctypes.c_void_p(objc.pyobjc_id(cfobj))


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
    addr = _addr(selector)
    ref = ctypes.c_void_p()
    size = ctypes.c_uint32(ctypes.sizeof(ref))
    err = _LIB.AudioObjectGetPropertyData(obj_id, ctypes.byref(addr), 0, None,
                                          ctypes.byref(size), ctypes.byref(ref))
    if err != 0 or not ref.value:
        raise RuntimeError(f"读 CFString 属性失败 sel=0x{selector:x} err={err}")
    return str(objc.objc_object(c_void_p=ref.value))


def _channels(obj_id: int, scope: int) -> int:
    addr = _addr(CA.kAudioDevicePropertyStreamConfiguration, scope)
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
    addr = _addr(CA.kAudioHardwarePropertyDevices)
    size = ctypes.c_uint32(0)
    err = _LIB.AudioObjectGetPropertyDataSize(CA.kAudioObjectSystemObject,
                                              ctypes.byref(addr), 0, None,
                                              ctypes.byref(size))
    if err != 0:
        raise RuntimeError(f"枚举音频设备失败 err={err}")
    n = size.value // 4
    ids = (ctypes.c_uint32 * n)()
    _LIB.AudioObjectGetPropertyData(CA.kAudioObjectSystemObject, ctypes.byref(addr),
                                    0, None, ctypes.byref(size), ids)
    out = []
    for dev_id in ids:
        try:
            out.append({
                "id": dev_id,
                "uid": _get_cfstr(dev_id, CA.kAudioDevicePropertyDeviceUID),
                "name": _get_cfstr(dev_id, CA.kAudioObjectPropertyName),
                "inputs": _channels(dev_id, CA.kAudioObjectPropertyScopeInput),
                "outputs": _channels(dev_id, CA.kAudioObjectPropertyScopeOutput),
            })
        except Exception:
            continue
    return out


def get_default_output() -> dict | None:
    dev_id = _get_u32(CA.kAudioObjectSystemObject,
                      CA.kAudioHardwarePropertyDefaultOutputDevice)
    for d in list_devices():
        if d["id"] == dev_id:
            return d
    return None


def set_default_output(dev_id: int) -> None:
    addr = _addr(CA.kAudioHardwarePropertyDefaultOutputDevice)
    val = ctypes.c_uint32(dev_id)
    size = ctypes.c_uint32(4)
    err = _LIB.AudioObjectSetPropertyData(CA.kAudioObjectSystemObject,
                                          ctypes.byref(addr), 0, None, size,
                                          ctypes.byref(val))
    if err != 0:
        raise RuntimeError(f"设置默认输出失败 err={err}")


def _s(s: str):
    return CFStringCreateWithCString(None, s.encode("utf-8"), kCFStringEncodingUTF8)


def create_multi_output() -> None:
    devs = list_devices()
    bh = next((d for d in devs if "blackhole" in d["uid"].lower()), None)
    if bh is None:
        print("未检测到 BlackHole，请先安装：brew install blackhole-2ch（装完可能需重启 coreaudiod）")
        sys.exit(1)
    default = get_default_output()
    if default is None:
        print("无法确定当前默认输出设备")
        sys.exit(1)
    if default["uid"] == AGG_UID:
        print("当前默认输出已是“会议内录输出”。换耳机时：先在系统设置-声音切回耳机，再重跑本脚本。")
        return
    print(f"当前输出：{default['name']}")

    # 删除旧的多输出设备（子设备可能已过期）
    for d in devs:
        if d["uid"] == AGG_UID:
            _LIB.AudioHardwareDestroyAggregateDevice(d["id"])

    keys = [_s(k) for k in ("uid", "name", "main", "private", "stacked", "subdevices")]
    vals = [_s(AGG_UID), _s(AGG_NAME), _s(default["uid"]),
            kCFBooleanFalse, kCFBooleanFalse,
            NSArray.arrayWithArray_([
                CFDictionaryCreate(None, [_s("uid")], [_s(default["uid"])], 1, None, None),
                CFDictionaryCreate(None, [_s("uid")], [_s(bh["uid"])], 1, None, None),
            ])]
    desc = CFDictionaryCreate(None, keys, vals, len(keys), None, None)

    out_id = ctypes.c_uint32(0)
    _LIB.AudioHardwareCreateAggregateDevice(_cf_id(desc), ctypes.byref(out_id))
    if out_id.value == 0:
        print("创建多输出设备失败")
        sys.exit(1)
    print(f"✓ 已创建“{AGG_NAME}”（{default['name']} + BlackHole 2ch）")
    set_default_output(out_id.value)
    print(f"✓ 系统默认输出已切换为“{AGG_NAME}”")
    print("提示：多输出模式下系统音量条可能失效，请用耳机自身音量调节；"
          "不需要内录时运行 --restore 恢复。")


def restore() -> None:
    devs = list_devices()
    if not any(d["uid"] == AGG_UID for d in devs):
        print("没有找到“会议内录输出”，无需恢复。")
        return
    for d in devs:
        if d["uid"] == AGG_UID or "blackhole" in d["uid"].lower():
            continue
        if d["outputs"] > 0:
            set_default_output(d["id"])
            print(f"✓ 已恢复默认输出为“{d['name']}”。（“{AGG_NAME}”保留，下次直接切换即可）")
            return
    print("未找到可恢复的普通输出设备。")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--restore", action="store_true", help="恢复为普通输出（停止内录）")
    args = ap.parse_args()
    restore() if args.restore else create_multi_output()


if __name__ == "__main__":
    main()
