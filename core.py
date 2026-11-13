#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核心地基:配置/识别引擎(降妖伏魔一个功能用的那部分)。

铃铛与地图在 tools/bell.py;截屏/OCR 在 ocr.py(与 keju 同源),客户端
窗口在 clients.py;这里只留调度、配置与 Engine 这些应用级接线。
截图(只读屏幕) -> OCR 读任务提示 -> 地图上标红点。
不读写游戏进程/内存,只认屏幕上已有的字。
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time

# Windows 进程环境在 appenv.py(单文件可拷走复用);本应用只包一层默认值
# (互斥体名/AppUserModelID 与以前逐字一致),core.XXX 的既有引用不变。
from appenv import (cleanup_runtime as _cleanup_runtime,
                    dpi_aware as _dpi_aware,
                    set_app_id as _set_app_id,
                    single_instance as _single_instance,
                    system_light_mode)


def set_app_id(app_id="MHXY.Bell"):
    """让 Windows 把本进程当成独立应用(本应用的 AppUserModelID)。"""
    _set_app_id(app_id)


def single_instance(name="Global\\MHXY_BELL_TOOL_MUTEX"):
    """工具只许开一个(本应用的互斥体名;已有实例在跑时返回 False)。"""
    return _single_instance(name)

try:
    import numpy as np
except ImportError:  # main() 会给出友好提示
    np = None

if getattr(sys, "frozen", False):          # PyInstaller 打包后
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
    _BUNDLE_DIR = getattr(sys, "_MEIPASS", BASE_DIR)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    _BUNDLE_DIR = BASE_DIR
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
LOG_PATH = os.path.join(BASE_DIR, "bell.log")
ICON_PATH = os.path.join(BASE_DIR, "data", "bell.ico")   # 窗口/任务栏图标


def cleanup_runtime(root=BASE_DIR):
    """退出扫尾:__pycache__(根/tools/ui)与本应用的旧日志 bell.log.old。

    当次的 bell.log 留着(排除故障靠它);删不掉的静默跳过。tools/ui 的
    缓存目录是本应用的布局,appenv 那边不带应用默认值,由这里显式给。
    """
    _cleanup_runtime(root,
                     dirs=("__pycache__", os.path.join("tools", "__pycache__"),
                           os.path.join("ui", "__pycache__")),
                     files=("bell.log.old",))


DEFAULT_CONFIG = {
    "use_gpu": True,     # OCR 用显卡加速(DirectML),失败自动回退 CPU
    "bell_client": "",       # 降妖伏魔:用户选的那台客户端(标题/角色名)
    "bell_interval": 0.0,    # 降妖伏魔:自己的扫描间隔(0=跟着调度节奏走)
    "bell_pos": [],          # 降妖伏魔:小窗上次的位置 [x, y](空=居中)
    "active_tool": "",       # 当前进入的功能(本应用固定 bell)
}

MIN_INTERVAL, MAX_INTERVAL = 0.4, 10.0   # 轮询间隔的合法区间(tools/bell.py 取上限)

REQUIRED_MODULES = ["numpy", "mss", "rapidocr_onnxruntime", "PIL"]


def ensure_data_files():
    """首次运行(尤其 exe)时,把内置的初始数据复制到程序目录。

    目录级的镜像只认"目标还不存在"这一次:之后的增删全归采集底图管,
    免得每次启动把删掉的旧文件又从镜像里拷回来。
    """
    import shutil
    # 打包版:地图底图(含 calib/bounds)镜像一份到程序目录。少这一份,冻结后的
    # MAP_DIR(=程序目录/data/maps)就是空的,降妖伏魔会"暂无该地图底图";
    # 源码运行两者同目录,自动跳过。
    src = os.path.join(_BUNDLE_DIR, "data", "maps")
    dst = os.path.join(BASE_DIR, "data", "maps")
    if src != dst and os.path.isdir(src) and not os.path.exists(dst):
        try:
            shutil.copytree(src, dst)
        except Exception:
            pass
    # 窗口图标同理:打包版在 _internal 里,镜像到程序目录的 data/ 才挂得上。
    src = os.path.join(_BUNDLE_DIR, "data", "bell.ico")
    dst = os.path.join(BASE_DIR, "data", "bell.ico")
    if (src != dst and os.path.isfile(src) and not os.path.exists(dst)):
        try:
            shutil.copyfile(src, dst)
        except Exception:
            pass


