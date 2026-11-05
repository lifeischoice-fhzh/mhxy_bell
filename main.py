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


def _low_priority():
    """进程降到「低于标准」优先级:游戏在前台时调度器先排游戏。

    用户反馈开着本工具"游戏/系统被拖卡" —— 扫描线程的截图/OCR 是周期性
    突发,和游戏抢时间片。降一档优先级后,忙时不抢、闲时照常跑,扫描节奏
    不受影响(每一拍只有几毫秒,让一让根本轮不到排队)。失败(旧系统/受限
    环境)就当没这回事,不影响启动。
    """
    try:
        import ctypes
        BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
        kernel32 = ctypes.windll.kernel32
        kernel32.SetPriorityClass(kernel32.GetCurrentProcess(),
                                  BELOW_NORMAL_PRIORITY_CLASS)
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
    else:
        # 工具只许开一个:已有实例就弹框退场(--layout 是命令行量表,不拦方便并用)
        if not core.single_instance():
            import ctypes
            ctypes.windll.user32.MessageBoxW(
                0, "降妖伏魔已经在运行,不能重复打开。", "降妖伏魔", 0x40)
            return 0
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
    _low_priority()
    core.set_app_id()          # 任务栏当成独立应用,不然显示的是 pythonw 的图标
    App().run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
