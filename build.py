# -*- coding: utf-8 -*-
"""一键打包脚本：把 按键显示.py 打包成单文件 exe。

用法：
    pip install pyinstaller
    python build.py
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ICON = os.path.join(HERE, "按键显示.ico")
SCRIPT = os.path.join(HERE, "按键显示.py")


def main():
    if not os.path.isfile(ICON):
        print("未找到 %s，将不带图标打包。" % ICON)
        icon_args = []
    else:
        icon_args = ["--icon", ICON]

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm",
        "--onefile",
        "--noconsole",
        "--exclude-module", "numpy",   # 用不到，排除后体积小 12 MB
        "--name", "按键显示",
        *icon_args,
        SCRIPT,
    ]
    print(" ".join(cmd))
    subprocess.check_call(cmd, cwd=HERE)
    out = os.path.join(HERE, "dist", "按键显示.exe")
    print()
    if os.path.isfile(out):
        print("打包完成：%s（%.1f MB）" % (out, os.path.getsize(out) / 1048576))
    else:
        print("打包结束，但未找到输出文件，请检查上方日志。")


if __name__ == "__main__":
    main()
