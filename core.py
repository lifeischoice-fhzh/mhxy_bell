#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核心地基:配置/OCR/截图/识别引擎(降妖伏魔一个功能用的那部分)。

铃铛与地图在 tools/bell.py;这里只留它要用的地基。
截图(只读屏幕) -> OCR 读任务提示 -> 地图上标红点。
不读写游戏进程/内存,只认屏幕上已有的字。
"""
from __future__ import annotations

import ctypes
import json
import os
import sys
import threading
import time

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

DEFAULT_CONFIG = {
    "use_gpu": True,     # OCR 用显卡加速(DirectML),失败自动回退 CPU
    "bell_client": "",       # 降妖伏魔:用户选的那台客户端(标题/角色名)
    "bell_interval": 0.0,    # 降妖伏魔:自己的扫描间隔(0=跟着调度节奏走)
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
    # 分辨率表同理:冻结后它被捆进 _MEIPASS(_internal),而 tools/bell.py 按程序
    # 目录的 data/ 找 —— 不镜像这份,打包版永远用不上内置的两档布局表。
    src = os.path.join(_BUNDLE_DIR, "data", "bell_layouts.json")
    dst = os.path.join(BASE_DIR, "data", "bell_layouts.json")
    if (src != dst and os.path.isfile(src) and not os.path.exists(dst)):
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
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


def _dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


os.makedirs(os.path.join(BASE_DIR, "data"), exist_ok=True)


CONFIG_SECTIONS = {
    "app": ("use_gpu", "active_tool"),
    "bell": ("bell_client", "bell_interval"),
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

# 梦幻西游电脑版主窗口的窗口类名(实测)。标题比类名不可靠:
# "梦幻西游"这四个字在浏览器标签、本应用自己的窗口标题里都有。
CLIENT_WINDOW_CLASS = "MHXYMainFrame"
CLIENT_WINDOW_TITLE = "梦幻西游 ONLINE"
CLIENT_MIN_W, CLIENT_MIN_H = 400, 300     # 比这还小就不可能是客户端画面


def find_client_windows():
    """枚举梦幻西游客户端窗口。

    返回 ([(标题, [x1,y1,x2,y2]), ...], [已最小化的窗口标题, ...])。
    该窗口客户区==窗口矩形(标题栏是游戏自绘的),所以矩形就是"整个客户端画面";
    结果按屏幕位置(先上后左)排序,多开时区域编号稳定。
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    found, minimized = [], []

    def text_of(hwnd):
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 2)
        user32.GetWindowTextW(hwnd, buf, n + 2)
        return buf.value

    def cls_of(hwnd):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        return buf.value

    def visit(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        title = text_of(hwnd)
        if cls_of(hwnd) != CLIENT_WINDOW_CLASS and title != CLIENT_WINDOW_TITLE:
            return True
        if user32.IsIconic(hwnd):
            minimized.append(title or "梦幻西游")      # 最小化:截不到画面
            return True
        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True
        box = [rect.left, rect.top, rect.right, rect.bottom]
        if (box[2] - box[0] < CLIENT_MIN_W or box[3] - box[1] < CLIENT_MIN_H
                or box[0] < -10000):                  # 最小化窗口的坐标是 -32000
            return True
        found.append((title or "梦幻西游", box))
        return True

    try:
        user32.EnumWindows(proto(visit), 0)
    except Exception:
        return [], []
    found.sort(key=lambda t: (t[1][1], t[1][0]))       # 先上后左
    return found, minimized


WARMUP_TIMEOUT = 30.0      # OCR 预热超时(本机首次 GPU 预热约 1 秒,给足余量)


class Ocr:
    """RapidOCR 封装(线程安全,懒加载)。"""

    def __init__(self, log=None):
        self._engine = None
        self._lock = threading.Lock()
        self._log = log or (lambda m: None)
        self.device = "CPU"
        self.ok = True                 # warmup 那次真实推理成功过吗(False=假就绪)
        self.err = ""                  # 不健康的原因(引擎/看门狗据此重建与报错)

    def warmup(self, timeout: float = WARMUP_TIMEOUT):
        """预热:建好引擎 + 真跑一次推理,结果记在 ok 上。

        GPU(DirectML) 首次推理要初始化显存/算子(约 1 秒),提前吃掉,
        否则第一拍会明显变慢。这次推理失败**不再静默**:GPU 上先按既有
        机制回退 CPU 再试,仍然不行就把 ok 标成 False(附 err)——引擎据此
        报"识别不可用"而不是"已就绪",看门狗也能发现假就绪。

        预热整段放进临时线程跑,主线程只等 timeout:万一卡在驱动/引擎里不
        返回,这里照样标 ok=False。否则引擎线程恒活 + ok 默认 True,看门狗
        永远不动作,日志还会说"引擎已就绪"。
        """
        box: dict = {}
        done = threading.Event()

        def _work():
            try:
                box["ok"], box["err"] = self._warmup_once()
            except BaseException as e:      # 临时线程里出事也得落到 ok 上
                box["ok"], box["err"] = False, f"{type(e).__name__}: {e}"
            finally:
                done.set()

        th = threading.Thread(target=_work, name="OCR预热", daemon=True)
        th.start()
        if not done.wait(timeout):
            # 超时:那次预热的结论不再采信(卡住的线程还在就让它去),按不可用报
            self.ok = False
            self.err = f"预热超时({timeout:.0f} 秒没返回,可能卡在显卡驱动)"
            self._log(f"[OCR]{self.err},识别不可用,看门狗将重建引擎")
            return
        self.ok = bool(box.get("ok", False))
        self.err = str(box.get("err") or "")

    def _warmup_once(self):
        """真跑一次预热推理,返回 (ok, err);不直接改 self.ok(超时那次不采信)。"""
        with self._lock:
            self._get()
        dummy = np.full((32, 160, 3), 255, dtype=np.uint8)
        try:
            self._infer(dummy)
        except Exception as err:
            self._log(f"[OCR]推理初始化失败({err}),设备可能不可用")
            if str(self.device).startswith("GPU"):
                self._fallback_to_cpu(err)     # 既有机制:GPU 出问题就重建为 CPU
            try:
                self._infer(dummy)             # 回退后再试一次
            except Exception as err2:
                self._log(f"[OCR]推理仍不可用({err2}):"
                          "识别会一直报错,看门狗将重建引擎")
                return False, str(err2)
        return True, ""

    def _get(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR
            self.device = "CPU"
            try:
                cfg = load_config()
                if app_cfg(cfg).get("use_gpu", True):
                    import onnxruntime as ort
                    if "DmlExecutionProvider" in ort.get_available_providers():
                        self._engine = RapidOCR(det_use_dml=True,
                                                rec_use_dml=True,
                                                cls_use_dml=True)
                        self.device = "GPU(DirectML)"
            except Exception:
                self._engine = None
            if self._engine is None:
                self._engine = RapidOCR()
        return self._engine

    def recognize(self, img_bgr) -> str:
        return "".join(b["text"] for b in self.recognize_blocks(img_bgr))

    def _infer(self, img_bgr, limit_side=None, limit_type=None):
        """跑一次推理。limit_side / limit_type 临时改 det 的缩放(改完还原)。

        limit_type 是 det 拿哪个边长去对 limit_side:**min**(默认)=短边不够就放大,
        **max** =长边超了才缩小。字本来就大的那块传 max + 一个够大的边长,就是
        "按原像素跑、别白放大"。

        det 的这两个属性挂在引擎实例上,整段在锁里做 —— 两个线程同时识别也
        不会互相看到对方的临时值。取不到那个属性(库换实现)就按默认跑。
        """
        with self._lock:
            eng = self._get()
            det = getattr(eng, "text_det", None)
            old = getattr(det, "limit_side_len", None)
            old_type = getattr(det, "limit_type", None)
            if limit_side and old is not None:
                try:
                    det.limit_side_len = int(limit_side)
                except Exception:
                    old = None
            if limit_type and old_type is not None:
                try:
                    det.limit_type = str(limit_type)
                except Exception:
                    old_type = None
            try:
                result, _ = eng(img_bgr, use_cls=False)
            finally:
                if old is not None:
                    det.limit_side_len = old
                if old_type is not None:
                    det.limit_type = old_type
        return result or []

    def _fallback_to_cpu(self, err):
        """GPU 运行中出错时,重建为 CPU 引擎,保证识别不中断。

        重建也进锁:引擎的创建一律发生在 self._lock 里(_get 同理)。锁里先
        复查一次设备 —— 两条线程同时识别失败时,后进锁的那条发现已经回退过
        就直接回去,不会把先建好的那份 CPU 引擎再建一遍(白占一份模型内存)。
        """
        try:
            from rapidocr_onnxruntime import RapidOCR
            with self._lock:
                if not str(self.device).startswith("GPU"):
                    return
                self._log(f"[OCR]GPU 识别异常({err}),自动回退 CPU")
                self._engine = RapidOCR()
                self.device = "CPU(已回退)"
        except Exception as e:
            self._log(f"[OCR]CPU 引擎重建失败: {e}")

    def recognize_blocks(self, img_bgr, limit_side=None, limit_type=None):
        """返回带坐标的文本块列表,按 (y, x) 排序。

        limit_side: 这一次识别的 det 输入下限(默认跟着引擎配置 736)。
        小图会被 det 放大到这个下限再检测 —— 识别准一点,但**很贵**(一块
        860x240 的小区域放大到 2840x736 再跑 det)。只扫游戏界面里的一小块时
        调小它,又快又不掉准头(实测调小后连"朱紫国"都读得更对)。

        limit_type: "min"(默认,短边不足就放大)/ "max"(长边超了才缩小)。
        字本来就大的那块(对话框条带)传 max + 足够大的 limit_side,就是按
        原像素跑 det —— 实测比放大到 480 快四成,读出来的东西一样。
        """
        try:
            result = self._infer(img_bgr, limit_side, limit_type)
        except Exception as e:
            if str(self.device).startswith("GPU"):
                self._fallback_to_cpu(e)
                result = self._infer(img_bgr, limit_side, limit_type)   # CPU 重试一次
            else:
                raise
        if not result:
            return []

        def sort_key(item):
            box = item[0]
            ys = [p[1] for p in box]
            xs = [p[0] for p in box]
            return (sum(ys) / len(ys), sum(xs) / len(xs))

        blocks = []
        for box, text, conf in sorted(result, key=sort_key):
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            blocks.append({
                "text": str(text),
                "x1": int(min(xs)), "y1": int(min(ys)),
                "x2": int(max(xs)), "y2": int(max(ys)),
                "conf": float(conf),
            })
        return blocks


class Screen:
    """mss 截图封装。region 为主显示器内的相对物理像素。

    mss 实例按线程各建一个:GDI DC 是线程亲和资源(实例创建时缓存),
    在 Engine 线程建、拿到工具线程里用会失效,所以谁第一次 grab 谁
    自己惰性建(threading.local 每线程各存一份)。
    """

    def __init__(self):
        self._local = threading.local()

    @property
    def _sct(self):
        sct = getattr(self._local, "sct", None)
        if sct is None:
            import mss
            sct = mss.mss()
            self._local.sct = sct
        return sct

    def grab(self, region=None):
        sct = self._sct
        mon = sct.monitors[1]
        if region:
            x1, y1, x2, y2 = region
            box = {"left": mon["left"] + int(x1), "top": mon["top"] + int(y1),
                   "width": max(1, int(x2 - x1)), "height": max(1, int(y2 - y1))}
        else:
            box = dict(mon)
        shot = sct.grab(box)
        arr = np.asarray(shot)          # BGRA
        return np.ascontiguousarray(arr[:, :, :3])  # BGR


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
