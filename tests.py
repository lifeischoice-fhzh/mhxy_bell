#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归测试:python tests.py

只覆盖降妖伏魔两组(从原 keju-answerer 项目的 tests.py 移植):
  bell      纯函数 + 工具线程(提示文法/类型判定/底图标定/调度/独立监听)
  bell_ui   小窗(建控件/抽屉/定位),Tk 真建、引擎和 OCR 是假的

原则:不联网、不发出声音、不碰真实配置/日志/地图数据(全部指向临时目录),
图片用合成图;需要 GPU 时会自动回退 CPU,不影响结果。
"""
import json
import os
import shutil
import sys
import tempfile
import time
import types

import numpy as np

import core
import gui
from tools import bell as tools_bell
from ui import bell as ui_bell         # 小窗/侧边栏(测版面用)
from ui import widgets as ui_widgets   # 窗口摆位/动效

results = []
sections = []
QUIET = False          # --quiet:只打 FAIL 和结果行(省上下文,给 agent 用)


def check(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    if QUIET and ok:
        return
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


def section(fn):
    """把函数登记成一个测试组(按登记顺序执行)。"""
    sections.append(fn)
    return fn


# patch() 要换哪几个模块里的同名值。列在这里的就是"真身所在的那份名字":
# 降妖伏魔只有一个共享模块 core(配置/截图/OCR/引擎/窗口枚举)。
# 例外(不在 core 里的,用例单独指名):
#   tools/ 里自己的常量(MAP_DIR / MAP_CALIB_PATH ...)—— mods=(tools_bell,)
PATCH_MODULES = (core,)


class patch:
    """临时替换模块级名字:core 里同名的值换掉,退出还原。

    mods 指定时只换这些模块 —— 真身不在 core 里的符号(住在 tools/bell 的
    路径常量之类)得这样单独指一下。
    """

    def __init__(self, mods=None, **kw):
        self.mods = tuple(mods) if mods else PATCH_MODULES
        self.kw = kw
        self.saved = []

    def __enter__(self):
        for name, val in self.kw.items():
            for mod in self.mods:
                if hasattr(mod, name):
                    self.saved.append((mod, name, getattr(mod, name)))
                    setattr(mod, name, val)
        return self

    def __exit__(self, *exc):
        for mod, name, old in reversed(self.saved):
            setattr(mod, name, old)
        self.saved = []
        return False


class Sandbox:
    """把配置/日志全部指到临时目录。"""

    def __init__(self):
        self.dir = tempfile.mkdtemp(prefix="bell_test_")

    def __enter__(self):
        self.data = os.path.join(self.dir, "data")
        os.makedirs(self.data, exist_ok=True)
        self.config = os.path.join(self.dir, "config.json")
        self.log = os.path.join(self.dir, "bell.log")
        self._p = patch(CONFIG_PATH=self.config, LOG_PATH=self.log)
        self._p.__enter__()
        return self

    def __exit__(self, *exc):
        self._p.__exit__(*exc)
        shutil.rmtree(self.dir, ignore_errors=True)
        return False


def blk(text, x1, y1, h=30):
    """构造一个 OCR 文本块(手写场景用)。"""
    return {"text": text, "x1": x1, "y1": y1, "x2": x1 + 30 * len(text),
            "y2": y1 + h, "conf": 0.95}


def _tcl_drain():
    """在主线程里回收 Tk 对象,避免解释器被后台线程的 GC 释放(Tcl_AsyncDelete)。"""
    import gc
    gc.collect()


def _pump(widget, ms=600):
    """替 Tk 事件循环转一会儿。

    窗口动效(淡入淡出/滑入)是 after() 驱动的,断言"窗口藏没藏/显没显"之前
    得让它跑完;不然测的是动画中间态。
    """
    end = time.time() + ms / 1000.0
    while time.time() < end:
        try:
            widget.update()
        except Exception:
            break
        time.sleep(0.01)


def _settled(widget, *wins, ms=3000):
    """等这些窗口的动效都跑完 —— 位置断言前必须等,不然读到的是滑动中间态。"""
    return _pump_until(widget, lambda: all(
        getattr(w, "_anim_after", None) is None for w in wins), ms)


def _pump_until(widget, cond, ms=3000):
    """转事件循环直到 cond() 成立(或超时),返回最后一次判断结果。

    动效是 after 驱动的:机器忙时回调会被拖慢,用固定时长等就容易偶发失败
    —— 等**状态**而不是等时间。
    """
    end = time.time() + ms / 1000.0
    while time.time() < end:
        if cond():
            return True
        try:
            widget.update()
        except Exception:
            break
        time.sleep(0.01)
    return bool(cond())
class FakeScreen:
    """假屏幕:按顺序返回预设画面,用完后重复最后一张。"""

    def __init__(self, crops=None):
        self.crops = list(crops) if crops else [np.zeros((30, 60, 3), np.uint8)]
        self.n = 0

    def grab(self, region=None):
        i = min(self.n, len(self.crops) - 1)
        self.n += 1
        return self.crops[i]


def panel_screen(w=1000, h=880):
    """合成一张"客户端画面":DIALOG_BAND 那一块铺一块"暗且不彩"的宽面板。

    对话框只认**面板带那条主路**(`panel_box` / `panel_frac` 按像素判"现在有没有
    对话框"),平色亮图给不出面板 —— 主路在它上面永远判不出对话框,要验"对话框
    说的值走主路",假屏就得真有一块面板。面板里画几行亮色"字"(占的面积很小,
    不影响"框里暗比")。返回 RGB (H,W,3),按区域裁由调用方自己来。
    """
    img = np.zeros((h, w, 3), np.uint8)
    img[:] = (200, 120, 60)                  # 亮且彩的"游戏世界"
    x0, y0, x1, y1 = tools_bell.rel_rect([0, 0, w, h], tools_bell.DIALOG_BAND)
    img[y0:y1, x0:x1] = 32                   # 半透明黑面板那种"暗且不彩"
    for i in range(3):
        yy = y0 + 30 + i * 45
        img[yy:yy + 16, x0 + 60:x1 - 60] = 230
    return img


class PanelShot:
    """按区域真裁的假屏(画面 = panel_screen(宽, 高))。

    和 FakeScreen 的差别:**看 region**。假 OCR 得靠"裁出来多大"分清对话框条带 /
    任务栏那块 / 对话框条带,而 FakeScreen 恒返回同一张图,裁哪都一样大。
    """

    def __init__(self, w=1000, h=880):
        self.rect = [0, 0, w, h]
        self.img = panel_screen(w, h)

    def grab(self, region=None):
        x0, y0, x1, y1 = [int(v) for v in region]
        return np.ascontiguousarray(self.img[y0:y1, x0:x1][:, :, ::-1])


def mk_engine(bank, blocks, cfg=None, crops=None):
    """搭一个假屏幕/假 OCR/假扬声器的 Engine,返回 (engine, app)。

    cfg 传分区结构(和 load_config() 一样):{"app": {...}, "keju": {...},
    "bell": {...}},只填要覆盖的键,缺的走 mk_engine 的默认值。
    """
    eng = core.Engine.__new__(core.Engine)
    app = types.SimpleNamespace()
    eng.app = app
    app.cfg = core.split_config({"regions": [[0, 0, 60, 30]], "threshold": 62,
                                 "exam_mode": True,
                                 "active_tool": "keju"})  # 默认当"已进入科举"跑
    for name, part in (cfg or {}).items():
        app.cfg.setdefault(name, {}).update(part)
    app.bank = bank
    app.said = []
    app.last_answer = ""
    app.logs = []            # 全部日志(小窗没有日志区,所有消息只进文件)

    def _log(msg, *a, **kw):
        app.logs.append(msg)

    app.speaker = types.SimpleNamespace(say=app.said.append)
    app.log = _log
    eng.screen = FakeScreen(crops)
    eng.ocr = types.SimpleNamespace(recognize_blocks=lambda img, **kw: blocks)
    eng.bell_tool = tools_bell.BellTool(
        app, lambda: eng.screen, lambda: eng.ocr)
    return eng, app



@section
def sec_bell():
    """降妖伏魔:任务提示里的地图+坐标、妖魔定位、底图与坐标标定。

    这组不碰科举相关的东西,单跑这一组是整份回归里最快的一段。
    """
    # 这组中途会把这两个全局函数换成桩(整组都靠它们),收尾要还原:
    # 免得后面的组继承这套假环境,用例顺序变成隐式依赖。
    _orig_cursor = tools_bell.cursor_pos
    _orig_find = core.find_client_windows
    bank = types.SimpleNamespace()   # 铃铛用例不碰题库:占位对象(保 mk_engine 形状)
    BELL_TEXT = ("我们要对付一只新的狡魔了，它是一只胆小而怯弱的法系妖，"
                 "不过却是身形矫健，敏捷快速。估计，要被他个好几次了。"
                 "我发现它的踪迹在朱紫国(88,94)，少侠们速度赶过去看看吧。")
    check("铃铛:严格/宽容两个正则都能认出地图+坐标",
          tools_bell.scan_bell([blk(BELL_TEXT, 100, 200)]) == ("朱紫国", 88, 94)
          and tools_bell.scan_bell([blk("踪迹在建邺城(5,6)，快去", 100, 200)])
          == ("建邺城", 5, 6)
          and tools_bell.scan_bell([blk("踪迹在建业城(5,6)，快去", 100, 200)])
          == ("建邺城", 5, 6)
          and tools_bell.scan_bell([blk("今天天气不错，适合出门。", 100, 200)]) is None)

    # 六种怪的提示原文(实测截图里的写法)都要认:写法不止一种
    title = {"text": "降妖伏魔", "x1": 700, "y1": 140, "x2": 780, "y2": 160}
    check("铃铛:对话框/任务栏/悬停三种写法都认得出地图+坐标",
          tools_bell.scan_bell([blk(
              "这个妖魔值得一战,它无所畏惧且强大蛮横!我发现它的踪迹在"
              "西梁女国(28,42),少侠们准备好了就过去看看吧。", 1, 1)])
          == ("西梁女国", 28, 42)                       # 梦魇魔·对话框
          and tools_bell.scan_bell([
              title, blk("◆蛊虫发现妖魔在宝象国(99,54),快去降服他吧。"
                         "任务剩余时间119分钟。", 700, 165)])
          == ("宝象国", 99, 54)                          # 逐妖蛊虫·任务栏
          and tools_bell.scan_bell([
              title, blk("在建邺城(15,122)处", 700, 165)])
          == ("建邺城", 15, 122))                        # 巧智魔/怯弱妖·悬停
    check("铃铛:任务栏只写「去X找Y」、没坐标 -> 什么都不认(不显示半成品)",
          tools_bell.scan_bell([title, blk(
              "去西梁女国找梦魇魔。剩余时间2小时。", 700, 165)]) is None
          and tools_bell.scan_bell([title, blk(
              "去建邺城找巧智魔。剩余时间2小时。", 700, 165)]) is None
          and tools_bell.scan_bell(
              [blk("你得到了90521点经验,6532两银子", 1, 1)]) is None)
    check("铃铛:只认那六张图 —— 别的任务/聊天里的地点(12,34)不算妖魔位置",
          tools_bell.canon_map("建邮城") == "建邺城"
          and tools_bell.canon_map("西凉女国") == "西梁女国"
          and tools_bell.known_map("建邮城") == "建邺城"
          and tools_bell.known_map("西梁") == "西梁女国"
          and tools_bell.known_map("五庄观") is None
          and tools_bell.scan_bell([blk(
              "◆蛊虫发现妖魔在五庄观(99,54),快去降服他吧。", 1, 1)]) is None
          and tools_bell.scan_bell([blk("去长安找掌柜(12,34)", 1, 1)]) is None
          and tools_bell.scan_bell([blk("玩家甲:我在东海湾(88,94)等你", 1, 1)])
          is None
          and tools_bell.scan_bell(
              [blk("去五庄观找蛊虫。剩余时间2小时。", 1, 1)]) is None)

    # 对话框和任务栏都说的时候怎么取舍:对话框优先、任务栏补充、不一致以"刚变的"为准
    dlg = blk("我发现它的踪迹在西梁女国(28,42),少侠们准备好了就过去看看吧。",
              1, 1)
    trk = blk("◆蛊虫发现妖魔在建邺城(15,122),快去降服他吧。", 700, 165)
    d, t, w = tools_bell.scan_bell_parts([dlg])
    check("铃铛:对话框说的单独认出来(任务栏没说话时就是它)",
          d == ("西梁女国", 28, 42) and t == d and w is None, f"{d} {t}")
    d, t, w = tools_bell.scan_bell_parts(
        [title, trk])                      # 任务栏的说法必须带着「降妖伏魔」标题
    check("铃铛:任务栏说的单独认出来(对话框没说话时就是它)",
          d is None and t == ("建邺城", 15, 122) and w is None, f"{d} {t}")
    d, t, w = tools_bell.scan_bell_parts([dlg, title, trk])
    check("铃铛:两处都有时分开认(才判得出「不一致」)",
          d == ("西梁女国", 28, 42) and t == ("建邺城", 15, 122), f"{d} {t}")

    # 整窗那条路删了(2026-10-21,只支持两档分辨率、任务栏框一律来自表):
    # bell_form / wide 宽窄口径 / 带锚点那条兜底(`_RE_BELL_ANY_ANCHORED`)随之
    # 删掉 —— 留一条"删干净"的检查,免得哪个名字又悄悄长回来。
    try:
        tools_bell.scan_bell_parts([], wide=True)
        _wide_gone = False
    except TypeError:
        _wide_gone = True
    check("铃铛:整窗口径删干净(wide 参数 / bell_form / 带锚点兜底都不在了)",
          _wide_gone
          and not hasattr(tools_bell, "bell_form")
          and not hasattr(tools_bell, "_RE_BELL_ANY_ANCHORED")
          and not hasattr(tools_bell, "track_rect")
          and not hasattr(tools_bell, "hunt_gap")
          and not hasattr(tools_bell, "_is_hdr")
          and not hasattr(tools_bell, "HUNT_GAPS")
          and not hasattr(tools_bell, "TRK_NOHDR_MAX"), "")

    # 现在喂进 `scan_bell_parts` 的都是**小块**(对话框文字带 / 表里的任务栏框),
    # 口径只剩一条:带锚点、没锚点的写法都认(小块里图名读花靠兜底接)。
    _title2 = blk("降妖伏魔", 700, 200)
    check("铃铛:带虚词锚点的写法照旧认(踪迹在 / 去X使用 / 妖魔在 / 去X / 在X处)",
          tools_bell.scan_bell_parts(
              [blk("我发现它的踪迹在朱紫国(144,99),少侠们速度赶过去吧。", 1, 1)]
          )[0] == ("朱紫国", 144, 99)
          and tools_bell.scan_bell_parts(
              [blk("去建邺城(101,127)使用招魂帖,然后妖魔就会到来。", 1, 1)]
          )[0] == ("建邺城", 101, 127)
          and tools_bell.scan_bell_parts(
              [_title2, blk("◆蛊虫发现妖魔在宝象国(99,54),快去降服他吧。",
                            700, 300)])[1] == ("宝象国", 99, 54)
          and tools_bell.scan_bell_parts(
              [_title2, blk("先去朱紫国(12,49)找掌柜", 700, 300)]
          )[1] == ("朱紫国", 12, 49)      # 老写法「去X(x,y)」走无锚点兜底(归任务栏)
          and tools_bell.scan_bell_parts(
              [_title2, blk("在建邺城(15,122)处", 700, 300)]
          )[1] == ("建邺城", 15, 122),    # 悬停那行也归任务栏那条
          " | ".join(str(tools_bell.scan_bell_parts(
              [_title2, blk(t, 700, 300)])) for t in (
              "◆蛊虫发现妖魔在宝象国(99,54),快去降服他吧。",
              "先去朱紫国(12,49)找掌柜", "在建邺城(15,122)处")))

    check("铃铛:自动模式下,任务追踪挂着多个任务只认「降妖伏魔」那段",
          tools_bell.scan_bell([
              {"text": "任务追踪", "x1": 700, "y1": 100, "x2": 800, "y2": 120},
              {"text": "降妖伏魔", "x1": 700, "y1": 140, "x2": 780, "y2": 160},
              {"text": "◆蛊虫发现妖魔在西梁女国(28,42),快去降服他吧。",
               "x1": 700, "y1": 165, "x2": 900, "y2": 185},
              {"text": "师门", "x1": 700, "y1": 260, "x2": 750, "y2": 280},
              {"text": "去长安城(12,34)找门派师父。",
               "x1": 700, "y1": 285, "x2": 900, "y2": 305},
          ]) == ("西梁女国", 28, 42))

    # 对话框那条主路(scoped=False):面板里就那一条任务,不做标题圈范围,原样认
    only_line = blk("去西梁女国(28,42),快去降服他吧。", 700, 165)
    check("铃铛:对话框主路(scoped=False)时不要求有标题",
          tools_bell.scan_bell([only_line], scoped=False) == ("西梁女国", 28, 42)
          and tools_bell.scan_bell([only_line]) is None)
    # 只支持两档客户端尺寸(1024x768 已不支持):表里没有的尺寸要能被判出来,
    # gui 靠这个弹"改分辨率"的提醒。
    check("铃铛:只支持 640x480 / 800x600 两档(1024x768 已不支持)",
          tools_bell.supported_size((815, 680))
          and tools_bell.supported_size((1011, 826))
          and not tools_bell.supported_size((1291, 1025))
          and tools_bell.layout_for((1291, 1025)) is None)

    # OCR 认错字(实测把"建邺城"读成"建邮城",整条提示就废了):常见错法都归一
    check("铃铛:OCR 认错的地图名也能认(建邮城/西粱/宝像/敖来/长寿郊外)",
          tools_bell.scan_bell([blk(
              "。去建邮城（101，127）使用招魂帖，然后妖魔就会到来。", 100, 200)])
          == ("建邺城", 101, 127)
          and tools_bell.scan_bell([blk(
              "我发现它的踪迹在西粱女国（16,103）", 100, 200)])
          == ("西梁女国", 16, 103)
          and tools_bell.scan_bell([blk(
              "我发现它的踪迹在宝像国（30,53）", 100, 200)])
          == ("宝象国", 30, 53)
          and tools_bell.scan_bell([blk(
              "我发现它的踪迹在敖来国（30,53）", 100, 200)])
          == ("傲来国", 30, 53)
          and tools_bell.scan_bell([blk(
              "我发现它的踪迹在长寿郊外（115,167）", 100, 200)])
          == ("长寿村", 115, 167))

    # 一个杀怪周期 = 一次"对话框给出图+坐标";周期内只有任务栏给出**新的图+坐标**
    # 才更新;任务栏只写地图没坐标的一律不管(不显示"坐标待定"那种半成品)。
    def _tracker(text):
        # 真任务栏框里就有「任务追踪」**表头** + 「降妖伏魔」标题(表里的框就是
        # 围着表头那一块手框的):假任务栏带上它们,和真读数同形。
        return [{"text": "任务追踪", "x1": 700, "y1": 118,
                 "x2": 790, "y2": 138},
                {"text": "降妖伏魔", "x1": 700, "y1": 145,
                 "x2": 780, "y2": 165},
                blk(text, 700, 170)]

    # 用**逐妖蛊虫**那种周期验任务栏(用户定的规矩:只有逐妖蛊虫/巧智魔/怯弱妖
    # 这几种才读任务栏;招魂幡/梦魇魔/迷幻妖 的坐标对话框里就有,一次都不读)
    #
    # 假屏得给得出"面板":对话框说的值只走**面板带那条主路**(tools/bell.py 的
    # `dialog_rect` → `panel_box` → `panel_text_cut`),平色图判不出面板,主路就
    # 永远读不到对话框;假 OCR 也按裁剪尺寸分派 —— 宽而矮的那条是对话框的文字带,
    # 其余(任务栏那块)是任务栏。对话框内容和任务栏内容分开摆:一个周期里
    # 变的是哪一个,用例里就改哪一个。
    _KW, _KH = 900, 640
    _kst = {"dlg": [blk("去宝象国(24,51)使用逐妖蛊虫,然后妖魔就会出现。",
                        100, 200)],
            "trk": _tracker("去宝象国(24,51)使用逐妖蛊虫,"
                            "然后跟着地上的蛊虫找到妖魔。")}

    def _ocr_k(img, **kw):
        h, w = img.shape[:2]
        if w > 500 and h != _KH:              # 对话框的文字带(宽而矮)
            return _kst["dlg"]
        return _kst["trk"]

    eng_k, app_k = mk_engine(
        bank, _kst["dlg"], cfg={"app": {"active_tool": "bell"}})
    eng_k.bell_tool.regions = lambda: [[0, 0, _KW, _KH]]
    eng_k.screen = PanelShot(_KW, _KH)
    eng_k.ocr.recognize_blocks = _ocr_k
    # 任务栏框来自分辨率表(900x640 不在表里):直接种一个框进去,后面"任务栏
    # 给出新坐标"那条用例才读得到任务栏。
    eng_k.bell_tool._slot[1] = tools_bell.SlotState(
        region=(0, 0, _KW, _KH), trk=[620, 193, 880, 390])
    eng_k._safe("cycle", True)
    check("周期:对话框给图+坐标 -> 直接定目标",
          eng_k.bell_tool.spot == ("宝象国", 24, 51)
          and eng_k.bell_tool.target == "宝象国 (24,51)",
          str(eng_k.bell_tool.spot))
    eng_k._safe("cycle", True)
    check("周期:同一条提示不重复记",
          len([m for m in app_k.logs if "妖魔位置" in m]) == 1,
          str([m for m in app_k.logs if "妖魔位置" in m]))
    _kst["trk"] = _tracker("去建邺城找巧智魔。剩余时间2小时。")
    eng_k._safe("cycle", True)
    check("周期:任务栏只写地图、没坐标 -> 不动(不显示坐标待定)",
          eng_k.bell_tool.spot == ("宝象国", 24, 51)
          and "待定" not in eng_k.bell_tool.target,
          f"{eng_k.bell_tool.spot} {eng_k.bell_tool.target!r}")
    _kst["trk"] = _tracker("◆蛊虫发现妖魔在建邺城(15,122),快去降服他吧。")
    eng_k._safe("cycle", True)
    check("周期:任务栏给出新的图+坐标 -> 跟着更新(逐妖蛊虫用道具后)",
          eng_k.bell_tool.spot == ("建邺城", 15, 122)
          and eng_k.bell_tool.target == "建邺城 (15,122)",
          str(eng_k.bell_tool.spot))
    _kst["dlg"] = [blk(
        "我发现它的踪迹在傲来国(30,53),少侠们准备好了就过去看看吧。",
        100, 200)]
    eng_k._safe("cycle", True)
    check("周期:又出现一个新对话框 -> 开新周期(目标换成它)",
          eng_k.bell_tool.spot == ("傲来国", 30, 53),
          str(eng_k.bell_tool.spot))
    # 招魂幡/梦魇魔 那几种:坐标对话框里就有 -> 这个周期里**一次都不读任务栏**
    # (用户定的规矩:只有逐妖蛊虫/巧智魔/怯弱妖要盯任务栏)
    _kst["trk"] = _tracker("去西梁女国找梦魇魔。剩余时间2小时。")
    eng_k._safe("cycle", True)
    check("周期:梦魇魔这种不读任务栏(任务栏里换什么坐标都不理)",
          eng_k.bell_tool._slot[1].trk_mode == "none"
          and eng_k.bell_tool.spot == ("傲来国", 30, 53),
          f"{eng_k.bell_tool._slot[1].trk_mode} "
          f"{eng_k.bell_tool.spot}")

    # OCR 把坐标分隔符认错/吃掉:真机日志里"（93.31）""（69101）""（107.146）"
    check("坐标:分隔符是句点/顿号/空格都算(真机把逗号读成句点)",
          tools_bell.scan_bell([blk(
              "去西梁女国（93.31）使用“招魂帖”,然后妖魔就会到来。", 1, 1)])
          == ("西梁女国", 93, 31)
          and tools_bell.scan_bell([blk(
              "去长寿村（107.146）使用招魂帖", 1, 1)]) == ("长寿村", 107, 146)
          and tools_bell.scan_bell([blk(
              "去朱紫国(144 99)使用招魂帖", 1, 1)]) == ("朱紫国", 144, 99))
    check("坐标:分隔符整个丢了(69101)也能按坐标范围反推唯一一种切法",
          tools_bell.scan_bell([blk(
              "去西梁女国（69101）使用“招魂帖”,然后妖魔就会到来。", 1, 1)])
          == ("西梁女国", 69, 101)
          # 切不出唯一解(两种切法都落在范围内)时不猜
          and tools_bell.scan_bell([blk(
              "去西梁女国（1010）使用招魂帖", 1, 1)]) is None)
    check("坐标:“去X(x,y)使用…”这种写法两处都要认(招魂幡两处 + 逐妖蛊虫第一步)",
          (lambda d, t, _w: (d or t))(*tools_bell.scan_bell_parts(
              [title, blk("去西梁女国(93,31)使用“招魂帖”", 700, 165)],
              scoped=True)) == ("西梁女国", 93, 31))

    # 贪心组会把开头几个字也当成图名、连坐标一起吃掉:校验不过时要**往回退一个字**
    # 接着找,不然真正能认的那一处就被吞了(真机上同一句话只差前面几个字,
    # `finditer` 的结果就不一样)。校验逻辑一个字没动,所以不会多出误报。
    _greedy = [
        ("长寿付（38.1）使用 妖贵虫", ("长寿村", 38, 1)),          # 本来就认得出
        ("降妖伏魔 长寿付（38.1）使用 妖贵虫", ("长寿村", 38, 1)),  # 原来 None
        ("1070敏任务追踪魔来国（101，14）使妖", ("傲来国", 101, 14)),  # 原来 None
    ]
    check("认图名+坐标:贪心吞掉真匹配时往回退一个字重试(真机复现过)",
          [tools_bell.scan_bell([blk(t, 1, 1)], scoped=False) for t, _w in _greedy]
          == [w for _t, w in _greedy],
          " | ".join(f"{t!r}->{tools_bell.scan_bell([blk(t, 1, 1)], scoped=False)}"
                     for t, _w in _greedy))
    check("认图名+坐标:第一处就命中时结果不变(重试不影响正常句子)",
          tools_bell.scan_bell([blk(
              "去建邺城(101,127)使用招魂帖,然后妖魔就会到来。", 1, 1)])
          == ("建邺城", 101, 127)
          and tools_bell.scan_bell([blk(
              "我发现它的踪迹在朱紫国(144,99),少侠们速度赶过去吧。", 1, 1)])
          == ("朱紫国", 144, 99)
          and tools_bell.scan_bell([blk(
              "◆蛊虫发现妖魔在宝象国(99,54),快去降服他吧。", 1, 1)])
          == ("宝象国", 99, 54))

    # 真机截图里最坑的一条:同一行的块底边差 1 像素,按 (y1,x1) 排就会拼错句子
    check("拼句:同一行的块按 x 拼,不能因为底边差 1 像素就被拆开",
          tools_bell.scan_bell([
              blk("降妖伏魔", 700, 140),
              {"text": "蛊虫发现妖魔在宝", "x1": 745, "y1": 166, "x2": 900,
               "y2": 186},
              {"text": "国150.54)", "x1": 722, "y1": 189, "x2": 830, "y2": 209},
              {"text": ",快去降服", "x1": 832, "y1": 188, "x2": 920,
               "y2": 208},
          ], scoped=True) == ("宝象国", 150, 54))
    check("地图名读花也能认(真机把“宝象国”读成“宝国”、括号也被吃掉)",
          tools_bell.known_map("宝国") == "宝象国"
          and tools_bell.scan_bell([blk(
              "蛊虫发现妖魔在宝国150.54),快去降服他吧。", 100, 200)])
          == ("宝象国", 150, 54)
          # 别人的地名不能被兜进来:"长安"跟"长寿村"只共一个"长"
          and tools_bell.known_map("长安") is None
          and tools_bell.known_map("长安城") is None)
    check("悬停:鼠标停在任务栏上时不做标题圈范围(标题常被读花,一 scoped 就全丢)",
          (lambda d, t, _w: (d or t))(*tools_bell.scan_bell_parts([
              {"text": "在建邮城（15，122）处", "x1": 700, "y1": 61,
               "x2": 900, "y2": 81},
              {"text": "双快通", "x1": 700, "y1": 87, "x2": 780,
               "y2": 107},          # 标题读花到连「降」都没了
          ], scoped=False)) == ("建邺城", 15, 122)
          and tools_bell.scan_bell_parts([
              {"text": "在建邮城（15，122）处", "x1": 700, "y1": 61,
               "x2": 900, "y2": 81},
              {"text": "双快通", "x1": 700, "y1": 87, "x2": 780, "y2": 107},
          ], scoped=True)[1] is None)
    check("悬停:坐标范围外的不认(单次读数只靠这条兜底)",
          tools_bell.in_bounds("西梁女国", 72, 98)
          and not tools_bell.in_bounds("西梁女国", 972, 98)
          and tools_bell.in_bounds("没范围的图", 9999, 9999))
    check("悬停:鼠标在不在那块矩形里(往外放宽 HOVER_GROW)",
          tools_bell.in_rect((500, 300), [400, 200, 600, 400])
          and not tools_bell.in_rect((500, 100), [400, 200, 600, 400])
          and tools_bell.in_rect((500, 150), [400, 200, 600, 400],
                                 grow=tools_bell.HOVER_GROW)
          and not tools_bell.in_rect(None, [400, 200, 600, 400]))
    check("悬停:要读的那块 = 面板往上多留一截 + 鼠标周围也带上(裁到扫描区里)",
          tools_bell.hover_rect([700, 300, 1000, 480], (900, 460),
                                [0, 0, 1024, 768])
          == [640, 180, 1024, 510]
          and tools_bell.hover_rect([700, 300, 1000, 480], None,
                                    [0, 0, 1024, 768])
          == [700, 180, 1000, 480]
          and tools_bell.hover_rect([700, 300, 1000, 480], (10, 10),
                                    [0, 0, 1024, 768])[0] == 0)
    # hover 档的"收手话术":判据只用**核心词**(整句太长,OCR 读花时对不上)。
    # 表见 `HOVER_STOP_WORDS`(4 张截图的原文写在它上面的注释里)。
    check("收手话术:核心词表认得出 4 张截图的原文(命中任意一条即收手)",
          [tools_bell.hover_stop(t) for t in (
              "三番两次，我都被你累断气了。你怎么这么执着啊。跑不动了。"
              "终于逮到你了，看打。我也跑累了，等下…",
              "打就打，我……我，我……你怎么不怕我。",
              "金蝉脱壳可是我的拿手好戏，刚试过了，拿我没办法吧。"
              "也就是个会跑的小妖魔，看我再来收服…等我准备好了再来。",
              "你再抓，我再跑；你再抓，我再跑呀……嘻嘻。")]
          # **2026-10-17 用户又把 `拿手好戏` 去掉了** —— 巧智魔那句现在认的是
          # `刚试过了`(同一句里的另一个词)
          == ["逮到你了", "你怎么不怕我", "刚试过了", "你再抓，我再跑"]
          # 表里每个词自己都认(单拿出来就是它自己;顺序随意,内容照抄用户的)
          and all(tools_bell.hover_stop(w) == w
                  for w in tools_bell.HOVER_STOP_WORDS)
          # 半角逗号那版走不带标点的兜底那条
          and tools_bell.hover_stop("你再抓,我再跑;你再抓,我再跑呀……嘻嘻。")
          == "我再跑"
          # **2026-10-16 去掉了 `金蝉脱壳`、2026-10-17 去掉了 `拿手好戏`**:
          # 这两个都不再触发收手
          and tools_bell.hover_stop("金蝉脱壳") == ""
          and tools_bell.hover_stop("拿手好戏") == ""
          and tools_bell.hover_stop("今天天气不错,适合出门。") == ""
          and tools_bell.hover_stop("") == "" and tools_bell.hover_stop(None) == "",
          str([tools_bell.hover_stop(t) for t in (
              "跑不动了", "金蝉脱壳", "你再抓,我再跑", "拿手好戏",
              "累短气", "累断气", "刚试过了", "三番两次", "打就打")]))



    # ---- 快路:框来自分辨率表,只扫那一小块(用户两条红线:准 + 快) ----
    # 合成一张"游戏窗口":亮底 + 可开关的对话框面板;扫哪块、扫到什么都由这里定。
    BG_C = (200, 120, 60)            # 亮且彩的"游戏世界"

    class Win:
        """合成窗口:能按区域裁,也能随时让对话框面板出现/消失。"""

        def __init__(self, w=900, h=640):
            self.w, self.h = w, h
            self.rect = [0, 0, w, h]
            rng = np.random.default_rng(7)
            base = np.zeros((h, w, 3), np.uint8)
            base[:] = BG_C
            self.base = np.clip(
                base.astype(np.int16)
                + rng.integers(-8, 8, (h, w, 3)), 0, 255).astype(np.uint8)
            self.dialog = False
            self.page = 1
            self.dlg_override = []           # 误读注入:非空时按顺序返回它

        def image(self):
            img = self.base.copy()
            if self.dialog:
                x0, y0, x1, y1 = tools_bell.rel_rect(
                    self.rect, tools_bell.DIALOG_BAND)
                img[y0:y1, x0:x1] = 32          # 半透明黑面板那种"暗且不彩"
                for i in range(2 * self.page):   # 面板里画几行"字"
                    yy = y0 + 30 + i * 45
                    img[yy:yy + 16, x0 + 60:x1 - 60] = 230
            return img

        def grab(self, region=None):
            x0, y0, x1, y1 = [int(v) for v in region]
            Win.last = [x0, y0, x1, y1]      # 刚裁的是哪一块(假 OCR 靠它分派内容)
            img = self.image()
            return np.ascontiguousarray(img[y0:y1, x0:x1][:, :, ::-1])

    win = Win()
    band = tools_bell.rel_rect(win.rect, tools_bell.DIALOG_BAND)
    part_h = band[3] - band[1]          # 面板框 = 整条带子(合成图就这样)
    HDR = {"text": "任务追踪", "x1": 700, "y1": 170, "x2": 790, "y2": 190}
    TITLE = {"text": "降妖伏魔", "x1": 700, "y1": 200, "x2": 780, "y2": 220}
    DLG_BLK = blk("去西梁女国(28,42)使用逐妖蛊虫,然后妖魔就会出现。",
                  100, 430)
    DLG_BLK2 = blk("去傲来国(11,22)使用逐妖蛊虫,然后妖魔就会出现。",
                   100, 430)
    TRK_BLK = blk("◆蛊虫发现妖魔在宝象国(99,54),快去降服他吧。", 700, 225)
    calls = []

    _BOX = [620, 193, 880, 390]     # 默认种进去的"表框"(相对窗口;宽 < 500)

    def seed_state(region, trk=None, mode="item"):
        """种一份扫描状态(表里的任务栏框 + 本周期任务类型)进去。

        框一律来自分辨率表、**任务类型只由对话框给**,所以"跟这两种来源无关"的
        用例(任务栏怎么读、悬停怎么触发、空读怎么办)直接摆一份状态,一直在
        "有框 + 类型已知"这条路上跑;两种来源本身各有专门用例盯着(见"类型只由
        对话框决定"那组)。`mode` 默认 "item":等价于"对话框已经说过这轮是逐妖蛊虫"。
        """
        return tools_bell.SlotState(
            region=tuple(region), trk=(list(trk) if trk else None),
            trk_mode=tools_bell.TrkMode(mode))

    # 对话框那边现在只读"面板里有字的那一截"(宽、矮),所以按宽高区分两类
    def ocr_of(img, **kw):
        w, h = img.shape[1], img.shape[0]
        calls.append((w, h))
        if w > 500:                           # 对话框的文字带
            if not win.dialog:
                return []
            if win.dlg_override:              # 注入的"读花"先顶上,取完自动回正常
                return [win.dlg_override.pop(0)]
            return [DLG_BLK if win.page == 1 else DLG_BLK2]
        return [HDR, TITLE, TRK_BLK]           # 任务栏那一小块

    # 测试里把鼠标位置钉住:不钉的话"真实鼠标"可能正好飘在任务栏那块,
    # 悬停那条快路会被意外打开(和真机一样,但会让断言时好时坏)
    tools_bell.cursor_pos = lambda: (0, 0)
    app_f = types.SimpleNamespace(
        cfg=core.split_config({
                               "active_tool": "bell"}),
        logs=[], log=lambda m, **kw: app_f.logs.append(m))
    core.find_client_windows = lambda w=win.w, h=win.h: (
        [("梦幻西游 ONLINE", [0, 0, w, h])], [])
    tool_f = tools_bell.BellTool(
        app_f, lambda: win,
        lambda: types.SimpleNamespace(recognize_blocks=ocr_of))
    # 类型只由对话框给 —— 这一组盯的是"任务栏那块怎么读/悬停怎么触发",所以先种
    # 一个 item 进去(等价于"对话框已经说过这轮是逐妖蛊虫"),之后每个新周期的类型
    # 由 DLG_BLK/DLG_BLK2(**逐妖蛊虫**文案)那两行定 ✓
    tool_f._slot[1] = seed_state(win.rect, trk=_BOX)
    tool_f.tick(force=True)                   # 第一拍:读表框那一小块,当轮就报
    check("快路:框来自表,第一拍只扫那一小块就把目标报出来(没有整窗/学框那一拍)",
          tool_f.ui_state()["spot"] == ("宝象国", 99, 54)
          and not any("整窗" in m or "学到任务栏框" in m for m in app_f.logs),
          f"spot={tool_f.ui_state()['spot']} | "
          + " | ".join(app_f.logs[-2:]))

    calls.clear()
    tool_f._ts = 0.0
    tool_f.tick(force=False)                  # 什么都没变:一次 OCR 都不该有
    check("快路:画面没变的一轮,一次 OCR 都不做(省下的就是那一两百毫秒)",
          calls == [], str(calls))
    tool_f._hb = 0.0                          # 心跳 10 秒一条,这里催它发一次
    tool_f._ts = 0.0
    tool_f.tick(force=False)
    check("快路:心跳把「扫了几轮 / OCR 几次 / 跳过几次」写进日志(省了多少看这个)",
          any("扫描心跳" in m and "跳过" in m for m in app_f.logs),
          " | ".join(m for m in app_f.logs if "心跳" in m))

    # 对话框出现:只该扫那条小带子(不整窗),而且当轮就把目标报出来
    win.dialog = True
    calls.clear()
    tool_f._ts = 0.0
    t0 = time.time()
    tool_f.tick(force=False)
    dt = (time.time() - t0) * 1000
    check("快路:对话框一出现就当轮报出目标(不用等任务栏那块)",
          tool_f.ui_state()["spot"] == ("西梁女国", 28, 42)
          and [c for c in calls if c[0] > 500 and c[1] != win.h]
          and not [c for c in calls if c[1] == win.h],
          f"用时{dt:.0f}ms 扫了{calls}")

    # 面板一直开着、里面的字换了(点 NPC 翻页):得马上重读,不能干等 DIALOG_GAP
    check("对话框:只读面板里有字的那一截(面板下面大半是空的)",
          tools_bell.panel_text_cut(
              np.zeros((400, 900, 3), np.uint8), (0, 0, 900, 400)).shape[0]
          == max(tools_bell.DIALOG_TEXT_MINH,
                 int(400 * tools_bell.DIALOG_TEXT_FRAC)) + tools_bell.DIALOG_PAD
          and tools_bell.panel_text_cut(
              np.zeros((400, 900, 3), np.uint8), (0, 0, 900, 200)).shape[0]
          == tools_bell.DIALOG_TEXT_MINH + tools_bell.DIALOG_PAD)

    check("快路:面板签名是定长的(跟面板大小无关,才比得出「有没有变」)",
          tools_bell.panel_sig(win.image()[band[1]:band[3], band[0]:band[2]],
                               (0, 0, 400, 200)).shape == (24, 48, 3)
          and tools_bell.sig_diff(None, None) > 900)

    # 面板是**半透明**的:身后的世界一直在动。签名必须先二值化再采样,否则"背景
    # 在动"会被当成"换了一页" —— 真机实测每 10 秒读 8~12 次、一半白烧(2026-10-17)。
    def _sig_img(bg, page=1):
        # 整块都是"半透明面板":面板盖满 box(真实调用也是拿面板自己那块当 box)
        img = np.full((200, 400, 3), bg, np.uint8)          # 身后的世界
        img[:, :] = (np.array(bg) * 0.15 + 30 * 0.85).astype(np.uint8)
        for i in range(2 * page):                            # 面板里的"字"
            img[40 + i * 30: 52 + i * 30, 60:340] = 235
        return img

    _s1 = tools_bell.panel_sig(_sig_img(60), (0, 0, 400, 200))
    _s2 = tools_bell.panel_sig(_sig_img(200), (0, 0, 400, 200))
    _s3 = tools_bell.panel_sig(_sig_img(60, page=2), (0, 0, 400, 200))
    check("快路:面板签名抗「背后的世界在动」(半透明面板不算换页),真换页照样认得出",
          tools_bell.sig_diff(_s1, _s2) == 0
          and tools_bell.sig_diff(_s1, _s3) > tools_bell.SIG_MIN,
          f"背景 60 vs 200 -> {tools_bell.sig_diff(_s1, _s2):.1f};"
          f" 换页 -> {tools_bell.sig_diff(_s1, _s3):.1f}")
    win.page = 2
    calls.clear()
    tool_f._ts = 0.0
    tool_f.tick(force=False)
    check("快路:面板里换了字就**当轮**换目标(用户实测的「等 2 秒」就是这条路径)",
          tool_f.ui_state()["spot"] == ("傲来国", 11, 22)
          and [c for c in calls if c[0] > 500 and c[1] != win.h],
          f"{tool_f.ui_state()['spot']} 扫了{calls}")
    # 鼠标挪到面板**边上**(没压进框里)也要触发悬停那条快路:真机上玩家就是把
    # 鼠标挪到面板文字行上,原来"必须压在框里"太严,实测漏了好几次
    tools_bell.cursor_pos = lambda: (950, 300)     # 框是 (682,182,,-362) 右边一点
    # 距上次读 0.6 秒(逐妖蛊虫盯着第二个坐标是 0.5s 一拍):该读了
    tool_f._slot[1].trk_ts = time.time() - 0.6
    calls.clear()
    tool_f._ts = 0.0
    tool_f.tick(force=False)
    read = [c for c in calls if c[1] not in (part_h, win.h)]
    check("悬停:鼠标在面板边角上也立刻读任务栏(不放过那一闪)",
          bool(read), f"扫了{calls}")
    check("过程日志:悬停那次读会打上「悬停」标记(便于事后统计)",
          any("悬停" in m for m in app_f.logs),
          " | ".join(m for m in app_f.logs if "悬停" in m)[:60])
    tools_bell.cursor_pos = lambda: (0, 0)
    win.page = 1                              # 翻回去,后面几条还按原状态断言
    tool_f._ts = 0.0
    tool_f.tick(force=False)
    # (原来这里还有两条"对话框和任务栏对不上 -> 立刻再扫一次 + 以对话框为准"的
    #  用例。2026-10-16 按用户要求**整套删掉**:现在不需要两处对上了 —— `_scan`
    #  末尾那段对账 + `st["mismatch"]` + 那两句日志都不在了。)

    # 对话框"改口"要有证据(用户定的规矩):同一块面板两次读出不一样的值时,后面
    # 那个不许直接覆盖 —— 先不报、立刻重扫;重扫回来还是它才算纠正。
    # 实测踩过:23:51 同一条对话框读出 建邺城(101,127) 和 建邺城(24,108),
    # 两个都落在坐标范围内,当场把红点挪到了错地方(用户的红线是"准")。
    n0 = len(app_f.logs)
    MISREAD = blk("我发现它的踪迹在西梁女国(24,108),少侠们过去看看吧。", 100, 430)

    def _flap_and_read(blocks):
        """面板闪一下(真机就是这么触发重读的),后面这一次会读到 blocks 里的字。"""
        win.dlg_override = list(blocks)
        win.dialog = False
        tool_f._ts = 0.0
        tool_f.tick(force=False)              # 面板消失
        win.dialog = True
        tool_f._ts = 0.0
        tool_f.tick(force=False)              # 面板又出现 -> 这次读出 blocks[0]

    _flap_and_read([MISREAD])                 # 只读花这一次:重扫就该读回原值
    check("对话框读花:不一样的值不覆盖,先不报并立刻重扫一次",
          tool_f.ui_state()["spot"] == ("西梁女国", 28, 42)
          and any("先不覆盖" in m and "立刻重扫" in m for m in app_f.logs[n0:]),
          f"{tool_f.ui_state()['spot']} | " + " | ".join(app_f.logs[n0:])[:180])

    _flap_and_read([MISREAD, MISREAD])        # 同一个值连读两次 -> 纠正过来
    check("对话框改口:同一个值连读两次 -> 纠正,以新值为准",
          tool_f.ui_state()["spot"] == ("西梁女国", 24, 108)
          and any("对话框改口" in m for m in app_f.logs[n0:]),
          f"{tool_f.ui_state()['spot']} | " + " | ".join(app_f.logs[n0:])[:180])
    check("过程日志:认到时也把读到的原文写上(不然「怎么读成这个」只能靠猜)",
          any("识别 对话框条带" in m and "读到:" in m for m in app_f.logs[n0:]),
          " | ".join(m for m in app_f.logs[n0:] if "识别" in m)[:180])

    # 对话框第二遍那一拍(`again`)**任务栏整支跳过**(2026-10-16 检视定的):那一拍带着
    # force/again,任务栏的"见过两次"复核会被放路,而此刻任务栏第一行**恰恰就是对话框
    # 刚给的那条**(「去X(x,y)使用逐妖蛊虫」两处同文)—— 它一旦抢先在任务栏那一支报
    # 出去,`_cycle` 先被写掉;等对话框确认时 `_publish` 里"定类型 + 清上一周期残留"
    # 那段(只有 `src == "对话框"` 才跑)就被整段跳过,这一轮的类型会沿用上一周期的
    # (该盯任务栏的没盯 -> 漏第二个坐标;反过来只是白读)。
    _frame = tools_bell.rel_rect(win.rect, (0.60, 0.20, 0.95, 0.45))
    _st1 = seed_state(win.rect, trk=_frame, mode="item")
    _st1.trk_last = _st1.trk_stale = ("宝象国", 150, 54)   # 上一周期那条读数
    tool_f._slot[1] = _st1
    tool_f._cycle[1] = tool_f._last[1] = ("宝象国", 150, 54)     # 上一只怪,还没换
    win.dlg_override = [MISREAD]        # 第一遍读花 -> 第二遍读回真值(同一块面板)
    win.dialog = True
    calls.clear()
    n1 = len(app_f.logs)
    tool_f._ts = 0.0
    tool_f.tick(force=False)
    _small1 = [c for c in calls if c[1] != win.h and c[0] <= 500]
    check("对话框第二遍那一拍:任务栏整支跳过(一次都不读、也不许它抢先报)",
          not _small1
          and not any("来自任务栏" in m for m in app_f.logs[n1:]),
          f"任务栏那块读了 {len(_small1)} 次 {_small1} | "
          + " | ".join(app_f.logs[n1:])[:160])

    # 第二遍那一拍**也不许"报出没被确认过的值"**(2026-10-16 检视定的):两次读得不一致
    # 时(第一遍读到真值、第二遍读花),末尾那条兜底会把第二遍那个读花值当拍报出去 ——
    # 单次读出就落红点,正是"两次相同放行"要挡的。现在第二遍只负责核对:这一拍什么都
    # 不报,下一拍会拿 `dlg_text` 重新 pend + 重扫,正确的值只晚 0.15s。
    _st2 = seed_state(win.rect, trk=_frame, mode="item")
    _st2.trk_last = _st2.trk_stale = ("宝象国", 150, 54)
    tool_f._slot[1] = _st2
    tool_f._cycle[1] = tool_f._last[1] = ("宝象国", 150, 54)
    _spot0 = tool_f.ui_state()["spot"]
    win.page = 1
    win.dlg_override = [DLG_BLK2]       # 第一遍:傲来国(11,22)(对当前目标来说是新的)
    win.dialog = True                   # 第二遍:回到默认那条 西梁女国(28,42)(不一致)
    n2 = len(app_f.logs)
    tool_f._ts = 0.0
    tool_f.tick(force=False)
    check("对话框第二遍那一拍:两次不一致时不许当拍报出去(留到下一拍)",
          tool_f.ui_state()["spot"] == _spot0
          and tool_f._cycle.get(1) == ("宝象国", 150, 54)
          and not any("妖魔位置" in m for m in app_f.logs[n2:]),
          f"spot={tool_f.ui_state()['spot']} cycle={tool_f._cycle.get(1)} | "
          + " | ".join(app_f.logs[n2:])[:160])

    # 话术门槛(用户定的 2026-10-16,表见 `BELL_WORDS`):面板那一拍读到的**整段文字**
    # 里必须含一个"铃铛任务的核心词"才认里面的坐标。挡的是"面板收紧失败、把下方聊天/
    # 世界频道一起读进来"那种**静态行** —— 它长成"图名+坐标"的样子,而且两遍必然读成
    # 一样,"两遍一致"挡不住它(这是唯一一条两遍一致防不住的误报路径)。
    _st3 = seed_state(win.rect, trk=_frame, mode="item")
    _st3.trk_last = _st3.trk_stale = ("宝象国", 99, 54)   # 任务栏那行没变
    tool_f._slot[1] = _st3
    tool_f._cycle[1] = tool_f._last[1] = ("宝象国", 150, 54)
    _spot3 = tool_f.ui_state()["spot"]
    _gate0 = tool_f._stat["dlg_gate"]
    win.dlg_override = [blk("玩家甲:去长寿村(50,60)集合,别乱跑。", 100, 430)]
    win.dialog = True
    n3 = len(app_f.logs)
    tool_f._ts = 0.0
    tool_f.tick(force=False)
    check("话术门槛:面板里读到聊天那种「图名+坐标」被挡下(不报、也不进待确认)",
          tool_f.ui_state()["spot"] == _spot3
          and not tool_f._slot[1].dlg_pend
          and tool_f._stat["dlg_gate"] == _gate0 + 1
          and not any("妖魔位置" in m for m in app_f.logs[n3:]),
          f"spot={tool_f.ui_state()['spot']} "
          f"pend={tool_f._slot[1].dlg_pend} gate={tool_f._stat['dlg_gate']}")

    # 任务栏那块连着读不到字(实测约一半时间是"没显示"):**只记数 + 一条诊断
    # 日志 —— 不动表里那个框**(用户定的 2026-10-16:面板被游戏藏起来是正常的,
    # 战斗中/切场景时它就不画)。
    win2 = Win()
    calls2 = []

    def ocr_blank(img, **kw):
        calls2.append((img.shape[1], img.shape[0]))
        return []                      # 任务栏那一小块一个字都读不到

    app_g = types.SimpleNamespace(
        cfg=core.split_config({
                               "active_tool": "bell"}),
        logs=[], log=lambda m, **kw: app_g.logs.append(m))
    tool_g = tools_bell.BellTool(
        app_g, lambda: win2,
        lambda: types.SimpleNamespace(recognize_blocks=ocr_blank))
    tool_g._slot[1] = seed_state(win2.rect, trk=_BOX)
    # 类型:当"对话框说过逐妖蛊虫"算

    def _tick_g():
        tool_g._ts = 0.0
        tool_g._slot[1].trk_ts = 0.0
        tool_g.tick(force=False)

    _tick_g()                                  # 第一拍:框是表里的,直接读那一小块
    _box0 = tool_g._slot[1].trk
    _miss = tools_bell.TRK_MISS_MAX
    for _ in range(_miss * 2 + 3):             # 一口气连读 19 次空
        _tick_g()
    _gst = tool_g._slot[1]
    check("空读:连着读不到字只记数,框照旧留着(没有整窗/作废那一说)",
          _box0 is not None and _gst.trk == _box0,
          f"框 {_box0} -> {_gst.trk}")
    _diag = [m for m in app_g.logs if "读不到字" in m]
    check("空读:诊断日志说的是「面板没显示、位置照旧留着」(不再说作废/重锚)",
          len(_diag) == 2                    # 19 次空 -> 第 8 / 16 次各一条,不刷屏
          and all("位置照旧留着" in m and "不作废" in m and "重锚" not in m
                  for m in _diag),
          " | ".join(_diag))

    # 开新周期时任务栏那边的残留要清干净(用户定的 2026-10-16)。但**屏幕上那条旧
    # 行清不掉**(游戏刷新有延迟):`trk_stale` 记下它 —— 这一整个周期都不许拿它当
    # "任务栏给的新目标",否则红点会被那条旧行翻回上一轮的坐标。
    # 两个周期都按**逐妖蛊虫**(item)算:只有 item/hover 的周期才读任务栏,这条
    # 用例要的正是"任务栏读得到、但那行旧值不许翻盘"。
    win7 = Win()
    STALE7 = blk("◆蛊虫发现妖魔在宝象国(99,54),快去降服他吧。", 700, 300)
    NEW7 = "去西梁女国(28,42)使用逐妖蛊虫,然后妖魔就会出现。"
    dlg7 = {"text": ""}

    _band7 = tools_bell.rel_rect(win7.rect, tools_bell.DIALOG_BAND)

    def ocr7(img, **kw):
        # 按"刚裁的是哪一块"分派(`Win.last`)—— 对话框那条读的是**面板里有字的那一截**
        # (面板框再切一刀,高度不是带子本身),按图片尺寸认会认错。
        if Win.last == _band7:                            # 对话框那条带子
            return [blk(dlg7["text"], 100, 430)] if dlg7["text"] else []
        return [HDR, TITLE, STALE7]            # 任务栏那一小块:那条旧行一直挂着

    app7 = types.SimpleNamespace(
        cfg=core.split_config({
                               "active_tool": "bell"}),
        logs=[], log=lambda m, **kw: app7.logs.append(m))
    tool7 = tools_bell.BellTool(
        app7, lambda: win7,
        lambda: types.SimpleNamespace(recognize_blocks=ocr7))
    tool7._slot[1] = seed_state(win7.rect, trk=_BOX)
    # ① 这一轮算逐妖蛊虫(要读任务栏)

    def _tick7():
        tool7._ts = 0.0
        tool7._slot[1].trk_ts = 0.0
        tool7.tick(force=False)

    tool7.tick(force=True)                     # ① 任务栏那条先成为本周期目标
    _first7 = tool7.ui_state()["spot"]
    check("新周期:任务栏先给出第一条(读的就是表框那一小块)",
          _first7 == ("宝象国", 99, 54) and tool7._slot[1].trk,
          f"spot={_first7} 框={tool7._slot[1].trk}")
    _n7 = len(app7.logs)
    win7.dialog = True                         # ② 对话框开新周期(改口:连读两次)
    dlg7["text"] = NEW7
    _tick7()
    _st7 = tool7._slot[1]
    check("新周期:任务栏残留一并清掉(trk_hist/trk_pub/trk_text/dlg_pend)",
          _first7 == ("宝象国", 99, 54)
          and tool7.ui_state()["spot"] == ("西梁女国", 28, 42)
          and _st7.trk_stale == ("宝象国", 99, 54)   # 旧行:留下来当记号
          and _st7.trk_hist == [] and _st7.trk_pub is None
          and _st7.trk_text is None and _st7.dlg_pend is None,
          f"{_first7} -> {tool7.ui_state()['spot']} trk_stale="
          f"{_st7.trk_stale} hist={_st7.trk_hist} "
          f"pub={_st7.trk_pub} text={_st7.trk_text} "
          f"pend={_st7.dlg_pend}")
    for _ in range(3):                         # ③ 那条旧行还挂着,连读几次
        _tick7()
    check("新周期:任务栏那条旧行不许把红点翻回旧坐标(trk_stale 挡住)",
          tool7.ui_state()["spot"] == ("西梁女国", 28, 42)
          and any("妖魔位置: 西梁女国" in m for m in app7.logs[_n7:])
          and not any("妖魔位置" in m and "宝象国" in m
                      for m in app7.logs[_n7:]),
          f"spot={tool7.ui_state()['spot']} | "
          + " | ".join(m for m in app7.logs[_n7:])[:200])

    # 框来自表,不再有"作废/重锚":框里读到别处的字(面板被战斗藏住的样子)
    # 也**不动表里那个框**。
    win8 = Win()
    calls8 = []

    def ocr8(img, **kw):
        calls8.append((img.shape[1], img.shape[0]))
        return [blk("东海湾 打捞珍珠", 60, 30)]   # 有字、但不是任务栏的内容

    app8 = types.SimpleNamespace(
        cfg=core.split_config({
                               "active_tool": "bell"}),
        logs=[], log=lambda m, **kw: app8.logs.append(m))
    tool8 = tools_bell.BellTool(
        app8, lambda: win8,
        lambda: types.SimpleNamespace(recognize_blocks=ocr8))
    tool8._slot[1] = seed_state(win8.rect, trk=[620, 193, 900, 492])
    _keep8 = list(tool8._slot[1].trk)
    for _ in range(6):
        tool8._slot[1].trk_ts = 0.0
        tool8._ts = 0.0
        tool8.tick(force=False)
    check("分辨率表:框里读到别处的字也不动表里那个框(不整窗、不作废)",
          tool8._slot[1].trk == _keep8
          and not [c for c in calls8 if c[1] == win8.h]
          and not any("作废" in m for m in app8.logs),
          f"框={tool8._slot[1].trk} "
          f"整窗={[c for c in calls8 if c[1] == win8.h]}")

    # 纯函数:门控判据与"学到的那块框"
    check("门控:暗且不彩的比例分得出「对话框面板在不在」",
          tools_bell.panel_box(win.image()[band[1]:band[3], band[0]:band[2]])
          is not None
          and tools_bell.panel_box(
              np.full((300, 800, 3), BG_C, np.uint8)) is None
          and tools_bell.panel_frac(np.full((10, 10, 3), 32, np.uint8)) == 1.0
          and tools_bell.panel_frac(np.full((10, 10, 3), BG_C, np.uint8)) == 0.0)
    check("防误读:同一个值要见过两次才算数(治任务栏把一只怪读成好几种)",
          tools_bell.confirmed(["A", "B", "A", "C"]) == "A"
          and tools_bell.confirmed(["A", "B", "C"]) is None
          and tools_bell.confirmed(["A", "A", "B", "B"]) == "B"   # 取最近那个
          and tools_bell.confirmed([None, "A", None, "A"]) == "A"
          and tools_bell.confirmed([]) is None)
    check("面板:又宽又矮的暗横条不算对话框(真机实测误判都是 800x50~150)",
          tools_bell.panel_box(
              np.concatenate([
                  np.full((60, 900, 3), 30, np.uint8),      # 又宽又矮的暗条
                  np.full((300, 900, 3), 200, np.uint8)])) is None
          and tools_bell.panel_box(
              np.concatenate([
                  np.full((30, 900, 3), 200, np.uint8),
                  np.full((280, 900, 3), 30, np.uint8),     # 够高:像对话框
                  np.full((30, 900, 3), 200, np.uint8)])) is not None)

    # **结构关**(用户实测 2026-10-16:进场打怪时战斗画面被当成面板,OCR 读回
    # 冷昕T/血条 这些):战斗画面同样"一整块暗"(真图框内暗比 0.91,过得了暗比
    # 关),但它的人/怪/血条把亮/彩像素**摊满所有行**(实测 0.77);对话框是
    # 文字行,亮/彩只挤在上面几行(实测 0.23)。有内容的行过半就不是面板。
    def _battle_band():
        b = np.full((360, 900, 3), 24, np.uint8)
        for i in range(0, 360, 4):         # 每个缩略行都有亮|彩块(人/怪/血条)
            x = (i * 37) % 500
            b[i:i + 2, x:x + 90] = (240, 80, 80)
        return b

    def _panel_with_text():
        p = np.full((300, 900, 3), 22, np.uint8)
        for ry in (40, 76, 112):           # 字只挤在上面三行(细笔画)
            for x in range(60, 520, 9):
                p[ry:ry + 3, x:x + 6] = (230, 230, 230)
        return p

    _pb = tools_bell.panel_box(_battle_band())
    check("面板:战斗画面那种「亮块摊满行」不认成对话框(暗比挡不住,靠行结构)",
          _pb is None
          and tools_bell.panel_box(np.concatenate([
              np.full((30, 900, 3), 200, np.uint8),
              _panel_with_text(),
              np.full((30, 900, 3), 200, np.uint8)])) is not None,
          f"战斗框={_pb}")

    check("防误读:条带/文字块按比例切得对(相对区域坐标)",
          tools_bell.rel_rect([100, 200, 900, 600], (0.0, 0.0, 0.5, 0.5))
          == [100, 200, 500, 400])
    check("过程日志:没认到时把读到的字也带上(排查时最想知道的就是这个)",
          tools_bell.read_note("任务栏", (800, 600), 12, 321.4, None)
          == "任务栏 800x600 块12 321ms → 一个字都没读到"
          and tools_bell.read_note("任务栏", (330, 180), 3, 99.6, None,
                                   [{"text": "去建邺城找巧智魔"}])
          == "任务栏 330x180 块3 100ms → 没认到(去建邺城找巧智魔)"
          and tools_bell.read_note("任务栏", (330, 180), 3, 99.6,
                                   ("宝象国", 99, 54))
          == "任务栏 330x180 块3 100ms → 宝象国(99,54)")
    _thr = tools_bell.BellTool.__new__(tools_bell.BellTool)
    _thr._note_seen = {}
    _thr_notes = []
    _thr.app = types.SimpleNamespace(
        log=lambda m, **kw: _thr_notes.append(m))
    _thr._note("读数", "同一句", 100.0)
    _thr._note("读数", "同一句", 101.0)              # 没变化、还没到点:不写
    _thr._note("读数", "同一句", 100.0 + tools_bell.LOG_GAP + 1)   # 兜底重写
    _thr._note("读数", "换了一句", 100.5)            # 变了:当场写
    check("过程日志:同一类没变化时按 LOG_GAP 节流(不然一轮一行把日志刷爆)",
          len(_thr_notes) == 3, str(_thr_notes))
    # 分辨率表:客户端每个尺寸下那两块在哪(相对窗口左上角)——
    # 窗口挪了/改大小都不用重设,多开时每个窗口吃同一张表
    check("分辨率表:坐标是相对窗口的,换算成屏幕坐标时 x/y 各用各的偏移",
          tools_bell.abs_rect([1000, 10, 2022, 819], [10, 20, 900, 300])
          == [1010, 30, 1900, 310]
          and tools_bell.abs_rect([0, 0, 100, 100], [1, 2, 3, 4])
          == [1, 2, 3, 4])
    check("分辨率表:尺寸差一两像素也算同一个(截图和 GetWindowRect 会差 1px)",
          tools_bell.LAYOUT_TOL >= 1
          and tools_bell.layout_for((815, 679)) is not None
          and tools_bell.layout_for((815, 680)) is not None
          and tools_bell.layout_for((816, 682)) is not None
          and tools_bell.layout_for((900, 640)) is None
          and tools_bell.layout_for((815, 680 - tools_bell.LAYOUT_TOL))
          is not None
          and tools_bell.layout_for((815, 680 - tools_bell.LAYOUT_TOL - 1))
          is None)
    check("分辨率表:支持的两档尺寸量到的对话框框(相对窗口左上角)",
          tools_bell.layout_for((815, 680)) == [69, 355, 763, 582]
          and tools_bell.layout_for((1011, 826)) == [168, 430, 860, 657]
          and tools_bell.layout_for((1291, 1025)) is None)

    import tempfile as _tf_mod
    _lay = os.path.join(_tf_mod.mkdtemp(prefix="keju_layout_"), "b.json")
    with patch(mods=(tools_bell,), LAYOUT_PATH=_lay):
        tools_bell.save_layout((1022, 809), dlg=[10, 20, 900, 300])
        tools_bell.save_layout("815x679", dlg=[5, 6, 800, 400])
        check("分辨率表:按客户端尺寸存取 dlg(相对窗口左上角)",
              tools_bell.layout_for((1022, 809)) == [10, 20, 900, 300]
              and tools_bell.layout_for((815, 679)) == [5, 6, 800, 400]
              and tools_bell.layout_for((999, 999)) is None)
        # 任务栏框**现在进表**(用户 2026-10-17:量过的尺寸只扫那一块,不再整窗找)。
        # 用**另一个尺寸**验证,别动上面那两个键(下面几条用例还要用它们)。
        tools_bell.save_layout((1400, 1000), dlg=[7, 8, 900, 600])
        tools_bell.save_layout((1400, 1000), dlg=[7, 8, 900, 600],
                               trk=[700, 200, 980, 380])
        with open(_lay, encoding="utf-8") as _f:
            _raw = json.load(_f)
        check("分辨率表:任务栏框也进表(量过的尺寸以后只扫那一块)",
              _raw["1400x1000"].get("trk") == [700, 200, 980, 380]
              and tools_bell.layout_trk((1400, 1000)) == [700, 200, 980, 380]
              and tools_bell.layout_trk((999, 999)) is None
              and tools_bell.layout_for((1400, 1000)) == [7, 8, 900, 600],
              str(_raw))
        _lt = tools_bell.BellTool.__new__(tools_bell.BellTool)
        check("分辨率表:对话框框按表换算成屏幕坐标(没量过的尺寸走比例兜底)",
              _lt.dialog_rect([1000, 10, 2022, 819]) == [1010, 30, 1900, 310]
              and _lt.dialog_rect([0, 0, 640, 480]) is not None)

    _cs = tools_bell.BellTool.__new__(tools_bell.BellTool)
    _cs._bad_size = ""
    check("尺寸检查:不支持的分辨率记下来给界面弹窗(支持的两档清空)",
          _cs.check_size((1291, 1025)) is False
          and _cs._bad_size == "1291x1025"
          and _cs.check_size((815, 680)) is True
          and _cs._bad_size == "")
    check("配置:手动框的键已删除",
          "bell_rect" not in core.CONFIG_SECTIONS["bell"]
          and "bell_rect" not in core.DEFAULT_CONFIG)
    # 任务栏读不读、读多勤:**按任务类型分档**(用户定的规矩)——
    #   逐妖蛊虫:用道具后任务栏会换一条新坐标 -> 盯着看,直到同一个新值连读两次;
    #   巧智魔/怯弱妖:第二个坐标只在鼠标悬停时才出现 -> 盯着看,读到坐标就停;
    #   其余(招魂幡/梦魇魔/迷幻妖):坐标对话框里就有 -> **一次都不读**。
    # 类型从认到的文字判(任务名/道具名),每个周期开头认一次。
    check("任务类型:逐妖蛊虫 -> 盯(任务栏会换新坐标)",
          tools_bell.trk_plan("去宝象国(24,51)使用逐妖蛊虫,然后妖魔就会出现。")
          == "item"
          and tools_bell.trk_plan("◆蛊虫发现妖魔在宝象国(150,54),"
                                  "快去降服他吧。任务剩余时间119分钟。")
          == "item")
    check("任务类型:巧智魔/怯弱妖 -> 盯(第二个坐标要悬停才出现)",
          tools_bell.trk_plan("去建邺城找巧智魔。剩余时间1小时59分。") == "hover"
          and tools_bell.trk_plan("去西梁女国找怯弱妖。剩余时间2小时。")
          == "hover")
    # **真机实录**(2026-10-16 上午 bell.log):这两类的对话框**确实点出怪名** ——
    # 之前担心"对话框和梦魇魔同形、认不出怪名,hover 那条第二坐标拿不到",
    # 真机原文就是上面这个样子,照规则判就行,不用为它们单开口子。
    check("任务类型:真机实录的怯弱妖/巧智魔对话框(怪名在对话框里) -> hover",
          tools_bell.trk_plan(
              "我们要对付一只新的妖魔了，它是一只胆小而怯弱的怯弱妖，"
              "不过却是身形矫健，敏捷快速。估计，要被他耍好几次了。"
              "我发现它的踪迹在朱紫国(88,94)，少侠们速度赶过去看看吧。")
          == "hover"
          and tools_bell.trk_plan("又一个！这次是一只精巧的巧智魔。"
                                  "它足智多谋而且狡猾无比。"
                                  "我发现它的踪迹在朱紫国(7,32)，"
                                  "少侠们准备好了就过去看看吧。") == "hover")
    check("任务类型:招魂帖/招魂幡/梦魇魔/迷幻妖 -> 一次都不读任务栏",
          all(tools_bell.trk_plan(t) == "none" for t in (
              "去朱紫国(12,49)使用“招魂帖”,等待被诱惑的妖魔上钩并降服它。",
              "去朱紫国(12,49)使用招魂帖,然后妖魔就会到来。",
              "看看你包里的新物品“招魂帖”,把它贴在指定位置。",
              "领取任务:降妖伏魔·招魂幡。",
              "去西梁女国找梦魇魔。剩余时间2小时。",
              "去西梁女国找迷幻妖。剩余时间2小时。")))
    check("任务栏节奏:逐妖蛊虫 0.5s / 悬停 0.25s / 认类型 0.6s / 没显示 1.0s",
          tools_bell.TRK_ITEM_GAP == 0.5
          and tools_bell.HOVER_GAP == 0.25
          and tools_bell.HOVER_GAP < tools_bell.TRK_ITEM_GAP
          < tools_bell.TRK_GAP < tools_bell.TRK_GAP_IDLE)

    # ---- 类型**只由对话框**决定(用户定的 2026-10-16) ----
    # 任务栏那份文字永远不参与定类型(连"对话框认不出时拿它当备胎"都不许):类型由
    # **对话框开新周期那一拍读到的文字**算(`trk_plan`)写进 `st["trk_mode"]`;还没
    # 开过周期时默认 `none` —— 任务栏**一次都不读**。任务栏那块只管"拿第二个坐标"。
    def _type_case(dlg_text, trk_text):
        """对话框写着 dlg_text、任务栏那块写着 trk_text:跑两拍,回(类型, 任务栏读几次)。

        哪块是哪块按"**刚裁的是哪一块**"认(`Win.last`)—— 对话框那条读的是
        "面板里有字的那一截"(面板框还要再切一刀);任务栏读的是表框那一小块
        (悬停那拍还要往上加 `HOVER_LIFT`)。
        """
        w9 = Win()
        cnt9 = {"trk": 0}
        _band9 = tools_bell.rel_rect(w9.rect, tools_bell.DIALOG_BAND)

        def ocr9(img, **kw):
            if Win.last == _band9:             # 对话框条带
                return [blk(dlg_text, 100, 430)] if dlg_text else []
            cnt9["trk"] += 1                   # 任务栏那一小块(含悬停加高的那拍)
            return [HDR, TITLE, blk(trk_text, 700, 300)]

        app9 = types.SimpleNamespace(
            cfg=core.split_config({
                                   "active_tool": "bell"}),
            logs=[], log=lambda m, **kw: app9.logs.append(m))
        tool9 = tools_bell.BellTool(
            app9, lambda: w9,
            lambda: types.SimpleNamespace(recognize_blocks=ocr9))
        tool9._slot[1] = seed_state(w9.rect, trk=_BOX, mode="none")
        # 初始态:对话框还没说过类型(none)—— 类型由下面两拍里的对话框给
        w9.dialog = True                   # 面板开着:对话框那条主路读得到
        with patch(mods=(tools_bell,), cursor_pos=lambda: (700, 300)):
            for _ in range(2):
                tool9._ts = 0.0
                tool9._slot[1].trk_ts = 0.0
                tool9.tick(force=False)
        return tool9._slot[1].trk_mode, cnt9["trk"], tool9.spot

    _c = _type_case("", "◆蛊虫发现妖魔在宝象国(150,54),快去降服他吧。")
    check("类型只由对话框:还没开过周期(默认 none)-> 任务栏一次都不读",
          _c[0] == "none" and _c[1] == 0, str(_c))
    _c = _type_case("去宝象国(24,51)使用逐妖蛊虫,然后妖魔就会出现。",
                    "◆蛊虫发现妖魔在宝象国(150,54),快去降服他吧。")
    check("类型只由对话框:对话框说是逐妖蛊虫 -> item,任务栏那块跟着读",
          _c[0] == "item" and _c[1] >= 1, str(_c))
    # **反例**:对话框是梦魇魔(该 none),任务栏那块却写着巧智魔/怯弱妖 ——
    # 类型必须仍是 none、任务栏**一次都不读**(这就是"任务栏不参与定类型")
    _c = _type_case("我发现它的踪迹在西梁女国(28,42),少侠们过去看看吧。",
                    "去建邺城找巧智魔。剩余时间1小时59分。")
    check("类型只由对话框(反例):对话框是梦魇魔 -> none,任务栏里写着巧智魔也不读",
          _c[0] == "none" and _c[1] == 0, str(_c))
    _c = _type_case("我发现它的踪迹在西梁女国(28,42),少侠们过去看看吧。",
                    "去建邺城找怯弱妖。剩余时间1小时59分。")
    check("类型只由对话框(反例):同一句对话框、任务栏里写着怯弱妖,照样不读任务栏",
          _c[0] == "none" and _c[1] == 0, str(_c))
    _c = _type_case("我发现它的踪迹在宝象国(150,54),去把巧智魔降服了吧。",
                    "去宝象国找巧智魔。剩余时间1小时59分。")
    check("类型只由对话框:对话框里点出巧智魔 -> hover,任务栏那块跟着读",
          _c[0] == "hover" and _c[1] >= 1, str(_c))

    # 上面是分类函数;"盯"和"不盯"还得真跑一遍 —— 用户定的规矩里"其他场景和
    # 时间段都不用读任务栏"是硬要求(读一次就是一百多毫秒),所以按**任务栏那块
    # 裁出来给 OCR 的次数**断言,而不是只看状态字段
    _reg2 = [0, 0, 1000, 880]

    class _Shot:
        """合成客户端画面:**DIALOG_BAND 那块是暗且不彩的宽面板**。

        对话框说的值只走面板带那条主路(`panel_box` 按像素找面板),平色图判不出
        面板,主路就永远读不到对话框;按区域真裁 —— 假 OCR 靠"刚裁的是哪一块"分层
        (`last`:代码裁哪块就 OCR 哪块)。
        """

        img = panel_screen(_reg2[2] - _reg2[0], _reg2[3] - _reg2[1])
        last = None                        # 最近一次交出去的那块 region

        def grab(self, region=None):
            x0, y0, x1, y1 = [int(v) for v in region]
            _Shot.last = [x0, y0, x1, y1]
            return self.img[y0:y1, x0:x1][:, :, ::-1]

    _dband2 = tools_bell.rel_rect(_reg2, tools_bell.DIALOG_BAND)   # 对话框那条带子

    # 这一组的用例都在"**已经有框**"这条路上跑(框一律来自分辨率表):由下面
    # `_bell_tool` 直接种一个表框进去(和 `_scan` 里那个 st 初始化同形),假 OCR
    # 仍按裁剪尺寸区分「任务栏那块 / 对话框条带」。
    _tr2 = [620, 193, 1000, 492]                       # 相对 _reg2 的任务栏框
    _tshape = (_tr2[3] - _tr2[1], _tr2[2] - _tr2[0])   # 裁出来是 (299, 380)

    def _bell_tool(bell_cfg, ocr):
        tool = tools_bell.BellTool(
            types.SimpleNamespace(cfg={"bell": bell_cfg},
                                  log=lambda m, **kw: None),
            _Shot, lambda: types.SimpleNamespace(recognize_blocks=ocr))
        tool.regions = lambda: [list(_reg2)]     # 桩里没有真客户端窗口
        tool._slot[1] = tools_bell.SlotState(
            region=tuple(_reg2), trk=list(_tr2))
        return tool

    with patch(mods=(tools_bell,), cursor_pos=lambda: None):
        # ①梦魇魔:任务栏里换什么坐标都不理 —— "不读"就是**一次都不 OCR**
        _meng = {"trk": "去西梁女国找梦魇魔。剩余时间2小时。"}
        _cnt = {"trk": 0}

        def _ocr_m(img, **kw):
            if img.shape[:2] == _tshape:
                _cnt["trk"] += 1
                # 真任务栏面板里就带「任务追踪」表头(表里的框就是围着它手框的)
                return [HDR, blk(_meng["trk"], 60, 30)]
            return [blk("我发现它的踪迹在西梁女国(28,42),"
                        "少侠们准备好了就过去看看吧。", 60, 30)]

        _mt = _bell_tool({}, _ocr_m)
        for _ in range(3):
            _mt._ts = 0.0
            _mt.tick(force=True)
        _mst = _mt._slot[1]
        _cnt0 = _cnt["trk"]
        _meng["trk"] = "◆蛊虫发现妖魔在宝象国(150,54),快去降服他吧。"
        for _ in range(6):
            _mt._ts = 0.0
            _mt.tick(force=False)
        check("梦魇魔这类:认过一次类型之后,任务栏一次都不再读",
              _mst.trk_mode == "none"
              and _mt.spot == ("西梁女国", 28, 42)
              and _cnt["trk"] == _cnt0,
              f"{_mst.trk_mode} {_mt.spot} 任务栏OCR {_cnt0}->"
              f"{_cnt['trk']}")

        # ②逐妖蛊虫:任务栏开头那条 = 对话框那条(还没用道具)-> 不能拿它当
        # "新坐标"提前收手;用道具后换成新坐标 -> 报出来、连读两次之后收手
        _gu = {"trk": "去宝象国(24,51)使用逐妖蛊虫,然后跟着地上的蛊虫找到妖魔。"}
        _gd = {"text": "去宝象国(24,51)使用逐妖蛊虫,然后妖魔就会出现。"}

        def _ocr_g(img, **kw):
            if img.shape[:2] == _tshape:
                return [HDR, blk(_gu["trk"], 60, 30)]
            return ([blk(_gd["text"], 60, 30)] if _gd["text"] else [])

        _gt = _bell_tool({}, _ocr_g)
        for _ in range(4):
            _gt._ts = 0.0
            _gt.tick(force=True)
        _gst = _gt._slot[1]
        check("逐妖蛊虫:任务栏还没换(还是对话框那条)-> 一直盯着,不提前收手",
              _gst.trk_mode == "item"
              and _gt.spot == ("宝象国", 24, 51),
              f"{_gst.trk_mode} {_gt.spot}")
        _gu["trk"] = "◆蛊虫发现妖魔在建邺城(15,122),快去降服他吧。"
        _gd["text"] = ""                       # 这时候玩家已经把对话框点掉了
        for _ in range(3):
            _gt._ts = 0.0
            _gt.tick(force=True)
        check("逐妖蛊虫:任务栏换出新坐标 -> 报出来、连读两次后收手(不再空转)",
              _gt.spot == ("建邺城", 15, 122)
              and _gst.trk_pub == ("建邺城", 15, 122)
              and _gst.trk_mode == "none",
              f"{_gt.spot} {_gst.trk_mode} {_gst.trk_pub}")

        # ③任务栏那个值必须**自己**出现过两次才算数(原来把 confirmed() 当布尔用、
        #   报的却是最新那次读数 —— "历史里有个稳定值"就放行一次单发读花;实测
        #   23:59:07 连着 5 次都对、第 6 次读成 (118,28) 就报了,红点在
        #   (118,28)/(18,28)/(18,23) 之间跳了三下)。
        #   悬停那条快路**只给巧智魔/怯弱妖**(用户定的):逐妖蛊虫的坐标是任务栏
        #   直接写着的、不靠鼠标 —— 所以鼠标正好压在任务栏附近也不许走那条。
        tools_bell.cursor_pos = lambda: (_tr2[0] + 30, _tr2[1] + 30)   # 压在任务栏上
        _sw = {"dlg": "去宝象国(150,54)使用逐妖蛊虫,然后妖魔就会出现。",
               "trk": "◆蛊虫发现妖魔在宝象国(150,54),快去降服他吧。"}

        def _ocr_sw(img, **kw):
            if img.shape[:2] == _tshape:
                return [HDR, blk(_sw["trk"], 60, 30)]
            return [blk(_sw["dlg"], 60, 30)] if _sw["dlg"] else []

        _wt = _bell_tool({}, _ocr_sw)
        for _ in range(3):                    # 认类型(item),任务栏那句也读稳两次
            _wt._ts = 0.0
            _wt._slot[1].trk_ts = 0.0
            _wt.tick(force=False)
        check("逐妖蛊虫:任务栏开头那条 = 对话框那条 -> 不当成新目标(也不收手)",
              _wt.spot == ("宝象国", 150, 54)
              and _wt._slot[1].trk_mode == "item",
              f"{_wt.spot} {_wt._slot[1].trk_mode}")
        _sw["trk"] = "◆蛊虫发现妖魔在宝象国(118,54)处,快去降服他吧。"  # 读花,还长成悬停那行
        _wt._ts = 0.0
        _wt._slot[1].trk_ts = 0.0
        _wt.tick(force=False)
        check("任务栏读花:单发一次不许覆盖(哪怕鼠标压在任务栏上、读成悬停那行的样子)",
              _wt.spot == ("宝象国", 150, 54), str(_wt.spot))

        # item 档的坐标就写在任务栏里,不靠悬停 —— 鼠标正好压在任务栏附近时
        # **也不许**松开「只认降妖伏魔标题下那段」的范围(否则同面板别的任务的行
        # 会被当成这一轮的新坐标)。这里往任务栏里塞一条**标题圈外**的别的任务、
        # 带图名+坐标,鼠标钉在任务栏上:目标必须还是对话框那条。
        _sc = {"dlg": "去宝象国(24,51)使用逐妖蛊虫,然后妖魔就会出现。",
               "trk": "去宝象国找逐妖蛊虫,然后跟着地上的蛊虫找到妖魔。"}

        def _ocr_sc(img, **kw):
            if _Shot.last != _dband2 and _Shot.last != _reg2:
                return [HDR, TITLE, blk(_sc["trk"], 700, 225),
                        blk("去朱紫国(88,66)寻找某某", 700, 430)]
            return [blk(_sc["dlg"], 60, 30)]

        with patch(mods=(tools_bell,), cursor_pos=lambda: (700, 300)):
            _sct = _bell_tool({}, _ocr_sc)
            _sct_logs = []
            _sct.app.log = lambda m, **kw: _sct_logs.append(m)
            for _ in range(3):
                _sct._ts = 0.0
                _sct._slot[1].trk_ts = 0.0
                _sct.tick(force=False)
        check("范围:item 档鼠标靠近任务栏也不松开标题圈范围(别的任务的坐标不许进来)",
              _sct.spot == ("宝象国", 24, 51),
              f"{_sct.spot} | " + " | ".join(_sct_logs[-6:]))

        # 巧智魔/怯弱妖:悬停那行**就是**鼠标压上去才出来的,单次读数就该认。
        # **类型只由对话框给**(2026-10-16),所以这里对话框那行得点出"巧智魔"来 ——
        # 招式原样是「踪迹在…」(见 `_RE_BELL_DIALOG`),怪名合成加进去,只为让
        # `trk_plan` 判成 hover;真机对话框里到底带不带怪名,是另一回事(见 AGENTS.md)。
        _hw = {"dlg": "我发现它的踪迹在宝象国(150,54),去把巧智魔降服了吧。",
               "trk": ["去宝象国找巧智魔。剩余时间1小时59分。",
                       "在宝象国(118,54)处"]}

        def _ocr_hw(img, **kw):
            # 鼠标压在任务栏上时读的是"任务栏那块"和"悬停那块"(任务栏面板 + 它上面
            # 那行,见 `hover_rect`)—— 两块都摆任务栏那边的内容:悬停那行只画在任务栏
            # 那一带。**悬停那块比任务栏那块还宽**(往左/往上扩出来的),按裁剪尺寸
            # 认它就认错了,直接看刚裁的是哪一块(`_Shot.last`)。
            if _Shot.last != _dband2 and _Shot.last != _reg2:
                return [HDR] + [blk(t, 60, 30 + i * 30)
                                for i, t in enumerate(_hw["trk"])]
            return [blk(_hw["dlg"], 60, 30)]

        _ht = _bell_tool({}, _ocr_hw)
        _ht._ts = 0.0
        _ht._slot[1].trk_ts = 0.0
        _ht.tick(force=False)                  # ① 对话框开周期(巧智魔 -> hover)
        _hw["dlg"] = ""                        # ② 玩家把对话框点掉了:第二个坐标本来
        for _ in range(2):                     #    就是鼠标停任务栏才有的,这时面板
            _ht._ts = 0.0                      #    多半已经关了(不关的话,面板里那条
            _ht._slot[1].trk_ts = 0.0       #    旧坐标会把红点"改口"翻回去)
            _ht.tick(force=False)
        check("巧智魔/怯弱妖:悬停那行单次读数就认(鼠标压在任务栏上正是它的用法)",
              _ht.spot == ("宝象国", 118, 54)
              and _ht._slot[1].trk_mode == "none",   # 读到就收手(盯完)
              f"{_ht.spot} {_ht._slot[1].trk_mode}")

        # 悬停档的收手**必须"命中悬停那行"**(用户 2026-10-17 实测踩到):任务栏
        # 那行正文「去X(x,y)…」也带坐标,只看"读到一个坐标"就收手的话,鼠标压上去
        # 才会出现的第二个坐标就再也拿不到了。
        _hw2 = {"dlg": "我发现它的踪迹在宝象国(150,54),去把巧智魔降服了吧。",
                "trk": "去宝象国(150,54)使用逐妖蛊虫,然后妖魔就会出现。"}

        def _ocr_h2(img, **kw):
            if _Shot.last != _dband2:              # 任务栏那一支(表框那一小块)
                return [HDR, TITLE, blk(_hw2["trk"], 700, 300)]
            return [blk(_hw2["dlg"], 60, 30)]

        _h2logs = []
        _h2 = tools_bell.BellTool(
            types.SimpleNamespace(
                cfg={"bell": {}},
                logs=_h2logs,
                log=lambda m, **kw: _h2logs.append(m)),
            _Shot, lambda: types.SimpleNamespace(recognize_blocks=_ocr_h2))
        _h2.regions = lambda: [list(_reg2)]
        _h2._slot[1] = tools_bell.SlotState(
            region=tuple(_reg2), trk=list(_tr2))
        tools_bell.cursor_pos = lambda: (_tr2[0] + 30, _tr2[1] + 30)
        _h2._ts = 0.0
        _h2.tick(force=False)                  # ①开周期(hover):这拍提前 return,不读任务栏
        _h2._ts = 0.0
        _h2._slot[1].trk_ts = 0.0
        _h2.tick(force=False)                  # ②任务栏那拍:读到「去X(x,y)」正文行
        check("巧智魔/怯弱妖:任务栏读到「去X(x,y)」(不是悬停那行)不许收手",
              _h2._slot[1].trk_mode == "hover"
              and not any("盯完" in m for m in _h2logs),
              f"mode={_h2._slot[1].trk_mode} logs={_h2logs}")
        # ③ 换成悬停那行:框一直在(来自表),单次就认 + 收手
        _hw2["trk"] = "在宝象国(118,54)处"      # 这才是悬停那行
        _h2._ts = 0.0
        _h2._slot[1].trk_ts = 0.0
        _h2.tick(force=False)
        check("巧智魔/怯弱妖:读到悬停那行 -> 认它、并收手",
              _h2._slot[1].trk_mode == "none"
              and _h2.spot == ("宝象国", 118, 54)
              and any("盯完" in m for m in _h2logs),
              f"mode={_h2._slot[1].trk_mode} spot={_h2.spot}")

        # ---- 报出目标那一行(小窗没有日志区,这就只是文件日志里的结论行)----
        # 对话框/任务栏认下坐标后各报一条;块数/耗时/读到啥在各自的读数行里。
        _ui9 = {"dlg": "又一个！这次是一只精巧的巧智魔。它足智多谋而且狡猾无比。"
                       "我发现它的踪迹在朱紫国(127,90),少侠们准备好了就过去看看吧。",
                "trk": "去朱紫国找巧智魔。剩余时间2小时。"}
        _ulogs = []

        def _ocr_ui(img, **kw):
            if _Shot.last == _dband2:
                return [blk(_ui9["dlg"], 100, 430)]
            return [HDR, TITLE, blk(_ui9["trk"], 700, 300)]

        _ut = tools_bell.BellTool(
            types.SimpleNamespace(
                cfg={"bell": {}}, logs=[],
                log=lambda m, **kw: _ulogs.append(m)),
            _Shot, lambda: types.SimpleNamespace(recognize_blocks=_ocr_ui))
        _ut.regions = lambda: [list(_reg2)]
        _ut._slot[1] = tools_bell.SlotState(
            region=tuple(_reg2), trk=list(_tr2))
        tools_bell.cursor_pos = lambda: (_tr2[0] + 30, _tr2[1] + 30)
        _ut._ts = 0.0
        _ut._slot[1].trk_ts = 0.0
        _ut.tick(force=False)                  # ①对话框(巧智魔):开周期
        _ut._ts = 0.0
        _ut._slot[1].trk_ts = 0.0
        _ut.tick(force=False)                  # ②任务栏那一拍(巧智魔的行没坐标)
        check("日志:对话框那拍报出目标(妖魔位置行,图名在前)",
              any(t == "[铃铛]妖魔位置: 朱紫国 (127,90)[来自对话框]"
                  for t in _ulogs),
              str(_ulogs))
        check("日志:整窗/学框那些行没有了(框来自表,没有那一拍)",
              all("整窗" not in t and "学到框" not in t for t in _ulogs),
              str([t for t in _ulogs if "整窗" in t or "学到框" in t]))
        # **同一件事不重复报**:报出目标那行就是结论行;同值再来(任务栏那拍
        # 和对话框同一个坐标)被 _last 去重,不再出第二条。
        _ui9["trk"] = "◆蛊虫发现妖魔在朱紫国(127,90),快去降服他吧。"
        for _ in range(3):                     # 任务栏给出坐标 -> 连读两次 -> 报出来
            _ut._ts = 0.0
            _ut._slot[1].trk_ts = 0.0
            _ut.tick(force=False)
        check("日志:同一件事只出现一次(同值被去重,任务栏那拍不再报)",
              _ulogs.count("[铃铛]妖魔位置: 朱紫国 (127,90)[来自对话框]") == 1
              and not any("[来自任务栏]" in t for t in _ulogs),
              str(_ulogs))

        # 待确认的新坐标**不能因为"一拍没读到"就丢**(2026-10-17 实测:第二遍重扫那拍
        # 撞上面板暗比 0.59 vs 阈值 0.60 被判"消失",(108,26) 直接没了,红点一直不刷新)。
        # 现在给 TTL:面板消失/读不到**持续超过 `PEND_TTL`** 才作废。
        _pd = {"n": 0}
        _A = blk("有的妖魔行迹隐秘。去朱紫国(127,90)使用蛊虫,然后跟着它。",
                 100, 430)
        _pdband = tools_bell.rel_rect(win.rect, tools_bell.DIALOG_BAND)

        def _ocr_pd(img, **kw):
            _pd["n"] += 1
            if Win.last != _pdband:            # 任务栏那一支不掺和
                return []
            # 第一遍读到 A;**第二遍(重扫那拍)什么都读不到** —— 就是真机那次
            # "面板暗比 0.59 被判消失"的样子;之后又读得回来。
            return [] if _pd["n"] == 2 else [_A]

        _pt = tools_bell.BellTool(
            types.SimpleNamespace(
                cfg={"bell": {}},
                logs=[], log=lambda m, **kw: None),
            lambda: win, lambda: types.SimpleNamespace(recognize_blocks=_ocr_pd))
        _pt._slot[1] = seed_state(win.rect, mode="item")
        _pt._cycle[1] = ("宝象国", 150, 54)
        win.dialog = True
        _pt._ts = 0.0
        _pt.tick(force=False)                  # 第一遍读到 A;重扫那拍没读到
        check("对话框:第二遍没读到 -> 待确认的新值别丢(等 TTL,不然红点不刷新)",
              _pt._slot[1].dlg_pend == ("朱紫国", 127, 90)
              and _pt.ui_state()["spot"] != ("朱紫国", 127, 90),
              f"pend={_pt._slot[1].dlg_pend} "
              f"spot={_pt.ui_state()['spot']}")
        _pt._ts = 0.0
        _pt._slot[1].dlg_ts = 0.0           # 假装过了 0.3 秒(测试不睡觉)
        _pt.tick(force=False)                  # 下一拍:同一句读回同一个值 -> 采信
        check("对话框:下一拍读到同一个值 -> 立刻采信(不用重新等两遍)",
              _pt._cycle.get(1) == ("朱紫国", 127, 90),
              str(_pt._cycle.get(1)))

        # 2026-10-17 16:05 真机抓出来的:**pend 刚记下就被当"超时"扔掉**。
        # `dlg_gone` 记的是"面板上次消失"的时刻,面板隔一阵就藏一下,它一直是老值;
        # 不复位的话,下一拍"面板又不见了"直接算超时(now - 老时刻 > PEND_TTL),
        # 紧接着那拍读到同一个值也只能重新走"先不覆盖" —— 日志里就是连着两条
        # 「西梁女国(99,36) 先不覆盖」。记 pend 时必须把 TTL 计时归零。
        _pd2 = {"n": 0}
        _A2 = blk("我发现它的踪迹在西梁女国(99,36),少侠们过去看看吧。", 100, 430)

        def _ocr_pd2(img, **kw):
            _pd2["n"] += 1
            if Win.last != _pdband:            # 任务栏那一支不掺和
                return []
            return [] if _pd2["n"] == 2 else [_A2]

        _logs2 = []
        _pt2 = tools_bell.BellTool(
            types.SimpleNamespace(
                cfg={"bell": {}},
                logs=_logs2,
                log=lambda m, **kw: _logs2.append(m)),
            lambda: win, lambda: types.SimpleNamespace(recognize_blocks=_ocr_pd2))
        _pt2._slot[1] = seed_state(win.rect, mode="item")
        _pt2._slot[1].dlg_gone = time.time() - 60   # 面板上次消失是 1 分钟前
        _pt2._cycle[1] = ("宝象国", 150, 54)
        win.dialog = True
        _pt2._ts = 0.0
        _pt2.tick(force=False)                 # 第一遍读到 A2;第二遍没读到
        check("对话框:记 pend 时 TTL 计时归零(旧的面板消失时刻不许把新值顶掉)",
              _pt2._slot[1].dlg_pend == ("西梁女国", 99, 36),
              f"pend={_pt2._slot[1].dlg_pend} "
              f"gone={_pt2._slot[1].dlg_gone}")
        _pt2._ts = 0.0
        _pt2._slot[1].dlg_ts = 0.0
        _pt2.tick(force=False)                 # 下一拍读回同一个值 -> 改口
        check("对话框:panel 闪一下之后读到同一个值 -> 改口(不再重新等两遍)",
              _pt2._cycle.get(1) == ("西梁女国", 99, 36)
              and any("对话框改口" in m for m in _logs2),
              f"{_pt2._cycle.get(1)} | " + " | ".join(_logs2)[:160])

        # 复读那拍**面板已经关了**(用户手快/对话自动关):两遍一致根本做不了。
        # 真机 16:06:28:「宝象国(149,53)」刚读到、面板就没了,整轮任务丢了,
        # 红点一直挂在上一轮(用户:"卡死不动了")。对话框里的目标是权威的 ——
        # 这一种情况直接用第一遍的值。
        _pd3 = {"n": 0}
        _A3 = blk("我发现它的踪迹在宝象国(149,53),少侠们过去看看吧。", 100, 430)
        _win_bak = win.dialog

        def _ocr_pd3(img, **kw):
            _pd3["n"] += 1
            if Win.last != _pdband:
                return []
            if _pd3["n"] == 1:
                win.dialog = False            # 读完这一下,面板就被关掉了
                return [_A3]
            return []

        _logs3 = []
        _pt3 = tools_bell.BellTool(
            types.SimpleNamespace(
                cfg={"bell": {}},
                logs=_logs3,
                log=lambda m, **kw: _logs3.append(m)),
            lambda: win, lambda: types.SimpleNamespace(recognize_blocks=_ocr_pd3))
        _pt3._slot[1] = seed_state(win.rect, mode="item")
        _pt3._cycle[1] = ("西梁女国", 73, 94)
        win.dialog = True
        _pt3._ts = 0.0
        _pt3.tick(force=False)
        check("对话框:复读那拍面板已经关了 -> 直接用第一遍的值(别把整轮丢了)",
              _pt3._cycle.get(1) == ("宝象国", 149, 53)
              and any("面板已经关了" in m for m in _logs3),
              f"{_pt3._cycle.get(1)} | " + " | ".join(_logs3)[:160])
        win.dialog = _win_bak

        # 2026-10-16 那两条(保留):①悬停档的裁剪**固定往上多留一截**
        # (`hover_rect` 的 `HOVER_LIFT=120`)—— 那行「在X(x,y)处」画在「降妖伏魔」
        # 标题**上方**,不往上扩就永远落在裁剪之外;②单次读到「在X(x,y)处」就认。
        # (鼠标不接近时压根不读 —— 那条是下面"鼠标把门"的规则。)
        _nh = {"dlg": "我发现它的踪迹在宝象国(150,54),去把巧智魔降服了吧。",
               "trk": "在宝象国(118,54)处"}
        _hs = []

        def _ocr_nh(img, **kw):
            _hs.append((img.shape[0], kw.get("limit_side")))
            if _Shot.last != _dband2:              # 任务栏那一支(含加高的悬停块)
                return [HDR, blk(_nh["trk"], 60, 30)]
            return [blk(_nh["dlg"], 60, 30)]

        tools_bell.cursor_pos = lambda: (_tr2[0] + 30, _tr2[1] + 30)   # 压在任务栏上
        _nt = _bell_tool({}, _ocr_nh)
        _nt._ts = 0.0
        _nt._slot[1].trk_ts = 0.0
        _nt.tick(force=False)                      # ① 对话框开周期(巧智魔 -> hover)
        _hs.clear()
        _nt._ts = 0.0
        _nt._slot[1].trk_ts = 0.0
        _nt.tick(force=False)                      # ② 鼠标到了:读加高过的那块
        check("悬停档:读的是往上加高过的那块,而且**单次**读到就认",
              _nt.spot == ("宝象国", 118, 54)
              and _hs and _hs[0][1] == tools_bell.OCR_LIMIT
              and all(h > _tshape[0] for h, _l in _hs),
              f"{_nt.spot} 裁剪{_hs}(原框高 {_tshape[0]},"
              f"HOVER_LIFT={tools_bell.HOVER_LIFT})")

        # ---- hover 档:任务栏扫描由**鼠标位置**把门(用户定的 2026-10-16) ----
        # "鼠标接近红框就开快速扫描,离开就停":不接近时任务栏这一支**整个跳过**
        # (一拍都不读、一次 OCR 都不做 —— 没鼠标就没有悬停行,读它纯属白花);
        # 鼠标一接近,那一拍自然开始读。
        # 不接近**不打日志**(省得刷屏,心跳里能看到节奏)。**item 档不受这道门管**
        # (逐妖蛊虫的坐标是任务栏里直接写着的,跟鼠标无关)。
        _gate = {"n": 0,
                 "dlg": "我发现它的踪迹在宝象国(150,54),去把巧智魔降服了吧。",
                 "trk": "在宝象国(118,54)处"}

        def _ocr_gate(img, **kw):
            # 只数"任务栏那一支"的读数(对话框那条主路照旧要跑,不然类型都定不出来)
            if _Shot.last != _dband2:
                _gate["n"] += 1
                return [HDR, blk(_gate["trk"], 60, 30)]
            return [blk(_gate["dlg"], 60, 30)]

        tools_bell.cursor_pos = lambda: (0, 0)     # 鼠标在别处(离任务栏很远)
        _gt2 = _bell_tool({}, _ocr_gate)
        _gt2._ts = 0.0
        _gt2._slot[1].trk_ts = 0.0
        _gt2.tick(force=False)                     # ① 对话框开周期(巧智魔 -> hover)
        _gate["n"] = 0
        for _ in range(3):                         # ② 鼠标一直在别处
            _gt2._ts = 0.0
            _gt2._slot[1].trk_ts = 0.0
            _gt2.tick(force=False)
        _n_away = _gate["n"]
        check("hover 档:鼠标不在附近 -> 任务栏一拍都不读(零 OCR)",
              _gt2._slot[1].trk_mode == "hover" and _n_away == 0,
              f"{_gt2._slot[1].trk_mode} 鼠标在别处时读任务栏 {_n_away} 次")

        _gt3 = _bell_tool({}, _ocr_gate)
        _gt3._slot[1] = seed_state(_reg2, trk=None, mode="hover")
        # 没量到框的尺寸(trk=None:不支持的分辨率,2026-10-21 起不读任务栏)
        tools_bell.cursor_pos = lambda: (5000, 5000)   # 连客户端窗口都不在附近
        _gate["n"] = 0
        for _ in range(3):                         # 没框:连读都不该读
            _gt3._ts = 0.0
            _gt3._slot[1].trk_ts = 0.0
            _gt3.tick(force=False)
        check("hover 档:没量到框的尺寸 -> 任务栏一拍都不读(没有整窗找框这回事了)",
              _gt3._slot[1].trk is None and _gate["n"] == 0,
              f"框={_gt3._slot[1].trk} 读任务栏 {_gate['n']} 次")

        tools_bell.cursor_pos = lambda: (_tr2[0] + 30, _tr2[1] + 30)   # 鼠标进附近
        _gate["n"] = 0
        _gt2._ts = 0.0
        _gt2._slot[1].trk_ts = 0.0
        _gt2.tick(force=False)
        _n_near = _gate["n"]
        tools_bell.cursor_pos = lambda: (0, 0)     # 又离开
        for _ in range(2):
            _gt2._ts = 0.0
            _gt2._slot[1].trk_ts = 0.0
            _gt2.tick(force=False)
        check("hover 档:鼠标一进附近就开扫,离开又停",
              _n_near >= 1 and _gate["n"] == _n_near,
              f"进附近时读 {_n_near} 次,离开后又读 {_gate['n'] - _n_near} 次")

        tools_bell.cursor_pos = lambda: (0, 0)     # 鼠标在别处
        _gate["n"] = 0
        _gate["dlg"] = "去宝象国(24,51)使用逐妖蛊虫,然后妖魔就会出现。"
        # 任务栏那句**不带坐标**:这样 item 档不会"读到两次就收手"(那会把它自己的
        # 读数停掉,和鼠标门搅在一起分不清)
        _gate["trk"] = "去宝象国找逐妖蛊虫。剩余时间1小时59分。"
        _it2 = _bell_tool({}, _ocr_gate)
        _it2._slot[1] = seed_state(_reg2, trk=_tr2, mode="item")
        for _ in range(3):                         # item 档:照旧读
            _it2._ts = 0.0
            _it2._slot[1].trk_ts = 0.0
            _it2.tick(force=False)
        check("hover 档的鼠标门管不到 item 档:鼠标在别处也照旧盯任务栏",
              _it2._slot[1].trk_mode == "item" and _gate["n"] >= 2,
              f"{_it2._slot[1].trk_mode} 鼠标在别处仍读 {_gate['n']} 次")
        _gate["dlg"] = "我发现它的踪迹在宝象国(150,54),去把巧智魔降服了吧。"
        _gate["trk"] = "在宝象国(118,54)处"

        # ---- 学到的框"超出扫描区就往内挪"(用户定的 2026-10-16) ----
        # 框是"窗口还大"的时候学的,后来 region 变小(改窗口尺寸/换客户端),直接用
        # 就有一截落在 region 外 —— 截图在那个边界切掉,行尾的坐标就没了(实测
        # `宝象 40，12）` 少了"1"和"国")。规矩:**宽高不变**,整体左移/上移(优先保住
        # 右边/下边,坐标在那儿),挪了才写一行日志。
        check("任务栏框:超出扫描区就往内挪(宽高不变,优先保住右边/下边)",
              tools_bell.fit_rect([0, 0, 1000, 880], [900, 100, 1100, 400])
              == [800, 100, 1000, 400]                     # 右出界 -> 左移
              and tools_bell.fit_rect([0, 0, 1000, 880], [10, 800, 300, 1000])
              == [10, 680, 300, 880]                       # 下出界 -> 上移
              and tools_bell.fit_rect([0, 0, 1000, 880], [10, 20, 300, 300])
              == [10, 20, 300, 300]                        # 没出界:原样
              and tools_bell.fit_rect([0, 0, 1000, 880], [-50, -20, 300, 300])
              == [0, 0, 350, 320],                         # 左/上出界 -> 右移/下移
              f"{tools_bell.fit_rect([0, 0, 1000, 880], [900, 100, 1100, 400])}")

        _far6 = {"last": None}
        _logs6 = []

        def _shot6(region):
            _far6["last"] = [int(v) for v in region]
            x0, y0, x1, y1 = [int(v) for v in region]
            return np.ascontiguousarray(
                np.full((y1 - y0, x1 - x0, 3), (200, 120, 60), np.uint8)[:, :, ::-1])

        app6 = types.SimpleNamespace(
            cfg=core.split_config({
                                   "active_tool": "bell"}),
            logs=[], log=lambda m, **kw: app6.logs.append(m))
        tool6 = tools_bell.BellTool(
            app6, lambda: types.SimpleNamespace(grab=_shot6),
            lambda: types.SimpleNamespace(
                recognize_blocks=lambda img, **kw: [
                    HDR, blk("在宝象国(118,54)处", 60, 30)]))
        tool6.regions = lambda: [list(_reg2)]
        # 学到的框右边缘 1060 超出 region(1000) -> 这一拍该整体左移 60
        tool6._slot[1] = seed_state(_reg2, trk=(760, 200, 1060, 500), mode="item")
        tools_bell.cursor_pos = lambda: (0, 0)
        tool6._ts = 0.0
        tool6._slot[1].trk_ts = 0.0
        tool6.tick(force=False)
        _moved = _far6["last"]
        check("任务栏框:超出扫描区时裁剪整体往里挪(宽不变)+ 日志留一行",
              _moved == [700, 200, 1000, 500]
              and any("任务栏框超出扫描区,已向内挪" in m and "原 x1=1060" in m
                      and "现 x1=1000" in m for m in app6.logs),
              f"裁到 {_moved} | " + " | ".join(
                  m for m in app6.logs if "向内挪" in m))

        # ---- 新坐标"换参数复读"确认(用户定的 2026-10-16) ----
        # 半透明面板 + 压缩让检测本身不稳,同一行换个 det 下限就能差字(实测
        # `宝象 40，12）` 少了"1"和"国")。同一块裁剪用 `TRK_RECHECK_LIMIT` 再读一次,
        # 两次 (图名,x,y) 一样才采信;不一样就不报、留着旧目标。
        def _recheck_case(same):
            st7 = {"dlg": "去宝象国(24,51)使用逐妖蛊虫,然后妖魔就会出现。",
                   "trk2": ("◆蛊虫发现妖魔在宝象国(150,54),快去降服他吧。"
                            if same else
                            "◆蛊虫发现妖魔在建邺城(15,122),快去降服他吧。"),
                   "limits": []}

            def ocr7(img, **kw):
                lim = kw.get("limit_side")
                if _Shot.last != _dband2:              # 任务栏那一支
                    st7["limits"].append(lim)
                    return [HDR, blk(
                        "◆蛊虫发现妖魔在宝象国(150,54),快去降服他吧。", 60, 30)
                        if lim == tools_bell.OCR_LIMIT
                        else blk(st7["trk2"], 60, 30)]
                return [blk(st7["dlg"], 60, 30)]

            app7 = types.SimpleNamespace(
                cfg=core.split_config({
                                       "active_tool": "bell"}),
                logs=[], log=lambda m, **kw: app7.logs.append(m))
            tool7 = tools_bell.BellTool(
                app7, _Shot, lambda: types.SimpleNamespace(recognize_blocks=ocr7))
            tool7.regions = lambda: [list(_reg2)]
            tool7._slot[1] = seed_state(_reg2, trk=_tr2)
            tool7._ts = 0.0
            tool7._slot[1].trk_ts = 0.0
            tool7.tick(force=False)                    # ① 对话框开周期(逐妖蛊虫 -> item)
            _first = tool7.spot
            tool7._ts = 0.0
            tool7._slot[1].trk_ts = 0.0
            tool7.tick(force=True)                     # ② 任务栏报新坐标(force 让门控让路)
            return (_first, tool7.spot, st7["limits"],
                    [m for m in app7.logs if "复读不一致" in m])

        _c1, _s1, _lim1, _lg1 = _recheck_case(True)    # 两次一致 -> 采信
        check("任务栏复读:同一块换 det 下限再读一次,一致 -> 采信并报",
              _lim1 == [tools_bell.OCR_LIMIT, tools_bell.TRK_RECHECK_LIMIT]
              and _s1 == ("宝象国", 150, 54) and not _lg1,
              f"{_c1} -> {_s1} limits={_lim1} {_lg1}")
        _c2, _s2, _lim2, _lg2 = _recheck_case(False)   # 两次不一致 -> 不报
        check("任务栏复读:两次不一致 -> 不报(保留旧目标)+ 日志里写明",
              _lim2 == [tools_bell.OCR_LIMIT, tools_bell.TRK_RECHECK_LIMIT]
              and _s2 == _c2 == ("宝象国", 24, 51)
              and _lg2 and "320 下读作 建邺城 (15,122)" in _lg2[0]
              and "先不更新" in _lg2[0],
              f"{_c2} -> {_s2} limits={_lim2} {_lg2}")

        # ---- 对话框那条文字带的 det 档(2026-10-21) ----
        # 那块字大,第一遍按**原像素**跑(max 900);复读那一拍照旧走 480 的放大档
        # —— 第一遍 max、第二遍 min,两遍不同参数、读出来一样才采信。
        _dlg_lim = []

        def _ocr_dl(img, **kw):
            if _Shot.last == _dband2:                    # 对话框的文字带
                _dlg_lim.append((kw.get("limit_side"), kw.get("limit_type")))
                return [blk("去宝象国(150,54)使用逐妖蛊虫,然后妖魔就会出现。",
                            60, 30)]
            return [HDR, blk("去宝象国(150,54)使用逐妖蛊虫,然后妖魔就会出现。",
                             60, 30)]

        _dl = _bell_tool({}, _ocr_dl)
        _dl._ts = 0.0
        _dl.tick(force=False)
        check("对话框 det 档:第一遍按原像素(max 900),复读换 480 放大档",
              _dlg_lim[:2] == [(tools_bell.DLG_LIMIT_SIDE, tools_bell.DLG_LIMIT_TYPE),
                               (tools_bell.OCR_LIMIT, None)]
              and _dl.spot == ("宝象国", 150, 54),
              f"{_dlg_lim} spot={_dl.spot}")

        check("过程日志:任务栏那一行带诊断后缀(裁剪宽 + 左右贴边,贴边=可能在切字)",
              tools_bell.edge_note([0, 0, 300, 200], [0, 0, 1000, 880])
              == " [宽300/左贴边]"
              and tools_bell.edge_note([700, 0, 1000, 200], [0, 0, 1000, 880])
              == " [宽300/右贴边]"
              and tools_bell.edge_note([0, 0, 1000, 200], [0, 0, 1000, 880])
              == " [宽1000/左贴边、右贴边]"
              and tools_bell.edge_note([700, 0, 900, 200], [0, 0, 1000, 880])
              == " [宽200/没贴边]"
              and any("识别 任务栏" in m and "[宽" in m for m in app6.logs),
              " | ".join(m for m in app6.logs if "识别 任务栏" in m)[:120])

        # ---- hover 档的"收手话术"(用户给的 4 张对话框截图,2026-10-16) ----
        # 对话框里出现这些话说明"追/逃"那一段结束了 -> 这个周期**不再扫任务栏**
        # (第二个坐标本来就只有悬停那行会喂,追完了就没了)。判据只用**核心词**
        # (`HOVER_STOP_WORDS`):整句太长,OCR 读花时对不上。原文:
        #   怯弱妖 1. 三番两次，我都被你累断气了。你怎么这么执着啊。跑不动了。
        #            (红字)终于逮到你了，看打。 / 我也跑累了，等下…
        #   怯弱妖 2. 打就打，我……我，我……你怎么不怕我。
        #   巧智魔 3. 金蝉脱壳可是我的拿手好戏，刚试过了，拿我没办法吧。
        #            (红字)也就是个会跑的小妖魔，看我再来收服…等我准备好了再来。
        #   巧智魔 4. 你再抓，我再跑；你再抓，我再跑呀……嘻嘻。
        _STOP_SHOTS = [
            ("三番两次，我都被你累断气了。你怎么这么执着啊。跑不动了。"
             "终于逮到你了，看打。我也跑累了，等下…"),
            ("打就打，我……我，我……你怎么不怕我。"),
            ("金蝉脱壳可是我的拿手好戏，刚试过了，拿我没办法吧。"
             "也就是个会跑的小妖魔，看我再来收服…等我准备好了再来。"),
            ("你再抓，我再跑；你再抓，我再跑呀……嘻嘻。"),
        ]
        _HOVER_DLG = "我发现它的踪迹在宝象国(150,54),去把巧智魔降服了吧。"
        _ITEM_DLG = "去宝象国(24,51)使用逐妖蛊虫,然后妖魔就会出现。"
        _NONE_DLG = "我发现它的踪迹在西梁女国(28,42),少侠们过去看看吧。"

        def _stop_case(dlg, stop_text, where="dlg"):
            """开一个周期(类型由 dlg 决定),再让对话框/任务栏出现 stop_text。

            返回 (开周期后的类型, 之后的类型, 话术出现后又读了几次任务栏, 收手日志)。
            面板内容"变了"这件事假屏上看不出来(`_Shot` 是张静态图),所以话术那几拍
            用 `force=True` 逼出重读。鼠标钉在任务栏上(鼠标不在附近时 hover 档本来就
            不读,那会把"之后一次都不读"变成空话)。
            """
            tools_bell.cursor_pos = lambda: (_tr2[0] + 30, _tr2[1] + 30)
            stt = {"dlg": dlg, "trk": "去宝象国找巧智魔。剩余时间1小时59分。",
                   "stop": ""}
            cnt = {"n": 0}

            def ocr10(img, **kw):
                if _Shot.last != _dband2:              # 任务栏那一支(含悬停那块)
                    cnt["n"] += 1
                    return [HDR, blk(stt["trk"] + (stt["stop"] if where == "trk"
                                                   else ""), 60, 30)]
                return [blk(stt["dlg"] + (stt["stop"] if where == "dlg" else ""),
                            60, 30)]

            app10 = types.SimpleNamespace(
                cfg=core.split_config({
                                       "active_tool": "bell"}),
                logs=[], log=lambda m, **kw: app10.logs.append(m))
            tool10 = tools_bell.BellTool(
                app10, _Shot,
                lambda: types.SimpleNamespace(recognize_blocks=ocr10))
            tool10.regions = lambda: [list(_reg2)]
            tool10._slot[1] = seed_state(_reg2, trk=_tr2)
            for _ in range(2):                     # ① 先把这个周期开起来
                tool10._ts = 0.0
                tool10._slot[1].trk_ts = 0.0
                tool10.tick(force=False)
            _m0 = tool10._slot[1].trk_mode
            cnt["n"] = 0                           # ② 话术出现,往后跑三拍
            stt["stop"] = stop_text
            for _ in range(3):
                tool10._ts = 0.0
                tool10._slot[1].trk_ts = 0.0
                tool10.tick(force=True)
            return (_m0, tool10._slot[1].trk_mode, cnt["n"],
                    [m for m in app10.logs if "收手话术" in m])

        _bad = []
        for _txt in _STOP_SHOTS:
            _hitw = next((w for w in tools_bell.HOVER_STOP_WORDS if w in _txt), "")
            _m0, _m1, _n, _lg = _stop_case(_HOVER_DLG, _txt)
            if not (_hitw and _m0 == "hover" and _m1 == "none" and _n == 0
                    and _lg and _hitw in _lg[0]):
                _bad.append((_hitw, _m0, _m1, _n, _lg))
        check("收手话术:hover 档出现这 4 张截图里的话 -> 收手,任务栏一次不再读",
              not _bad, str(_bad))

        _m0, _m1, _n, _lg = _stop_case(_HOVER_DLG, "~~逮到你了！！（读花的样子")
        _m0b, _m1b, _nb, _lgb = _stop_case(_HOVER_DLG, "（读花)逮到你了")
        check("收手话术:核心词够稳(标点去光/前后加乱码,读花的样子也认)",
              _m1 == "none" and _n == 0 and _lg and "逮到你了" in _lg[0]
              and _m1b == "none" and _nb == 0 and _lgb
              and "逮到你了" in _lgb[0],
              f"{_lg} | {_lgb}")

        _m0, _m1, _n, _lg = _stop_case(_NONE_DLG, _STOP_SHOTS[0])
        check("收手话术(反例):none 档出现同样的话 -> 什么都不变(none 也不读任务栏)",
              _m0 == "none" and _m1 == "none" and _n == 0 and not _lg,
              f"{_m0}->{_m1} 读{_n}次 {_lg}")
        _m0, _m1, _n, _lg = _stop_case(_ITEM_DLG, _STOP_SHOTS[0])
        check("收手话术(反例):item 档出现同样的话 -> 不被它停下,照样盯任务栏",
              _m0 == "item" and _m1 == "item" and _n >= 2 and not _lg,
              f"{_m0}->{_m1} 读{_n}次 {_lg}")
        _m0, _m1, _n, _lg = _stop_case(_HOVER_DLG, _STOP_SHOTS[0], where="trk")
        check("收手话术(反例):同样的话出现在**任务栏**那块 -> 不算(只认对话框原文)",
              _m0 == "hover" and _m1 == "hover" and _n >= 2 and not _lg,
              f"{_m0}->{_m1} 读{_n}次 {_lg}")

        # 2026-10-16 调整过的词表:逐个新词各跑一条(读花的样子:前后加乱码,
        # 只留那个词) —— hover 档命中就该收手、日志写它、之后任务栏一次不再读。
        # (`拿手好戏` 2026-10-17 被用户去掉了,所以不在这个表里;它的反例在下面。)
        _new_words = ["刚试过了", "三番两次", "累短气", "累断气", "打就打"]
        _bad2 = []
        for _w in _new_words:
            _m0, _m1, _n, _lg = _stop_case(_HOVER_DLG, f"~~{_w}！！")
            if not (_m0 == "hover" and _m1 == "none" and _n == 0
                    and _lg and f"({_w})" in _lg[0]):
                _bad2.append((_w, _m0, _m1, _n, _lg))
        check("收手话术:2026-10-16 新加的那几个词逐个都收手(刚试过了/三番两次/"
              "累短气/累断气/打就打)",
              not _bad2, str(_bad2))
        # **反例**:`拿手好戏` 2026-10-17 也被去掉了 —— 它不再触发收手
        _m0, _m1, _n, _lg = _stop_case(_HOVER_DLG, "金蝉脱壳可是我的拿手好戏。")
        check("收手话术(反例):`拿手好戏` 已从词表去掉 -> 不再收手,照旧盯任务栏",
              _m0 == "hover" and _m1 == "hover" and _n >= 2 and not _lg,
              f"{_m0}->{_m1} 读{_n}次 {_lg}")
        # **反例**:`金蝉脱壳` 这次被用户从表里去掉了 —— 它不再触发收手
        _m0, _m1, _n, _lg = _stop_case(_HOVER_DLG, "金蝉脱壳,拿我没办法吧。")
        check("收手话术(反例):`金蝉脱壳` 已从词表去掉 -> 不再收手,照旧盯任务栏",
              _m0 == "hover" and _m1 == "hover" and _n >= 2 and not _lg,
              f"{_m0}->{_m1} 读{_n}次 {_lg}")
        tools_bell.cursor_pos = lambda: None

        # 正盯着等坐标的那两档:**读不到字也不许退回慢节奏**。真机上任务栏整块
        # 没显示约占一半时间,一退避就可能正好漏掉它刚出现的那一下,而且
        # `trk_gap` 一旦退回 1.0s,整个周期都不会再调回来(用户定的:逐妖蛊虫
        # 0.5s 一直盯到"同一个坐标连读两次"才收手)。
        _cg = {"trk": "◆蛊虫发现妖魔在宝象国(150,54),快去降服他吧。"}

        def _ocr_cg(img, **kw):
            if img.shape[:2] == _tshape:
                return ([HDR, blk(_cg["trk"], 60, 30)]
                        if _cg["trk"] is not None else [])
            return [blk("去宝象国(24,51)使用逐妖蛊虫,然后妖魔就会出现。",
                        60, 30)]

        _ct = _bell_tool({}, _ocr_cg)
        for _ in range(2):                        # 认类型 -> item
            _ct._ts = 0.0
            _ct._slot[1].trk_ts = 0.0
            _ct.tick(force=False)
        _cg["trk"] = None                         # 任务栏整块没显示
        _ct._ts = 0.0
        _ct._slot[1].trk_ts = 0.0
        _ct.tick(force=False)
        check("逐妖蛊虫盯着第二个坐标:读不到字也不退回 1.0s(一直 0.25s)",
              _ct._slot[1].trk_mode == "item"
              and _ct._slot[1].trk_gap == tools_bell.TRK_ITEM_GAP,
              f"{_ct._slot[1].trk_mode} "
              f"节奏{_ct._slot[1].trk_gap}")

        # 巧智魔/怯弱妖那条悬停行同理(只闪一下;用的是 HOVER_GAP)。
        # 同样:对话框那行得点出"巧智魔"来 —— 类型只由对话框给(2026-10-16)。
        # 任务栏那份文字**没带坐标**(鼠标在别处时任务栏就只写"去X找巧智魔"那样):
        # 这样"盯着看"不会提前收手,才测得到"空读时用的是 HOVER_GAP"。
        _ch = {"trk": ["去宝象国找巧智魔。剩余时间1小时59分。"]}

        def _ocr_ch(img, **kw):
            # 悬停档的裁剪**往上加高过**(`hover_rect`,2026-10-16 起不再看鼠标在不在),
            # 按裁剪尺寸认会认错 —— 直接看刚裁的是哪一块(`_Shot.last`),和 `_ocr_hw` 一样。
            if _Shot.last != _dband2:
                if _ch["trk"] is None:
                    return []
                return [HDR] + [blk(t, 60, 30 + i * 30)
                                for i, t in enumerate(_ch["trk"])]
            return [blk("我发现它的踪迹在宝象国(150,54),去把巧智魔降服了吧。",
                        60, 30)]

        _ct2 = _bell_tool({}, _ocr_ch)
        for _ in range(2):
            _ct2._ts = 0.0
            _ct2._slot[1].trk_ts = 0.0
            _ct2.tick(force=False)
        _ch["trk"] = None
        _ct2._ts = 0.0
        _ct2._slot[1].trk_ts = 0.0
        _ct2.tick(force=False)
        check("巧智魔/怯弱妖盯着悬停那行:读不到字也不退回 1.0s(用 HOVER_GAP)",
              _ct2._slot[1].trk_mode == "hover"
              and _ct2._slot[1].trk_gap == tools_bell.HOVER_GAP,
              f"{_ct2._slot[1].trk_mode} "
              f"节奏{_ct2._slot[1].trk_gap}")

    # 真机截图夹具(docs/shots):`check_shots.py` 和 `expected.json` 靠**文件名**
    # 对号。这里只查"文件都在 + 表里的图名/坐标合法",**不跑 OCR** —— 回归里不建
    # 真引擎(那条红线见 AGENTS.md);真识别由 `python check_shots.py` 单独跑。
    _shots_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "docs", "shots")
    with open(os.path.join(_shots_dir, "expected.json"), encoding="utf-8") as _f:
        _shot_rows = json.load(_f)["shots"]
    _shot_bad = [
        s["file"] for s in _shot_rows
        if not os.path.exists(os.path.join(_shots_dir, s["file"]))
        or s.get("map") not in tools_bell.BELL_MAP_NAMES
        or not tools_bell.in_bounds(s.get("map"), s.get("x", -1),
                                    s.get("y", -1))]
    check("真机截图夹具:expected.json 里的文件都在、图名/坐标都合法",
          bool(_shot_rows) and not _shot_bad,
          f"{len(_shot_rows)} 张,坏 {_shot_bad}")

    check("只认一台:多开时界面靠角色名让用户选(标题里抠得出来)",
          tools_bell.client_name(
              "梦幻西游 ONLINE - (湖北2区[黄鹤楼] - 祭花′[29024311])") == "祭花′"
          and tools_bell.client_name("梦幻西游 ONLINE") == "梦幻西游 ONLINE")

    # 六种怪的真实文案(**逐字**,来源标在条目里)—— 这张表就是防"把一种的文案套到
    # 另一种上"。2026-10-16 晚上用户又给了三张 1:1 截图,招魂幡/逐妖蛊虫/梦魇魔这三条
    # 从"按表补的"升级成逐字原文(老版本缺首句/尾巴是猜的)。
    FORMS = [
        ("招魂幡·对话框(真机截图原文)",
         "看看你包里的新物品“招魂帖”，把它贴在指定位置，可以使得妖魔来自投罗网。"
         "去朱紫国(12,49)使用招魂帖，然后妖魔就会到来。", ("朱紫国", 12, 49)),
        ("招魂幡·任务栏(真机截图原文)",
         "去朱紫国(12,49)使用“招魂帖”，等待被诱惑的妖魔上钩并降服它。"
         "剩余时间2小时。", ("朱紫国", 12, 49)),
        ("逐妖蛊虫·对话框(真机截图原文)",
         "有的妖魔行迹隐秘。所以你得使用你包裹中的物品“逐妖蛊虫”，"
         "让这个蛊虫来给你带路。去宝象国(56,79)使用蛊虫，然后跟着它，"
         "它会找到妖魔的。", ("宝象国", 56, 79)),
        ("逐妖蛊虫·任务栏第一步(真机截图原文,坐标跟对话框同值)",
         "◆去宝象国(56,79)使用“逐妖蛊虫”，然后跟着地上的蛊虫找到妖魔。"
         "任务剩余时间120分钟。", ("宝象国", 56, 79)),
        ("逐妖蛊虫·用道具后任务栏换的新坐标(真机截图原文)",
         "◆蛊虫发现妖魔在宝象国(150,54),快去降服他吧。任务剩余时间119分钟。",
         ("宝象国", 150, 54)),
        ("梦魇魔·对话框(真机截图原文)",
         "这个妖魔值得一战，它无所畏惧且强大蛮横！你得有足够的胆色，"
         "再去挑战它吧。我发现它的踪迹在西梁女国(28,42)，"
         "少侠们准备好了就过去看看吧。", ("西梁女国", 28, 42)),
        ("梦魇魔·任务栏(只有图)",
         "去西梁女国找梦魇魔。剩余时间2小时。", None),
        ("迷幻妖·任务栏(只有图)",
         "去建邺城找迷幻妖。剩余时间2小时。", None),
        ("迷幻妖·对话框(真机截图原文)",
         "接下来你们遇到的将是一只狡猾的迷幻妖。想要抓住它，可不容易。"
         "我发现它的踪迹在傲来国(30,53)，少侠们速度赶过去看看吧。",
         ("傲来国", 30, 53)),
        ("巧智魔·任务栏(只有图)",
         "去建邺城找巧智魔。剩余时间1小时59分。", None),
        ("巧智魔·对话框(真机 bell.log)",
         "又一个！这次是一只精巧的巧智魔。它足智多谋而且狡猾无比。"
         "我发现它的踪迹在朱紫国(7,32)，少侠们准备好了就过去看看吧。",
         ("朱紫国", 7, 32)),
        ("怯弱妖·对话框(真机截图原文)",
         "我们要对付一只新的妖魔了，它是一只胆小而怯弱的怯弱妖，不过却是身形矫健，"
         "敏捷快速。估计，要被他耍好几次了。我发现它的踪迹在朱紫国(88,94)，"
         "少侠们速度赶过去看看吧。", ("朱紫国", 88, 94)),
        # 悬停那两行是"鼠标停在任务栏上"时读的(scoped=False,不做标题圈范围)
        ("巧智魔·悬停才显示的第二个坐标",
         "在建邺城(15,122)处", ("建邺城", 15, 122), False),
        ("怯弱妖·任务栏(只有图)",
         "去西梁女国找怯弱妖。剩余时间1小时59分。", None),
        ("怯弱妖·悬停才显示的第二个坐标",
         "在西梁女国(72,98)处", ("西梁女国", 72, 98), False),
    ]
    bad = []
    for row in FORMS:
        d, t, w = row[0], row[1], row[2]
        sc = row[3] if len(row) > 3 else True
        got = tools_bell.scan_bell([blk(t, 700, 165)], scoped=sc)
        if got != w:
            bad.append((d, got, w))
    check("六种怪的真实文案逐个认(招魂帖是招魂幡的,别套到逐妖蛊虫上)",
          not bad, str(bad))
    # 话术门槛的反面:六种怪的**对话框原文**都得过得了这道门槛 —— 不然真任务会被
    # 自己的门槛挡了。(悬停那两行是任务栏那一支读的,不吃这道门槛,不在这一条里。)
    _miss = [row[0] for row in FORMS
             if "对话框" in row[0] and not tools_bell.has_bell_words(row[1])]
    check("话术门槛:六种怪的对话框原文都过得了(别把自己的任务挡了)",
          not _miss, str(_miss))
    # 标题那行常被读花(实测「降双快通」/「降欢风衡」/「降妖优魔」):**以「降」开头
    # 且不长**就认 —— 别的任务标题不以「降」开头,不会误认(「降妖伏魔」标题下
    # 那一段就是 _bell_scope 圈范围用的)。
    check("任务栏框:标题读花成「降双快通」「降欢风衡」也认(只认以降开头且不长)",
          all(tools_bell._is_title(t) for t in ("降妖伏魔", "降双快通",
                                               "降欢风衡", "降妖优魔"))
          and not tools_bell._is_title("师门任务")
          and not tools_bell._is_title("法宝合成")
          and not tools_bell._is_title("双快通"))

    # 假屏同样得给得出"面板"(对话框只走面板带那条主路,见上面「周期」那组的说明),
    # 所以这里不用 mk_engine 默认的 FakeScreen(平色、按 region 也不裁),换成
    # PanelShot + 一个 1000x880 的合成客户端窗口。这个桩的假 OCR 对所有裁剪都
    # 返回同一组块(对话/任务栏说得一样),分派与否不影响结果。
    eng_b, app_b = mk_engine(bank, [blk(BELL_TEXT, 100, 200)],
                             cfg={"app": {"active_tool": "bell"}})
    eng_b.bell_tool.regions = lambda: [[0, 0, 1000, 880]]
    eng_b.screen = PanelShot(1000, 880)
    eng_b._safe("cycle", True)
    check("铃铛:新妖魔只写日志不给界面播报(用户不要语音)",
          app_b.said == []
          and app_b.logs and any("[铃铛]" in m and "88" in m
                                 for m in app_b.logs)
          and eng_b.bell_tool.target == "朱紫国 (88,94)",
          f"{app_b.said} {eng_b.bell_tool.target}")
    check("铃铛:引擎上留了结构化的妖魔位置(界面画红点用)",
          eng_b.bell_tool.spot == ("朱紫国", 88, 94), str(eng_b.bell_tool.spot))
    _pos0 = len([m for m in app_b.logs if "妖魔位置" in m])
    eng_b._safe("cycle", True)
    check("铃铛:同一只妖魔不重复记(坐标没变就不再报一轮)",
          app_b.said == []
          and len([m for m in app_b.logs if "妖魔位置" in m]) == _pos0,
          str([m for m in app_b.logs if "妖魔位置" in m]))
    eng_b.ocr.recognize_blocks = lambda img, **kw: [
        blk("我发现它的踪迹在西凉女国(12,34)，少侠", 100, 200)]
    eng_b._safe("cycle", True)
    check("铃铛:换了妖魔(地图/坐标变了)会再记一轮,且都不出声",
          app_b.said == []
          and eng_b.bell_tool.target == "西梁女国 (12,34)",
          f"{app_b.said} {eng_b.bell_tool.target}")
    check("铃铛:底图名按官方写法归一(西凉女国 -> 西梁女国)",
          tools_bell.scan_bell([blk("踪迹在西凉女国(12,34)，少侠", 100, 200)])
          == ("西梁女国", 12, 34)
          and tools_bell.map_asset("不存在的地图") is None
          and tools_bell.map_calib("不存在的地图") == (1.0, 1.0, 0.0, 0.0))

    # 间隔夹紧:bell_interval 手改/旧配置的野值要兜回合法区间。
    # 铃铛的下限是自己的 BELL_MIN_INTERVAL(0.15s)—— 现在一轮只截两块小图 +
    # 1ms 门控,不用跟着科举那个 0.4s 慢慢来。
    eng_b.app.cfg["bell"]["bell_interval"] = 99.0
    check("铃铛:间隔超过上限被夹住",
          eng_b.bell_tool.interval() == core.MAX_INTERVAL)
    eng_b.app.cfg["bell"]["bell_interval"] = 0.01
    check("铃铛:间隔低于下限被夹住",
          eng_b.bell_tool.interval() == tools_bell.BELL_MIN_INTERVAL
          and tools_bell.BELL_MIN_INTERVAL < core.MIN_INTERVAL,
          f"{eng_b.bell_tool.interval()} 下限={tools_bell.BELL_MIN_INTERVAL}")
    eng_b.app.cfg["bell"]["bell_interval"] = 0.0
    check("铃铛:没配(0)就用铃铛自己的下限(比科举快一档)",
          eng_b.bell_tool.interval() == tools_bell.BELL_MIN_INTERVAL)
    eng_b.app.cfg["bell"]["bell_interval"] = 2.5
    check("铃铛:区间内的配置原样生效", eng_b.bell_tool.interval() == 2.5)

    # 有坐标范围时:连角色位置都不用点,直接按范围算
    # (这些名字已经搬到 tools/bell.py,所以连底图目录也得patch 到那边)
    with tempfile.TemporaryDirectory(prefix="keju_bounds_") as d:
        mdir = os.path.join(d, "data", "maps")
        os.makedirs(mdir, exist_ok=True)
        with patch(mods=(tools_bell,), MAP_DIR=mdir,
                   MAP_CALIB_PATH=os.path.join(mdir, "calib.json"),
                   MAP_BOUNDS_PATH=os.path.join(mdir, "bounds.json")):
            with open(tools_bell.MAP_BOUNDS_PATH, "w",
                      encoding="utf-8") as f:
                json.dump({"建邺城": [0, 0, 286, 144]}, f)
            check("铃铛:范围不合法就不给标定",
                  tools_bell.map_calib_from_bounds(695, 345,
                                                   [0, 0, 0, 144]) is None)
            cal = tools_bell.map_calib_from_bounds(695, 345, [0, 0, 286, 144])
            check("铃铛:按坐标范围算标定,输出落点对得上两个角",
                  cal is not None
                  and abs(cal[1] + 345 / 144) < 1e-9 and abs(cal[3] - 345) < 1e-9,
                  str(cal))
            tools_bell.save_map_calib("建邺城", *cal)
            check("铃铛:(0,0) 落底图左下角、(286,144) 落右上角",
                  tools_bell.map_pixel("建邺城", 0, 0) == (0.0, 345.0)
                  and tools_bell.map_pixel("建邺城", 286, 144) == (695.0, 0.0),
                  f"{tools_bell.map_pixel('建邺城', 0, 0)} "
                  f"{tools_bell.map_pixel('建邺城', 286, 144)}")
            check("铃铛:没底图的图不给自动标定",
                  tools_bell.auto_calibrate_from_bounds()
                  == [("建邺城", "没有底图")],
                  str(tools_bell.auto_calibrate_from_bounds()))

    # 独立性:科举和降妖伏魔各用各的区域、各用各的开关,互不干扰。
    # 假屏得给得出"面板"(对话框只走面板带那条主路,见 `Win` 那组的说明):
    # 类型也只由对话框给(2026-10-16),所以铃铛这边得有块真面板才认得出妖魔。
    eng_i, app_i = mk_engine(bank, [blk(BELL_TEXT, 100, 200)],
                             cfg={"keju": {"regions": [None] * 4},
                                  "app": {"active_tool": "bell"}})
    eng_i.bell_tool.regions = lambda: [[0, 0, 1000, 880]]
    eng_i.screen = PanelShot(1000, 880)
    eng_i._safe("cycle", True)
    check("独立:科举一个区域都没框,铃铛照样认妖魔(只是不出声)",
          app_i.said == [] and eng_i.bell_tool.target,
          f"{app_i.said} {eng_i.bell_tool.target}")

    with patch(find_client_windows=lambda: ([], [])):
        eng_k, app_k = mk_engine(
            bank, [blk(BELL_TEXT, 100, 200)],
            cfg={"keju": {"regions": [[0, 0, 60, 30]]},
                 "app": {"active_tool": "bell"}})
        eng_k._safe("cycle", True)
        check("独立:没找到客户端时,铃铛不去借科举的区域",
              app_k.said == [] and eng_k.bell_tool.target == "",
              f"{app_k.said} {eng_k.bell_tool.target!r}")

    check("独立:铃铛有自己的客户端/间隔配置;监听常开(没有开关键)",
          "bell_on" not in core.DEFAULT_CONFIG
          and "bell_client" in core.DEFAULT_CONFIG
          and "bell_interval" in core.DEFAULT_CONFIG
          and "bell_rect" not in core.DEFAULT_CONFIG)

    # 只跑"当前进入的那个功能":没进去就什么都不做,进去了也不串台
    eng_n, app_n = mk_engine(bank, [blk(BELL_TEXT, 100, 200)],
                             cfg={"app": {"active_tool": ""}})
    eng_n._safe("cycle", True)
    check("调度:没进任何功能时,铃铛不认",
          app_n.said == [] and eng_n.bell_tool.target == "",
          f"{app_n.said} {eng_n.bell_tool.target!r}")

    eng_o, app_o = mk_engine(
        bank, [blk("御前科举大赛第1关：这一关考的是综合。题目："
                   "第一道题的题干内容是什么", 100, 200)],
        cfg={"app": {"active_tool": "bell"}})
    eng_o._safe("cycle", True)
    check("调度:进了降妖伏魔,科举的题目一个字都不播",
          app_o.said == [] and eng_o.bell_tool.target == ""
          and eng_o.bell_tool.spot is None,
          f"{app_o.said} {eng_o.bell_tool.target!r}")

    check("调度:进入标记有缺省值(监听常开,没有开关键)",
          core.DEFAULT_CONFIG["active_tool"] == ""
          and "bell_on" not in core.DEFAULT_CONFIG)

    # 扫哪:多开时按角色名挑;挑中的那台关了 -> 扫描暂停,但要**说一次**原因
    # (不然日志里只是"不再有新行",看起来像卡死)。
    _reg_logs = []
    _reg = tools_bell.BellTool.__new__(tools_bell.BellTool)
    _reg.app = types.SimpleNamespace(log=lambda m, **kw: _reg_logs.append(m))
    _reg.cfg = lambda k, d=None: {"bell_client": "祭花′"}.get(k, d)
    _wins = {"v": ([("A - 烛龙′[1]", [0, 0, 800, 600]),
                    ("B - 祭花′[2]", [900, 0, 1700, 600])], [])}
    with patch(find_client_windows=lambda: _wins["v"]):
        check("扫哪:多开时按角色名挑那一台",
              _reg.regions() == [[900, 0, 1700, 600]] and _reg_logs == [],
              f"{_reg.regions()} {_reg_logs}")
        _wins["v"] = ([("A - 烛龙′[1]", [0, 0, 800, 600]),
                       ("C - 别个[3]", [900, 0, 1700, 600])], [])
        _reg.regions()
        _reg.regions()                        # 同样的原因只说一次
        check("扫哪:选中的客户端不在了 -> 返回空 + 日志说一次原因",
              _reg.regions() == [] and len(_reg_logs) == 1
              and "祭花′" in _reg_logs[0], str(_reg_logs))
        _wins["v"] = ([], [])
        _reg.regions()
        check("扫哪:一个客户端都没枚举到 -> 也留一条原因(不刷屏)",
              len(_reg_logs) == 2 and "没枚举到客户端" in _reg_logs[1],
              str(_reg_logs))

    # 采集底图:先按坐标范围标定,没有范围才点角色位置
    with tempfile.TemporaryDirectory(prefix="keju_map_") as d:
        mdir = os.path.join(d, "data", "maps")
        with patch(mods=(tools_bell,), MAP_DIR=mdir,
                   MAP_CALIB_PATH=os.path.join(mdir, "calib.json")):
            tools_bell.save_map_calib("朱紫国", 2.0, 2.0)
            check("铃铛:标定写进 calib.json,别的图仍是默认",
                  tools_bell.map_calib("朱紫国") == (2.0, 2.0, 0.0, 0.0)
                  and tools_bell.map_calib("宝象国") == (1.0, 1.0, 0.0, 0.0),
                  tools_bell.map_calib("朱紫国"))
            tools_bell.save_map_calib("宝象国", 3.0, 4.0)
            check("铃铛:再采一张图不会覆盖已写好的标定",
                  tools_bell.map_calib("朱紫国") == (2.0, 2.0, 0.0, 0.0)
                  and tools_bell.map_calib("宝象国") == (3.0, 4.0, 0.0, 0.0))
            path = tools_bell.map_asset_save_path("朱紫国")
            check("铃铛:采集的底图存到 data/maps/<中文名>.png",
                  path.endswith(os.path.join("data", "maps", "朱紫国.png"))
                  and os.path.isdir(os.path.dirname(path)), path)
    check("铃铛:六张铃铛地图都用官方名,且拼音表能对上(老图集兼容)",
          len(tools_bell.BELL_MAP_NAMES) == 6
          and all(n in tools_bell.MAP_STEMS for n in tools_bell.BELL_MAP_NAMES),
          str(tools_bell.BELL_MAP_NAMES))

    # 录入地图:自己从画面里找地图矩形 + 核对是哪张图
    img = np.full((300, 400, 3), (30, 30, 40), np.uint8)
    img[60:240, 200:360] = (150, 120, 80)          # 地图本体(一整块彩色矩形)
    img[100:110, 220:240] = (200, 60, 60)          # 图里一点红屋顶
    rect = tools_bell.find_map_rect(img, min_side=100, max_side=900)
    check("录入地图:能从画面里框出地图矩形",
          rect == (200, 60, 359, 239), str(rect))
    check("录入地图:画面里没有地图(全暗)就不给",
          tools_bell.find_map_rect(np.full((300, 400, 3), 30, np.uint8),
                                   min_side=100, max_side=900) is None)
    hollow = np.full((300, 400, 3), (30, 30, 40), np.uint8)
    hollow[0:20, :] = hollow[-20:, :] = (120, 40, 40)   # 只有一圈边框(空心)
    hollow[:, 0:20] = hollow[:, -20:] = (120, 40, 40)
    check("录入地图:空心的/碎块状的不算地图(填充率要够)",
          tools_bell.find_map_rect(hollow, min_side=100, max_side=900) is None)
    # 给了坐标范围比例:按比例挑,对不上的不要
    two = np.full((300, 700, 3), (30, 30, 40), np.uint8)
    two[60:260, 40:340] = (150, 120, 80)           # 300x200 比例 1.5(更大)
    two[80:220, 420:660] = (150, 120, 80)          # 240x140 比例 1.714
    check("录入地图:按这张图的坐标范围比例挑那一块(大块比例不对就不要)",
          tools_bell.find_map_rect(two, want_ratio=240 / 140.0,
                                   min_side=100, max_side=900)
          == (420, 80, 659, 219))
    check("录入地图:画面里那块的比例和这张图都对不上 -> 不给",
          tools_bell.find_map_rect(two, want_ratio=1.0,
                                   min_side=100, max_side=900) is None)
    tb = [{"text": "宝象国 123,45"}, {"text": "任务追踪 去朱紫国找掌柜"},
          {"text": "西牛贺洲 丝绸之路"}, {"text": ""}]
    check("录入地图:从画面文字里认出出现过哪几张地图名",
          tools_bell.map_names_in(tb) == ["宝象国", "朱紫国"]
          and tools_bell.map_names_in([]) == [], str(tools_bell.map_names_in(tb)))
    check("录入地图:老资料的别名归一(西凉女国 -> 西梁女国)",
          tools_bell.map_names_in([{"text": "西凉女国 66,88"}]) == ["西梁女国"])
    with tempfile.TemporaryDirectory(prefix="keju_bounds_") as d:
        bp = os.path.join(d, "bounds.json")
        with open(bp, "w", encoding="utf-8") as f:
            json.dump({"宝象国": [0, 0, 159, 120]}, f)
        with patch(mods=(tools_bell,), MAP_BOUNDS_PATH=bp):
            check("录入地图:坐标范围给出这张图的长宽比",
                  abs(tools_bell.map_ratio("宝象国") - 159 / 120.0) < 1e-9
                  and tools_bell.map_ratio("没有这张图") is None)

    # 收尾:把这组开头换掉的全局桩还原(见函数开头的说明)。
    tools_bell.cursor_pos = _orig_cursor
    core.find_client_windows = _orig_find


# ---------------------------------------- 5.5 降妖伏魔的窗口层(小窗/抽屉)


class BellEngine:
    """铃铛窗口用例的引擎替身:接住 refresh_tools + 工具线程那两个口。

    不让测试真去启停工具线程(一启停就真的开始扫屏)。
    """

    def __init__(self):
        self.keju_tool = None
        self.bell_tool = types.SimpleNamespace(
            reset=lambda: None, locate=lambda: 0,
            ui_state=lambda: {"spot": None, "target": ""})

    def refresh_tools(self):
        pass

    def is_alive(self):
        return True


class BellApp(gui.App):
    """只借 gui.App 的方法,不走 __init__ —— 铃铛窗口用例不需要真引擎/OCR。

    真 App 会建 Engine(里面是 OCR 会话),而整个回归里已经有好几组各建一份;
    再多一份会踩到 native 层(ORT/COM)的上限 —— 实测全量跑到后面直接
    segfault。所以这里用 `__new__` 绕开 __init__,只把方法用得着的属性摆齐。
    """


_BELL_ALIVE = []      # 这组建的 App/Tk 对象一直留着,别让它们被 GC:
# Tk 的 Variable/PhotoImage/Tk 解释器在析构时会回调 Tcl,要是在测试收尾/别的
# 线程里被回收,进程会直接崩(Tcl_AsyncDelete / segfault)。留个引用最省事。


def _bell_app():
    """摆好 App 方法要用的属性(Tk 是真的,引擎/OCR 是假的)。"""
    import tkinter as tk
    app = BellApp.__new__(BellApp)
    app.root = tk.Tk()
    app.root.withdraw()                   # 测试时不弹窗
    app.cfg = core.load_config()          # 走沙箱里的 CONFIG_PATH
    app.logs = []
    app.engine = BellEngine()
    app.speaker = None
    _BELL_ALIVE.append(app)               # 见上面:别让 Tk 对象被回收

    def log(msg, detail="", **kw):
        app.logs.append(msg)
        gui.App.log(app, msg, detail)      # 仍写进沙箱的 bell.log
    app.log = log
    return app



@section
def sec_bell_ui():
    """小窗:版面(面板头 + 一颗「自动定位」+ 保留的抽屉)/ 定位 / 采集逻辑。

    调的是 gui.App 上的真方法,但 App 本身是 `__new__` 出来的空壳:Tk 真建、
    引擎和 OCR 是假的。所以这一组几秒跑完,改小窗先跑这一组就够。
    """
    def _txt(w):
        try:
            return str(w.cget("text"))
        except Exception:
            return ""

    def _walk(w):
        yield w
        for c in w.winfo_children():
            yield from _walk(c)

    def _texts(win):
        return [t for t in (_txt(w) for w in _walk(win)) if t]

    from PIL import Image
    with Sandbox(), tempfile.TemporaryDirectory(prefix="keju_bellui_") as d:
        mdir = os.path.join(d, "data", "maps")
        os.makedirs(mdir, exist_ok=True)
        bounds = os.path.join(mdir, "bounds.json")
        with open(bounds, "w", encoding="utf-8") as f:
            # 底图比例要和宝象国的坐标范围(159x120)对上,不然会被判成"不是这张图"
            json.dump({"宝象国": [0, 0, 159, 120]}, f)
        # 整组都在沙箱里:底图/标定/坐标范围都别落到仓库的 data/maps
        with patch(mods=(tools_bell,), MAP_DIR=mdir, MAP_BOUNDS_PATH=bounds,
                   MAP_CALIB_PATH=os.path.join(mdir, "calib.json")), \
                patch(find_client_windows=lambda: ([], [])):
            app = _bell_app()
            log_rec = app.logs
            inflight = []
            app._enter_bell_slow = lambda: inflight.append(
                getattr(app.bell_win, "_anim_after", None) is not None)
            app.show_bell()
            _settled(app.root, app.bell_win)
            check("小窗:定位/标定这些慢活排在动画起跑之后",
                  inflight == [True], str(inflight))
            check("小窗:摆到请求尺寸的居中位(set_place 定的)",
                  app.bell_win.state() == "normal"
                  and ui_widgets.win_origin(app.bell_win)
                  == getattr(app.bell_win, "p_xy", None),
                  f"小窗={ui_widgets.win_origin(app.bell_win)} "
                  f"p_xy={getattr(app.bell_win, 'p_xy', None)}")

            # ---- 版面:采集入口撤了(抽屉保留) / 只剩「自动定位」/ 没有日志区 ----
            check("小窗:界面上没有采集/监听/日志入口(按钮、坐标行、日志区都没建)",
                  not any(hasattr(app, n) for n in (
                      "bell_map_btn", "bell_watch_btn", "bell_log_btn",
                      "bell_coord_var", "bell_log_frame", "bell_log_box",
                      "bell_on_var")),
                  str([n for n in ("bell_map_btn", "bell_watch_btn",
                                   "bell_log_btn", "bell_coord_var",
                                   "bell_log_frame", "bell_log_box",
                                   "bell_on_var")
                       if hasattr(app, n)]))
            check("小窗:采集的代码保留 —— 抽屉控件照建,只是没有入口按钮",
                  hasattr(app, "bell_drawer") and hasattr(app, "bell_rows")
                  and hasattr(app, "bell_detail_shot")
                  and app.bell_drawer_open is False,
                  f"drawer={hasattr(app, 'bell_drawer')} "
                  f"rows={hasattr(app, 'bell_rows')} "
                  f"detail={hasattr(app, 'bell_detail_shot')}")
            check("小窗:没有「降妖伏魔」抬头(2026-10-21 用户定的:不要抬头)",
                  not any("◆ 降妖伏魔 ◆" in _txt(w)
                          for w in _walk(app.bell_win)),
                  str(_texts(app.bell_win)))
            check("小窗:底下只剩一颗「自动定位」(宽度随文字走,不会挤到显示不全)",
                  _txt(app.bell_locate_btn) == "自动定位"
                  and int(app.bell_locate_btn.cget("width") or 0) == 0
                  and not hasattr(app, "bell_frame_btn")
                  and not hasattr(app, "bell_region_clear_btn"),
                  f"{_txt(app.bell_locate_btn)} / "
                  f"width={app.bell_locate_btn.cget('width')}")
            # 卡片高度以前是写死的 430px,内容要 479px —— 底下的按钮直接被裁掉。
            # 现在由内容撑,这里量一遍:按钮的下边缘得在卡片里面。
            _card = app.bell_locate_btn.master
            _rows = (app.bell_locate_btn,)
            _bottoms = {str(w): w.winfo_rooty() - _card.winfo_rooty()
                        + w.winfo_height() for w in _rows}
            check("小窗:卡片装得下底下的按钮(不会被裁掉)",
                  all(b <= _card.winfo_height() for b in _bottoms.values())
                  and _card.winfo_height() > 0,
                  f"卡片高={_card.winfo_height()} 按钮下边缘={_bottoms}")
            # ---- 首次进入自动定位:定位结果当场落盘 + 按钮显示角色名 ----
            one = [("梦幻西游 ONLINE - (湖北2区[黄鹤楼] - 祭花′[29024311])",
                    [800, 100, 1615, 780])]
            with patch(find_client_windows=lambda: (list(one), [])):
                app._set("bell_client", "")
                app.engine.bell_tool.locate = lambda: 1
                gui.App._enter_bell_slow(app)   # 上面那条用例把实例方法换成了桩
                with open(core.CONFIG_PATH, encoding="utf-8") as f:
                    saved_bell = json.load(f)["bell"]
                check("进功能:自动定位到单台也当场存下客户端",
                      app.cfg["bell"]["bell_client"] == one[0][0]
                      and saved_bell.get("bell_client") == one[0][0],
                      str(saved_bell.get("bell_client")))
                check("进功能:按钮变成角色名(客户端矩形不再显示)",
                      _txt(app.bell_locate_btn) == "祭花′"
                      and not hasattr(app, "bell_coord_var"),
                      _txt(app.bell_locate_btn))
            with patch(find_client_windows=lambda: ([], [])):
                app.engine.bell_tool.locate = lambda: 0
                gui.App._enter_bell_slow(app)
                check("进功能:没定位到 -> 按钮还是「自动定位」",
                      _txt(app.bell_locate_btn) == "自动定位",
                      _txt(app.bell_locate_btn))
            app.engine.bell_tool.locate = lambda: 0       # 还原(后面的用例靠它)
            shown_texts = _texts(app.bell_win)
            # 监听常开(2026-10-20 起):没有"关着"这回事,没妖魔时画布上只写等待
            def _hint_txt():
                return str(app.bell_hint.cget("text"))

            def _canvas_txt():
                c = app.bell_canvas
                return "\n".join(c.itemcget(i, "text") for i in c.find_all()
                                 if c.type(i) == "text")

            app._bell_spot = object()          # 逼它重画(不然缓存命中直接返回)
            ui_bell.draw_bell(app)
            check("小窗:监听常开 —— 没妖魔时只画「等待」,不再提示开关",
                  "等待铃铛任务提示" in _canvas_txt() and _hint_txt() == "",
                  f"{_canvas_txt()} / {_hint_txt()!r}")

            check("小窗:不再显示那两句提示语(右键说明 / 红点说明)",
                  not any("右键" in t for t in shown_texts)
                  and not any("红点即妖魔位置" in t for t in shown_texts),
                  str([t for t in shown_texts if "右键" in t or "红点" in t]))

            # 坐标那行是 **PIL 画的图**,`bell_var` 改了它不会自己变 —— 轮询里必须
            # 跟着重画(2026-10-17 用户报"一直显示等待铃铛任务提示")。
            app.engine.bell_tool = types.SimpleNamespace(
                ui_state=lambda: {"spot": ("宝象国", 96, 44),
                                  "target": "宝象国 (96,44)"})
            app._drain_logs()              # 轮询那个方法(每 POLL_MS 调一次)
            check("小窗:轮询里换了目标 -> 坐标那行跟着重画(不是一直停在「等待…」)",
                  getattr(app, "bell_coord_text", "") == "宝象国 (96,44)",
                  getattr(app, "bell_coord_text", None))

            # ---- 地图采集:界面入口已撤(底图内置),采集逻辑保留(直接调 record_map) ----
            shot = Image.new("RGB", (500, 320), (30, 30, 40))
            shot.paste((150, 120, 80), (150, 60, 362, 220))     # 212x160
            app.engine.ocr = types.SimpleNamespace(
                recognize_blocks=lambda img: [{"text": "宝象国 123,45"}])
            with patch(mods=(gui,), freeze_screen=lambda: shot):
                check("采集(逻辑保留):录一张 -> 存底图 + 按坐标范围自动标定",
                      app.record_map("宝象国") is True
                      and os.path.exists(os.path.join(mdir, "宝象国.png"))
                      and tools_bell.map_calib("宝象国") != (1.0, 1.0, 0.0, 0.0)
                      and any("已录入地图 宝象国" in m for m in log_rec),
                      log_rec[-1] if log_rec else "")
                app.engine.ocr = types.SimpleNamespace(
                    recognize_blocks=lambda img: [{"text": "朱紫国 88,66"}])
                check("采集:画面里是别的地图 -> 拒绝录入并说明原因",
                      app.record_map("宝象国") is False
                      and "不是「宝象国」" in log_rec[-1], log_rec[-1])
                with patch(mods=(gui,), freeze_screen=lambda: Image.new(
                        "RGB", (500, 320), (30, 30, 40))):
                    check("采集:画面里没有地图 -> 提示先按 Tab 打开地图",
                          app.record_map("宝象国") is False
                          and "画面里没有「宝象国」" in log_rec[-1], log_rec[-1])
                with patch(mods=(tools_bell,),
                           MAP_BOUNDS_PATH=os.path.join(d, "没有这个文件.json")):
                    check("采集:没有坐标范围的图不给录(录了也标定不了)",
                          app.record_map("宝象国") is False
                          and "没有坐标范围" in log_rec[-1], log_rec[-1])

            # ---- 自动定位 / 多客户端弹窗 / 分辨率提醒 ----
            import tkinter.messagebox as mb
            pops = []
            warns = []
            mb.showinfo = lambda *a, **k: pops.append(a)
            mb.showwarning = lambda *a, **k: warns.append(a)
            with patch(find_client_windows=lambda: (
                    [("梦幻西游 ONLINE", [800, 100, 1615, 780])], [])):
                app.on_locate_clients()
                check("定位:单客户端 -> 只把角色名写在按钮上(矩形不再显示)",
                      _txt(app.bell_locate_btn) == "梦幻西游 ONLINE"
                      and not hasattr(app, "bell_coord_var"),
                      _txt(app.bell_locate_btn))
                check("定位:单客户端也当场存下选择",
                      app.cfg["bell"]["bell_client"] == "梦幻西游 ONLINE",
                      app.cfg['bell'].get('bell_client'))
            with patch(find_client_windows=lambda: (
                    [("梦幻西游 ONLINE - (湖北2区[黄鹤楼] - 祭花′[29024311])",
                      [800, 100, 1615, 780])], [])):
                app._set("bell_client", "")
                app.on_locate_clients()
                check("定位:真实标题只把角色名写在按钮上",
                      _txt(app.bell_locate_btn) == "祭花′"
                      and app.cfg["bell"]["bell_client"].endswith(
                          "祭花′[29024311])"),
                      f"{_txt(app.bell_locate_btn)} / "
                      f"{app.cfg['bell'].get('bell_client')}")
            with patch(find_client_windows=lambda: (
                    [("梦幻西游 ONLINE - (湖北2区[黄鹤楼] - 祭花′[29024311])",
                      [800, 100, 1811, 926]),
                     ("梦幻西游 ONLINE - (湖北2区[黄鹤楼] - 葬龙′[29023982])",
                      [0, 0, 815, 680])], [])), \
                    patch(mods=(ui_bell,), pick_client=lambda *a, **k: 1):
                app.on_locate_clients()
                check("定位:多开 -> 弹列表按角色名选一台(选完只认这一台)",
                      app.cfg["bell"].get("bell_client")
                      == "梦幻西游 ONLINE - (湖北2区[黄鹤楼] - 葬龙′[29023982])",
                      app.cfg["bell"].get("bell_client"))
                check("定位:支持的两档分辨率不弹任何框",
                      pops == [] and warns == [], f"{pops} {warns}")
            with patch(find_client_windows=lambda: ([], [])):
                app.on_locate_clients()
                check("定位:没找到客户端也给提示(弹框说清楚)",
                      len(pops) == 1 and "没找到客户端" in str(pops[-1]),
                      str(pops))
            app._bell_size_warned = ""
            with patch(find_client_windows=lambda: (
                    [("梦幻西游 ONLINE", [0, 0, 1291, 1025])], [])):
                app.on_locate_clients()
                _warn_txt = " ".join(str(v) for v in warns)
                check("定位:不支持的分辨率 -> 弹框提醒改成 640x480 / 800x600",
                      len(warns) == 1 and "640x480" in _warn_txt
                      and "800x600" in _warn_txt and "1291x1025" in _warn_txt,
                      _warn_txt or "没弹提醒")
                app.on_locate_clients()
                check("定位:同一个不支持尺寸只弹一次(不每拍刷屏)",
                      len(warns) == 1, str(warns))

            # ---- 截图区域:只采鼠标所在客户端那块 ----
            check("地图采集:矩形相交判断",
                  gui.rects_overlap([0, 0, 100, 100], [50, 50, 200, 200])
                  and not gui.rects_overlap([0, 0, 10, 10], [50, 50, 60, 60])
                  and not gui.rects_overlap(None, [0, 0, 1, 1]))
            check("地图采集:物理像素 -> Tk 逻辑坐标(125% 缩放不会判错相交)",
                  gui.scale_rect([1000, 500, 2000, 1000], 1.25)
                  == [800, 400, 1600, 800]
                  and gui.scale_rect([1, 2, 3, 4], 1.0) == [1, 2, 3, 4]
                  and gui.scale_rect(None, 1.25) is None)
            with patch(find_client_windows=lambda: (
                    [("梦幻西游 ONLINE", [800, 100, 1800, 900])], [])):
                check("地图采集:鼠标所在客户端那块取得到",
                      gui.client_under_cursor() == [800, 100, 1800, 900])
            with patch(find_client_windows=lambda: (
                    [("梦幻西游 ONLINE", [0, 0, 100, 100])], [])):
                check("地图采集:客户端小得不合理(最小化)就退回整屏",
                      gui.client_under_cursor() is None)

            app.bell_win.geometry("+150+120")
            _pump(app.root, 120)
            app.engine.ocr = types.SimpleNamespace(
                recognize_blocks=lambda img: [{"text": "宝象国 123,45"}])
            with patch(find_client_windows=lambda: (
                    [("梦幻西游 ONLINE", [40, 20, 460, 300])], [])), \
                    patch(mods=(gui,), freeze_screen=lambda: shot):
                check("地图采集:整屏裁到客户端那块后,坐标还是对的",
                      app.record_map("宝象国") is True
                      and Image.open(os.path.join(mdir, "宝象国.png")).size
                      == (212, 160),
                      str(Image.open(os.path.join(mdir, "宝象国.png")).size))

            # ---- 红圆点:画点不画字;只有地图没坐标时不画点 ----
            app.engine.bell_tool.ui_state = lambda: {
                "spot": ("宝象国", 88, 66), "target": "宝象国 (88, 66)"}
            app._bell_spot = None
            ui_bell.draw_bell(app)
            items = [app.bell_canvas.type(i)
                     for i in app.bell_canvas.find_all()]
            ovals = [i for i in app.bell_canvas.find_all()
                     if app.bell_canvas.type(i) == "oval"]
            check("地图:只画一个红圆点,不标坐标字(也没有十字线)",
                  "text" not in items and "line" not in items
                  and len(ovals) == 1
                  and app.bell_canvas.itemcget(ovals[0], "fill") == "#ff2d2d",
                  str(items))
            app.engine.bell_tool.ui_state = lambda: {
                "spot": ("宝象国", None, None), "target": ""}
            app._bell_spot = None
            ui_bell.draw_bell(app)
            kinds = [app.bell_canvas.type(i)
                     for i in app.bell_canvas.find_all()]
            check("地图:只有地图没坐标时不画点、也不写字",
                  kinds == ["image"] and str(app.bell_hint.cget("text")) == "",
                  f"{kinds} / {app.bell_hint.cget('text')!r}")

            app.root.destroy()                # Tk 用完就拆(没有真引擎要收)


def main(argv=None):
    global QUIET
    argv = list(sys.argv[1:] if argv is None else argv)
    QUIET = "--quiet" in argv or "-q" in argv
    t0 = time.time()
    for fn in sections:
        if not QUIET:
            print(f"\n--- {fn.__name__[4:]} ---")
        fn()
    failed = [r for r in results if not r[1]]
    _tcl_drain()
    print(f"\n结果: {len(results) - len(failed)}/{len(results)} 通过"
          f"(耗时 {time.time() - t0:.1f}s)")
    for name, _, detail in failed:
        print(f"  FAIL: {name} — {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
