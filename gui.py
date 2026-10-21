"""界面层:窗口生命周期调度与各按钮回调(布局在 ui/ 下)。"""
import os
import time

import core                 # 地基:配置/截图/OCR/引擎与键名归属表
                            # (一律 core.xxx 现取,别再拷名字过来:
                            #  测试里 patch 的是 core 上的那份)
from tools import bell as tools_bell   # 底图/标定归降妖伏魔自己
from ui import bell as ui_bell
from ui import widgets as ui_widgets   # 摆位/动效:窗口共用这一份
from ui.widgets import freeze_screen, stop_anim, pop_in


ENGINE_RESTART_MAX = 3    # 看门狗连续重建上限:到顶就停手,别每 10 秒重建一次刷日志


def rects_overlap(a, b, pad=0):
    """两个矩形 [x1,y1,x2,y2] 有没有相交(pad 给点余量)。"""
    if not a or not b:
        return False
    return (a[0] - pad < b[2] and b[0] - pad < a[2]
            and a[1] - pad < b[3] and b[1] - pad < a[3])


def scale_rect(rect, k):
    """矩形坐标 / k(k = 物理像素 / Tk 逻辑像素)。

    系统缩放 125% 时,Tk 的 winfo_* 是 1536×864 那套坐标,而截图(mss)和
    窗口矩形(winuser)是 1920×1080 那套 —— 两套混着比会判错。
    """
    if not rect or not k or k == 1.0:
        return rect
    return [int(v / k) for v in rect]


def screen_scale(root):
    """物理像素 / Tk 逻辑像素 的倍率;取不到按 1 算。"""
    try:
        import mss
        with mss.mss() as sct:
            phys = sct.monitors[1]["width"]
        logical = root.winfo_screenwidth()
        if phys > 0 and logical > 0:
            return phys / float(logical)
    except Exception:
        pass
    return 1.0


def client_under_cursor():
    """鼠标所在的那个客户端窗口矩形 [x1,y1,x2,y2];取不到返回 None。

    多开时鼠标在哪个客户端上,要采的就是那个(不是固定取第一个);窗口小到
    不合理(比如最小化后只剩个壳)就返回 None,调用方退回整屏。
    """
    try:
        found, _mini = core.find_client_windows()
    except Exception:
        return None
    if not found:
        return None
    try:
        import ctypes
        from ctypes import wintypes
        p = wintypes.POINT()
        ctypes.windll.user32.GetCursorPos(ctypes.byref(p))
        cur = (int(p.x), int(p.y))
    except Exception:
        cur = None
    picks = [r for _t, r in found
             if cur and r[0] <= cur[0] <= r[2] and r[1] <= cur[1] <= r[3]]
    rect = max(picks or [r for _t, r in found],
               key=lambda r: (r[2] - r[0]) * (r[3] - r[1]))
    try:
        x1, y1, x2, y2 = [int(v) for v in rect]
    except Exception:
        return None
    if x2 - x1 < 200 or y2 - y1 < 200:
        return None
    return [x1, y1, x2, y2]


# ---------------- GUI ----------------

POLL_MS = 50      # 界面刷新间隔:小窗的红点/日志都靠它落屏(50ms 人眼看不出延迟)

