"""降妖伏魔:一个完全独立的功能。

自己一条线程、自己的区域和状态。跟 core 只有一条单行道:调用时现取截图 /
OCR / 窗口枚举这些基础设施(这是唯一被允许的共享)。日志用 [铃铛]。

提示文法在 tools/bell_parse.py,面板/签名在 tools/panel.py,底图与标定在
tools/maps.py,画面找地图在 tools/mapfind.py,量框命令行在 tools/layout.py;
本文件只留扫描状态机(BellTool)与它的调度常量。下面那串 import 里有一部分
只是**再导出**给 gui/ui/tests 用(它们仍只认 tools_bell.XXX)。
"""
import threading
import time
from dataclasses import dataclass, field

from tools.bell_parse import (  # noqa: F401
    HOVER_GAP, HOVER_STOP_WORDS, TRK_GAP, TRK_ITEM_GAP, TYPE_HOVER, TrkMode,
    _RE_BELL_HOVER, _hit, _is_title, _plan_note, _spot, confirmed,
    has_bell_words, hover_stop, in_bounds, known_map, scan_bell,
    scan_bell_parts, trk_plan, watch_gap)
from tools.layout import cmd_layout  # noqa: F401
from tools.mapfind import find_map_rect  # noqa: F401
from tools.maps import (  # noqa: F401
    BELL_MAP_NAMES, MAP_STEMS, auto_calibrate_from_bounds, canon_map,
    load_map_bounds, map_asset, map_asset_save_path, map_calib,
    map_calib_from_bounds, map_names_in, map_pixel, map_ratio, save_map_calib)
from tools.panel import (  # noqa: F401
    DIALOG_BAND, DIALOG_DARK_FRAC, DIALOG_PAD, DIALOG_TEXT_FRAC,
    DIALOG_TEXT_MINH, _dark_of, flat_panel_box, panel_box, panel_frac,
    panel_sig, panel_text_cut, read_note, sig_diff)

TAG = "铃铛"
CYCLE_LOG_MARK = "对话框开新周期"    # 文件里的周期分界日志(**只进文件**,用户定的
# 2026-10-17:界面上不再刷它)。它跟"报出目标[来自对话框]"那条同一刻写出。

DIALOG_GAP = 2.0                         # 面板内容没变时,这么久兜底重读一次
# 非铃铛面板(买东西/闲聊/聊天频道)的内容一直在滚:变了也别每拍都读 —— 真机
# 上这种占 OCR 的大头(2026-10-21 会话:490 秒里 267 次 OCR 全是它,每次一两百
# 毫秒,全白烧)。铃铛面板(`dlg_bell=True`)不受影响:翻页要当轮重读。
# 2026-10-31 用户反馈"游戏被拖卡"又从 0.6 放宽到 1.2:每次识别都是一截 GPU
# 爆发(DirectML 中位 ~0.7s),白读减半;代价只是"从非铃铛面板换到铃铛面板"
# 最多晚 1.2 秒认出来(本来也在秒级节奏里)。
DIALOG_OTHER_GAP = 1.2
SIG_MIN = 10.0                           # 面板内容签名差多少算"这页换了"
PEND_TTL = 10.0                          # 待确认的对话框值最多挂这么久(面板消失/读不到
# 持续超过它就作废)—— 2026-10-17:重扫撞上面板暗比 0.59(阈值 0.60)被判"消失",
# 一拍没读到就把新坐标扔了,红点一直不刷新 ✗
# 悬停行("在建邺城(15,122)处")出现在「降妖伏魔」标题**上方** —— 那一截由
# `HOVER_LIFT` 在裁剪时往上留(见 hover_rect),这里的 HOVER_GROW 只管
# "鼠标算不算在任务栏附近"(触发器要大一圈)。
HOVER_GROW = 90                          # 鼠标"在任务栏附近"的放宽量(触发器要大一圈)
HOVER_LIFT = 120                         # 悬停那行要往上多留一截才圈得住
TRK_HIST = 6                             # 留最近几次任务栏读数(判"认准了没有")
# **item 档的内容签名门控**(2026-10-21):等的是"任务栏换了字",不是定时读 ——
# 原来 0.5s 一次的定时 OCR,在等道具生效的几十秒里几乎全是白读。现在没变最多
# TRK_SIG_GAP 兜底一次、变了当拍就读;只有读到**没确认的候选**时才收紧回
# TRK_ITEM_GAP(两遍一致要连读)。hover 档不吃这套(裁剪跟着鼠标走,签名不可比)。
TRK_SIG_GAP = 2.0
# 任务栏签名差多少算"换了字":坐标行换一两个字在 24x48 的采样格里只有 2~4 个格
# (差 0.5~1.0),比"整页换"的 SIG_MIN=10 低得多;任务栏深底不透光,背景在动进
# 不了签名(对话框同款实测差 0)。阈值偏低的代价只是"偶尔多读一次",不会漏。
TRK_SIG_MIN = 0.5

# 连着这么多次"一个字都没读到"就写一条诊断日志(**只记数、不动框**;
# 用户定的 2026-10-16:面板被游戏藏起来是正常的 —— 实测约一半读数是 0 块,而且
# 这三类任务要拿坐标时玩家本来就得开着面板;作废+重锚一次要耗 8×0.25s ≈ 2 秒,
# 过不了"快"这条红线)。
TRK_MISS_MAX = 8
LOG_GAP = 10.0                           # 同一类过程日志没变化时最多这么久写一条
BELL_MIN_INTERVAL = 0.15                 # 铃铛自己的扫描下限(比 core 那档 0.4s 快)
OCR_LIMIT = 480                          # 只扫小块时的 det 输入下限(默认 736 太贵)
# 新坐标"换参数复读"用的 det 下限(用户定的 2026-10-16):半透明面板 + 压缩让检测
# 本身不稳,同一行换个参数就能差字(实测 `宝象 40，12）` 少了"1"和"国")。同一块裁剪
# 用这个下限再读一次,两次 (图名,x,y) 一样才采信(见 `BellTool._recheck`)。
TRK_RECHECK_LIMIT = 320
# 对话框那一条文字带的 det 档(2026-10-21 量的):那块字本来就大(16 / 18 / 20 /
# 24 / 28px 都试过,各档全都读对),而 `min 480` 会把它从 692x178 **放大**到
# 1866x480 再跑 det。同一块交替量 20~30 次:`480/min` 124~180ms,按原像素
# 51~115ms —— 从不更慢,GPU 闲的时候快一倍多。`max` 只在长边超过 `DLG_LIMIT_SIDE`
# 时才缩;900 比最宽的对话框带(893)还大,所以就是"不缩也不放"。
DLG_LIMIT_TYPE = "max"
DLG_LIMIT_SIDE = 900
# 对话框"两遍一致"的第二遍(见 `_scan` 里 `again` 那段)照旧走 `OCR_LIMIT=480`
# 的放大档 —— 和第一遍的"按原像素"正好是两个参数,读出来一样才采信。实测
# 320/min 比 480/min 还慢十几毫秒,所以复读不另设档位。


def client_choices():
    """枚举到的**已登录**客户端 -> [(角色名, 标题, 矩形)];界面拿去弹列表。

    登录窗(标题抠不出角色名)不列 —— 与 `find_client_canvases` 的登录闸同一
    判据(client_common,与 keju 同源):登录角色才识别,别让人选进来又提示
    分辨率/没有画面。全是登录窗时返回空,界面据此提示「请先登录角色」。
    """
    import core
    out = []
    try:
        found, _mini = core.find_client_windows()
    except Exception:
        return out
    for title, box in found:
        name = core.client_name(title)
        if not name:
            continue
        out.append((name, title, [int(v) for v in box]))
    return out


def abs_rect(region, rel):
    """相对区域左上角的矩形 -> 屏幕绝对坐标。"""
    return [int(region[0]) + int(rel[0]), int(region[1]) + int(rel[1]),
            int(region[0]) + int(rel[2]), int(region[1]) + int(rel[3])]


def rel_rect(region, frac):
    """按比例从一块区域里切一块 -> 绝对矩形。"""
    x0, y0, x1, y1 = [float(v) for v in region]
    w, h = x1 - x0, y1 - y0
    ax, ay, bx, by = frac
    return [int(x0 + w * ax), int(y0 + h * ay),
            int(x0 + w * bx), int(y0 + h * by)]


def trk_seed_rel(region, found):
    """任务栏框:画布×`TRK_BOXES` 的**绝对框** -> 相对窗口(`SlotState.trk` 口径)。

    `core.trk_rect` 锚在画布上、给的是屏幕坐标;扫描时 `abs_rect` 还要再加一次
    窗口原点 —— 不先减掉就会按窗口位置整体偏掉(窗口不在 (0,0) 时尤其明显)。
    拿不到画布/这一档没框返回 None。
    """
    import core
    if not found:
        return None
    box = core.trk_rect(found[0], found[1])
    if not box:
        return None
    x0, y0 = int(region[0]), int(region[1])
    return [int(box[0]) - x0, int(box[1]) - y0,
            int(box[2]) - x0, int(box[3]) - y0]


def fit_rect(region, rect):
    """把 rect 整体挪进 region(**宽高不变**),挪了返回新矩形、没挪返回原矩形。

    给"表里的任务栏框"用:框是按某台机器的窗口量的,换台机器尺寸差一截
    (表按 ±8px 容差命中别的行)时,直接用就有一截落在 region 外面 —— 截图在那个
    边界就切掉,行尾的坐标就没了(实测 `宝象 40，12）`(少"1"和"国")、
    `去长寿村找怯弱。`(少"妖")。优先保住**右边/下边**(坐标在行尾、在下面那行),
    所以是整块左移/上移。
    """
    rx0, ry0, rx1, ry1 = [int(v) for v in region]
    x0, y0, x1, y1 = [int(v) for v in rect]
    w, h = x1 - x0, y1 - y0
    nx0, ny0 = x0, y0
    if x1 > rx1:                     # 右出界:整体左移
        nx0 -= x1 - rx1
    if y1 > ry1:                     # 下出界:整体上移
        ny0 -= y1 - ry1
    if nx0 < rx0:                    # 左出界(框比 region 还宽):再挪回去
        nx0 = rx0
    if ny0 < ry0:
        ny0 = ry0
    if (nx0, ny0) == (x0, y0):
        return rect
    return [nx0, ny0, nx0 + w, ny0 + h]


