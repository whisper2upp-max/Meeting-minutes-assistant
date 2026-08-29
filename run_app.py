"""PyInstaller / 直接运行入口：绝对导入，避免 __main__ 相对导入问题。"""

from meetingkit.entry import run

if __name__ == "__main__":
    run()