class App:
    """组合 Tk 根窗口与各工作线程。"""

    # ---- 配置读写:所有回调都碰,按归属表归到对应分区 ----
    def _section(self, key):
        """查归属表;认不出的键记一条警告(打错键别静默落进 app 分区)。"""
        section = core.key_section(key)
        if section is not None:
            return section
        seen = getattr(self, "_unknown_keys", None)
        if seen is None:
            seen = self._unknown_keys = set()
        if key not in seen:
            seen.add(key)
            self.log(f"[配置]键「{key}」不在归属表里,已暂存到 app 分区")
        return "app"

    def _get(self, key, default=None):
        return self.cfg.setdefault(self._section(key), {}).get(key, default)

    def _set(self, key, val):
        self.cfg.setdefault(self._section(key), {})[key] = val

    def _save_cfg(self):
        """落盘配置;文件被占用(save_config 重试 4 次后 raise)也不让调用方炸掉。

        启动路径(_enter_bell 等)没有 try 兜着,打包版连 stderr 都没有 ——
        在这儿兜一层,失败记日志就够了,配置晚点再存总比整个应用起不来强。
        """
        try:
            core.save_config(self.cfg)
        except Exception as e:
            self.log(f"[配置]保存失败(文件被占用?): {e}")

    def __init__(self):
        import tkinter as tk

        self.root = tk.Tk()
        # 按钮回调里没接住的异常,默认只打到 stderr(用户根本看不到);记进日志
        self.root.report_callback_exception = self._on_tk_error
        self.root.withdraw()           # 主窗口不露面:界面就是降妖伏魔小窗
        self.cfg = core.load_config()
        # 第一次跑(没选过皮肤)跟随系统深浅色;选过就以配置为准(2026-10-21)
        _bell_part = core.bell_cfg(self.cfg)
        _bell_part["ui_mode"] = core.default_ui_mode(_bell_part.get("ui_mode"))
        try:
            if os.path.exists(core.LOG_PATH):
                import datetime
                mtime_day = datetime.date.fromtimestamp(
                    os.path.getmtime(core.LOG_PATH))
                too_big = os.path.getsize(core.LOG_PATH) > 2_000_000
                if mtime_day != datetime.date.today() or too_big:
                    # 非当天日志(或过大):轮转成 .old 保留一份,不累积
                    os.replace(core.LOG_PATH, core.LOG_PATH + ".old")
        except Exception:
            pass
        self.log("[应用]启动")

        self._engine_bad = 0           # 看门狗连续不健康次数(退避用,启动归零)
        self.engine = core.Engine(self)
        self.engine.start()

        self.log("[应用]就绪 —— 自动定位客户端,读到妖魔就在图上标点")
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(POLL_MS, self._drain_logs)
        self.show_bell()              # 启动直接进降妖伏魔(单窗应用)

    # ---- 窗口摆位 ----
    def _show_here(self, win, size=None, pos=None):
        """把窗口摆到位再淡入;set_place 按请求尺寸居中(单窗应用只此一处)。

        显示本身交给 `pop_in`(它先设全透明再 deiconify,不然会闪一帧满不透明),
        并把这扇窗提到前面 —— 不然它可能开在游戏/浏览器后面,用户看不到。
        `pos` 给了就用它(小窗记住的位置),坏了 set_place 自己退回居中。
        """
        xy = ui_widgets.set_place(win, size=size, pos=pos)
        pop_in(win, xy=xy)
        try:
            win.lift()
        except Exception:
            pass

    def _enter_bell(self):
        """登记当前功能(active_tool=bell):监听常开,refresh_tools 照它分派。

        慢活(清状态/定位客户端/按坐标范围标定)放到窗口弹出来之后再做 ——
        不然用户点完要等它跑完才看见动画。
        """
        self._set("active_tool", "bell")
        self.engine.refresh_tools()
        self._save_cfg()

    def _enter_bell_slow(self):
        """窗口已经在弹了,再做慢活:清状态、定位客户端、按坐标范围标定。"""
        self.engine.bell_tool.reset()
        self.log("[降妖伏魔]已进入,开始初始化")
        # 定位归工具自己:失败/最小化的提示也由它打
        try:
            n_wins = self.engine.bell_tool.locate()
        except Exception as err:
            n_wins = 0
            self.log(f"[铃铛]自动定位失败: {err}")
        if n_wins:
            # 定位结果当场存下来(单台也存):底行显示角色名;
            # 多开时顺便让用户按角色名选一台(选过就不再弹)。
            self._ask_bell_client()
            rect = self._bell_client_rect()
            self._refresh_bell_locate(rect)
            self.log(f"[铃铛]发现 {n_wins} 个客户端,已按整个客户端定位")
            self._warn_bell_size_rect(rect)
        else:
            self._refresh_bell_locate(None)
            self.log("[铃铛]没找到客户端窗口:先启动游戏再进降妖伏魔")
        self._save_cfg()
        self._auto_map_calib()          # 按坐标范围补底图标定(只影响铃铛)

    def _bell_open(self):
        """地图小窗是不是开着(0操作模式靠它判断要不要自动弹)。"""
        w = getattr(self, "bell_win", None)
        return bool(w is not None and w.winfo_exists())

    def show_bell(self):
        """降妖伏魔(应用唯一的窗口):妖魔位置大字 + 底图红点,新怪自动更新。

        快部分(点亮监听 + 建窗)先走,慢活(定位/标定)排在动画起跑之后
        —— 见 `_enter_bell_slow`。
        """
        self._enter_bell()
        if not self._bell_open():
            ui_bell.build_bell(self)
        bt = self.engine.bell_tool.ui_state()["target"]
        # 有没有目标都要写一次:重进功能时工具刚 reset,窗口里可能还挂着上一次的地名
        self.bell_var.set(bt)
        ui_bell.set_coord(self, bt)
        # 大小由内容定(皮肤换了以后高度会变,写死一个数会摆偏):set_place 拿
        # 窗口的请求尺寸来居中;存过位置就摆回上次拖到的地方。
        self._show_here(self.bell_win, pos=self._get("bell_pos"))
        self._enter_bell_slow()           # 慢活排在动画起跑之后
        ui_bell.draw_bell(self)

    def _bell_client_label(self):
        """底行那句角色名:选定的客户端;没定位到就空着(界面不写"定位"字样)。"""
        name = tools_bell.client_name(str(self._get("bell_client") or ""))
        return name or ""

    def _refresh_bell_locate(self, rect=None):
        """把定位结果写到小窗底行:定位到哪台客户端就写角色名,没定位到写占位句。

        客户端矩形不再显示(用户定的 2026-10-20)。
        """
        try:
            ui_bell.set_client(self, self._bell_client_label() if rect else "")
        except Exception:
            pass

    def on_toggle_theme(self):
        """底行那颗 ☀/☾:深色(A) / 明亮(B)两套皮肤来回切。

        选择记进 `ui_mode`,下次进来还是这套(配置在 bell 分区)。
        """
        mode = "a" if str(self._get("ui_mode", "a") or "a") == "b" else "b"
        self._set("ui_mode", mode)
        self._save_cfg()
        ui_bell.apply_theme(self, mode)
        self.log(f"[铃铛]界面换成{'明亮' if mode == 'b' else '深色'}模式")

    def on_locate_clients(self):
        """重新找客户端(底行那个 ↻);多开时弹列表让用户按角色名选一台。"""
        found, _mini = core.find_client_windows()
        if not found:
            self._refresh_bell_locate(None)
            # 就地提示,不弹模态框(2026-10-21 用户定的):点一下 ↻ 不该打断游戏
            ui_bell.flash_foot(self, "没找到客户端")
            self.log("[铃铛]没找到客户端窗口")
            return
        if not self._ask_bell_client(force=len(found) > 1):
            return
        rect = [int(v) for v in (self._bell_client_rect()
                                 or [int(v) for _t, v in found[:1]])]
        self._refresh_bell_locate(rect)
        self.log(f"[铃铛]已定位客户端 ({rect[0]},{rect[1]})-({rect[2]},{rect[3]})")
        self._warn_bell_size_rect(rect)

    def _ask_bell_client(self, force=False):
        """多开时让用户按角色名选一台(降妖伏魔只认一台)。返回 True = 有可用客户端。

        force=True:点「自动定位」时即便选过也重新问一次。
        """
        choices = tools_bell.client_choices()
        if not choices:
            return False
        if len(choices) == 1:                 # 只有一台:直接认它,别打扰
            self._set("bell_client", choices[0][1])
            self._save_cfg()                  # 定位到就落盘,下次进来看得到
            return True
        want = str(self._get("bell_client") or "")
        if want and not force:
            return True                       # 选过了就不弹
        pick = ui_bell.pick_client(self.bell_win, choices,
                                   current=want if force else "")
        if pick is None:
            return bool(want)                 # 取消了:保留原来的选择
        self._set("bell_client", choices[pick][1])
        self._save_cfg()
        self.log(f"[铃铛]选定的客户端:{choices[pick][0]}")
        return True

    def _bell_client_rect(self):
        """选定的那台客户端现在在哪(按标题/角色名匹配);找不到返回 None。"""
        want = str(self._get("bell_client") or "")
        try:
            found, _mini = core.find_client_windows()
        except Exception:
            return None
        if len(found) == 1:
            return [int(v) for v in found[0][1]]
        for title, box in found:
            if title == want or tools_bell.client_name(title) == want:
                return [int(v) for v in box]
        return None

    def _warn_bell_size_rect(self, rect):
        """自动定位到的客户端尺寸不支持时提醒一次(只支持 640x480 / 800x600)。"""
        if not rect:
            return
        w = int(rect[2]) - int(rect[0])
        h = int(rect[3]) - int(rect[1])
        if not tools_bell.supported_size((w, h)):
            self._warn_bell_size(f"{w}x{h}")

    def _warn_bell_size(self, size):
        """弹一次"改分辨率"的提醒:同一个尺寸只弹一次,别每拍都弹。"""
        if not size or size == getattr(self, "_bell_size_warned", ""):
            return
        self._bell_size_warned = size
        import tkinter.messagebox as mb
        parent = getattr(self, "bell_win", None)
        try:
            if parent is None or not parent.winfo_exists():
                parent = self.root
        except Exception:
            parent = self.root
        mb.showwarning(
            "分辨率不支持",
            "降妖伏魔只支持 640x480 和 800x600 两种客户端分辨率。\n\n"
            f"当前客户端窗口是 {size}。请在游戏设置里把分辨率改成 "
            "640x480 或 800x600，再点小窗右下角的 ↻。",
            parent=parent)

    # ---- 地图采集(窗口在 ui/bell,流程方法在这一层:入口层才同时够得着 tools 和 ui)。
    # **界面入口已撤**(用户定的 2026-10-20,底图内置),但功能只是从界面移除:
    # 抽屉控件与下面三个回调全保留,要开放时把「地图采集」按钮加回去、
    # command 指到 on_map_import 即可 ----
    def on_map_import(self):
        """「地图采集」:拉出/收起右侧抽屉(同一扇窗,不开新界面)。"""
        ui_bell.toggle_drawer(self)

    def on_map_btn(self, name):
        """抽屉里每张图共用的按钮:没采过=采集;采过了=查看。"""
        if tools_bell.map_asset(name):
            ui_bell.show_detail(self, name)
            return
        ok = self.record_map(name)
        ui_bell.refresh_drawer(self)          # 按钮状态跟采集结果走
        if ok:
            ui_bell.show_detail(self, name)   # 采完顺便展示一下

    def on_map_detail(self, name):
        """抽屉切到这张地图的页(只显示地图本身)。"""
        ui_bell.show_detail(self, name)

    def record_map(self, name):
        """把游戏里正打开的那张地图截下来当底图。成功返回 True。

        流程:找出鼠标所在的客户端那块 -> 只藏压在那块上的自家窗口(界面不闪)
        -> 截图并只留客户端那块 -> 按这张图的坐标范围比例找地图 ->
        核对画面里读到的地图名 -> 裁下来存成 data/maps/<图名>.png ->
        有坐标范围就顺手标定。
        """
        import numpy as np
        # 只采鼠标所在的那个客户端那块:更快,也不会把浏览器/别的窗口当成地图
        area = client_under_cursor()
        # 只藏压在那块上的自家窗口 —— 采集窗一般摆在游戏外面,界面就不会闪
        # (Tk 的窗口坐标是逻辑像素,客户端矩形是物理像素:比之前先换算)
        shown = self._hide_own_windows(
            over=scale_rect(area, screen_scale(self.root)))
        try:
            img = freeze_screen()
        except Exception as err:
            self.log(f"[铃铛]录入地图失败:截图出错({err})")
            return False
        finally:
            for w in shown:
                w.deiconify()
            self.root.update()
        if area:
            try:
                img = img.crop((area[0], area[1], area[2] + 1, area[3] + 1))
            except Exception:
                pass
        ratio = tools_bell.map_ratio(name)
        if not ratio:                 # 没有坐标范围:录了也没法定红点
            self.log(f"[铃铛]录入失败:「{name}」没有坐标范围"
                     "(data/maps/bounds.json 里没有这一条),录了也标定不了")
            return False
        rect = tools_bell.find_map_rect(np.asarray(img), ratio)
        if not rect:
            self.log(f"[铃铛]录入地图失败:画面里没有「{name}」那张图 —— "
                     "先在游戏里按 Tab 打开地图,再点「录入」")
            return False
        try:
            blocks = self.engine.ocr.recognize_blocks(
                np.asarray(img)[:, :, ::-1].copy())
        except Exception:
            blocks = []
        here = tools_bell.map_names_in(blocks)
        if name not in here and here:            # 画面里是别的图:别录错
            self.log(f"[铃铛]录入失败:画面里读到的是「{here[0]}」,"
                     f"不是「{name}」—— 打开「{name}」那张图再录")
            return False
        x0, y0, x1, y1 = rect
        crop = img.crop((x0, y0, x1 + 1, y1 + 1))
        try:
            crop.save(tools_bell.map_asset_save_path(name))
        except Exception as err:
            self.log(f"[铃铛]录入地图失败:保存出错({err})")
            return False
        cal = ""
        try:
            for n, msg in tools_bell.auto_calibrate_from_bounds(overwrite=True):
                if n == name and msg.startswith("sx="):
                    cal = f",已按坐标范围标定({msg})"
        except Exception:
            pass
        self._bell_spot = None
        note = "" if name in here else ",没读到地图名(没核对)"
        self.log(f"[铃铛]已录入地图 {name}({crop.width}×{crop.height})"
                 f"{cal}{note}")
        return True

    def _hide_own_windows(self, over=None):
        """采集前把自家窗口藏起来,只记下本来就显示着的(别把自己截进底图)。

        over 给了就只藏**跟它相交**的那些窗口:这次只截那一块,摆在外面的窗口
        不用动 —— 用户点的采集窗一般就在游戏外面,不动它界面就不会闪。
        """
        wins = [getattr(self, n, None) for n in ("bell_win", "root")]
        shown = []
        for w in wins:
            if w is None or not w.winfo_exists() or not w.winfo_viewable():
                continue
            if over is not None:
                box = (w.winfo_rootx(), w.winfo_rooty(),
                       w.winfo_rootx() + w.winfo_width(),
                       w.winfo_rooty() + w.winfo_height())
                if not rects_overlap(box, over):
                    continue
            shown.append(w)
        for w in shown:
            w.withdraw()
        self.root.update()
        return shown

    def _auto_map_calib(self):
        """按 bounds.json 标定(每次都重算)。范围改了会自动生效,没变就不刷日志。"""
        before = {n: tools_bell.map_calib(n) for n in tools_bell.load_map_bounds()
                  if not n.startswith("_")}
        for name, msg in tools_bell.auto_calibrate_from_bounds(overwrite=True):
            if not msg.startswith("sx="):
                self.log(f"[铃铛]{name} 未自动标定:{msg}")
            elif before.get(name) != tools_bell.map_calib(name):
                self.log(f"[铃铛]{name} 按坐标范围标定 {msg}")

    # ---- 引擎看门狗:重启时旧引擎的回收 ----
    def _retire_engine(self, old):
        """回收旧引擎:先停它的识别,再把 stop+join 丢后台,Tk 线程绝不在这等。

        直接 shutdown() 会 join 工具线程(最多 3 秒),而看门狗
        跑在 Tk 主线程上,界面会真冻住。所以:
        ① 先 deactivate:旧工具立刻不再识别,旧/新两套短暂并存时不会乱标点;
        ② stop+join 交给一条临时线程:旧线程照样会退,只是界面不等它。
        """
        off = getattr(getattr(old, "bell_tool", None), "deactivate", None)
        if off is not None:
            try:
                off()
            except Exception:
                pass
        shutdown = getattr(old, "shutdown", None)
        if shutdown is None:
            return
        import threading as _th

        def _bg():
            try:
                shutdown()
            except Exception as e:
                self.log(f"[引擎]旧引擎关闭失败(忽略): {e}")

        _th.Thread(target=_bg, name="引擎回收", daemon=True).start()

    # ---- 线程安全日志 ----
    def _on_tk_error(self, exc, val, tb):
        """界面回调里没接住的异常:Tk 默认只写到 stderr,用户看不见,记进日志。"""
        where = ""
        try:
            import traceback
            frames = traceback.extract_tb(tb) if tb else []
            if frames:
                where = f" @ {frames[-1].name}:{frames[-1].lineno}"
        except Exception:
            where = ""
        try:
            self.log(f"[界面]回调出错({exc.__name__}):{val}{where}")
        except Exception:
            pass

    def log(self, msg: str, detail: str = ""):
        """所有消息都写 bell.log 文件(小窗没有日志区,2026-10-21 撤)。

        detail: 只写进文件的补充信息(如 OCR/块数耗时),方便按日志定位问题。
        消息统一成 [时间][模块]内容;万一哪条忘了写模块,兜底成 [其他]。
        """
        if not msg.startswith("["):
            msg = "[其他]" + msg
        try:
            with open(core.LOG_PATH, "a", encoding="utf-8") as f:
                stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                f.write(f"{stamp} {msg}{detail}\n")
        except Exception:
            pass

    def _drain_logs(self):
        # 这一趟的活各自兜一层:这个方法是 `after` 自排自的整条界面刷新链的入口,
        # 只要有一次异常漏出去,链就断了 —— 窗口还能拖、引擎还在扫,但
        # 红点/坐标再也不更新,看起来就是"卡死不动"(原项目 2026-10-17 检视定的)。
        # 妖魔位置:读到妖魔就刷大字坐标 + 红点
        try:
            bst = self.engine.bell_tool.ui_state()
            bt = bst["target"]
            # 扫描中发现客户端尺寸不支持(窗口被拉伸/换分辨率):弹一次提醒改回来
            bad = bst.get("bad_size")
            if bad:
                if self._get("active_tool") == "bell":
                    self._warn_bell_size(bad)
            else:
                self._bell_size_warned = ""   # 改回支持的分辨率:下次再歪了还能提醒
            # 目标清空(工具 reset)也要刷一次:不然窗口里还挂着上一次的地名
            bv = getattr(self, "bell_var", None)
            if bv is not None and bv.get() != bt:
                bv.set(bt)
                # 地名/坐标是两个控件,`bell_var` 改了它们不会自己变 ——
                # 必须跟着写(原项目 2026-10-17 用户报"一直停在等待")。
                ui_bell.set_coord(self, bt)
                ui_bell.draw_bell(self)
        except Exception:
            pass
        # 引擎线程看门狗:线程退出、或 OCR 假就绪(warmup 推理失败)都重建(10 秒冷却)
        try:
            alive = self.engine.is_alive()
            # 线程活着不等于识别可用:健康标志不正常时同样重建
            healthy = alive and bool(getattr(self.engine, "ocr_ok", True))
            if healthy:
                self._engine_bad = 0            # 起来了:退避计数归零
            elif time.time() - getattr(self, "_engine_restart_ts", 0) > 10:
                # 每 10 秒最多算一次,免得计数被刷屏的每一拍顶上去
                self._engine_restart_ts = time.time()
                self._engine_bad = getattr(self, "_engine_bad", 0) + 1
                if self._engine_bad > ENGINE_RESTART_MAX:
                    # 到顶就停手:这台机器重建多少次也起不来,再重建只是白刷日志
                    if self._engine_bad == ENGINE_RESTART_MAX + 1:   # 只提示这一次
                        self.log(f"[引擎]连续 {ENGINE_RESTART_MAX} 次重建都没恢复"
                                 "(OCR 起不来或线程退出),已停止自动重建:"
                                 "请检查显卡驱动/依赖,修好后重启应用")
                else:
                    self.log("[引擎]线程已退出,正在自动重启…" if not alive
                             else "[引擎]OCR 不健康,正在重建引擎…")
                    old = self.engine   # 先停掉旧引擎的活,别放出僵尸工具线程
                    self._retire_engine(old)    # 停识别 + 后台回收:Tk 线程不等
                    self.engine = core.Engine(self)
                    self.engine.start()
                    # 监听常开(没有开关了):重建后直接按 active_tool 重新分派
                    self.engine.refresh_tools()
        except Exception:
            pass
        self.root.after(POLL_MS, self._drain_logs)

    def save_bell_pos(self):
        """把小窗当前位置记进配置(下次启动摆回原处,不再压回屏幕正中)。

        `win_origin` 给的是 geometry 那一套坐标,和 `set_place(pos=...)` 对得上。
        """
        win = getattr(self, "bell_win", None)
        if win is None:
            return
        try:
            if not win.winfo_exists():
                return
            xy = ui_widgets.win_origin(win)
            if xy:
                self._set("bell_pos", [int(xy[0]), int(xy[1])])
        except Exception:
            pass

    def on_close(self):
        """退出应用:关小窗(它就是唯一的界面)、存配置、拆 Tk。

        引擎/工具线程都是 daemon,进程一退就没了 —— 不在这里等它们(join 会让
        界面冻住,原项目的老坑)。
        """
        self.save_bell_pos()              # 位置也一起存,下次摆在原地
        self._save_cfg()
        for w in (getattr(self, "bell_win", None),):
            if w is not None:
                stop_anim(w)              # 没跑完的动效先停,别跟销毁撞上
        try:
            self.bell_win.destroy()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()
