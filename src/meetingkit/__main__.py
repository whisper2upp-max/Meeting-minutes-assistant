if __package__ in (None, ""):  # 被当作脚本直接执行（如 PyInstaller）
    from meetingkit.entry import run
else:  # python -m meetingkit
    from .entry import run

if __name__ == "__main__":
    run()