def edge_note(rect, region):
    """任务栏读数的诊断后缀:裁剪宽度 + 左右有没有贴扫描区边(贴边=可能在切字)。

    真机丢字的两个来源:框左边切进表头(`务追踪`)、框右边被 region 截断(行尾的坐标
    没了)。每次任务栏读数在"识别 任务栏 …"行末尾带 ` [宽186/右贴边]`,排查
    "这个框为什么读不全"先看这两个数。**只诊断不防线**:它不改行为,会改行为的
    是 B(`fit_rect` 内挪)和 C(320 复读)那两道。
    """
    w = int(rect[2]) - int(rect[0])
    bits = [n for n, hit in (("左贴边", int(rect[0]) <= int(region[0])),
                             ("右贴边", int(rect[2]) >= int(region[2])))
            if hit]
    return f" [宽{w}/{'、'.join(bits) if bits else '没贴边'}]"



def cursor_pos():
    """鼠标在屏幕上的物理像素位置;取不到返回 None。

    巧智魔/怯弱妖的第二个坐标**只有鼠标停在任务栏上才显示**,而玩家手快时
    那个悬停行可能只闪一下 —— 靠 1.2 秒的扫描节奏会漏。鼠标位置几乎是白拿的
    (`GetCursorPos` 不用一毫秒),用它当"现在可能有悬停行"的触发器最合适。
    """
    try:
        import ctypes
        from ctypes import wintypes
        p = wintypes.POINT()
        if not ctypes.windll.user32.GetCursorPos(ctypes.byref(p)):
            return None
        return int(p.x), int(p.y)
    except Exception:
        return None


def in_rect(pos, rect, grow=0):
    """点在不在这块矩形里(grow = 往外放宽多少像素)。"""
    if not pos or not rect:
        return False
    x, y = pos
    return (rect[0] - grow <= x <= rect[2] + grow
            and rect[1] - grow <= y <= rect[3] + grow)


def hover_rect(rect, cur, region, lift=HOVER_LIFT, half=260, up=90, dn=50):
    """鼠标在任务栏附近时要读的那一块:面板往上多留一截 + 鼠标周围也带上。

    悬停行**一般**画在标题上面(所以往上留),但也见过画在光标边上的 —— 一块
    盖住两者的矩形最省事(一次 OCR 就够,不用读两遍)。裁到扫描区域里。
    """
    x0, y0, x1, y1 = rect[0], rect[1] - lift, rect[2], rect[3]
    if cur:
        x0 = min(x0, cur[0] - half)
        x1 = max(x1, cur[0] + half)
        y0 = min(y0, cur[1] - up)
        y1 = max(y1, cur[1] + dn)
    rx0, ry0, rx1, ry1 = [int(v) for v in region]
    return [max(rx0, int(x0)), max(ry0, int(y0)),
            min(rx1, int(x1)), min(ry1, int(y1))]


# 支持档判定与文案(supported_res / supported_res_text)在 clients.py(本应用
# 口径,档位表本体 SUPPORTED_RES 在 client_common 两边同源),core 再导出 ——
# 这里只经 core 调用,别在本文件抄一份(两个真相必分叉)。


# 对话框在**游戏画面(WSGAME 画布)**里的定稿比例表(`DLG_RATIOS`)和
# 画布×比例的纯几何(`dialog_rect`)在 client_common(与 keju 同源,core 再导出)
# —— 那是**游戏属性**(对话框贴在画布哪里由游戏决定),真机量一次两边共用,
# 不在 tools 再抄一份;这里的 fixed_dialog 只管"够不够暗/读不读/日志说什么"。


def canvas_res_of(region):
    """窗口矩形 -> 里面那层游戏画面(WSGAME)的 [矩形, 游戏分辨率, 版式];没有 None。

    对话框框(`fixed_dialog` 的画布×`DLG_RATIOS`)、任务栏框种框
    (`trk_rect` 的画布×`TRK_BOXES`)和界面的分辨率提醒共用这一条。
    画布按"矩形落在窗口里"配对(region 是顶层窗口、画布是它里面的子窗口,
    同一进程枚举,坐标系一致);游戏分辨率由 `core.find_client_canvases`
    按画布尺寸 ÷ 倍率算出,精确等于游戏设置的那一档;版式 "tab"/"win" 随
    画布一起给,只用于日志/存档文件名(比例表/框表不按版式分)。
    """
    import core
    try:
        canvases, _mini = core.find_client_canvases()
    except Exception:
        return None
    x0, y0, x1, y1 = [int(v) for v in region]
    for _title, res, rect, _scale, mode in canvases:
        cx0, cy0, cx1, cy1 = (int(v) for v in rect)
        if cx0 >= x0 and cy0 >= y0 and cx1 <= x1 and cy1 <= y1:
            return [[cx0, cy0, cx1, cy1], (int(res[0]), int(res[1])), mode]
    return None

@dataclass
class SlotState:
    """一个客户端槽位的全部扫描状态(`BellTool._slot` 的值)。

    以前是散装 dict(二十来个无 schema 的键,`st.get(...)` / `st["x"] = ...`),
    2026-10-21 收敛成这一个类:字段有名字、有默认值、有注释,改一处行为时
    别的键在哪儿一目了然。**字段默认值 = 以前"键不存在"时的语义**,行为一个字没改。
    """
    region: tuple = ()                  # 这个槽对应的客户端窗口矩形(物理像素)
    res: tuple | None = None            # 里面那层游戏画面的分辨率(变了要重取任务栏框)
    # ---- 任务栏那侧 ----
    trk: list | None = None             # 任务栏框(来自分辨率表,相对窗口;None=没量到)
    trk_mode: TrkMode = TrkMode.NONE    # 本周期任务类型(只由对话框给,见 TrkMode)
    trk_gap: float = TRK_GAP            # 任务栏当前兜底节奏(秒,item 档签名门控用)
    trk_ts: float = 0.0                 # 上次读任务栏的时刻
    trk_hist: list = field(default_factory=list)  # 最近几次任务栏读数("见过两次"用)
    trk_text: tuple | None = None       # 本周期任务栏认下来的那条
    trk_psig: object | None = None      # 任务栏内容签名(item 档门控,None=还没读过)
    trk_last: tuple | None = None       # 最后一次任务栏值(跨周期留着,开新周期当 stale)
    trk_stale: tuple | None = None      # 屏幕上还挂着的旧行(本周期不许拿它当新目标)
    trk_pub: tuple | None = None        # 本周期任务栏报出去的那条(item 收手判据)
    miss: int = 0                       # 连着几次一个字都没读到
    hover_warn_ts: float = 0.0          # 上次"鼠标不在框里"诊断日志的时刻
    # ---- 对话框那侧 ----
    dlg_on: bool = False                # 上一拍有没有判出对话框面板(暗比滞回用)
    dlg_ts: float = 0.0                 # 上次读对话框的时刻
    dlg_rect: tuple | None = None       # 上次读的时候那个面板框(签名用它,别用当轮的)
    dlg_psig: object | None = None      # 面板内容签名(None=没读过/上拍没读成,下拍必读)
    dlg_bell: bool = True               # 这块面板是不是铃铛任务(不是就别按节奏重读)
    dlg_text: tuple | None = None       # 对话框认下来的目标(面板还在、字没变时沿用)
    dlg_raw: str | None = None          # 对话框这一拍读到的原文(定类型/收手话术用)
    dlg_sample: tuple | None = None     # 非铃铛对话框的样本(part, blocks, ms),心跳带一条
    dlg_pend: tuple | None = None       # 待确认的改口值(两遍一致才放行)
    dlg_gone: float = 0.0               # 面板开始读不到的时刻(dlg_pend 的 TTL 从这儿算)
    dlg_ms: float = 0.0                 # 上次读对话框的耗时(ms),慢机器自适应间隔用