def check_deps() -> list[str]:
    import importlib.util
    missing = []
    for mod in REQUIRED_MODULES:
        try:
            if importlib.util.find_spec(mod) is None:
                missing.append(mod)
        except Exception:
            missing.append(mod)
    if np is None and "numpy" not in missing:
        missing.append("numpy")
    return missing
os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)


CONFIG_SECTIONS = {
    "app": ("use_gpu", "active_tool"),
    "bell": ("bell_client", "bell_interval", "ui_mode", "bell_pos"),
}
_KEY_SECTION = {k: s for s, ks in CONFIG_SECTIONS.items() for k in ks}


def key_section(key: str):
    """配置键 -> 分区名;认不出的键返回 None(调用方自行兜底/告警)。"""
    return _KEY_SECTION.get(key)


def split_config(cfg: dict) -> dict:
    """平铺配置 -> {分区: {键: 值}}。认不出归属的键放 app,免得丢。"""
    out = {s: {} for s in CONFIG_SECTIONS}
    for k, v in (cfg or {}).items():
        out[_KEY_SECTION.get(k, "app")][k] = v
    return out


def flatten_config(raw):
    """{分区: {...}} -> 平铺;老格式(平的)和非配置(非 dict)原样返回。"""
    if not isinstance(raw, dict):
        return raw
    if not any(isinstance(raw.get(s), dict) for s in CONFIG_SECTIONS):
        return raw
    out = {}
    for s in CONFIG_SECTIONS:
        part = raw.get(s)
        if isinstance(part, dict):
            out.update(part)
    for k, v in raw.items():
        if k not in CONFIG_SECTIONS and not isinstance(v, dict):
            out[k] = v
    return out


def app_cfg(cfg: dict) -> dict:
    """共享设置分区(OCR/当前功能)。缺了就地补一个空 dict。"""
    return cfg.setdefault("app", {})


def bell_cfg(cfg: dict) -> dict:
    """降妖伏魔自己的分区。"""
    return cfg.setdefault("bell", {})



def default_ui_mode(ui_mode=None) -> str:
    """小窗皮肤:a 深色 / b 明亮。

    用户选过(`bell.ui_mode` 是 a/b)就用它;没选过的第一次跑跟随系统
    (2026-10-21 用户要求:别让"明亮党"每次开都要手动切)。
    """
    mode = str(ui_mode or "")
    if mode in ("a", "b"):
        return mode
    return "b" if system_light_mode() else "a"


def load_config() -> dict:
    """读配置,运行期一律是 {app / bell} 两个分区。

    DEFAULT_CONFIG 只是"默认值表"(平的):先分区,再把文件里的值按同一张
    归属表并进去,认不出的键落到 app(免得丢)。
    """
    cfg = split_config(DEFAULT_CONFIG)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, encoding="utf-8") as f:
                saved = split_config(flatten_config(json.load(f)))
            for name, part in saved.items():     # 逐分区合并,默认值不丢
                cfg[name].update(part)
        except Exception:
            pass
    return cfg


def save_config(cfg: dict):
    """写配置(直接落分区结构)。被杀软/另一实例短暂占住文件时重试几次。

    open 也在重试圈内:.tmp 这个名字同样可能被占用,只重试 replace 不重试
    open 的话,占住的是 tmp 时照样一次就炸。
    """
    tmp = CONFIG_PATH + ".tmp"
    for i in range(4):
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            os.replace(tmp, CONFIG_PATH)
            return
        except PermissionError:
            if i == 3:
                raise
            time.sleep(0.15 * (i + 1))


from tools.bell import BellTool        # noqa: E402 降妖伏魔(独立功能)

# 截屏/OCR 在 ocr.py(与 keju 同源的单文件,同步 = 整文件覆盖;本应用多
# limit_type 快路径与耗时诊断)。这里只再导出 —— core.Ocr/Screen 的既有
# 引用(Engine/tools/check_shots)与测试补丁语义不变。
from ocr import Ocr, Screen, _err_text  # noqa: E402,F401

# 客户端窗口/游戏画布枚举在 client_common.py(与 keju 同源的单文件,同步=
# 整文件覆盖)+ clients.py(本应用口径);这里只再导出 —— core.XXX 的既有
# 引用与测试补桩(tests 直接对 core 模块属性赋 lambda)语义不变,tools 层
# 也仍只 import core(红线)。
from clients import (DLG_RATIOS,  # noqa: E402,F401
                     SUPPORTED_RES, TRK_BOXES, box_of, canvas_game_res,
                     client_name, dialog_rect, draw_box, find_client_canvases,
                     find_client_windows, ratio_of, supported_res,
                     supported_res_text, trk_rect)


