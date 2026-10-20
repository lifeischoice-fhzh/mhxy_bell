#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""梦幻西游 · 降妖伏魔(入口)

逻辑拆分:
- core.py 配置 / OCR / 截图 / 识别引擎(地基)+ 依赖检查
- gui.py  窗口的显示/隐藏/生命周期调度与按钮回调
- ui/     各窗口的布局(bell / widgets)
- tools/  铃铛自己的线程与匹配(bell)
本文件只保留命令行入口:core / tools 里的名字一律调用时现取。
"""
import argparse
import os
import sys

import core
from gui import App


def _ensure_console():
    """打包为窗口程序后没有控制台;命令行模式临时分配一个,便于看输出。"""
    if sys.stdout is None:
        try:
            import ctypes
            ctypes.windll.kernel32.AllocConsole()
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)   # UTF-8,避免中文乱码
            sys.stdout = open("CONOUT$", "w", encoding="utf-8", buffering=1)
            sys.stderr = sys.stdout
        except Exception:
            pass


def main():
    ap = argparse.ArgumentParser(description="梦幻西游降妖伏魔助手")
    ap.add_argument("--layout", action="store_true",
                    help="量当前客户端尺寸下对话框的位置,写进分辨率表"
                         "(任务栏坐标不进表:它能被拖走)")
    args = ap.parse_args()

    if args.layout:
        _ensure_console()          # 打包版才有意义,源码运行无副作用
    core.ensure_data_files()

    missing = core.check_deps()
    if missing:
        print("缺少依赖: " + ", ".join(missing))
        print("请先安装:  pip install -r "
              f"\"{os.path.join(core.BASE_DIR, 'requirements.txt')}\"")
        return 1

    if args.layout:
        from tools import bell as tools_bell      # core 已经带进来了,这里只是取名字
        return tools_bell.cmd_layout()

    core._dpi_aware()
    App().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