class BellTool(threading.Thread):
    """妖魔位置监听:自己决定扫哪、自己认,位置交给界面画点。

    不播报语音(用户要求):认出来只写日志 + 更新界面上的点。

    只走**快路**(对着用户那两条红线:准、快):对话框位置是固定的(游戏把它贴在
    画布下方居中,框 = 画布 × `DLG_RATIOS`),先用 1ms 的"暗面板"判据挡掉
    绝大多数轮次,真有面板才 OCR 那一小块;任务栏框**来自 common 的
    TRK_BOXES**(`core.trk_rect`,画布×定稿框),只读那一小块 —— 没框的档
    任务栏那支一次都不读(2026-11-12 表刚换画布锚定,待真机重新框,期间
    整支不读)。原来"还没框时扫整窗找表头学框 / 连着没表头就作废重锚 /
    整窗找框的退避和冷却"那条兜底链,2026-10-21 随"只支持表里量过的档"
    整套删掉了(框不再学习、不再作废)。

    过程都写进日志(bell.log 里能看到扫了哪块、多大、几毫秒、认到了什么)。
    """

    name = "降妖伏魔"

    def __init__(self, app, screen, ocr):
        super().__init__(daemon=True)
        self.app = app
        self._screen = screen          # 取引擎的截图封装(基础设施)
        self._ocr = ocr                # 取 OCR 封装(基础设施)
        self.enabled = False
        self.spot = None               # 当前妖魔位置 (地图名, x, y)
        self.target = ""               # 小窗大字那一行(铃铛不播语音)
        self._last = {}                # 每个客户端最近报过的位置
        self._cycle = {}               # 每个客户端当前杀怪周期的目标(图+坐标)
        self._slot = {}                # 每个客户端的扫描状态(学到的框/历史读数)
        self._fail = {}                # 每处的失败原因:同样的错只记一条,别刷屏
        self._note_seen = {}           # 过程日志节流:每类上次写的是什么、什么时候
        self._warned_size = ""         # 日志里提醒过"这个尺寸不支持"了吗
        self._bad_size = ""            # 最近一次自动定位到的不支持尺寸(界面轮询弹窗)
        self._no_client = ""           # 扫不到客户端时说过的那句话(同样的只说一次)
        self._client_now = ""          # 当前自动/手动接入的那台(标题,界面据此写角色名)
        self._client_name = ""         # 上面那台的角色名
        self._client_rect = None       # 上面那台的窗口矩形
        self._client_lost = False      # 客户端退出/回登录页:界面据此收掉旧角色名
        self._stat = {"rounds": 0, "ocr": 0, "skip": 0, "dlg": 0,
                      "dlg_other": 0, "dlg_gate": 0}
        self._hb = 0.0                 # 上次心跳的时间
        self._ts = 0.0
        self._halt = threading.Event()
        self._wake = threading.Event()

    # ---- 生命周期 ----
    def activate(self):
        self.enabled = True
        self._wake.set()

    def deactivate(self):
        self.enabled = False

    def reset(self):
        """进入 / 退出这个功能时调用:上次的妖魔记录全部作废。"""
        self._last.clear()
        # `_cycle` 也得清(2026-10-16 检视发现):它记的是"每个客户端当前杀的是哪一只"。
        # 不清的话退出功能再进来、屏幕上还挂着同一条对话框时会判成"值没变" ->
        # 不重报,而 spot 刚被清成 None -> 小窗一直停在"等待铃铛任务提示",
        # 直到玩家换一只怪。清掉它,重进功能后同一条提示能重新报出来。
        self._cycle.clear()
        self._slot.clear()
        self._fail.clear()
        self._note_seen.clear()
        self.spot = None
        self.target = ""
        self._ts = 0.0
        self._hb = 0.0
        self._bad_size = ""
        self._client_now = ""
        self._client_name = ""
        self._client_rect = None
        self._client_lost = False
        watch = getattr(self, "_watch", None)
        if watch is not None:
            watch.reset()              # 重进功能:客户端快照记忆作废
        self._stat = {"rounds": 0, "ocr": 0, "skip": 0, "dlg": 0,
                      "dlg_other": 0, "dlg_gate": 0}

    def stop(self):
        self._halt.set()
        self._wake.set()

    # ---- 自己的配置 ----
    def cfg(self, key, default=None):
        """自己的配置只在 bell 分区取:别人的设置这里看不到。"""
        return (self.app.cfg.get("bell") or {}).get(key, default)

    def on(self):
        """监听**常开**(用户定的 2026-10-20):「自动监听」按钮已从界面撤掉,
        应用开着就在扫,不再有开关这回事。"""
        return True

    # ---- 只读状态口:gui/ui 只认这个口,不摸下面的字段 ----
    def ui_state(self):
        """界面刷新要的只读快照:妖魔位置、显示行、不支持的分辨率、当前客户端。"""
        return {"spot": getattr(self, "spot", None),
                "target": getattr(self, "target", ""),
                "bad_size": getattr(self, "_bad_size", ""),
                "client": getattr(self, "_client_now", ""),
                "client_name": getattr(self, "_client_name", ""),
                "client_rect": getattr(self, "_client_rect", None),
                "client_lost": bool(getattr(self, "_client_lost", False))}

    def interval(self):
        """扫描节奏:没单独配就用铃铛自己的下限;配了就夹到合法区间。

        下限比 core 的默认轮询(0.4s)快一档:现在一轮只是截两块小图 + 1ms
        门控,快得起。
        """
        import core
        gap = float(self.cfg("bell_interval", 0.0) or 0.0)
        if gap <= 0:
            return BELL_MIN_INTERVAL
        return min(core.MAX_INTERVAL, max(BELL_MIN_INTERVAL, gap))

    # ---- 扫哪:永远自动枚举客户端窗口(没有手动框这条路了) ----
    def regions(self):
        """扫描区域:**恒为一个**(降妖伏魔只管一台客户端)。

        优先级:用户在列表里选过的那台 > 第一个已登录角色。登录窗(标题抠
        不出角色名)一律不接;启动时还在登录页就返回空,登录角色后**自动
        接入监听**(与 keju 的自动收编同口径),不用再点药丸。多开且没选过
        时自动接第一台,点左下角药丸可切换。

        启动/登录/登出/关闭/最小化/还原的判定在 `client_watch`(纯逻辑,
        与 keju 同源可复用):这里每拍枚举一次窗口,把窗口包成快照、记日志、
        选一台(实测一次枚举 ≈0.24ms,比截图/OCR 便宜得多,不做缓存 ——
        缓存会让窗口挪动/换分辨率晚一拍甚至更久,2026-11-12 用户定的)。
        返回空(扫描暂停)时**说一次原因**:多开时关掉选中的那台客户端很常见,
        不说的话日志里只是"不再有新行",看起来像卡死。
        """
        import core

        from client_watch import choose_one
        want = str(self.cfg("bell_client") or "")
        snaps = self._poll_clients()
        if snaps is None:
            return []
        pick, why = choose_one(snaps, want, getattr(self, "_client_now", ""),
                               getattr(self, "_client_rect", None))
        if pick is None:
            if why == "gone":
                # 正在跟的那台被关了/退出登录:扫描暂停,等用户重新选
                # (启动时在登录页那种 `_client_now` 为空的情况走自动接入)
                shown = core.client_name(want) or want
                self._no_client_note(
                    f"选定的客户端「{shown}」不在枚举结果里 —— "
                    "扫描暂停,点左下角的药丸重新选一台")
                self._client_lost = True
                return []
            self._client_now = ""
            self._client_name = ""
            self._client_rect = None
            if why == "login":
                self._no_client_note("只枚举到登录窗口 —— 登录角色后自动接入监听")
                self._client_lost = True       # 回登录页 = 这个角色不在了
            elif why == "minimized":
                # 最小化:截不到画面,但客户端还在 —— 不算"退出",名字留着
                # (还原窗口后照常继续);只说一次原因,别每拍刷
                self._no_client_note(
                    "客户端已最小化 —— 截不到画面,扫描暂停(还原窗口后自动继续)")
                self._client_lost = False
            else:
                self._no_client_note("没枚举到客户端窗口(游戏没开或退出了) —— 扫描暂停")
                self._client_lost = True
            return []
        title, box = pick.title, pick.box
        name = pick.name
        # 同一窗口标题变了(多标签版切标签/换角色):继续跟,不写"自动接入"
        # (Tracker 已经记了一条「换成了…」),配置由界面轮询跟着改
        matched_want = why == "renamed" or (
            bool(want) and (title == want or name == want))
        rect = [int(v) for v in box]
        if title != getattr(self, "_client_now", ""):
            if want and not matched_want:
                self.app.log(f"[{TAG}]登录角色后自动接入「{name}」")
            elif not want:
                logged = [c for c in snaps if c.logged and not c.minimized]
                if len(logged) == 1:
                    self.app.log(f"[{TAG}]检测到已登录客户端「{name}」,自动接入监听")
                else:
                    self.app.log(f"[{TAG}]检测到 {len(logged)} 个已登录客户端,"
                                 f"自动接入第一台「{name}」(点左下角药丸可切换)")
        self._no_client_note("")
        self._client_lost = False
        self._client_now = title
        self._client_name = name
        self._client_rect = rect
        return [rect]

    def _log_client_event(self, ev):
        """把 `client_watch` 的变化挑要落日志的写进 bell.log。

        只写**靠扫描暂停那句看不出来**的:登出、换角色、还原。启动/新登录/
        挪窗/换档各有各的去处(接入日志、check_size 提醒),关闭和最小化由
        暂停原因那句说一次 —— 别再重复刷屏。
        """
        if ev.kind == "logout":
            if ev.client.logged:
                # 同一窗口里换了角色(真换角色,或多标签版点了另一个标签):
                # 新角色已经在了,应用会按选择策略接下去 —— 别再说"已退出
                # 登录"(切标签并没有登出),一条中性日志够看
                self.app.log(
                    f"[{TAG}]当前角色换成「{ev.client.name}」(原「{ev.old.name}」)")
            else:
                self.app.log(f"[{TAG}]{ev.note} —— 登录角色后自动接入监听")
        elif ev.kind == "restored":
            self.app.log(f"[{TAG}]{ev.note}")

    def _poll_clients(self):
        """枚举一次客户端窗口:刷新快照 + 记登录/登出/换角色事件。

        返回快照列表;枚举失败返回 None(调用方当"这拍不扫")。**每拍都查**
        (实测一次 ≈0.24ms,比截图/OCR 便宜得多);不做缓存 —— 窗口挪动/
        换分辨率要当拍跟上(2026-11-12 用户定的)。
        """
        import core

        from client_watch import Tracker, snapshot
        try:
            found, mini = core.find_client_windows()
        except Exception:
            return None
        snaps = snapshot(found, mini, core.client_name)
        watch = getattr(self, "_watch", None)
        if watch is None:
            watch = self._watch = Tracker()
        for ev in watch.poll(snaps):
            self._log_client_event(ev)
        return snaps

    def _no_client_note(self, msg):
        """扫不到客户端时只说一次(每个 tick 都打就是刷屏)。"""
        if getattr(self, "_no_client", None) == msg:
            return
        self._no_client = msg
        if msg:
            self.app.log(f"[{TAG}]{msg}")

    def check_size(self, size):
        """游戏设置分辨率(画布口径)支持吗?不支持记下来(界面轮询给药丸红字提示)。

        三档:640x480 / 800x600 / 1024x768(2026-11-12 用户定的,1024 与
        keju 对齐重新加入),**按游戏设置分辨率精确判** —— 窗口尺寸/显示
        缩放都不参与(同一个游戏分辨率在不同缩放下窗口差一截,老的"窗口
        尺寸±8 容差"口径在这里错档)。返回 True = 支持。
        """
        w, h = int(size[0]), int(size[1])
        import core
        if core.supported_res((w, h)):
            if getattr(self, "_bad_size", ""):
                # 从不支持改回支持档:说一声「继续识别」(keju 那边是"自动纳入
                # 观测";单客户端这里本来就一直在跟,只是恢复读数)
                log = getattr(getattr(self, "app", None), "log", None)
                if log:
                    log(f"[{TAG}]游戏分辨率已恢复到支持档 {w}×{h},继续识别")
            self._bad_size = ""
            return True
        self._bad_size = f"{w}x{h}"
        return False

    def fixed_dialog(self, region, found=None):
        """对话框框 = **游戏画面 × 定稿比例**(绝对坐标);拿不到画布/档位返回 None。

        `found` 是这一拍已经查好的 `canvas_res_of(region)`(不给就现查)—— 扫描
        一拍只枚举一次窗口,任务栏框和对话框框共用同一份画布。

        比例按**游戏设置分辨率**分档(`DLG_RATIOS`,三档 2026-11-08/11-12 定稿,
        两种版式共用);画布物理像素 = 游戏分辨率 × 显示器倍率,所以同一档比例
        在任何缩放下都贴。不支持的分辨率提醒一次(界面轮询靠 `_bad_size`
        弹窗);支持但比例还没量的档位也整支不读、只说一次(见下)。
        """
        if found is None:
            found = canvas_res_of(region)
        if not found:
            return None
        import core
        canvas, res, mode = found
        if not self.check_size(res):
            label = f"{res[0]}x{res[1]}"
            if getattr(self, "_warned_size", "") != label:
                self._warned_size = label
                # 措辞与 keju 的 _log_unsupported 同口径:尺寸 + 已跳过 + 支持档
                self.app.log(f"[{TAG}]游戏分辨率 {label} 不支持,已跳过 —— 只支持 "
                             f"{core.supported_res_text()}(请在游戏设置里改一下)")
            return None
        if res not in core.DLG_RATIOS:
            # 支持但档位比例还没量(现三档都有,2026-11-12):没有比例就没有
            # 框,整支不读 —— 和"没有比例兜底"同一条口径。只说一次;量完往
            # client_common 的 DLG_RATIOS 补一行就自动恢复。
            label = f"{res[0]}x{res[1]}"
            if getattr(self, "_warned_ratio", "") != label:
                self._warned_ratio = label
                self.app.log(f"[{TAG}]游戏分辨率 {label} 的对话框比例还没量 —— "
                             "这一档暂不识别,重新画框定稿后自动恢复")
            return None
        return core.dialog_rect(canvas, res)

    def locate(self):
        """重新枚举客户端窗口(只是记条日志;扫描永远按窗口实时来)。"""
        import core
        try:
            wins, minimized = core.find_client_windows()
        except Exception as err:
            self.app.log(f"[{TAG}]自动定位失败: {err}")
            return 0
        for t in minimized:
            self.app.log(f"[{TAG}]客户端已最小化,截不到画面: {t}")
        return len(wins)

    # ---- 扫描 ----
    def _log_fail(self, what, key, err):
        """同一处的同类失败只记一条(恢复了再记下一条),别每轮刷屏。

        截图/识别失败本来就该记日志;这里以前是全 continue,
        出了事日志里一个字都没有,没法查。
        """
        if self._fail.get((what, key)) == str(err):
            return
        self._fail[(what, key)] = str(err)
        where = (key if isinstance(key, str)
                 else ",".join(str(v) for v in tuple(key)[:4]))
        self.app.log(f"[{TAG}]{what}失败({where}): {err}")

    def _grab(self, screen, rect, what):
        """截一块;失败记一条(去重)并返回 None。"""
        try:
            crop = screen.grab(rect)
        except Exception as err:
            self._log_fail("截图", what, err)
            return None
        self._fail.pop(("截图", what), None)      # 恢复了:下次失败重新记
        return crop

    def _note(self, kind, text, now, base=""):
        """过程日志节流:内容变了就写,没变最多 LOG_GAP 秒写一条。

        不节流的话快路一轮一行,一分钟几百行 —— bell.log 一小时能到十几兆。
        心跳那行不受影响,它自带 10 秒间隔。
        """
        last = self._note_seen.get(kind)
        if last and last[0] == text and now - last[1] < LOG_GAP:
            return
        self._note_seen[kind] = (text, now)
        self.app.log(f"[{TAG}]{base}{text}")

    def _read(self, ocr, crop, what, limit=OCR_LIMIT, limit_type=None):
        """OCR 一块,返回 (文字块, 毫秒);失败返回 (None, 毫秒)。

        默认按 OCR_LIMIT 调小 det 的放大下限 —— 整窗那种大图本来就不会被放大,
        传了也一样;小区域能省一大半时间。字本来就大的那块(对话框条带)传
        `limit_type="max"` + 足够大的 `limit`,就是"按原像素跑",更快。
        """
        t0 = time.time()
        try:
            if limit_type:
                blocks = ocr.recognize_blocks(crop, limit_side=limit,
                                              limit_type=limit_type)
            elif limit:
                blocks = ocr.recognize_blocks(crop, limit_side=limit)
            else:
                blocks = ocr.recognize_blocks(crop)
        except TypeError:                       # 桩/旧实现不吃这个参数
            blocks = ocr.recognize_blocks(crop)
        except Exception as err:
            self._log_fail("识别", what, err)
            return None, (time.time() - t0) * 1000
        self._fail.pop(("识别", what), None)
        self._stat["ocr"] += 1
        return blocks, (time.time() - t0) * 1000

    def _recheck(self, ocr, crop, what, scoped):
        """同一块裁剪**换 det 下限**再读一次,返回解析出的 (图名,x,y) 或 None。

        给"新坐标要复读确认"那条用(见 `_scan` 里采信新值之前那一段):解析口径和主读
        那次**完全一致**(同一套 `scan_bell_parts`/`known_map`/`_coord_of`),只是 det
        下限换成 `TRK_RECHECK_LIMIT` —— 换个参数看还能不能读出同一个值。
        """
        blocks, _ms = self._read(ocr, crop, what, limit=TRK_RECHECK_LIMIT)
        if not blocks:
            return None
        d, t, _w = scan_bell_parts(blocks, scoped=scoped)
        return d or t

    def tick(self, force=False):
        if not self.on():
            return
        screen, ocr = self._screen(), self._ocr()
        if screen is None or ocr is None:
            return
        now = time.time()
        if not force and now - self._ts < self.interval():
            return
        self._ts = now
        self._stat["rounds"] += 1
        for slot, region in enumerate(self.regions(), 1):
            try:
                if self._scan(slot, region, screen, ocr, force, now):
                    break                  # 一轮只报一个,别一下刷出好几个
            except Exception as err:
                self._log_fail("扫描", tuple(region), err)
        self._heartbeat(now)

    def _scan(self, slot, region, screen, ocr, force, now, again=False):
        """扫一个客户端,返回 True = 这轮报了新目标。

        force=True 时门控全部让路 —— 它只是**测试钩子**(铃铛这条路上没有任何
        产品功能在用它:循环调的是无参 `tick()`)。
        again=True 只由"对话框读到新目标要当场再扫一遍"那一条发起(见下面那段);
        这一拍**任务栏那一支整支跳过**(理由见那一段的注释)。
        """
        st = self._slot.get(slot)
        # 画布/分辨率这一拍现查:窗口挪了/改档了,裁剪坐标必须当拍跟上
        _c = canvas_res_of(region)
        if _c is None:
            # 这一拍没画布(登录窗 / 最小化 / 窗口刚挪还没摆稳):**整拍不读**
            # —— 任务栏那支也不能按表框去截,否则会读到别处的内容。
            self._stat["skip"] += 1
            return False
        _res = (int(_c[1][0]), int(_c[1][1]))
        if st is None or st.region != tuple(region):
            # 区域变了(窗口被拖动 / 换了客户端):换一份扫描状态。
            # 顺带把"这个槽当前的目标"也清掉(2026-10-16 检视发现):不清的话,
            # 换了客户端/窗口挪了之后,新画面的目标会被判成"跟旧的一样"而不重报。
            # **`_last`(同一条不重复报)留着**:拖动窗口时每拍都会走这条路,
            # 清了它就会每拍重报同一条(刷屏);它也只是"同值不重报",不挡新目标。
            self._cycle.pop(slot, None)
            # 任务栏框**来自 common 的 TRK_BOXES**(`core.trk_rect`,画布×占画比;
            # 用户 2026-11-12 定的进 client_common 与 keju 共用 —— 任务面板画在
            # 游戏画面哪里是游戏属性。按**游戏设置分辨率**分档、两版式共用,
            # 三档都有(2026-11-12 定稿);查不到的档任务栏那支不读,没有
            # 兜底 —— 不存在"现场找"这条路了)。
            _trk_seed = trk_seed_rel(region, _c)
            # **任务栏那侧的"盯"不作废**(2026-10-24 真机抓到的):逐妖蛊虫的
            # 第二个坐标多半在对话框关掉之后才刷出来,这几十秒里窗口挪一像素
            # 就把整份状态换新、trk_mode 抹回 none —— 等新坐标的循环悄悄死掉,
            # 任务栏一次都不再读(心跳节奏退回 0.60s、OCR 0 次),第二坐标全程
            # 拿不到。所以换新时把"盯什么、读到过什么"原样带过去(trk_mode/gap/
            # hist/text/last/stale/pub/miss),几何相关的(region/框/签名/时刻)
            # 照旧换新 —— trk_ts/trk_psig 归零,换新后第一拍立刻重读一次;
            # 换客户端的话,下一张对话框开新周期会重新定类型。
            _old = st
            st = SlotState(region=tuple(region), res=_res, trk=_trk_seed)
            if _old is not None:
                st.trk_mode = _old.trk_mode
                st.trk_gap = _old.trk_gap
                st.trk_hist = _old.trk_hist
                st.trk_text = _old.trk_text
                st.trk_last = _old.trk_last
                st.trk_stale = _old.trk_stale
                st.trk_pub = _old.trk_pub
                st.miss = _old.miss
            if _trk_seed:
                self.app.log(f"[{TAG}]任务栏框用表里量的那格 "
                             f"{tuple(_trk_seed)}(这个尺寸只扫这里)")
            self._slot[slot] = st
        elif _res is not None and st.res != _res:
            # **游戏里换了分辨率**(窗口矩形往往一像素都不动,不能等它变):
            # 任务栏框是按游戏分辨率分档取的,留着旧档的框会去读错位置/读不到。
            # 按新档重取,签名/时刻归零让下一拍立刻重读;"盯什么、读到过什么"
            # (trk_mode/gap/hist/text/last/stale/pub/miss)原样带过去 —— 和窗口
            # 挪动那份同一个理由(2026-10-24:别让等第二坐标的循环悄悄死掉)。
            st.res = _res
            st.trk = trk_seed_rel(region, _c)
            st.trk_ts = 0.0
            st.trk_psig = None
            label = f"{_res[0]}x{_res[1]}"
            self.app.log(f"[{TAG}]游戏分辨率变成 {label},"
                         + (f"任务栏框已按新档重取 {tuple(st.trk)}" if st.trk
                            else "这一档没有任务栏框,任务栏那支不读"))
        dialog = track = None
        panel_gone = False      # 这一拍连面板都没判出来(而不是"有面板但没读出坐标")

        # ---- 快路 1:对话框(位置固定) ----
        # 框 = 游戏画面(WSGAME 画布)× 定稿比例(`DLG_RATIOS`,按游戏设置
        # 分辨率分档,两版式共用):
        # 位置是死的,直接按框裁、只拿"这块地方够不够暗"当"现在有没有对话框"的
        # 判据 —— 不用 panel_box 去猜(暗场景里它会跟身后的暗区糊成一片,实测分不开)。
        # **没有比例兜底**(2026-11-08 用户定的):分辨率现在能精确拿到,拿不到
        # 精确档(画布没配到 / 游戏分辨率不支持)就整拍不识别 —— 不支持的档
        # `fixed_dialog` 里已经提醒过一次,这里不再说话。
        fixed = self.fixed_dialog(region, _c)
        crop = self._grab(screen, fixed, "对话框") if fixed else None
        if crop is not None:
            # 定稿比例框是最宽的那种对话框,是个**上界**:先在框里按像素收紧到
            # 实际面板 —— 窄一点的对话框(纯文字那种)就不会把左边那片游戏世界
            # 一起读进来;收不出来(暗场景糊成一片)就整块当面板用,宁可多读也不漏字。
            # **滞回**:已经在"有面板"状态时用低 0.05 的线,别让暗比在阈值边上
            # 抖一下就把面板判没了(2026-10-17 实测:第二遍重扫撞上 0.59 vs 0.60,
            # 新坐标就这么丢了)。
            # 暗掩码同一拍只算一次:panel_frac 要它,panel_box 的两道暗比
            # 门槛也要它 —— 原来面板开着时一轮算三遍(每遍 13~20ms),现在一遍。
            _dark = _dark_of(crop)
            _pf = 0.0 if _dark is None else float(_dark.mean())
            _thr = (DIALOG_DARK_FRAC - 0.05 if st.dlg_on
                    else DIALOG_DARK_FRAC)
            # 暗比先算、过了门槛才去找面板框(panel_box 是门控里最贵的一步);
            # 没面板的轮次(绝大多数)整步省掉,一拍少 4~5ms
            flat_hit = False
            if _pf >= _thr:
                tight = panel_box(crop, dark=_dark)
                if tight:
                    box = tight
                else:
                    box = (0, 0, crop.shape[1], crop.shape[0])
            else:
                # 暗比不够(游戏里换成了**浅色对话框皮肤**):按**结构锚点**
                # 再判一次 —— 一整块低频平坦的横条(空白区)+ 上面 2~3 排文字行,
                # 跟配色无关(2026-11-12 用户提的口径)。真机实测:浅色面板的
                # 空白带 92px、行平坦度 0.8+,同尺寸世界段全部 <0.5。
                box = flat_panel_box(crop)
                flat_hit = box is not None
            on = box is not None
            if on != st.dlg_on:
                st.dlg_on = on
                # **只进文件,不进界面**(用户定的 2026-10-17):面板出现/消失是
                # 环境噪音(录像里、切场景时来回跳),界面上刷它没意义;
                # 查问题时 `bell.log` 里照样有。
                self.app.log(f"[{TAG}]对话框面板"
                             f"{'出现' if on else '消失'}"
                             f"(暗比 {_pf:.2f}{',结构' if flat_hit else ''})")
            if box:
                self._stat["dlg"] += 1
                # 面板里的内容一变(点 NPC 翻页)就马上重读;没变才按 DIALOG_GAP
                # 的节奏兜底。**签名要用"上次读的时候那个框"**:panel_box 的边
                # 会抖 ±4 像素,拿当轮的框去算,光是抖动就有 18~35 的差,比"换了
                # 一段对话"(15~38)还大 —— 框固定住,抖动就没了。
                psig = panel_sig(crop, st.dlg_rect or box)
                changed = (st.dlg_psig is not None
                           and sig_diff(psig, st.dlg_psig) >= SIG_MIN)
                # 非铃铛面板(买东西/闲聊/聊天频道)的内容一直在滚 —— 每拍都"变了",
                # 但变的是别人的聊天,不是我们的任务。给"变了就重读"加一道最小间隔
                # (2026-10-21 真机会话:490 秒里 267 次 OCR 全是这种白读,每次一两
                # 百毫秒)。铃铛面板不受影响:翻页要当轮重读。
                # 间隔下限跟着"上一读实际耗时"放大:识别快的机器还是 0.6~1.2s;
                # CPU 回退的慢机器一读就是两三秒,还按固定间隔就是背靠背白烧
                # (2026-11-03 用户机器日志:面板开着时 OCR 一秒不歇,游戏被 CPU
                # 爆发拖卡)。
                other_gap = max(DIALOG_OTHER_GAP, st.dlg_ms / 1000.0 * 1.2)
                if (changed and not st.dlg_bell
                        and now - st.dlg_ts < other_gap):
                    changed = False
                # 确认**不是铃铛任务**的对话框(买东西/闲聊那些):内容没变就别按
                # 节奏重读了 —— 真机上这种占八成,每次白烧一百多毫秒。
                # 铃铛面板的兜底间隔同理自适应(见上面那条的注释)。
                due_gap = max(DIALOG_GAP, st.dlg_ms / 1000.0 * 1.2)
                due = (now - st.dlg_ts >= due_gap
                       and st.dlg_bell)
                # **有待确认的新坐标时,0.3 秒就再读一遍**(用户定的"立刻马上再读一次,
                # 两次相同放行"):重扫那拍要是撞上面板闪一下/读花,别干等 2 秒的
                # `DIALOG_GAP` —— 而 `dlg_bell` 被那一拍置成 False 之后根本不会再读
                # (2026-10-17 实测:值挂着、红点一直不刷新)。TTL 到点 `dlg_pend`
                # 会被清掉,所以这里不会无限读。
                if (st.dlg_pend is not None
                        and now - st.dlg_ts >= 0.3):
                    due = True
                # **读不读看签名,不看"面板是不是重新出现了"**:面板暗比在阈值边上
                # 一抖(真机日志 0.52~0.67 反复横跳),出现/消失一秒翻两三次,原来
                # 每次"出现"都强制重读一遍 —— 字没变也白烧一整次 OCR。`dlg_psig`
                # 是跨"面板消失"留着的(见下面 else 那段):它还在就说明这块面板读过,
                # 内容真变了走 `changed`;None 只有两种 —— 还没读过 / 上一拍没读成。
                if force or again or st.dlg_psig is None or changed or due:
                    # 只把面板**有字的那一截**喂给 OCR:不带身后的游戏世界,
                    # 也不带上方的任务栏(它那两行也会带坐标,混进来会被当成
                    # "对话框说的"),更不带面板下半截那片空白
                    part = panel_text_cut(crop, box)
                    # 第一遍:按原像素跑(字大,放大只白烧 det);第二遍(`again`)
                    # 换回 480 的放大档 —— 复读要的是"换个参数还读出同一个值"。
                    if again:
                        blocks, ms = self._read(ocr, part, "对话框")
                    else:
                        blocks, ms = self._read(ocr, part, "对话框",
                                                limit=DLG_LIMIT_SIDE,
                                                limit_type=DLG_LIMIT_TYPE)
                    st.dlg_ts = now
                    st.dlg_ms = ms          # 自适应间隔的依据(见上面 other_gap/due_gap)
                    if blocks is not None:
                        # 对话框里那句可能是"踪迹在…"也可能是"去X(x,y)使用招魂帖",
                        # 两种都算对话框说的 —— 别只取一种把招魂帖那种漏掉
                        d, t, _w = scan_bell_parts(blocks, scoped=False)
                        dialog = d or t
                        # 这一拍面板上读到的**原文**:开新周期时拿它定任务类型
                        # (类型只由对话框给,见 `_publish` / `trk_plan`);另外它还要
                        # 过下面那道"话术门槛"
                        st.dlg_raw = "".join((b.get("text") or "")
                                             for b in blocks)
                        # **话术门槛**(用户定的 2026-10-16,表见 `BELL_WORDS`):
                        # 这一段文字里一个"铃铛任务的核心词"都没有 -> 里面的"图名+坐标"
                        # 当读花,不认。挡的是"面板收紧失败(整块当面板)时把下方聊天/
                        # 世界频道一起读进来"那种**静态行** —— 它两遍必然读成一样,
                        # "两遍一致"挡不住它。**只在对话框这条主路吃门槛**,任务栏那支
                        # 不吃(悬停那行单独读出来时没有核心词)。
                        if dialog and not has_bell_words(st.dlg_raw):
                            self._stat["dlg_gate"] += 1
                            self._note("话术门槛", f"面板里读到 {_spot(dialog)},"
                                       "但那一段里没有铃铛任务的核心词 —— 当读花,"
                                       "这一段不认", now, "话术门槛 ")
                            dialog = None
                        st.dlg_text = dialog
                        # hover 档(巧智魔/怯弱妖)的"收手话术"(用户定的 2026-10-16):
                        # 对话框里出现这些(见 `HOVER_STOP_WORDS`)说明追/逃那一段结束了
                        # -> 这个周期不再扫任务栏。**只有 hover 档有这条**,`none`/`item`
                        # 一个字都不动;也不拿它去推断类型什么的。
                        # (这一段读的原文跟"有没有坐标"无关:收手话术那几句都没有坐标,
                        #   被上面那道门槛挡下也不影响它 —— 见 `hover_stop` 的用例。)
                        stop = hover_stop(st.dlg_raw)
                        if stop and st.trk_mode == TrkMode.HOVER:
                            st.trk_mode = TrkMode.NONE
                            self.app.log(f"[{TAG}]对话框出现收手话术({stop})"
                                         " —— 这个周期不再扫任务栏")
                        st.dlg_bell = bool(dialog)     # 这块面板是不是铃铛任务
                        if dialog:
                            # 过程行(`_note` 自带 10 秒节流);报出目标时另有
                            # 「妖魔位置」那一条,读数细节(块数/耗时/读到啥)都在这行。
                            self._note("对话框", read_note(
                                "对话框条带", (part.shape[1], part.shape[0]),
                                len(blocks), ms, dialog, blocks), now, "识别 ")
                        else:
                            # 不是铃铛任务:不逐条刷日志,心跳里汇总(带一条样本)
                            self._stat["dlg_other"] += 1
                            st.dlg_sample = (part, blocks, ms)
                            # **公告对话框却没解析出坐标**:把原文整段记一笔(只进
                            # 文件,`_note` 自带 10 秒节流)。2026-10-17 16:59 实测:
                            # 「接下来你们遇到的将是一只狡猾的迷幻妖。想要抓住它,可」
                            # 只读到第一句、坐标那句没进 OCR —— 整轮新目标丢掉,红点
                            # 挂在上一轮(用户:"为什么不刷新")。心跳那行只留 26 个字,
                            # 看不出"字被裁掉了"还是"读花了",所以要原文。
                            _raw = st.dlg_raw or ""
                            if has_bell_words(_raw) and any(
                                    w in _raw for w in ("迷幻妖", "梦魇魔",
                                                        "巧智魔", "怯弱妖",
                                                        "逐妖蛊虫")):
                                self._note("公告原文", _raw[:120], now,
                                           base="公告对话框只认出怪名、没坐标 —— "
                                                "原文: ")
                                # **巧智魔/怯弱妖被遮住时转盯悬停**(2026-11-07 真机:
                                # 藏宝阁广告横幅/「打坐」弹窗正好盖在「踪迹在X(x,y)」
                                # 那一行上,整轮只读出怪名 —— 当天 8 次这种乱码,对应
                                # 的怪在发布列表里一只都没出现,用户:"第一坐标经常没
                                # 识别到")。被盖住的字谁也读不出来,但这两类的行进坐标
                                # 本来就靠鼠标悬停任务栏那行「在X(x,y)处」(玩家必然去
                                # 悬停拿第二坐标),对话框没给坐标就让悬停那行顶上。
                                # **不动正在盯的周期**(item 档盯到一半,不许被一次读花
                                # 改道);迷幻妖/梦魇魔没有悬停行,只能等下一只。
                                if (st.trk_mode == TrkMode.NONE
                                        and any(w in _raw for w in TYPE_HOVER)):
                                    st.trk_mode = TrkMode.HOVER
                                    st.trk_gap = watch_gap(st.trk_mode)
                                    self.app.log(
                                        f"[{TAG}]对话框的坐标行被广告/弹窗盖住了,"
                                        "只认出怪名 —— 这个周期改盯任务栏悬停坐标"
                                        "(鼠标压到任务栏上,读「在X(x,y)处」那行)")
                        # 框和签名**一起**记:下一轮拿这个框算签名,形状才不会变
                        st.dlg_rect = box
                        st.dlg_psig = panel_sig(crop, box)
                    else:
                        # 这一拍没读成(引擎报错/回退中):当"没读过",下一拍再试
                        st.dlg_psig = None
                else:
                    dialog = st.dlg_text       # 面板还在、字没变:沿用上次读的
            else:
                st.dlg_text = None
                st.dlg_bell = True               # 面板没了:兜底重读(due)重新开张
                panel_gone = True
                # **`dlg_pend` 别在这儿清**:面板闪一下(实测暗比 0.59 vs 阈值 0.60)
                # 就把待确认的新坐标扔了 —— 交给下面那个 `PEND_TTL`。
                # **签名和框留着**(别清):`panel_sig` 拿它当基准比"面板里的字变了
                # 没有"(变了当拍就重读),框固定住还能免掉 `panel_box` 边抖 ±4px
                # 带来的假变化;而且它是"这块面板读过没有"的记号 —— 面板闪一下又
                # 回来时签名一样,就不会白重读(见上面读的触发条件)。

        # 对话框认到了**新的目标**:**立刻马上再读一次,两遍读到同一个值才放行**
        # (用户定的 2026-10-16 傍晚:「对话框里读出了新的目标后,立刻马上再读一次,
        # 两次相同放行」)。对话框里的目标永远是对的 —— 这条要防的是**我们自己读花**:
        # 实测踩过 23:51 把「建邺城(101,127)」读成「建邺城(24,108)」(两个都落在建邺城
        # 的范围内,`in_bounds` 挡不住),当场把红点挪到了错地方。
        # 规矩:读到和当前目标不一样的值 -> 记进 `st.dlg_pend`、**不覆盖**(报出去的
        # 目标不动)、`again=True` **当场**重扫一次同一块面板;第二遍还是这个值 ->
        # 采信并报出去(红点多花一次 ~180ms,买的是"不把读花报给用户");读回原值 ->
        # 刚才那次是读花,丢掉。第一遍读到的值**不进 `_cycle`**、也不更新界面。
        if dialog:
            cur = self._cycle.get(slot)
            if dialog == st.dlg_pend:
                if cur:
                    self.app.log(f"[{TAG}]对话框改口: {_spot(dialog)}"
                                 "(同一个值连读两次),以它为准")
                else:
                    self.app.log(f"[{TAG}]对话框 {_spot(dialog)}"
                                 "(连着两遍读到一样),以它为准")
                st.dlg_pend = None
                st.dlg_gone = 0.0            # 这一拍读到了:TTL 计时归零
                # 开新周期要做的两件事(清任务栏那边的残留 + 拿对话框的文字定
                # 任务类型)**都由 `_publish` 在周期真的换了那一刻统一处理**,
                # 这里不碰状态。周期里的目标下一轮(0.15s 后)才看任务栏那块。
                if self._publish(slot, dialog, "对话框"):
                    return True
            elif dialog == cur:
                st.dlg_pend = None           # 又读回原值:刚才那次是读花
            elif not again:                   # 这一轮还没为第二遍回过头
                st.dlg_pend = dialog
                # **TTL 从"这一拍读不到"开始算**(2026-10-17 15:05 实测抓出来的):
                # `dlg_gone` 是"面板上次消失"的时刻,只要面板隔一阵就藏一下,它
                # 一直是老值 —— 不复位的话,新记下的 pend 会在下一拍"面板不见了"
                # 直接判超时(now - 老时刻 > 10 秒),等于单发就被扔了。
                # 真机就是这条把「西梁女国(99,36)」连读两次都丢了(两遍都写"先不覆盖")。
                st.dlg_gone = 0.0
                if cur:
                    # **只进文件**(用户定的 2026-10-17):这条是"第一遍不采信"的过程行,
                    # **每接一个新任务都会出现一次**,界面上留结果(紧跟的"以它为准"/
                    # "改口")就够了 —— 不然每轮两条、看着像在报错。
                    self.app.log(f"[{TAG}]对话框读到 {_spot(dialog)},和当前目标 "
                                 f"{_spot(cur)} 不一样 —— 先不覆盖,立刻重扫一次")
                else:
                    self.app.log(f"[{TAG}]对话框读到 {_spot(dialog)} —— "
                                 "先不采信,立刻重扫一次(两遍一样才算)")
                return self._scan(slot, region, screen, ocr, True, now,
                                  again=True)
        else:
            # 这一拍没读出目标(面板闪了一下 / 换成了没坐标的一句 / 没认出来):
            # **别立刻作废待确认的那个值** —— 2026-10-17 15:38:44 实测:第二遍重扫
            # 那一拍面板暗比 0.59(阈值 0.60)被判"消失",(108,26) 就这么丢了,红点
            # 一直不刷新。现在给个 TTL:面板消失/读不到**持续超过 `PEND_TTL`** 才作废
            # (TTL 之外它还挂着的话,下一句恰好读出同一个值就会**单发**命中,
            #  等于绕过"两遍一致" —— 所以必须有这个上限)。
            pend = st.dlg_pend
            if again and panel_gone and pend:
                # 复读那一拍**面板已经关了**(用户手快/对话自动关):第二遍根本读不到,
                # 等下去也等不来"两遍一致",整轮任务就这么丢了(2026-10-17 16:06 实测:
                # 「宝象国(149,53)」刚读到、面板就没了,红点一直挂在上一轮)。
                # 对话框里的目标是权威的 —— 这一种情况**直接用第一遍的值**。
                st.dlg_pend = None
                st.dlg_gone = 0.0
                self.app.log(f"[{TAG}]对话框复读那一拍面板已经关了 —— 直接用第一遍"
                             f"读到的 {_spot(pend)}(两遍一致做不了)")
                if self._publish(slot, pend, "对话框"):
                    return True
            if not st.dlg_gone:
                st.dlg_gone = now
            if now - st.dlg_gone >= PEND_TTL:
                st.dlg_pend = None

        # ---- 快路 2:任务栏(只在"这轮任务需要它"时才读) ----
        # 用户定的规矩:只有逐妖蛊虫(用道具后任务栏换一条新坐标)、巧智魔、怯弱妖
        # 这3类任务才关心任务栏;其余(招魂帖/招魂幡/梦魇魔/迷幻妖)坐标对话框里就有
        # —— **一次都不读**。
        # **类型由对话框给**(`_publish` 里按 `trk_plan(对话框文字)` 写进 `trk_mode`):
        # 还没开过周期(没对话框说过类型)时默认 `none` —— 任务栏一次都不读。
        # 任务栏那份文字只用来**拿第二个坐标**,永远不参与定类型。
        # 框一律来自分辨率表:表里没有的尺寸(不支持的分辨率)同样一次都不读。
        mode = st.trk_mode
        if again:
            # 这一拍是"对话框第二遍"回头扫(见上面那段):**任务栏整支不碰**。
            # 它的全部目的就是把对话框那块再读一遍;任务栏 0.15s 后的下一拍照常读,
            # 不会漏(item/hover 就是 0.25~0.5s 盯的节奏),顺带省一次 ~130ms 的 OCR。
            #
            # 更要紧的是**别让它在这一拍报出去**(用户 2026-10-16 检视时定的):
            # 这一拍带着 `force`/`again`,任务栏那条"见过两次"复核会被放路
            # (`got and (force or again or ok == got ...)`);而此刻任务栏第一行
            # 恰恰**就是对话框刚给的那条**(「去X(x,y)使用逐妖蛊虫」两处同文),
            # 它会抢先以 `src="任务栏"` 报出、把 `_cycle[slot]` 先写掉 ——
            # 等对话框第二遍确认时 `bell != self._cycle.get(slot)` 已不成立,
            # `_publish` 里**只有 `src == "对话框"` 才跑的那段**(定任务类型 +
            # 清上一周期残留)就被整段跳过,这一轮的类型会沿用上一周期的
            # (该盯任务栏的没盯 -> 漏第二个坐标;反过来只是白读)。
            self._stat["skip"] += 1
            track = st.trk_text
        elif mode == "none" or st.trk is None:
            # 不读:类型是 none(其余任务),或者这个尺寸没量过任务栏框(不支持的
            # 分辨率,2026-10-21 起不再有"整窗找框"的兜底)—— 沿用这个周期里
            # 已经拿到的。
            track = st.trk_text
            self._stat["skip"] += 1
        else:
            # 表里量的框:只扫那一块;**超出扫描区就往内挪**(宽高不变,见 `fit_rect`)
            rect = abs_rect(region, st.trk)
            fit = fit_rect(region, rect)
            if fit != rect:
                bits = []
                if fit[2] != rect[2]:
                    bits.append(f"原 x1={rect[2]},现 x1={fit[2]}")
                if fit[3] != rect[3]:
                    bits.append(f"原 y1={rect[3]},现 y1={fit[3]}")
                self.app.log(f"[{TAG}]任务栏框超出扫描区,已向内挪"
                             f"({';'.join(bits)})")
                rect = fit
            what = "任务栏"
            # 鼠标停在任务栏那块**及其周围** = 悬停坐标可能出来了(巧智魔/怯弱妖)。
            # 只要求"压在框上"太严:玩家会把鼠标挪到面板的文字行、panel 的边角上。
            cur = cursor_pos()
            near = in_rect(cur, rect, grow=HOVER_GROW)
            # **hover 档:鼠标不接近就整支跳过**(用户定的 2026-10-16)—— 那行
            # 「在X(x,y)处」只有玩家把鼠标压到任务栏上才显示,没鼠标读它纯属白花
            # OCR。不打日志(省得刷屏,心跳里能看到节奏)。**item 档不受影响**:
            # 逐妖蛊虫的坐标是任务栏里直接写着的,跟鼠标无关,照旧 0.5s 盯。
            if mode == "hover" and not near:
                self._stat["skip"] += 1
                crop = None
                crop_rect = None
                # **鼠标和任务栏框对不上时,把两边坐标写进文件**(用户 2026-10-17 报
                # "鼠标移到任务栏还是没有快扫"时加的诊断):只看"跳过"数分不清是
                # "鼠标真不在附近"还是"框学歪了/窗口尺寸变了" —— 有这两组坐标一眼就知道。
                # 5 秒最多一条(鼠标一直在动,不节流会刷屏),只进 bell.log。
                if cur and now - st.hover_warn_ts >= 5.0:
                    st.hover_warn_ts = now
                    self.app.log(
                        f"[{TAG}]悬停:鼠标 {tuple(int(v) for v in cur)} 不在任务栏框 "
                        f"{tuple(int(v) for v in rect)} ±{HOVER_GROW} 里 —— 这一拍不读"
                        "(把鼠标挪进那个框;框不对就点小窗右下角的 ↻ 重新找)")
            else:
                # **悬停档永远往上多留一截**(用户定的 2026-10-16 上一条):那行画在
                # 「降妖伏魔」标题**上方**,不往上扩就永远落在裁剪之外。鼠标走近了才
                # 会读到(上面那道门),所以这里光标是真位置、`hover_rect` 的
                # ±260/±90 那圈也照旧带上;往上留的那 120px 才是必须的那一截
                # (224×180 -> 224×300)。
                crop_rect = (hover_rect(rect, cur, region)
                             if mode == "hover" else rect)
                crop = self._grab(screen, crop_rect, what)
            if crop is not None:
                # **item 档先过内容签名**(和对话框 panel_sig 同一套二值化采样:
                # 面板深底让背景动不了签名):等的是"任务栏换了字" —— 变了当拍
                # 就读,没变最多 TRK_SIG_GAP 兜底一次。**只有上一次读到了字**
                # (`miss == 0`,面板显示着)才看签名:面板藏起来时裁的是生世界,
                # 亮像素一直在动,签名只会每拍都"变了"。
                # hover 档不吃这套:悬停那行在表框**上方**,裁剪又跟着鼠标走、
                # 签名不可比 —— 保持 HOVER_GAP 的定时读(玩家主动压上去,就几秒)。
                trk_changed = False
                if mode == "item" and st.miss == 0:
                    trk_sig = panel_sig(crop,
                                        (0, 0, crop.shape[1], crop.shape[0]))
                    trk_changed = (st.trk_psig is None
                                   or sig_diff(trk_sig,
                                               st.trk_psig) >= TRK_SIG_MIN)
                    st.trk_psig = trk_sig
                gap = st.trk_gap
                if force or again or trk_changed or now - st.trk_ts >= gap:
                    blocks, ms = self._read(ocr, crop, what)
                    st.trk_ts = now
                    if blocks is not None:
                        # 任务栏那行也可能是"去X(x,y)使用逐妖蛊虫"这种(用道具后
                        # 刷出来的新坐标)—— 它在 scan_bell_parts 里归到 dialog
                        # 那一类,只取 track 会把它整个丢掉。
                        # 鼠标停在任务栏上时**不做标题圈范围**:悬停行在标题上面,
                        # 而且标题常被读花("降双快通"/"降欢风衡"),一 scoped 就全丢。
                        # **只有 hover 档**需要松开范围:悬停行不属于「降妖伏魔」标题
                        # 下面那一段。item(逐妖蛊虫)档的坐标就写在任务栏里,照旧
                        # 圈范围 —— 否则鼠标一靠近任务栏,同面板别的任务的行也会被
                        # 当成这一轮的新坐标。
                        scoped = not (mode == "hover" and near)
                        d3, t3, _w = scan_bell_parts(blocks, scoped=scoped)
                        # 取 d3 or t3 是**必须**的:任务栏那行"去X(x,y)使用逐妖蛊虫"
                        # 在 scan_bell_parts 里归到 dialog 那一类,只取 t3 会把它丢掉。
                        # 但它在这里只当"任务栏报的值"(带"见过两次"复核),**不**算
                        # "对话框说的" —— 用户定的:对话框只认上面面板带那条主路。
                        got = d3 or t3
                        hist = st.trk_hist
                        hist.append(got)
                        del hist[:-TRK_HIST]
                        text = "".join((b.get("text") or "") for b in blocks)
                        hover = _hit(text, _RE_BELL_HOVER) is not None
                        # "见过两次才算数":**要报的这个值自己**得在最近几次读数里
                        # 出现过 ≥2 次。原来把 confirmed() 当布尔用、报的却是 got,
                        # 于是"历史里随便有个稳定值"就放行最新那次单发读花 ——
                        # 实测 23:59:07 连着 5 次都对、第 6 次读成 (118,28),当场报出去,
                        # 红点跟着在 (118,28)/(18,28)/(18,23) 之间跳了三下。
                        ok = confirmed(hist)
                        # 悬停那条(「在X(x,y)处」)是**巧智魔/怯弱妖**独有的:那行画在
                        # 标题上方、可能只闪一下,所以单次读数也敢认(2026-10-16 起
                        # **不再要求"鼠标在附近"** —— 那行会不会出现跟我们的光标没关系,
                        # 靠 `hover_rect` 固定往上留一截去覆盖它)。
                        # 逐妖蛊虫的坐标是任务栏直接写着的(「◆蛊虫发现妖魔在X(x,y)」),
                        # 不许走这条 —— 不然任务栏里一句"在X(x,y)处"样子的话就单次
                        # 报出去了(用户的规矩:只有巧智魔/怯弱妖才认悬停那条)。
                        if got and (
                                force or again or ok == got
                                or (mode == "hover"
                                    and hover and in_bounds(*got))):
                            # **新坐标先"换参数复读"确认一次**(用户定的 2026-10-16):
                            # 半透明面板 + 压缩让检测本身不稳,同一行换个 det 下限就能
                            # 差字(实测 `宝象 40，12）` 少了"1"和"国")。同一块裁剪用
                            # `TRK_RECHECK_LIMIT` 再读一次,两次解析出的 (图名,x,y)
                            # 一样才采信;不一样就不报(留着旧目标等下一拍)—— 只对
                            # **和当前目标不同的新值**做,而且**每个候选只复读一次**。
                            ok_re = True
                            if got != self._cycle.get(slot):
                                re_got = self._recheck(ocr, crop, what, scoped)
                                if re_got != got:
                                    ok_re = False
                                    self.app.log(
                                        f"[{TAG}]任务栏复读不一致: "
                                        f"{TRK_RECHECK_LIMIT} 下读作 "
                                        f"{_spot(re_got) if re_got else '没认到'}"
                                        ",先不更新")
                            # 不管复读一不一致,**这一次读数照记**(`trk_text`/`trk_last`
                            # 的语义是"最近一次读数",事后看日志/历史都对得上);
                            # 只有"报出去"这一步被复读挡住。
                            st.trk_text = got   # 本周期认下来的那条(开新周期清)
                            # trk_last 跨周期留着:开新周期时用它当"屏幕上那条旧行"
                            # (`trk_stale`),防游戏的刷新延迟把红点带回旧坐标。
                            st.trk_last = got
                            if ok_re:
                                track = got
                        # 这一轮读完,决定下一轮还读不读、读多勤
                        if not blocks:
                            # 任务栏整块没显示(实测约一半时间):**只记数 + 留一条
                            # 诊断日志,不动那个框**(用户定的 2026-10-16)。
                            # 空读不代表面板没了 —— 面板被游戏藏起来是正常的(战斗中/
                            # 切场景时它就不画),而且这三类任务要拿坐标时玩家本来就
                            # 得开着面板。
                            # 但**"正盯着等坐标"的两种档不许慢下来**:
                            #   item(逐妖蛊虫):等用道具后刷出来的第二个坐标 ——
                            #     0.5s 一直盯到"同一个坐标连读两次"才收手;
                            #   hover(巧智魔/怯弱妖):等鼠标压上去才冒出来的那行,
                            #     只闪一下,同样不能退避(用 HOVER_GAP)。
                            # 一退避就可能正好漏掉它刚出现的那一下 —— 而且这两种
                            # 一读不到字就退回慢节奏、而且**整段周期都不会再调回来**,
                            # 等于后面的等待全变慢了一倍。空读时签名也指望不上
                            # (裁的是生世界),所以这里一律用"盯着看"的节奏。
                            st.miss += 1
                            st.trk_gap = watch_gap(mode)
                            if st.miss >= TRK_MISS_MAX:
                                # 连着这么多次"一个字都没读到":写一条诊断日志就完,
                                # **不动那个框**(面板这会儿没显示而已)。计数归零,
                                # 免得每拍都写(它只是个"面板怎么老不开"的信号)。
                                st.miss = 0
                                self.app.log(
                                    f"[{TAG}]任务栏那块连着 {TRK_MISS_MAX} 次"
                                    "读不到字 —— 面板这会儿没显示(位置照旧留着,"
                                    "不作废)")
                        else:
                            st.miss = 0
                            if mode == "item":
                                # 下一拍的兜底节奏:读到**没确认的候选**就紧跟
                                # (TRK_ITEM_GAP,两遍一致要连读);否则慢兜底 ——
                                # 任务栏变化交给上面的内容签名盯着
                                st.trk_gap = (watch_gap(mode)
                                              if got and ok != got
                                              else TRK_SIG_GAP)
                                # 逐妖蛊虫:同一个坐标连读两次 = 新坐标到手,停。
                                # 两个条件得分开看:
                                #   ①值跟本周期目标不同 -> 这才是"任务栏换的新坐标";
                                #   ②值就是本周期目标、但**是任务栏报出去的** -> 已经
                                #     到手了,别再空转(不然用道具后这轮会一直 0.5s
                                #     盯着看)。
                                # **不能只看①**:任务栏开头写的就是对话框给的那条
                                # 坐标("去X(x,y)使用逐妖蛊虫"),拿它当"读到了"的话,
                                # 用道具之前就停了(踩过这个坑)。
                                if (len(hist) >= 2 and hist[-1]
                                        and hist[-1] == hist[-2]
                                        and (hist[-1] != self._cycle.get(slot)
                                             or st.trk_pub == hist[-1])):
                                    st.trk_mode = TrkMode.NONE
                                    self.app.log(f"[{TAG}]任务栏新坐标连着读到"
                                                 f"两次,盯完(这轮不再读任务栏)")
                            elif (mode == "hover" and got and hover
                                  and got != self._cycle.get(slot)):
                                # 巧智魔/怯弱妖的"第二坐标"= **悬停那行** + **跟对话框
                                # 给的坐标不一样**才收手(用户定的 2026-10-17)。两条
                                # 都是被真机日志逼出来的:
                                #   ① 命中的必须是**悬停那行**(`hover`) —— 任务栏里
                                #      别的坐标(比如"去X(x,y)"那种正文行)不算;
                                #   ② 还得**≠ 对话框给的坐标**(`got != _cycle[slot]`):
                                #      相等就不是"第二坐标",这一轮接着盯。
                                #      (`_publish` 在这之后才跑,所以这里 `_cycle` 还是
                                #       对话框那条 —— 拿它当"对话框坐标"是准的。)
                                st.trk_mode = TrkMode.NONE
                                self.app.log(f"[{TAG}]任务栏坐标读到了(悬停那行),盯完"
                                             "(这轮不再读任务栏)")
                        self._note(what, read_note(
                            what, (crop.shape[1], crop.shape[0]),
                            len(blocks), ms, got, blocks)
                            + (" 悬停" if near else "")
                            + edge_note(crop_rect, region), now, "识别 ")

        # 兜底:对话框那条主路认到了新目标、但当拍**没报成**(面板带那条路提前
        # return 掉了,或者值越界/跟上次一样被 `_publish` 挡了)—— 这儿再走一次
        # `_publish`(周期真换了的话,残留清理 + 定类型都在里面)。
        # **`again` 那一拍不走这条**(2026-10-16 检视定的):第二遍只负责**核对**,
        # 不报"没被确认过"的值。两次读得不一样时(第一遍读对、第二遍读花),这条兜底
        # 会把第二遍那个读花值当拍报出去 —— 单次读出就落红点,正是"两次相同放行"
        # 要挡的。这一拍什么都不报的话下一拍会拿 `dlg_text` 重新 pend + 重扫
        # (`not again` 那条),正确的值只晚 0.15s,不会丢。
        if (not again and dialog and dialog != self._cycle.get(slot)
                and self._publish(slot, dialog, "对话框")):
            return True

        # 一个杀怪周期 = 一次"对话框给出图+坐标"。周期内只有任务栏给出**新的
        # 图+坐标**才更新(逐妖蛊虫用道具后就是这种);任务栏只写地图、没坐标的
        # 一律不管 —— 不显示"坐标待定"那种半成品。
        return bool(track and track != self._cycle.get(slot)
                    and track != st.trk_stale
                    and self._publish(slot, track, "任务栏"))

    def _publish(self, slot, bell, src):
        """把这个目标摆上前台:更新周期锚 + 界面状态 + 日志。

        返回 True 表示"确实报了"(和上次一样就不再报 —— 同一只妖魔不重复刷)。
        """
        if not bell:
            return False
        if not in_bounds(*bell):
            # 六张图的坐标范围都在 bounds.json 里,妖魔不会在图外面 —— 落在外面的
            # 坐标一定是数字读花了。报了等于把红点画到错地方(用户的红线是"准"),
            # 所以宁可这轮不报:面板还开着的话下一轮重读会拿到对的。
            self.app.log(f"[{TAG}]{bell[0]} ({bell[1]},{bell[2]}) 不在这张图的"
                         "坐标范围内,当成数字读花,先不报")
            return False
        if bell != self._cycle.get(slot):
            self._cycle[slot] = bell
            if src == "对话框":
                # **对话框开新周期**(用户定的 2026-10-16),两件事都在这儿办:
                #
                # ① **任务类型由对话框这一拍的文字定**(`trk_plan`):item(逐妖蛊虫)
                #    / hover(巧智魔/怯弱妖) -> 之后要盯任务栏那块;其余(招魂帖/
                #    招魂幡/梦魇魔/迷幻妖,或压根没认出任务名)-> none,一次都不读。
                #    **任务栏那份文字永远不参与定类型**(它只负责"拿第二个坐标"),
                #    连"对话框认不出时拿它当备胎"都不许 —— 否则任务栏里挂着别的
                #    任务的行就会把类型带偏。
                # ② 任务栏那边的残留一并清掉:trk_hist/trk_pub/trk_text/dlg_pend
                #    (上一周期的读数历史、"报出去的那条"、本周期认下来的那条读数、
                #    待确认的改口值,全不许串过来)。
                #    trk_stale:屏幕上的旧行**清不掉**(游戏刷新有延迟),所以把它
                #    记下来 —— 这一整个周期都不拿它当"任务栏给的新目标"(否则红点
                #    会被那条旧行翻回上一轮的坐标)。取 `trk_last`(最后认下来的那
                #    条任务栏值,**跨周期留着**):拿 `trk_text` 的话,上一周期一次
                #    任务栏都没认下来时它就空了,旧行反而没人挡。
                #    每个周期都在这里重设一次,不跨周期泄漏。
                st_ = self._slot.setdefault(slot, SlotState())
                mode = trk_plan(st_.dlg_raw or "")
                st_.trk_mode = mode
                # item 平时慢兜底(变化由内容签名盯着),hover 保持 0.25s(裁剪
                # 跟着鼠标走,签名不可比,只能定时);none 一次都不读,纯显示值
                st_.trk_gap = (TRK_SIG_GAP if mode == "item"
                               else watch_gap(mode))
                st_.trk_stale = st_.trk_last
                st_.trk_hist = []
                st_.trk_pub = None
                st_.trk_text = None
                st_.dlg_pend = None
                self.app.log(f"[{TAG}]{CYCLE_LOG_MARK}:任务栏这轮{_plan_note(mode)}")
        if self._last.get(slot) == bell:
            return False
        self._last[slot] = bell
        if src == "任务栏":
            # 记下"这个周期里任务栏报出去的那条":逐妖蛊虫靠它判"新坐标已经到手,
            # 不用再盯了"(见 item 那段)。
            self._slot.setdefault(slot, SlotState()).trk_pub = bell
        self.spot = bell
        self.target = f"{bell[0]} ({bell[1]},{bell[2]})"
        self.app.log(f"[{TAG}]妖魔位置: {bell[0]} ({bell[1]},{bell[2]})"
                     f"[来自{src}]")
        return True

    def _heartbeat(self, now):
        """每 10 秒报一条:这段时间扫了几轮、OCR 几次、跳过几次。

        门控跳过的轮次不逐条写日志(会刷屏),这里给个总数 —— 看 OCR 次数
        比轮数少多少,就知道节流有没有在省。
        """
        if now - self._hb < 10.0:
            return
        if self._stat["rounds"] == 0:
            return
        self._hb = now
        s = self._stat
        bits = [f"{s['rounds']} 轮 / OCR {s['ocr']} 次 / 跳过 {s['skip']} 次"
                f" / 对话框 {s['dlg']} 轮 / 非铃铛对话 {s['dlg_other']} 次"
                f" / 话术门槛挡下 {s['dlg_gate']} 次"]
        for st in self._slot.values():
            samp = st.dlg_sample
            st.dlg_sample = None
            part, blocks, ms = samp or (None, None, None)
            if blocks is not None:
                bits.append("样本:" + read_note(
                    "对话框", (part.shape[1], part.shape[0]), len(blocks),
                    ms, None, blocks))
        for slot, s2 in sorted(self._slot.items()):
            bits.append(f"槽{slot}: 任务栏"
                        + ("有框" if s2.trk else "没量到框")
                        + f"/节奏{s2.trk_gap:.2f}s"
                        + ("/有坐标" if s2.trk_text else ""))
        # **只进文件**(用户定的 2026-10-17):心跳是"这 10 秒扫了几轮 /
        # 白烧了几次"的体检数字;要看就去 bell.log 里 grep
        # 「扫描心跳」(它自带那段时间的轮数/OCR 数/跳过数/样本)。
        self.app.log(f"[{TAG}]扫描心跳: " + " ".join(bits))
        s["rounds"] = s["ocr"] = s["skip"] = s["dlg"] = 0
        s["dlg_other"] = s["dlg_gate"] = 0

    def run(self):
        while not self._halt.is_set():
            if not self.enabled or self._screen() is None:
                self._wake.wait()
                self._wake.clear()
                continue
            t0 = time.time()
            try:
                self.tick()
            except Exception as e:
                self.app.log(f"[{TAG}]出错: {e}")
            time.sleep(max(0.0, self.interval() - (time.time() - t0)))