class Engine(threading.Thread):
    """截图 + OCR 的执行线程:起基础设施;识别任务由铃铛自己的线程跑。"""

    def __init__(self, app):
        super().__init__(daemon=True)
        self.app = app
        # 工具线程一起来就会通过 _screen()/_ocr() 取这两个,先把它们摆好再 start
        self.screen = None
        self.ocr = Ocr(self.app.log)
        self.bell_tool = BellTool(app, lambda: self.screen,
                                  lambda: self.ocr)
        self.bell_tool.start()

    def _safe(self, name, *args):
        """按方法名执行识别任务:任何异常(含方法缺失)都记堆栈,不让线程死掉。"""
        try:
            getattr(self, name)(*args)
        except Exception:
            import traceback
            self.app.log("[引擎]任务异常(已恢复):\n"
                         + traceback.format_exc())

    @property
    def ocr_ok(self):
        """OCR 是不是真的能用(warmup 那次真实推理成功过才算)。

        看门狗的第二条判据:线程活着不等于识别可用(warmup 里推理失败曾经
        被吞掉,日志照样说"已就绪",谁也发现不了)。
        """
        return bool(getattr(self.ocr, "ok", True))

    def shutdown(self, timeout: float = 3.0):
        """停掉铃铛线程并等它退出。

        看门狗重建引擎前必须调一次:否则旧的铃铛线程还攥着自己的
        enabled 继续识别,谁也回收不了。
        """
        try:
            self.bell_tool.stop()
        except Exception as e:
            self.app.log(f"[引擎]停止工具线程失败: {e}")
        try:
            self.bell_tool.join(timeout)        # 没 start 过的线程会抛,忽略即可
        except Exception:
            pass
        if self.bell_tool.is_alive():
            self.app.log("[引擎]铃铛线程未能退出")

    def run(self):
        # 引擎初始化整段兜异常:打包版无控制台,静默死掉会让看门狗每 10 秒
        # 重建一次,所以原因必须落到日志里。
        try:
            self.screen = Screen()
            self.ocr.warmup()
            if self.ocr_ok:
                self.app.log(f"[OCR]引擎已就绪(识别设备: "
                             f"{getattr(self.ocr, 'device', 'CPU')})")
            else:
                # 假就绪:这里绝不能再打"已就绪"(否则看门狗永远发现不了)
                self.app.log("[OCR]引擎起来了但识别不可用:"
                             f"{getattr(self.ocr, 'err', '') or '推理失败'}"
                             "(看门狗会重建)")
        except BaseException as e:
            import traceback
            self.app.log(f"[OCR]引擎初始化失败: {e}")
            self.app.log(traceback.format_exc())
            return
        self._wake_tools()              # 截图/OCR 都就绪了,可以开工了
        # 识别任务全在铃铛自己的线程里跑,这条线程只剩"活着=基础设施还在"
        # 这一个作用,看门狗盯着它。
        while True:
            time.sleep(0.5)

    def refresh_tools(self):
        """按"当前进了哪个功能 + 开关"决定铃铛线程跑不跑。

        开关一律走工具自己的生命周期 API(activate / deactivate),不在外面
        直接摆 enabled —— 开/停这件事由工具自己说了算。
        """
        tool = str(app_cfg(self.app.cfg).get("active_tool") or "")
        self._switch_tool(self.bell_tool, tool == "bell" and self.bell_tool.on())
        self._wake_tools()

    def _switch_tool(self, tool, on: bool):
        """开 / 停一条工具线程(activate / deactivate 是它们的生命周期 API)。"""
        try:
            (tool.activate if on else tool.deactivate)()
        except Exception as e:                  # 工具没有这套 API:至少把标志摆对
            tool.enabled = bool(on)
            self.app.log(f"[引擎]切换工具开关失败({e})")

    def _wake_tools(self):
        """工具线程空闲时完全不轮询,状态一变就得叫它一声。"""
        self.bell_tool._wake.set()

    def cycle(self, force: bool):
        """按当前进入的功能分派一轮识别(铃铛唯一)。"""
        if str(app_cfg(self.app.cfg).get("active_tool") or "") == "bell":
            self.bell_tool.tick(force)
