"""降妖伏魔:一个完全独立的功能。

自己一条线程、自己的区域和状态。和科举没有来往 —— 不 import 它、不碰它的
任何东西。跟 core 只有一条单行道:调用时现取截图 / OCR / 窗口枚举这些基础
设施(这是唯一被允许的共享)。日志用 [铃铛],跟产品其他地方一致。
"""
import json
import os
import re
import sys
import threading
import time

TAG = "铃铛"
CYCLE_LOG_MARK = "对话框开新周期"    # 文件里的周期分界日志(**只进文件**,用户定的
# 2026-10-17:界面上不再刷它)。小窗日志区那套"交替换底色"改成认下面这条 ——
# "报出目标、而且来源是对话框"就是新周期开始(它跟这条分界日志同一刻写出)。
CYCLE_UI_MARK = "[来自对话框]"

# 数据目录的根:跟 core.BASE_DIR 同一套规则(打包后跟着可执行文件走)。
# 这里不能在模块级 import core —— core 要在模块级 import 本文件,反过来在
# 模块级取 core 的名字只会拿到一个还没加载完的 core。
if getattr(sys, "frozen", False):          # PyInstaller 打包后
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# 降妖伏魔(铃铛):任务提示里的"地图名+坐标"。
#
# **六种怪各说各的,别把一种的文案套到另一种上**(用户给的截图实证)。
# **每只怪的对话框都有自己的一句**,别偷懒写"同 XX" —— 2026-10-16 用户专门纠正过
# 怯弱妖那条(它和巧智魔/梦魇魔**都不是**同一句,只是结构一样):
#
#   | 怪     | 对话框(原文,坐标处用 X(x,y) 代替)                        | 任务栏                                                    | 玩法 |
#   | ------ | --------------------------------------------------------- | --------------------------------------------------------- | ---- |
#   | 招魂幡 | 看看你包里的新物品"招魂帖",把它贴在指定位置,可以使得妖魔来自投罗网。去X(x,y)使用招魂帖,然后妖魔就会到来。 | 去X(x,y)使用"招魂帖",等待被诱惑的妖魔上钩并降服它。剩余时间2小时。 | 到点用招魂帖 |
#   | 逐妖蛊虫| 有的妖魔行迹隐秘。…去X(x,y)使用蛊虫,然后跟着它,它会找到妖魔的。 | ①◆去X(x,y)使用"逐妖蛊虫",然后跟着地上的蛊虫找到妖魔。(**坐标跟对话框同值**) ②用道具后换成 ◆蛊虫发现妖魔在X(x,y),快去降服他吧。 | 到点用道具,**任务栏换一条新的坐标** |
#   | 梦魇魔 | 这个妖魔值得一战,…我发现它的踪迹在X(x,y),少侠们准备好了就过去看看吧。 | 去X找梦魇魔。剩余时间2小时。 | 直接杀 |
#   | 迷幻妖 | 接下来你们遇到的将是一只狡猾的迷幻妖。想要抓住它,可不容易。我发现它的踪迹在X(x,y),少侠们速度赶过去看看吧。 | 去X找迷幻妖。(只有图)                                      | 点怪会被传送走,回原点再点一次 |
#   | 巧智魔 | 又一个！这次是一只精巧的巧智魔。它足智多谋而且狡猾无比。我发现它的踪迹在X(x,y),少侠们准备好了就过去看看吧。 | 去X找巧智魔。(只有图);杀完换新图**也没坐标**                | 鼠标停任务栏才临时显示"在X(x,y)处" |
#   | 怯弱妖 | 我们要对付一只新的妖魔了,它是一只胆小而怯弱的怯弱妖,不过却是身形矫健,敏捷快速。估计,要被他耍好几次了。我发现它的踪迹在X(x,y),少侠们速度赶过去看看吧。 | 去X找怯弱妖。(只有图);怪会跑,新图也没坐标                   | 同上(鼠标悬停任务栏,才显示"在X(x,y)处") |
#
# 归纳成四种写法(代码只认这四种,不认怪名):
#   对话框/招魂帖类:「去X(x,y)使用…」            → `_RE_BELL_USE` / `_RE_BELL_ANY`
#   对话框/踪迹类  :「…我发现它的踪迹在X(x,y)…」  → `_RE_BELL_DIALOG`
#   任务栏         :「◆蛊虫发现妖魔在X(x,y)…」    → `_RE_BELL_TRACK`
#   悬停(巧智魔/怯弱妖):「在X(x,y)处」           → `_RE_BELL_HOVER`
# 四种都要求"地图名 + 坐标"**同时**出现,而且**地图名必须是这六张之一**(用户确认
# 铃铛只去这六张图):别的任务/聊天里的"某某地(12,34)"不能被当成妖魔位置。
# 另有两条**没有虚词锚点**的兜底(`_RE_BELL_KNOWN` / `_RE_BELL_ANY`),只在读**红框
# 那一小块**时用(图名读花靠它兜);读**大字面/整窗**那一拍一律不用 —— 见下面的
# `_RE_BELL_ANY_ANCHORED` 与 `scan_bell_parts(..., wide=True)`。
BELL_MAPS = ("长寿村", "傲来国", "朱紫国", "建邺城",
             "西梁女国", "西凉女国", "宝象国")
# 官方名(没有"西凉"这个别名):采集底图/写标定都按这个列表来
BELL_MAP_NAMES = ("长寿村", "傲来国", "朱紫国", "建邺城",
                  "西梁女国", "宝象国")
_MAP_NAME = r"([\u4e00-\u9fa5]{2,6})"        # 地图名:2~6 个汉字
# 坐标:括号里那两个数。真机上 OCR 经常把分隔符认错 —— 实测见过
# "（93.31）"(逗号读成句点)、"（69101）"(逗号整个丢了)、全角括号+空格。
# 所以:分隔符放开(句点/顿号/空格/冒号/连字符都算),分隔符**丢了**的
# 连写数字(69101)也接住 —— 但要用坐标范围反推唯一一种切法,不然不猜。
_COORD_SEP = r"[,，.。·、:：;；\-–—/\\\s]"
_COORD = (r"[^()（）\d]{0,4}[（(]?\s*"
          r"(?:(?P<cx>\d{1,3})\s*" + _COORD_SEP + r"{1,3}\s*(?P<cy>\d{1,3})"
          r"|(?P<crun>\d{4,7}))"
          r"\s*[)）]")
# 对话框说的(最权威):「…我发现它的踪迹在朱紫国(144,99),少侠们速度赶过去看看吧。」
_RE_BELL_DIALOG = re.compile(r"踪迹在" + _MAP_NAME + _COORD)
# 任务栏 / 鼠标悬停说的:「◆蛊虫发现妖魔在宝象国(99,54)…」「在建邺城(15,122)处」
_RE_BELL_TRACK = re.compile(
    r"(?<!踪迹)(?:妖魔在|发现在|出现在|在)" + _MAP_NAME + _COORD)
# 招魂幡/逐妖蛊虫那种"没锚点"的写法:「去建邺城(101,127)」。`(?:去|到)?` 是可选的,
# 所以**光秃秃的「长寿村(50,60)」也进得来** —— 读红框那一小块时靠它兜住 OCR 把
# 图名读花的情况(实测"建邮城"/"宝国");但读**大字面**(整窗)时要把这个口子收掉,
# 见下面的 `_RE_BELL_ANY_ANCHORED`。
_RE_BELL_ANY = re.compile(r"(?:去|到)?" + _MAP_NAME + _COORD)
# 同上,但**必须**带"去/到"锚点:大字面那一拍(`scan_bell_parts(..., wide=True)`)
# 只认这条。原因:`_RE_BELL_KNOWN` 和 `_RE_BELL_ANY` 都是"没有虚词也能认",而整窗里
# 混着聊天/别的任务的行 —— 别人聊天打一句「长寿村(50,60)」就会被兜底认成**对话框
# 说的**(`scan_bell_parts` 最后那条兜底归 dialog),而对话框是**立刻报**的,红点当场
# 就飞了。带上"去/到"之后,聊天里要凑出这个词才算数(老写法「去建邺城(101,127)」
# 照旧保留)。
_RE_BELL_ANY_ANCHORED = re.compile(r"(?:去|到)" + _MAP_NAME + _COORD)
# 招魂幡/逐妖蛊虫那种"用道具"的写法:「去建邺城(101,127)使用招魂帖…」
# (靠后面的"使用"和别的任务的「去X(x,y)找Y」区分开)
_RE_BELL_USE = re.compile(r"(?:去|到)" + _MAP_NAME + _COORD + r"使用")
# 鼠标停在任务栏上才冒出来的悬停行:「在建邺城(15,122)处」—— 巧智魔/怯弱妖的
# 第二个坐标就长这样,而且可能只闪一下(见 cursor_pos / HOVER_GROW / HOVER_LIFT)
_RE_BELL_HOVER = re.compile(r"在" + _MAP_NAME + _COORD + r"处")
# 没锚点、但地图名是我们认识的六张:直接「<地图名>(x,y)」也认(老写法兜底)
_RE_BELL_KNOWN = re.compile(
    r"(" + "|".join(BELL_MAPS) + r")" + _COORD)
# OCR 认错地图名很常见(实测"建邺城"读成"建邮城"),常见错法归一到官方名
_BELL_CANON = {
    "长寿": "长寿村", "常寿": "长寿村", "长寿郊外": "长寿村",
    "傲来": "傲来国", "敖来": "傲来国", "傲莱": "傲来国",
    "朱紫": "朱紫国", "珠紫": "朱紫国", "朱柴": "朱紫国",
    "建邺": "建邺城", "建业": "建邺城", "建邮": "建邺城", "建邦": "建邺城",
    "西梁": "西梁女国", "西凉": "西梁女国", "西粱": "西梁女国",
    "宝象": "宝象国", "宝像": "宝象国",
}


def canon_map(name: str) -> str:
    """把 OCR 认出来的地图名归一到官方写法(认不出就原样返回)。

    归一表按前缀匹配:"建邮城" 命中 "建邮" -> "建邺城"。
    """
    name = (name or "").strip()
    for wrong in sorted(_BELL_CANON, key=len, reverse=True):
        if name.startswith(wrong) or name == wrong:
            return _BELL_CANON[wrong]
    return name


def known_map(name: str):
    """图名(已归一)是不是铃铛会去的那六张之一;不是返回 None。

    铃铛只会把人送去这六张图,所以"认不出来"一律当没认到 —— 不然任务追踪/聊天里
    随便一句"某某地(12,34)"都会被当成妖魔位置。

    前两条是正常匹配;最后那条兜的是**真机上地图名被读花**的情况:实测
    "宝象国"被读成"宝国"(两个字被并成一个)、"建邺城"读成"建邮城"。判据是
    "跟某张图**对得上至少两个字**,而且只对得上这一张"。所以"长安"(跟"长寿村"
    只共一个"长")不会放行 —— 那是别的任务里的地名,不能当真。
    """
    n = canon_map(name)
    for m in BELL_MAP_NAMES:
        if n == m or n.startswith(m) or (len(n) >= 2 and m.startswith(n)):
            return m
    hits = [m for m in BELL_MAP_NAMES if len(set(n) & set(m)) >= 2]
    return hits[0] if len(hits) == 1 else None


def in_bounds(name, x, y):
    """这个坐标落在这张图的坐标范围里吗(没范围就放行)。

    鼠标悬停那条路"只读到一次也认",所以多一道最便宜的检查:范围对不上
    多半是数字读花了,宁可先不认。
    """
    try:
        minx, miny, maxx, maxy = [float(v)
                                  for v in load_map_bounds().get(name)]
    except Exception:
        return True
    return minx <= x <= maxx and miny <= y <= maxy


def _split_run(run, name):
    """OCR 把分隔符整个吃掉时("69101")按坐标范围反推切法。

    只有**唯一一种**切法落在这张图的范围内才算数 —— 切不开就当没认到,不猜。
    """
    bounds = load_map_bounds().get(name)
    if not bounds or not run or len(run) < 4:
        return None
    try:
        minx, miny, maxx, maxy = [float(v) for v in bounds]
    except Exception:
        return None
    got = []
    for i in range(1, min(4, len(run))):
        x, y = int(run[:i]), int(run[i:])
        if minx <= x <= maxx and miny <= y <= maxy:
            got.append((x, y))
    return got[0] if len(got) == 1 else None


def _coord_of(m, name):
    """从匹配里取出 (x, y)。"""
    if m.group("cx"):
        return int(m.group("cx")), int(m.group("cy"))
    return _split_run(m.group("crun"), name)


def _hit(text, pat):
    """在这段文字里找第一处"地图名 + 坐标"。

    匹配上了但**校验不过**(图名不是那六张 / 坐标取不出来)时,不是跳到这次匹配的
    末尾接着找,而是**往回退一个字**(`m.start() + 1`)重试 —— 贪心组会把开头那几个
    字也当成图名、连坐标一起吃掉,`finditer` 不回头,真正能认的那一处就被吞了。
    实测(同一句话只差前面几个字):
      `长寿付（38.1）使用 妖贵虫`             -> 认得出
      `降妖伏魔 长寿付（38.1）使用 妖贵虫`    -> 原来认不出(通配组把"降妖伏魔"当图名)
      `1070敏任务追踪魔来国（101，14）使妖`    -> 原来认不出(真正能认的"来国（101，14）"被吞)
    校验逻辑一个字没动(`known_map` / `_coord_of`,调用方的 `in_bounds`、"见过两次"
    也照旧),所以不会多出误报;第一处就命中的情况结果不变。
    """
    pos = 0
    while pos <= len(text):
        m = pat.search(text, pos)
        if not m:
            return None
        name = known_map(m.group(1))
        if name:
            got = _coord_of(m, name)
            if got:
                return (name, got[0], got[1])
        pos = m.start() + 1
    return None


_BELL_TITLE = "降妖伏魔"          # 任务追踪里,本任务的标题
_BELL_TITLE_SPAN = (80, 140)      # 标题上 80 / 下 140 像素内才算本任务的说明

# ---- 扫描范围与"便宜的门控":先花 1~2ms 判断要不要 OCR,再决定花那 200ms ----
# 游戏把对话框贴在窗口下方居中(底边≈0.85H,字越多越往上长),位置基本固定;
# 面板"暗且不彩"的像素占比远高于它身后那个一直在动的游戏世界 —— 实测 15 张真
# 截图(有面板 0.89~0.95 / 没面板 0.35~0.43),用这个当"有没有对话框"的判据,
# 1ms 出结果,不花 OCR 的钱。
DIALOG_BAND = (0.08, 0.34, 0.96, 0.90)   # 对话框可能出现的那块(占客户端窗口比)
DIALOG_PAD = 8                           # 按面板框裁字时往外留几个像素
# 对话框的字挤在面板**上半部分**(实测 2~3 行都在顶上):只读那一截就够,
# 面板下面大半是空的 —— 每次省三成时间,报点也更快。
DIALOG_TEXT_FRAC = 0.62
DIALOG_TEXT_MINH = 170
DIALOG_DARK, DIALOG_SAT = 105, 70        # "暗且不彩"的上限
DIALOG_DARK_FRAC = 0.60                  # 一行/一列里暗像素占比超过它才算面板
# 框**里面**的暗比:真对话框 0.82~0.94(实测 13 张图),而"夜里整条带子都暗"
# 那种假框只有 0.6~0.7 —— 真机日志里它每轮都骗我们去 OCR(读到的是客户端页签名),
# 一秒两三次,既慢又白烧显卡。
PANEL_MIN_DARK = 0.78
# **结构关**(2026-10-16 用户实测:进场打怪时战斗画面被当成面板,OCR 读回来的
# 是 冷昕T/血条 这些)。战斗画面同样能"一整块暗"(框内暗比实测 0.91),暗比
# 挡不住;但对话框是**文字行**——亮/彩像素只挤在少数几行里,战斗画面的人/怪/
# 血条摊满所有行(两张真图实测:对话框"有内容的行"占 0.23,战斗画面 0.77)。
DIALOG_BRIGHT = 130                      # "亮"的下限(文字笔画和血条都过它)
BUSY_ROW_FRAC = 0.08                     # 一行里"亮|彩"占比到这么多算"有内容"
PANEL_MAX_BUSY = 0.50                    # 有内容的行超过这个占比就不是面板
DIALOG_MIN_H = 200                       # 面板至少这么高(真对话框实测 244~405)
DIALOG_GAP = 2.0                         # 面板内容没变时,这么久兜底重读一次
SIG_MIN = 10.0                           # 面板内容签名差多少算"这页换了"
PEND_TTL = 10.0                          # 待确认的对话框值最多挂这么久(面板消失/读不到
# 持续超过它就作废)—— 2026-10-17:重扫撞上面板暗比 0.59(阈值 0.60)被判"消失",
# 一拍没读到就把新坐标扔了,红点一直不刷新 ✗
TRK_MARGIN = 18                          # 学到的任务栏框往外留的余量
PANEL_W, PANEL_H = 330, 180              # 任务栏围着标题那个框的大小(像素)
# 学到的框**四周再留一层安全边距**(防切字,跑一轮可调):真机丢字的第一个来源是
# 框的**左边界切进表头文字**(实测「任务追踪」被读成 `务追踪`、「任追踪」)—— 框是
# 拿表头块的 (x1,y1) 减 TRK_MARGIN 定的,左边天然切字;右边也常切掉行尾(坐标所在)。
# 顺序 = (左, 上, 右, 下)。右/下给得大一点:坐标在行尾/最下面那行。
TRK_PAD = (24, 18, 40, 18)
# 注:原来这里有个 TRK_DEFAULT(按窗口比例猜任务栏在哪)。**已经删掉** ——
# 任务栏在游戏里能随便拖,猜出来的位置没有依据(用户定的规矩:只有逐妖蛊虫/
# 巧智魔/怯弱妖这3类任务才关心任务栏;还没有红框时**扫整窗去找**表头,
# 找到之后只扫红框;其余类型压根不碰)。
# 悬停行("在建邺城(15,122)处")出现在「降妖伏魔」标题**上方** —— 那一截由
# `HOVER_LIFT` 在裁剪时往上留(见 hover_rect),这里的 HOVER_GROW 只管
# "鼠标算不算在任务栏附近"(触发器要大一圈)。
HOVER_GROW = 90                          # 鼠标"在任务栏附近"的放宽量(触发器要大一圈)
HOVER_LIFT = 120                         # 悬停那行要往上多留一截才圈得住
# ---- 任务栏读不读、读多勤:按**任务类型**决定(用户定的规矩) ----
#   逐妖蛊虫:用道具后任务栏会换一条新坐标 -> 0.5 秒盯,直到**同一个值连读两次**
#             (确认到手)就停;
#   巧智魔/怯弱妖:第二个坐标只在鼠标悬停时才出现 -> 0.25 秒盯,读到坐标就停;
#   其余(招魂帖/招魂幡/梦魇魔/迷幻妖):坐标对话框里就有 -> **一次都不读**。
# 类型**只由对话框给**(见 `_publish` / `trk_plan`),不用用户配置。
TRK_ITEM_GAP = 0.5                       # 逐妖蛊虫盯着第二个坐标的节奏(用户定的 0.5)
TRK_WATCH_GAP = 0.25                     # 盯着看时的节奏(悬停那行 / 整窗找框第一档)
TRK_GAP = 0.6                            # 其余档的节奏
TRK_GAP_IDLE = 1.0                       # 任务栏没显示时(重试)的节奏
# 还没学到任务栏框时"整窗找表头"的节流档位:连着这么多次**整窗也没学到框**,节奏
# 就往后挪一档(0.25 → 0.5 → 1.0 → 2.0,封顶 2.0),一旦学到框立刻回到第一档。
# 真机上踩到过:region 稍微不含任务栏、或者表头一时读不出来,就会"连着十几二十次
# 整窗扫"(每次 ~300~470ms,实测一趟 19 次)—— 越找不到越要慢下来。
HUNT_GAPS = (TRK_WATCH_GAP, 0.5, 1.0, 2.0, 4.0, 8.0)
# 连着这么多次整窗都没学到框 -> **歇一会儿再试**(用户 2026-10-17 报"卡死"后定的):
# 每次整窗 OCR 在真机上 2~3 秒(89 个文字块),面板被别的界面藏住时重锚**必然失败**,
# 2 秒一次的阶梯等于每 4 秒烧 2.5 秒 GPU —— 表现出来就是窗口卡住。真被拖走时整窗
# 一次就学到了,所以这个冷却只会在"面板根本没画"时触发。
HUNT_PAUSE_AFTER = 3
HUNT_PAUSE = 15.0          # 2026-10-17 从 30 收到 15:面板回来时别白等半分钟
TYPE_ITEM = "逐妖蛊虫"                     # 任务栏会刷新新坐标的那种
TYPE_HOVER = ("巧智魔", "怯弱妖")           # 第二个坐标要悬停才出现的那种
# **话术门槛**(用户定的 2026-10-16):对话框那一拍读到的**整段文字**里必须含一个
# "铃铛任务的核心词",才认那段里的"图名+坐标"。挡的是这条真实路径:面板收紧失败时
# (`box = 整块`)会把下方的聊天/世界频道一起读进来 —— 聊天里一句
# 「去长寿村(50,60)集合,别乱跑」正好长成"图名+坐标",而且它是**静态行**:
# "两遍一致"对静态内容必然一致,挡不住它。
# 用"或"、而且都挑短的:OCR 丢一两个字还剩别的词能命中(整句模板一丢字整条就废)。
# **任务栏那一支不吃这道门槛**:它已经有 wide 规则 + 见过两次;更要紧的是悬停那行
# (`在建邺城(15,122)处`)单独读出来时一个核心词都没有,加了会把 hover 档废掉。
BELL_WORDS = ("使用", "踪迹在", "招魂", "蛊虫", "妖魔",
              "梦魇魔", "迷幻妖", "巧智魔", "怯弱妖")
HOVER_GAP = 0.25                         # 鼠标停任务栏上时的节奏(悬停行可能只闪一下)
# ---- hover 档的"收手话术"(用户给的 4 张对话框截图,2026-10-16) ----
# 怯弱妖:
#   1. 三番两次，我都被你累断气了。你怎么这么执着啊。跑不动了。
#      (红字)终于逮到你了，看打。 / 我也跑累了，等下…
#   2. 打就打，我……我，我……你怎么不怕我。
# 巧智魔:
#   3. 金蝉脱壳可是我的拿手好戏，刚试过了，拿我没办法吧。
#      (红字)也就是个会跑的小妖魔，看我再来收服…等我准备好了再来。
#   4. 你再抓，我再跑；你再抓，我再跑呀……嘻嘻。
# 含义:这两个怪的任务里"第二个坐标"是靠鼠标悬停那行喂进来的;出现这些话术说明
# 追/逃那一段结束了 -> 这个周期**没必要再扫任务栏**。判据**只取短而有辨识度的
# 核心词**:整句太长,OCR 读花时对不上(实测逗号/省略号经常读成别的,所以还留了
# 不带标点的 `我再跑` 兜底);这两个怪都走 hover,话术不会串到别的类型上,所以
# **不必按怪分**,命中任意一条即收手。
# **2026-10-16 用户调整过词表**:去掉 `金蝉脱壳`(它不再触发收手),加上
# `拿手好戏` / `刚试过了`(巧智魔)和 `三番两次` / `累短气` / `打就打`(怯弱妖)。
# **2026-10-17 又去掉 `拿手好戏`**(用户定的:那句「金蝉脱壳可是我的拿手好戏」
# 不再触发收手,巧智魔这边只留 `刚试过了`)。
# `累短气` 是用户给的写法;**`累断气` 也留着** —— 截图原文是"我都被你累断气了",
# 断/短 两个方向都可能被 OCR 读花,留两个都认。
HOVER_STOP_WORDS = ("逮到你了", "跑不动了", "你怎么不怕我",
                    "三番两次", "累短气", "累断气", "打就打",
                    "刚试过了", "你再抓，我再跑", "我再跑")
TRK_HIST = 6                             # 留最近几次任务栏读数(判"认准了没有")
TRK_CONFIRM = 2                          # 同一个值要见过这么多次才认(治误读)
# 连着这么多次"一个字都没读到"就写一条诊断日志(**只记数、不作废框、不整窗**;
# 用户定的 2026-10-16:面板被游戏藏起来是正常的 —— 实测约一半读数是 0 块,而且
# 这三类任务要拿坐标时玩家本来就得开着面板;作废+重锚一次要耗 8×0.25s ≈ 2 秒,
# 过不了"快"这条红线)。
TRK_MISS_MAX = 8
# 连着这么多次"读到了字、却没有「任务追踪」表头"就认定任务栏被拖走了(用户定的
# 2026-10-16,2026-10-17 由 2 放宽到 4):框是"位置记忆",拖走之后它一直指着旧地方
# (读回来的是身后的场景文字)。这是**唯一**的作废判据。**只认"读到了字"**:一个字都
# 没读到是"面板被藏起来了"(约占一半时间,那是正常的)。
# 放宽的理由有实测:00:39 那次"面板被战斗藏起来"时,框里读到的是战斗 UI 的字
# («大认黄»/«0 法术»),连着 2 拍就被当成"被拖走"→ 作废 → 接着 12 秒里整窗扫了 7 次
# (约 3.2 秒白烧),而面板回来时的位置只差 3px(就是同一个地方)。放宽到 4 之后这种
# 一闪而过的藏面板不会再误作废;代价是真被拖走时晚 2 拍(0.5~1 秒)才发现。
TRK_NOHDR_MAX = 4
LOG_GAP = 10.0                           # 同一类过程日志没变化时最多这么久写一条
BELL_MIN_INTERVAL = 0.15                 # 铃铛自己的扫描下限(比科举快一档)
OCR_LIMIT = 480                          # 只扫小块时的 det 输入下限(默认 736 太贵)
# 新坐标"换参数复读"用的 det 下限(用户定的 2026-10-16):半透明面板 + 压缩让检测
# 本身不稳,同一行换个参数就能差字(实测 `宝象 40，12）` 少了"1"和"国")。同一块裁剪
# 用这个下限再读一次,两次 (图名,x,y) 一样才采信(见 `BellTool._recheck`)。
TRK_RECHECK_LIMIT = 320


def client_name(title):
    """从客户端窗口标题里抠角色名:「… - (湖北2区[黄鹤楼] - 祭花′[29024311])」-> 祭花′。

    降妖伏魔只管**一台**客户端,多开时要让用户按角色名选,所以要能从标题里
    读出一个认得出来的名字。
    """
    tail = (title or "").split(" - ")[-1]
    return tail.split("[")[0].strip("() （）").strip()


def client_choices():
    """枚举到的客户端 -> [(角色名, 标题, 矩形)];界面拿去弹列表让用户选。"""
    import core
    out = []
    try:
        found, _mini = core.find_client_windows()
    except Exception:
        return out
    for title, box in found:
        out.append((client_name(title) or title, title,
                    [int(v) for v in box]))
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


def fit_rect(region, rect):
    """把 rect 整体挪进 region(**宽高不变**),挪了返回新矩形、没挪返回原矩形。

    给"学到的任务栏框"用:框可能是窗口**还大**的时候学的,后来 region 变小
    (窗口改尺寸/换客户端),直接用就有一截落在 region 外面 —— 截图在那个边界就切掉,
    行尾的坐标就没了(实测 `宝象 40，12）`(少"1"和"国")、`去长寿村找怯弱。`(少"妖")。
    优先保住**右边/下边**(坐标在行尾、在下面那行),所以是整块左移/上移。
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
    """**临时**统计(量完可以删):裁剪宽度 + 左右有没有贴扫描区边(贴边=可能在切字)。

    真机丢字的两个来源:框左边切进表头(`务追踪`)、框右边被 region 截断(行尾的坐标
    没了)。这行就是量"这一拍到底裁了多宽、有没有贴边"。
    """
    w = int(rect[2]) - int(rect[0])
    bits = [n for n, hit in (("左贴边", int(rect[0]) <= int(region[0])),
                             ("右贴边", int(rect[2]) >= int(region[2])))
            if hit]
    return f" [宽{w}/{'、'.join(bits) if bits else '没贴边'}]"


def panel_text_cut(crop, box):
    """面板里"真有字"的那一截:上半部分(留够 2~5 行的余量)。

    读整个面板的话,下面大半是空的 —— 白花的像素。裁到文字带之后每次 OCR
    省三成时间,而且面板一出现就能更快报点。
    """
    keep = max(DIALOG_TEXT_MINH, int((box[3] - box[1]) * DIALOG_TEXT_FRAC))
    return _cut(crop, (box[0], box[1], box[2], min(box[3], box[1] + keep)))


def _cut(arr, box, pad=DIALOG_PAD):
    """按 (x0,y0,x1,y1) 裁一块,往外留 pad,裁到画面里。"""
    h, w = arr.shape[:2]
    x0 = max(0, int(box[0]) - pad)
    y0 = max(0, int(box[1]) - pad)
    x1 = min(w, int(box[2]) + pad)
    y1 = min(h, int(box[3]) + pad)
    return arr[y0:y1, x0:x1]


def panel_frac(rgb):
    """这块画面里"暗且不彩"的像素占比(对话框那种半透明黑面板很高)。"""
    import numpy as np
    a = np.asarray(rgb)
    if a.ndim != 3 or a.shape[2] < 3 or not a.size:
        return 0.0
    a = a.astype(np.int16)
    mx = a.max(axis=2)
    return float(((mx < DIALOG_DARK)
                  & ((mx - a.min(axis=2)) < DIALOG_SAT)).mean())


def panel_box(rgb):
    """对话框那块深色面板在画面里的外接框(相对这块画面);没有返回 None。

    面板是"暗且不彩"的一整块:先在 1/4 缩略图上按**行**找"这一行里暗像素占比
    够高"的范围,再在这个范围里按**列**找。比只看整块占比多给一样东西 ——
    面板**在哪**:于是 OCR 只喂面板那一块,既不带身后一直在动的游戏世界,也不带
    上方任务栏那两行(它也会带坐标,混进来会被当成"对话框说的")。
    """
    import numpy as np
    a = np.asarray(rgb)
    if a.ndim != 3 or a.shape[2] < 3 or not a.size:
        return None
    h, w = a.shape[:2]
    small = a[::4, ::4].astype(np.int16)
    mx = small.max(axis=2)
    mn = small.min(axis=2)
    dark = (mx < DIALOG_DARK) & ((mx - mn) < DIALOG_SAT)
    rows = np.nonzero(dark.mean(axis=1) >= DIALOG_DARK_FRAC)[0]
    if not rows.size:
        return None
    y0, y1 = int(rows[0]), int(rows[-1]) + 1
    cols = np.nonzero(dark[y0:y1].mean(axis=0) >= DIALOG_DARK_FRAC)[0]
    if not cols.size:
        return None
    box = (int(cols[0]) * 4, y0 * 4,
           min(w, (int(cols[-1]) + 1) * 4), min(h, y1 * 4))
    # 面板是一条**横贯窗口的大横条**(实测真对话框 868~902 x 244~405):
    # 只够半屏宽的多半是游戏世界里的一坨暗色建筑(实测误报 0.27~0.36W),
    # 太矮的(实测误报 800x50~150)是地图窗边框/UI 黑条之类 —— 两条都卡住。
    if box[2] - box[0] < 0.6 * w or box[3] - box[1] < DIALOG_MIN_H:
        return None
    # 最后三关:①整条带子大部分是暗的(真对话框盖住条带 0.61~0.95;游戏世界里
    # 凑巧"又宽又高"的暗块只有 0.29~0.58);②**框里面**得更暗(真对话框 0.82~0.94,
    # "夜里整条带子都暗"的假框 0.6~0.7);③**结构**:框里的亮/彩像素得挤在少数
    # 几行(那是文字),摊满所有行的是战斗画面的人/怪/血条(见 PANEL_MAX_BUSY 处
    # 的注释,两张真图实测 0.23 对 0.77)。
    if panel_frac(a) < DIALOG_DARK_FRAC:
        return None
    if panel_frac(a[box[1]:box[3], box[0]:box[2]]) < PANEL_MIN_DARK:
        return None
    content = ((mx[y0:y1, int(cols[0]):int(cols[-1]) + 1] >= DIALOG_BRIGHT)
               | ((mx[y0:y1, int(cols[0]):int(cols[-1]) + 1]
                   - mn[y0:y1, int(cols[0]):int(cols[-1]) + 1]) >= DIALOG_SAT))
    busy = (content.mean(axis=1) >= BUSY_ROW_FRAC).mean()
    if busy >= PANEL_MAX_BUSY:
        return None
    return box


def has_panel(rgb):
    """这块画面里有没有对话框那种深色面板。"""
    return panel_box(rgb) is not None


def trk_plan(text):
    """这段文字说的任务,任务栏要不要盯、为什么盯(用户定的规矩)。

    返回 "item"(逐妖蛊虫:盯到同一个坐标连读两次)/ "hover"(巧智魔/怯弱妖:
    盯到读出坐标)/ "none"(其余:对话框里就有坐标,一次都不用读)。

    **只拿对话框的文字喂它**(用户定的 2026-10-16):类型由对话框开新周期那一刻
    定下,任务栏那份文字永远不参与定类型(连"对话框认不出时拿它当备胎"都不许)。
    注意**招魂帖/招魂幡 → none**:只有逐妖蛊虫才需要第二个坐标(招魂帖是招魂幡
    用的道具,别把"用道具"当成"阿要盯任务栏")。
    """
    t = text or ""
    if TYPE_ITEM in t or "蛊虫" in t:      # 用道具后刷新出来的那行写的是"蛊虫…"
        return "item"
    if any(n in t for n in TYPE_HOVER):
        return "hover"
    return "none"


def watch_gap(mode):
    """这一档"盯着看"的节奏:逐妖蛊虫 0.5s、巧智魔/怯弱妖 0.25s(悬停行只闪一下)。"""
    return {"item": TRK_ITEM_GAP, "hover": HOVER_GAP}.get(mode, TRK_GAP)


def _plan_note(mode):
    """日志里那句"这轮任务栏怎么用"。"""
    return {"item": "要盯新坐标(逐妖蛊虫,连读两次就停)",
            "hover": "要盯悬停坐标(巧智魔/怯弱妖,读到就停)",
            "none": "一次都不读(对话框里就有坐标,或没认出任务名)",
            }.get(mode, mode)


def hover_stop(text):
    """对话框这段文字里有没有 hover 档的"收手话术";命中就返回那个核心词,没有返回 ""。

    表见 `HOVER_STOP_WORDS`(4 张截图的原文也在那儿)。这**只**给 hover 档用:命中说明
    追/逃那一段结束了,这个周期不再扫任务栏(调用点见 `_scan` 的对话框那一拍)。
    几处都命中时返回表里靠前的那个 —— 日志里报哪个都一样,反正都要收手。
    """
    t = text or ""
    for w in HOVER_STOP_WORDS:
        if w in t:
            return w
    return ""


def has_bell_words(text):
    """这段文字里有没有"铃铛任务的核心词"(话术门槛,表见 `BELL_WORDS`)。

    只给**对话框那条主路**用:读到的整段文字里一个核心词都没有,那这段里的"图名+坐标"
    就当读花、不认(聊天/世界频道那种静态行就是这么被挡下的)。任务栏那一支不吃它 ——
    悬停那行单独读出来时没有核心词,吃了会把 hover 档废掉。
    """
    t = text or ""
    return any(w in t for w in BELL_WORDS)


# 界面日志里要显示"这是哪种怪" —— 文案里认得出的写法 -> 显示名。招魂帖是**招魂幡**
# 用的道具,它的对话框里就写着"招魂帖"(用户那张表就是这么对的)。
BELL_KIND_WORDS = (("招魂帖", "招魂幡"), ("招魂幡", "招魂幡"),
                   ("逐妖蛊虫", "逐妖蛊虫"), ("蛊虫", "逐妖蛊虫"),
                   ("梦魇魔", "梦魇魔"), ("迷幻妖", "迷幻妖"),
                   ("巧智魔", "巧智魔"), ("怯弱妖", "怯弱妖"))


def bell_kind(text):
    """这段文字里点的是哪种怪(只给**界面日志**用);认不出返回 ""。

    **只认名字,不猜**:梦魇魔的对话框里压根没有"梦魇魔"三个字(那条只在任务栏),
    所以它这里认不出来 —— 界面就只显示"对话框 朱紫国(127,90)"。
    """
    t = text or ""
    for word, name in BELL_KIND_WORDS:
        if word in t:
            return name
    return ""


def ui_spot(pos):
    """界面日志里的坐标写法:"朱紫国(127,90)"(用户给的格式,不带空格)。"""
    if not pos:
        return ""
    name, x, y = pos
    if x is None or y is None:
        return name
    return f"{name}({x},{y})"


def hunt_gap(n):
    """还没学到任务栏框时,"整窗找表头"这一拍该等多长(连没找着的次数 -> 间隔)。

    档位见 `HUNT_GAPS`(0.25 → 0.5 → 1.0 → 2.0,封顶 2.0):连着 n 次整窗都没学到
    框,就用第 n 档;学到框时调用方把 n 归零(下一拍立刻回到 0.25,不拖慢重新定位)。
    """
    return HUNT_GAPS[min(max(int(n), 0), len(HUNT_GAPS) - 1)]


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


SIG_GRID = (24, 48)                      # 面板内容签名的采样格(行, 列)


def panel_sig(rgb, box, grid=SIG_GRID):
    """面板**里面**的内容签名(定长小图)。**先按亮度二值化再采样**。

    为什么二值化(2026-10-17 用户报"又卡死了"后改的):游戏的面板是**半透明**的,
    身后的世界一直在动 —— 直接采原始像素,背景一动签名就变,门控把"背景在动"
    当成"换了一段话",于是**每 10 秒读 8~12 次**(一半还是"非铃铛对话"白烧),
    GPU 一直被占着,游戏一卡一卡。二值化后进签名的只有"哪些像素亮"(= 文字笔画
    的位置),背景明暗怎么变都不影响;真翻页(字换了)掩码照样变 ✔。
    采样成固定 24x48 是为了让签名跟面板大小无关:框的边缘会抖 ±4 像素;
    返回值和老签名同形 (24,48,3),`sig_diff`/`SIG_MIN` 一个字不用改。
    """
    import numpy as np
    a = np.asarray(rgb)
    if a.ndim != 3 or not a.size:
        return None
    h, w = a.shape[:2]
    x0 = max(0, min(int(box[0]), w - 1))
    y0 = max(0, min(int(box[1]), h - 1))
    x1 = max(x0 + 1, min(int(box[2]), w))
    y1 = max(y0 + 1, min(int(box[3]), h))
    sub = a[y0:y1, x0:x1]
    mask = (sub.max(axis=2) >= DIALOG_BRIGHT).astype(np.uint8) * 255
    sh, sw = mask.shape[:2]
    ys = np.linspace(0, sh - 1, grid[0]).astype(int)
    xs = np.linspace(0, sw - 1, grid[1]).astype(int)
    return np.repeat(mask[ys][:, xs][:, :, None], 3, axis=2)


def sig_diff(a, b):
    """两个签名差多少(平均绝对差);缺一个或形状不同就当"变了"。"""
    import numpy as np
    if a is None or b is None:
        return 999.0
    if getattr(a, "shape", None) != getattr(b, "shape", None):
        return 999.0
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())


def confirmed(hist, need=TRK_CONFIRM):
    """最近几次读数里,**从新往旧**找到第一个出现过 ≥need 次的值;没有返回 None。

    治的是真机上把同一段文字读花:实战日志里同一只怪的任务栏被读成
    宝象国(56,79)/(66,79)/(50,79)/(56,7)/(56,1) 五种,每种都当"新目标"报了出去,
    16 秒里报 9 个点 —— 红点在原地乱跳。真值会反复出现(10~29 次),
    误读基本只出现一次,所以要"见过两次才算数"。
    """
    for v in reversed(list(hist or [])):
        if v and hist.count(v) >= need:
            return v
    return None


def read_note(what, size, nblock, ms, got=None, blocks=None):
    """一行"识别过程"日志:扫了哪块、多大、几个文字块、多久、认到了什么。

    读到的原文**两边都带上**。没认到时最想知道"它到底读成了啥"(出过一次
    "任务栏一直没认到",当初没写字,事后完全看不出原因);认到的时候也要 ——
    不然"建邺城(101,127) 是怎么变成建邺城(24,108) 的"只能靠猜(实测踩过)。
    """
    w, h = int(size[0]), int(size[1])
    seen = " ".join((b.get("text") or "") for b in (blocks or []))[:26]
    if got:
        tail = f"{got[0]}({got[1]},{got[2]})"
        if seen:
            tail += f" 读到:{seen}"
    else:
        tail = f"没认到({seen})" if seen else "一个字都没读到"
    return f"{what} {w}x{h} 块{nblock} {ms:.0f}ms → {tail}"


def _spot(bell):
    """一个目标在日志里的写法(`地图名 (x,y)`);几处文案都按这一份来。"""
    return f"{bell[0]} ({bell[1]},{bell[2]})"


def _is_hdr(text):
    """这一行是不是「任务追踪」表头。

    表头是**面板开着**的可靠标志(任务名可能被读花,表头基本不会);而且它在
    任务名**上面**,拿它当锚,框自然把"降妖伏魔"和它上面那行悬停坐标都圈进来。
    判据(2026-10-16 放宽一个字):整行不长 + 有「追」+ 至少还有一个「任/务」——
    真机上那行加粗小绿字经常把「任」丢掉(实测读到过「务追踪」),`任务追踪` /
    `务追踪` / `任务追` / `任追踪` 都要认;`任务剩余时间120分钟。`(太长)、
    `师门任务`(没有「追」)照旧不认。误伤面靠 `track_rect()` 里"面板里还得有
    「降妖伏魔」"(`_title_y`)那条兜着。
    """
    t = (text or "").strip()
    return len(t) <= 8 and "追" in t and ("任" in t or "务" in t)


def _is_title(text):
    """这一行是不是「降妖伏魔」的标题行。

    那行是加粗的绿字,OCR 常常把后两个字认错(实测"降妖闪通"/"降妖快通"/
    "降妖伏麾"都有),但**前两个字"降妖"每次都认对** —— 所以认前两个字就够,
    再加"整行不能太长"把它和正文里出现"降妖"的句子分开。
    """
    t = (text or "").strip()
    if _BELL_TITLE in t:
        return len(t) <= 12
    if "降妖" in t:
        return len(t) <= 8
    # **2026-10-17 加第三种**:整行**以「降」开头**且不长也算 —— 实测标题被读成
    # 「降双快通」/「降欢风衡」时前两个字就花了,而"降"一般还认得出;别的任务
    # (师门/法宝合成/签到答题…)标题都不以「降」开头,所以不会误认。框的位置
    # 仍由**表头**定,这条只用来确认"面板里挂的是降妖伏魔"。
    return t.startswith("降") and len(t) <= 8


def _order(blocks, tol=12):
    """把文字块按"行"排好:同一行里按 x 排,行与行按 y 排。

    OCR 给的是每个块的框,同一行的两个块底边(y1)能差一两个像素 —— 直接按
    (y1, x1) 排会把右边那块甩到下一行去,拼出来的句子就乱了。实测:
    `蛊虫发现妖魔在宝` + `国150.54)` + `，快去降服` 三个块,直接排变成
    "…在宝，快去降服国150.54)…" —— "在宝国" 再也拼不出来,坐标就丢了。
    """
    rows = []
    for b in sorted(blocks, key=lambda b: b.get("y1", 0) + b.get("y2", 0)):
        mid = (b.get("y1", 0) + b.get("y2", 0)) / 2.0
        if rows and abs(mid - rows[-1][0]) <= tol:
            rows[-1][1].append(b)
        else:
            rows.append((mid, [b]))
    out = []
    for _mid, row in rows:
        out.extend(sorted(row, key=lambda b: b.get("x1", 0)))
    return out


def _title_y(blocks):
    """「降妖伏魔」标题那一行的 y(找不到返回 None)。"""
    for b in _order(blocks):
        if _is_title(b.get("text")):
            return b.get("y1", 0)
    return None


def _bell_span(blocks, title_y):
    """标题上下那一段里的块(不含对话框那两种说法)。"""
    up, down = _BELL_TITLE_SPAN
    out = []
    for b in blocks:
        t = b.get("text") or ""
        if "踪迹在" in t or _RE_BELL_USE.search(t):
            continue
        y = b.get("y1", 0)
        if title_y - up <= y <= title_y + down:
            out.append(b)
    return out


def _bell_scope(blocks):
    """任务追踪里会挂着好几个任务,**只认「降妖伏魔」标题下的那一段**。

    别的任务(师门/抓鬼…)也有"去某某地(x,y)"的行,不圈范围就会认错。
    对话框那两种写法(「…踪迹在X(x,y)…」「去X(x,y)使用招魂帖」)不属于任务
    追踪,始终保留。找不到「降妖伏魔」标题时,任务追踪的行全部丢弃 ——
    没有标题,说明这个任务根本不在追踪列表里。
    """
    blocks = _order([b for b in blocks if (b.get("text") or "").strip()])
    title_y = _title_y(blocks)
    span_ids = set()
    if title_y is not None:
        span_ids = {id(b) for b in _bell_span(blocks, title_y)}
    kept = []
    for b in blocks:
        t = b.get("text") or ""
        if ("踪迹在" in t or "妖魔在" in t            # 对话框/任务栏的说法
                or _RE_BELL_USE.search(t)
                or id(b) in span_ids):
            kept.append(b)
    return kept


def track_rect(blocks, size, margin=TRK_MARGIN):
    """整窗扫完,把任务栏那一块学下来(任务栏是能被用户拖走的)。

    **两步**(用户定的):①先找「任务追踪」表头 —— 找不到就说明面板没开,直接
    返回 None,后面什么都不做;②面板里得真有「降妖伏魔」这段,挂着别的任务就不读。
    框 = 围着表头的一个固定大小的框(表头左上角往右下扩 panel_w × panel_h)——
    表头在任务名上面,所以框自然把任务名、正文、以及悬停那行坐标都圈进来。
    不取"标题上下那段块的并集":那段里混着聊天/经验那些横贯整屏的行,并集一出来
    就是整屏宽,OCR 反而更慢。

    blocks 是整窗扫出来的块(坐标相对那张图),size = (宽, 高)。
    学不到(没标题)返回 None —— 调用方过一会儿再整窗扫一次重学。
    """
    blocks = [b for b in blocks if (b.get("text") or "").strip()]
    # 第一步:找「任务追踪」表头。找不到 = 面板根本没开,后面什么都不用做
    #(用户定的规矩:先找任务追踪,没有就不继续了)。
    hdr = None
    for b in _order(blocks):
        if _is_hdr(b.get("text")):
            hdr = b
            break
    if hdr is None:
        return None
    # 第二步:面板里得真有「降妖伏魔」这一段 —— 挂着别的任务就别读这块
    if _title_y(blocks) is None:
        return None
    title = hdr
    w, h = int(size[0]), int(size[1])
    x0 = max(0, int(title.get("x1", 0)) - margin)
    y0 = max(0, int(title.get("y1", 0)) - margin)
    x1 = min(w, x0 + PANEL_W)
    y1 = min(h, y0 + PANEL_H)     # 表头下面那一段:任务名 + 正文 + 悬停行
    if x1 - x0 < 60 or y1 - y0 < 30:
        return None
    # **四周再留一层安全边距**(用户定的 2026-10-16,见 `TRK_PAD`):防着"框边切字"
    # —— 左边切进表头(`务追踪`)、右边切掉行尾的坐标(`宝象 40，12）`)。扩完夹回图片内。
    x0 = max(0, x0 - TRK_PAD[0])
    y0 = max(0, y0 - TRK_PAD[1])
    x1 = min(w, x1 + TRK_PAD[2])
    y1 = min(h, y1 + TRK_PAD[3])
    return (x0, y0, x1, y1)


def scan_bell_parts(blocks, scoped=True, wide=False):
    """把这一轮文字块里"对话框说的"和"任务栏说的"分开认出来。

    返回 (dialog, tracker, where):
      dialog / tracker: (地图名, x, y)  —— 对话框开新周期,任务栏在周期内补充
      where: 恒为 None(任务栏只写"去X找Y"、没坐标的,一律不管)

    `wide=True` = **这一拍读的是大字面**(整个客户端窗口 / 整窗那一拍,`_scan` 里
    传的是 `wide=not rect_known`):这种读数里混着聊天、别的任务的行,所以只认
    **带虚词锚点**的写法(`踪迹在` / `去/到…使用` / `(妖魔)在…` / `去/到…`),
    两条"光秃秃的图名+坐标"兜底一律不用 —— 实测聊天里一句 `长寿村(50,60)` 会被
    兜底认成 **dialog**,而 dialog 是**立刻报**的,红点当场就飞了。
    读红框那一小块时(wide=False)照旧保留兜底:那里的图名读花("建邮城"/"宝国")
    就靠它兜住(容错不能丢)。

    任务追踪里可能挂着别的任务:自动模式下只看「降妖伏魔」标题下的那一段;
    对话框那条主路(scoped=False,面板里就那一条任务)不圈范围,原样认。
    """
    blocks = _bell_scope(blocks) if scoped else blocks
    text = "".join((b.get("text") or "") for b in _order(blocks))
    # 「去X(x,y)使用招魂帖/逐妖蛊虫」是**对话框**说的(招魂幡、逐妖蛊虫第一步),
    # 跟「踪迹在…」同级。悬停行(「在X(x,y)处」)不算 —— 它是任务栏那边的
    # 第二个坐标,归 track(`_RE_BELL_TRACK` 就认它)。
    dialog = (_hit(text, _RE_BELL_DIALOG) or _hit(text, _RE_BELL_USE))
    track = _hit(text, _RE_BELL_TRACK)
    if not track and not wide:
        track = _hit(text, _RE_BELL_KNOWN)      # 老写法兜底(没锚点但有图名+坐标)
    if not (dialog or track):
        # 兜底:"去建邺城(101,127)"。大字面那一拍只认带"去/到"的那种写法
        any_hit = _hit(text, _RE_BELL_ANY_ANCHORED if wide else _RE_BELL_ANY)
        if any_hit:
            dialog = any_hit
    return dialog, track, None


def bell_form(text, wide=False):
    """这段文字里认出来的值是哪条文法来的(只给日志用);没有返回 ""。

    **这是为了统计"大字面(整个窗口)读数供值"临时加的,量完可以删。**
    顺序和 `scan_bell_parts` 一致(别自己重排):对话框两条在前、任务栏两条
    居中、最后才是"对话框·无锚点兜底"那条 —— 顺序变了,统计出来的"哪条文法
    命中"就不是它实际走的路径了。`wide=True` 与"大字面那一拍"同口径:跳过
    "任务栏·无锚点兜底",最后那条也只认带"去/到"的写法(名字不变,两种口径
    才好对着统计)。
    """
    rules = [(_RE_BELL_DIALOG, "对话框·踪迹在"),
             (_RE_BELL_USE, "对话框·去X使用"),
             (_RE_BELL_TRACK, "任务栏·有锚点(在/妖魔在)")]
    if not wide:
        rules.append((_RE_BELL_KNOWN, "任务栏·无锚点兜底"))
    rules.append((_RE_BELL_ANY_ANCHORED if wide else _RE_BELL_ANY,
                  "对话框·无锚点兜底"))
    for pat, name in rules:
        if _hit(text, pat):
            return name
    return ""


def scan_bell(blocks, scoped=True):
    """从 OCR 文字块里找"地图名+坐标":对话框优先,任务栏作补充;都没有返回 None。"""
    dialog, track, _where = scan_bell_parts(blocks, scoped=scoped)
    return dialog or track


# ---- 底图:data/maps/ 下按地图名或拼音名放图(png/jpg) ----
MAP_DIR = os.path.join(BASE_DIR, "data", "maps")
MAP_CALIB_PATH = os.path.join(MAP_DIR, "calib.json")
MAP_BOUNDS_PATH = os.path.join(MAP_DIR, "bounds.json")
MAP_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
# 拼音名对应 24 张老图集里的文件名(只有这几张收得到)
MAP_STEMS = {
    "长寿村": ("changshoucun", "changshoujiaowai"),
    "傲来国": ("aolaiguo",),
    "朱紫国": ("zhuziguo",),
    "建邺城": ("jianye",),
    "西梁女国": ("xiliangnvguo",),
    "宝象国": ("baoxiangguo",),
}


def map_asset(name: str):
    """找地图底图:先按中文名找,再按拼音名找;都没有返回 None。"""
    stems = [name] + list(MAP_STEMS.get(name, ()))
    for stem in dict.fromkeys(stems):
        for ext in MAP_EXTS:
            p = os.path.join(MAP_DIR, stem + ext)
            if os.path.exists(p):
                return p
    return None


# 录入地图时用的判据(纯函数,好离线测)
MAP_RECT_MIN, MAP_RECT_MAX = 160, 1500   # 地图矩形的边长合理区间
MAP_RECT_FILL = 0.55                     # 连通块占自己外接框的比例(更低的是一圈描边/碎块)
MAP_RECT_TOL = 0.03                      # 外接框长宽比与坐标范围比例的允许偏差
MAP_RECT_TIGHT = 0.04                    # 偏差够小就不再试后面的彩色度档
MAP_SAT_LEVELS = (35, 25, 45, 55)        # 逐级试的"彩色度"(六张图在 35 档命中最多)


def _band(cover, frac):
    """覆盖比例 ≥ frac 的最长连续段 -> (起点, 终点);没有返回 None。"""
    best = None
    start = None
    for i, v in enumerate(cover >= frac):
        if v:
            if start is None:
                start = i
        elif start is not None:
            if best is None or i - start > best[1] - best[0]:
                best = (start, i - 1)
            start = None
    if start is not None and (best is None
                              or len(cover) - start > best[1] - best[0]):
        best = (start, len(cover) - 1)
    return best


def _components(mask, min_side, max_side):
    """mask 里边长落在区间内的连通块 -> [(像素数, x0, y0, x1, y1)]。"""
    import collections

    import numpy as np
    h, w = mask.shape
    seen = np.zeros((h, w), bool)
    out = []
    for y in range(h):
        if not mask[y].any():
            continue
        for x in range(w):
            if not mask[y, x] or seen[y, x]:
                continue
            dq = collections.deque([(x, y)])
            seen[y, x] = True
            n = 0
            minx = maxx = x
            miny = maxy = y
            while dq:
                cx, cy = dq.popleft()
                n += 1
                if cx < minx:
                    minx = cx
                elif cx > maxx:
                    maxx = cx
                if cy < miny:
                    miny = cy
                elif cy > maxy:
                    maxy = cy
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1),
                               (cx, cy - 1)):
                    if (0 <= nx < w and 0 <= ny < h and mask[ny, nx]
                            and not seen[ny, nx]):
                        seen[ny, nx] = True
                        dq.append((nx, ny))
            bw, bh = maxx - minx + 1, maxy - miny + 1
            if min_side <= bw <= max_side and min_side <= bh <= max_side:
                out.append((n, minx, miny, maxx, maxy))
    return out


def map_ratio(name):
    """这张地图坐标范围的长宽比(用来核对"截到的是不是它");没范围返回 None。"""
    try:
        min_x, min_y, max_x, max_y = [float(v)
                                      for v in load_map_bounds().get(name)]
    except Exception:
        return None
    if max_x <= min_x or max_y <= min_y:
        return None
    return (max_x - min_x) / (max_y - min_y)


def find_color_blob(rgb, want_ratio=None, min_side=MAP_RECT_MIN,
                    max_side=MAP_RECT_MAX):
    """按"整块彩色区"找地图本体(快,六张图里五张能直接命中)。

    地图窗口画的就是**一张整块的图**:某个彩色度档下它会连成一整个连通块,外接框
    刚好是图本身(实测六张图的原始截图误差 ≤1px);窗口周围被挡住的场景要么碎成
    小块、要么彩色度不够连不起来。

    want_ratio = 这张地图坐标范围的长宽比(get 自 bounds.json)—— 给了就挑"外接框
    比例离它最近"的那块,顺带验一下截到的确实是这张图;没给就挑面积最大的那块。

    连通块的外接框有时会连上周围一小片场景(彩色度低的地图会这样),所以每块再按
    "行/列覆盖比例"裁一次,原框和裁剪框都当候选。
    """
    import numpy as np
    a = np.asarray(rgb).astype(np.int16)
    if a.ndim != 3 or a.shape[2] < 3:
        return None
    sat = a.max(axis=2) - a.min(axis=2)
    best = None
    for th in MAP_SAT_LEVELS:
        mask = sat > th
        for n, minx, miny, maxx, maxy in _components(mask, min_side, max_side):
            bw, bh = maxx - minx + 1, maxy - miny + 1
            if n / float(bw * bh) < MAP_RECT_FILL:
                continue
            cands = [(minx, miny, maxx, maxy)]
            sub = mask[miny:maxy + 1, minx:maxx + 1]
            rb, cb = _band(sub.mean(axis=1), 0.5), _band(sub.mean(axis=0), 0.5)
            if rb and cb:
                x0, y0 = minx + cb[0], miny + rb[0]
                x1, y1 = minx + cb[1], miny + rb[1]
                trim = (x1 - x0 + 1) * (y1 - y0 + 1)
                if (trim / float(n) >= 0.6
                        and min_side <= x1 - x0 + 1 <= max_side
                        and min_side <= y1 - y0 + 1 <= max_side):
                    cands.append((x0, y0, x1, y1))
            for box in cands:
                bw, bh = box[2] - box[0] + 1, box[3] - box[1] + 1
                ratio = bw / float(bh)
                if want_ratio:
                    err = abs(ratio / want_ratio - 1)
                    if err > MAP_RECT_TOL:
                        continue
                elif not 0.5 <= ratio <= 2.5:
                    continue
                else:
                    err = 0.0
                key = (round(err, 4), -(bw * bh))
                if best is None or key < best[0]:
                    best = (key, box)
        if best and best[0][0] <= MAP_RECT_TIGHT:
            break
    return best[1] if best else None


# ---- 兜底:地图窗那圈深色外框(灰石头城那种彩色块法认不出来的,靠它) ----
MAP_FRAME_DARK = 95        # 外框的"深"上限(max(RGB))
MAP_FRAME_SAT = 70         # 外框的彩度上限(发黑的才要)
MAP_FRAME_MIN_RUN = 120    # 框线至少这么长(min_side 的三分之二上下)
MAP_FRAME_SIDE = 0.5       # 框线两侧至少有一侧"亮"到这个程度以下:是线不是深色块
MAP_FRAME_TOL = 0.12       # 外框比地图本体多一圈边,长宽比会漂,所以放宽


def _runs(mask, axis, min_run):
    """沿 axis 逐行/逐列找"细深色段" -> [(位置, 段长, 段起, 段止)]。

    细=这一段的外面至少有一侧是亮的(不是一大片深色):地图窗的描边就是这种线。
    """
    n = mask.shape[axis]
    out = []
    for i in range(n):
        line = mask[i] if axis == 0 else mask[:, i]
        best = cur = 0
        start = best_s = 0
        for j, val in enumerate(line):
            if val:
                if cur == 0:
                    start = j
                cur += 1
                if cur > best:
                    best, best_s = cur, start
            else:
                cur = 0
        if best < min_run:
            continue
        s, e = best_s, best_s + best - 1
        if axis == 0:
            up = float(mask[i - 1, s:e + 1].mean()) if i > 0 else 0.0
            dn = float(mask[i + 1, s:e + 1].mean()) if i + 1 < n else 0.0
        else:
            up = float(mask[s:e + 1, i - 1].mean()) if i > 0 else 0.0
            dn = float(mask[s:e + 1, i + 1].mean()) if i + 1 < n else 0.0
        if min(up, dn) < MAP_FRAME_SIDE:
            out.append((i, best, s, e))
    return out


def _overlap(a, b):
    """两个区间 [起,止] 的重叠长度。"""
    return max(0, min(a[1], b[1]) - max(a[0], b[0]) + 1)


def find_map_frame(rgb, want_ratio=None, min_side=MAP_RECT_MIN,
                   max_side=MAP_RECT_MAX):
    """按"地图窗的深色外框"找地图**窗口**,返回 (x0,y0,x1,y1);找不到 None。

    外框跟地图本身配色无关(灰石头城也有),所以彩色块法认不出来的图靠它。
    判据:上/下两条横线的**跨度基本重合**(拐角那几像素会被别的东西打断,所以
    只要求重叠够多)、左右两条竖线同理,四条线框出的矩形边长在区间内、长宽比
    接近 want_ratio(外框比图本体多一圈边,这里只粗筛 ±12%:真正的比例核对
    在裁出地图本体之后)。
    """
    import numpy as np
    a = np.asarray(rgb).astype(np.int16)
    if a.ndim != 3 or a.shape[2] < 3:
        return None
    v = a.max(axis=2)
    mask = (v < MAP_FRAME_DARK) & ((v - a.min(axis=2)) < MAP_FRAME_SAT)
    rows = _runs(mask, 0, MAP_FRAME_MIN_RUN)
    cols = _runs(mask, 1, MAP_FRAME_MIN_RUN)
    best = None
    for t, tl, ts0, ts1 in rows:
        for b, bl, bs0, bs1 in rows:
            if b <= t:
                continue
            bh = b - t + 1
            if not (min_side <= bh <= max_side):
                continue
            if _overlap((ts0, ts1), (bs0, bs1)) < 0.85 * min(tl, bl):
                continue                                   # 上下不是同一条窗框
            bw_exp = (tl + bl) / 2.0
            if not (min_side <= bw_exp <= max_side):
                continue
            if want_ratio and abs(bw_exp / bh / want_ratio - 1) > MAP_FRAME_TOL:
                continue
            for l, ll, ls0, ls1 in cols:
                if ll < 0.9 * bh or not (t - 8 <= ls0 and ls1 <= b + 8):
                    continue
                for r, rl, rs0, rs1 in cols:
                    if r <= l or rl < 0.9 * bh:
                        continue
                    if not (t - 8 <= rs0 and rs1 <= b + 8):
                        continue
                    bw = r - l + 1
                    if abs(bw - bw_exp) > 0.05 * bw_exp:
                        continue
                    err = (abs(bw / float(bh) / want_ratio - 1)
                           if want_ratio else 0.0)
                    key = (round(err, 3), -(bw * bh))
                    if best is None or key < best[0]:
                        best = (key, (l, t, r, b))
    return best[1] if best else None


def find_map_rect(rgb, want_ratio=None, min_side=MAP_RECT_MIN,
                  max_side=MAP_RECT_MAX):
    """在整屏截图里找游戏地图那一块,返回 (x0,y0,x1,y1);找不到返回 None。

    先按整块彩色区找(快);找不到再找地图窗的深色外框,在框内重找一次本体 ——
    两条路是互补的:彩色块法在灰石头城(建邺城)上会失败,外框法在竖长图
    (长寿村)上会失败,合起来六张都稳。实测(把官方的地图窗截图贴进真游戏
    截图做的全屏模拟):六张全部命中,与地图本体差 ≤1px;没开地图的真截图全拒。
    """
    import numpy as np
    rect = find_color_blob(rgb, want_ratio, min_side, max_side)
    if rect:
        return rect
    frame = find_map_frame(rgb, want_ratio, min_side, max_side)
    if not frame:
        return None
    x0, y0, x1, y1 = frame
    inner = np.asarray(rgb)[y0:y1 + 1, x0:x1 + 1]
    got = find_color_blob(inner, want_ratio, min_side, max_side)
    if not got:
        return None
    return (got[0] + x0, got[1] + y0, got[2] + x0, got[3] + y0)


# ---- 分辨率表:客户端每个尺寸下,对话框 / 任务栏在哪(相对窗口左上角) ----
# 游戏 UI 是"固定像素"的:同一个客户端尺寸下,对话框和任务栏的大小、位置都是死的。
# 存成**相对客户端窗口**的坐标,窗口挪了/多开都不用重设。
# **只保留两档**(用户 2026-10-17 定的):640x480(窗口 815x680)、
# 800x600(窗口 1011x826)。表里没有的尺寸 = 不支持,界面会弹窗让用户改分辨率。
# 用 `python main.py --layout` 自动量当前这个尺寸的对话框框,量完写进这个文件。
LAYOUT_PATH = os.path.join(BASE_DIR, "data", "bell_layouts.json")


def cmd_layout(save=True) -> int:
    """命令行:`--bell-layout` —— 量当前客户端尺寸下**对话框那块**在哪,写进分辨率表。

    对话框那块要**当下开着对话框**才量得到:先把铃铛任务的对话框调出来再跑。
    (任务栏坐标**不进表**了:它靠扫整窗现场定位,见 `LAYOUT_PATH` 上面的说明。)
    """
    out = measure_layout()
    if not out:
        print("没找到客户端窗口(游戏没开?或被最小化了)")
        return 1
    for size, row in out.items():
        print(f"  客户端 {size}:")
        if row.get("dlg"):
            print(f"    对话框 dlg={row['dlg']}")
        else:
            print("    对话框:没看到对话框面板 —— 先把一个铃铛对话框打开再跑")
        if save and row:
            print(f"    已写入 {save_layout(size, row.get('dlg'))}")
    return 0


def load_layouts() -> dict:
    """分辨率表:{"1022x809": {"dlg": [x0,y0,x1,y1]}};读不了返回 {}。"""
    try:
        with open(LAYOUT_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


# 尺寸对不上时的容差:截图里的窗口矩形和 GetWindowRect 能差几个像素(实测
# 同一台 800x600 的客户端,截图是 1011x826、实测是 1015x829)。三个已知尺寸
# 彼此差 200 像素以上,所以放宽到 20 也不会认错档。
LAYOUT_TOL = 20


def layout_row(size):
    """这个客户端尺寸量过吗?返回表里那一行(dict)或 None(坐标都相对窗口左上角)。

    表里两样:`dlg` = 对话框框;**`trk` = 任务栏框**(围着「任务追踪」表头那块)。

    精确匹配先试;差 ±LAYOUT_TOL 像素也算(截图和 GetWindowRect 会差一两像素,
    实测同一台机器上 815x680 和 815x679 都出现过)。
    """
    if not size:
        return None
    data = load_layouts()
    w, h = int(size[0]), int(size[1])
    row = data.get(f"{w}x{h}")
    if not isinstance(row, dict):
        for key, val in data.items():
            if key.startswith("_"):
                continue
            try:
                kw, kh = (int(v) for v in key.lower().split("x"))
            except Exception:
                continue
            if abs(kw - w) <= LAYOUT_TOL and abs(kh - h) <= LAYOUT_TOL:
                row = val if isinstance(val, dict) else None
                break
    return row if isinstance(row, dict) else None


def supported_size(size):
    """这个客户端尺寸降妖伏魔支持吗(表里量过的两档:815x680 / 1011x826)。

    也就是游戏里的 640x480 / 800x600。1024x768 已不支持(表里那一行已删)。
    """
    return layout_for(size) is not None


def layout_for(size):
    """这个客户端尺寸的**对话框框**(相对窗口左上角)或 None。"""
    return (layout_row(size) or {}).get("dlg") or None


def layout_trk(size):
    """这个客户端尺寸的**任务栏框**(相对窗口左上角)或 None。

    量过的尺寸把任务栏框也写进表(用户 2026-10-17 要求):这个分辨率以后**只扫
    这一块**,不再花 2~3 秒整窗找「任务追踪」表头。没量的尺寸照旧现场找。
    """
    trk = (layout_row(size) or {}).get("trk")
    return [int(v) for v in trk] if trk and len(trk) == 4 else None


def save_layout(size, dlg=None, trk=None):
    """把这个尺寸量到的框写进表里(读-改-写)。size 给 (宽,高) 或 "宽x高"。"""
    data = load_layouts()
    if isinstance(size, str) and "x" in size:
        key = size
    else:
        key = f"{int(size[0])}x{int(size[1])}"
    row = data.get(key) if isinstance(data.get(key), dict) else {}
    row.pop("icons", None)    # 老版本写进去的"判进没进战斗"那格:功能已删,一起清
    if dlg:
        row["dlg"] = [int(v) for v in dlg]
    if trk:
        row["trk"] = [int(v) for v in trk]
    data[key] = row
    os.makedirs(os.path.dirname(LAYOUT_PATH), exist_ok=True)
    with open(LAYOUT_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return key, row


def measure_layout(screen=None):
    """量当前客户端窗口里**对话框那块**在哪(相对窗口左上角)。

    必须是**当下正开着对话框**才量得到(靠像素找面板)。任务栏坐标**不进表**:
    面板在游戏里能随便拖、量一次写死没意义 —— 它靠"扫整窗找「任务追踪」表头"
    现场定位(所以这里连 OCR 都不用开)。返回 {尺寸: {...}}。
    """
    import core
    core._dpi_aware()          # 和主程序同一套:量出来的是**物理像素**,才对得上
    sc = screen or core.Screen()
    out = {}
    try:
        wins, _mini = core.find_client_windows()
    except Exception:
        wins = []
    for _title, rect in wins:
        x0, y0, x1, y1 = [int(v) for v in rect]
        size = (x1 - x0, y1 - y0)
        row = {}
        band = rel_rect(rect, DIALOG_BAND)
        try:
            bcrop = sc.grab(band)
            box = panel_box(bcrop)
        except Exception:
            box = None
        # 量出来的框要是快盖满整条带子,那多半是"没开对话框"时把整条带子当成了
        # 面板(暗场景会这样)—— 这种别写进表里,免得把错的坐标固化下来
        wide = box and (box[2] - box[0]) >= 0.92 * (band[2] - band[0])
        if box and not wide:
            row["dlg"] = [band[0] - x0 + box[0], band[1] - y0 + box[1],
                          band[0] - x0 + box[2], band[1] - y0 + box[3]]
        out[f"{size[0]}x{size[1]}"] = row
    return out


def map_names_in(blocks, names=BELL_MAP_NAMES):
    """画面里的文字块出现过的地图名(去重、别名归一)。

    只用来核对"现在打开的是不是这张图":游戏 HUD 一直写着当前地图名,所以录那张
    图时它一定在;任务追踪/聊天里提到别的地图名也拦得住。地图窗口里那些**邻近**
    地图的标注(比如"解阳山""丝绸之路")不在 BELL_MAP_NAMES 里,不会被算进来。
    """
    found = []
    for b in blocks:
        text = (b.get("text") or "").strip()
        if not text:
            continue
        for n in names:
            if n in text and n not in found:
                found.append(n)
        for alias, canon in _BELL_CANON.items():
            if alias in text and canon in names and canon not in found:
                found.append(canon)
    return found


def map_calib(name: str):
    """底图缩放系数:图片像素 = 坐标 * s + o。

    默认 (1,1,0,0),即"底图像素 == 游戏坐标"。老图集若整体缩放过,
    在 data/maps/calib.json 里写 {"地图名": {"sx":..,"sy":..,"ox":..,"oy":..}}。
    """
    try:
        with open(MAP_CALIB_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    v = data.get(name) or {}
    if not isinstance(v, dict):
        v = {}
    try:
        return (float(v.get("sx", 1.0)) or 1.0, float(v.get("sy", 1.0)) or 1.0,
                float(v.get("ox", 0.0)), float(v.get("oy", 0.0)))
    except Exception:
        return (1.0, 1.0, 0.0, 0.0)


def map_pixel(name: str, x: int, y: int):
    """游戏坐标 -> 底图上的像素位置(浮点)。"""
    sx, sy, ox, oy = map_calib(name)
    return (x * sx + ox, y * sy + oy)


def map_asset_save_path(name, ext=".png"):
    """游戏里采集来的底图存到 data/maps/<中文名>.png,并保证目录存在。"""
    os.makedirs(MAP_DIR, exist_ok=True)
    return os.path.join(MAP_DIR, name + ext)


def save_map_calib(name, sx, sy, ox=0.0, oy=0.0):
    """把某张地图的缩放系数写进 data/maps/calib.json(读-改-写,别覆盖别的图)。"""
    try:
        with open(MAP_CALIB_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    data[name] = {"sx": float(sx), "sy": float(sy),
                  "ox": float(ox), "oy": float(oy)}
    os.makedirs(MAP_DIR, exist_ok=True)
    with open(MAP_CALIB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def map_calib_from_bounds(w, h, bounds):
    """底图就是整张地图时,直接按坐标范围算出标定。

    bounds = [min_x, min_y, max_x, max_y]。游戏里地图原点 (0,0) 在**左下角**、
    y 轴朝上,所以 y 方向要翻过来(用负的 sy 加偏移表示),x 方向是普通的线性。
    返回 (sx, sy, ox, oy),范围不合法返回 None。
    """
    try:
        min_x, min_y, max_x, max_y = [float(v) for v in bounds]
    except Exception:
        return None
    if max_x <= min_x or max_y <= min_y or w <= 0 or h <= 0:
        return None
    sx = w / (max_x - min_x)
    sy = h / (max_y - min_y)
    return (sx, -sy, -min_x * sx, max_y * sy)


def load_map_bounds() -> dict:
    """地图坐标范围:data/maps/bounds.json 里 {"地图名": [minx, miny, maxx, maxy]}。"""
    try:
        with open(MAP_BOUNDS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def auto_calibrate_from_bounds(overwrite=False):
    """有坐标范围的地图,自动算标定,省得挨个手点角色位置。

    返回 [(地图名, 说明)]。默认只补没有标定的那些,overwrite=True 才重算。
    """
    from PIL import Image
    out = []
    bounds_all = load_map_bounds()
    if not bounds_all:
        return out
    try:
        with open(MAP_CALIB_PATH, encoding="utf-8") as f:
            done = json.load(f)
        done = done if isinstance(done, dict) else {}
    except Exception:
        done = {}
    for name, bounds in bounds_all.items():
        if name.startswith("_"):          # 以 _ 开头的是注释行,不是地图
            continue
        path = map_asset(name)
        if not path:
            out.append((name, "没有底图"))
            continue
        if not overwrite and name in done:
            out.append((name, "已有标定,跳过"))
            continue
        try:
            with Image.open(path) as im:
                w, h = im.size
        except Exception as err:
            out.append((name, f"底图读不了({err})"))
            continue
        cal = map_calib_from_bounds(w, h, bounds)
        if not cal:
            out.append((name, "坐标范围不合法"))
            continue
        save_map_calib(name, *cal)
        out.append((name, f"sx={cal[0]:.2f} sy={cal[1]:.2f}"))
    return out


class BellTool(threading.Thread):
    """妖魔位置监听:自己决定扫哪、自己认,位置交给界面画点。

    不播报语音(用户要求):认出来只写日志 + 更新界面上的点。

    只走**快路**(对着用户那两条红线:准、快):对话框位置是固定的(游戏把它贴在
    窗口下方居中),先用 1ms 的"暗面板"判据挡掉绝大多数轮次,真有面板才 OCR
    那一小块;任务栏用**学下来的**小框只读那一小块(分辨率表里只有对话框坐标,
    任务栏坐标不进表)。

    **整窗只出现在快路里、只为定位任务栏框**(用户定的终态):还没有学到框时,
    那一拍读的就是整个 region(节流 `TRK_WATCH_GAP`),读到「任务追踪」表头 +
    「降妖伏魔」就把框学下来;**唯一的作废判据**是"框里连着 2 次读到了字、却没有
    表头"(任务栏被拖走了)—— 作废之后下一拍又回到"还没有框"那一支,还是这段代码。
    读完一个字都没读到**不作废**(面板被游戏藏起来是正常的,只记数 + 一条诊断日志)。
    原来另有一条"慢路:整窗扫"的通道(`reanchor` / `full_ts` / `hdr_lost` /
    两处说法不一致时的对账重扫),2026-10-16 按用户要求整套撤掉了。

    过程都写进日志(界面日志框能直接看到扫了哪块、多大、几毫秒、认到了什么)。
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
        """界面刷新要的只读快照:当前妖魔位置、显示行、不支持的分辨率。"""
        return {"spot": self.spot, "target": self.target,
                "bad_size": self._bad_size}

    def interval(self):
        """扫描节奏:没单独配就用铃铛自己的下限;配了就夹到合法区间。

        下限比科举(0.4s)快一档:现在一轮只是截两块小图 + 1ms 门控,快得起。
        """
        import core
        gap = float(self.cfg("bell_interval", 0.0) or 0.0)
        if gap <= 0:
            return BELL_MIN_INTERVAL
        return min(core.MAX_INTERVAL, max(BELL_MIN_INTERVAL, gap))

    # ---- 扫哪:永远自动枚举客户端窗口(没有手动框这条路了) ----
    def regions(self):
        """扫描区域:**恒为一个**(降妖伏魔只管一台客户端)。

        优先级:用户在列表里选过的那台 > 只枚举到一台。
        枚举到多台又没选过时返回空 —— 界面会弹列表让用户按角色名选
        (见 `client_choices` / `gui.on_locate_clients`)。
        """
        import core
        want = str(self.cfg("bell_client") or "")
        try:
            found, _mini = core.find_client_windows()
        except Exception:
            return []
        if len(found) == 1 or not want:
            return ([[int(v) for v in found[0][1]]] if len(found) == 1 else [])
        for title, box in found:
            if title == want or client_name(title) == want:
                return [[int(v) for v in box]]
        return []

    def layout(self, region):
        """这个客户端尺寸量过的**对话框框**(相对窗口左上角);不支持返回 None。

        表里还带任务栏框(`trk`),由 `layout_trk` 单独读。
        """
        return layout_for((region[2] - region[0], region[3] - region[1]))

    def check_size(self, size):
        """自动定位到的客户端尺寸支持吗?不支持就记下来(界面轮询会弹窗)。

        只支持 640x480 / 800x600 两档客户端(实测窗口 815x680 / 1011x826)。
        返回 True = 支持。
        """
        w, h = int(size[0]), int(size[1])
        if supported_size((w, h)):
            self._bad_size = ""
            return True
        self._bad_size = f"{w}x{h}"
        return False

    def fixed_dialog(self, region):
        """分辨率表里这个尺寸的对话框框(绝对坐标);不支持返回 None 并提醒一次。"""
        dlg = self.layout(region)
        size = (region[2] - region[0], region[3] - region[1])
        if dlg:
            self.check_size(size)
            return abs_rect(region, dlg)
        if not self.check_size(size):
            label = f"{size[0]}x{size[1]}"
            if getattr(self, "_warned_size", "") != label:
                self._warned_size = label
                self.app.log(f"[{TAG}]客户端尺寸 {label} 不支持 —— 只支持 "
                             "640x480 / 800x600 两档分辨率,请在游戏设置里改一下")
        return None

    def dialog_rect(self, region):
        """对话框要扫的那块:**分辨率表 > 按窗口比例猜**(不支持的分辨率兜底)。

        表里的坐标是相对客户端窗口左上角的 —— 客户端挪了/改大小都不用重设。
        """
        # 自动枚举出来的永远是"整个客户端窗口",所以对话框一律查表/按比例

        dlg = self.layout(region)
        if dlg:
            return abs_rect(region, dlg)
        return rel_rect(region, DIALOG_BAND)

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

        科举那边截图/识别失败本来就记日志;这里以前是全 continue,
        出了事日志里一个字都没有,没法查。
        """
        if self._fail.get((what, key)) == str(err):
            return
        self._fail[(what, key)] = str(err)
        where = (key if isinstance(key, str)
                 else ",".join(str(v) for v in tuple(key)[:4]))
        self.app.log(f"[{TAG}]{what}失败({where}): {err}", ui=False)

    def _grab(self, screen, rect, what):
        """截一块;失败记一条(去重)并返回 None。"""
        try:
            crop = screen.grab(rect)
        except Exception as err:
            self._log_fail("截图", what, err)
            return None
        self._fail.pop(("截图", what), None)      # 恢复了:下次失败重新记
        return crop

    def _note(self, kind, text, now, base="", ui_text="", ui=True):
        """过程日志节流:内容变了就写,没变最多 LOG_GAP 秒写一条。

        不节流的话快路一轮一行,一分钟几百行 —— 界面那个 8 行的日志框直接废掉,
        keju.log 一小时能到十几兆。心跳那行不受影响,它自带 10 秒间隔。

        `ui_text` 是**界面上显示的那一份**(用户定的 2026-10-17):界面只要
        "任务栏 巧智魔 未发现坐标" 这种一眼能扫的短句,块数/耗时/读到啥/框多宽这些
        细节全留在文件里(文件里那条 msg 一个字没变)。给了 ui_text 就不带 `base`。
        `ui=False` = 这条**只进文件**(对话框那条读数就是:报了目标之后界面已经有
        一模一样的"对话框 巧智魔 朱紫国(59,52)",再刷一条就是重复 —— 用户定的)。
        """
        last = self._note_seen.get(kind)
        if last and last[0] == text and now - last[1] < LOG_GAP:
            return
        self._note_seen[kind] = (text, now)
        self.app.log(f"[{TAG}]{base}{text}", ui=ui,
                     ui_text=(f"[{TAG}]{ui_text}" if ui_text else None))

    def _read(self, ocr, crop, what, limit=OCR_LIMIT):
        """OCR 一块,返回 (文字块, 毫秒);失败返回 (None, 毫秒)。

        默认按 OCR_LIMIT 调小 det 的放大下限 —— 整窗那种大图本来就不会被放大,
        传了也一样;小区域能省一大半时间。
        """
        t0 = time.time()
        try:
            if limit:
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
        产品功能在用它:循环调的是无参 `tick()`),**没有"触发整窗扫"的含义**。
        again=True 只由"对话框读到新目标要当场再扫一遍"那一条发起(见下面那段);
        这一拍**任务栏那一支整支跳过**(理由见那一段的注释)。
        """
        st = self._slot.get(slot)
        if st is None or st.get("region") != tuple(region):
            # 区域变了(窗口被拖动 / 换了客户端):学到的位置作废、重学。
            # 顺带把"这个槽当前的目标"也清掉(2026-10-16 检视发现):不清的话,
            # 换了客户端/窗口挪了之后,新画面的目标会被判成"跟旧的一样"而不重报。
            # **`_last`(同一条不重复报)留着**:拖动窗口时每拍都会走这条路,
            # 清了它就会每拍重报同一条(刷屏);它也只是"同值不重报",不挡新目标。
            # **`hunt`(整窗找框的节流档位)也留着**:清零等于拖动时每 0.15s 整窗
            # OCR 一次(白烧)。
            _keep_hunt = (st or {}).get("hunt", 0)
            self._cycle.pop(slot, None)
            # **量过的尺寸:任务栏框直接用表里那个**(用户 2026-10-17:这个分辨率
            # 以后只扫这里,不再花 2~3 秒整窗找表头)。没量过的尺寸还是 None ->
            # 照旧现场扫整窗找「任务追踪」表头。
            _trk_seed = layout_trk((region[2] - region[0],
                                    region[3] - region[1]))
            st = {"region": tuple(region), "trk": _trk_seed,
                  "trk_fixed": bool(_trk_seed),   # 表里量的:不作废、不整窗
                  "miss": 0,
                  "trk_nohdr": 0, "dlg_pend": None,
                  "trk_last": None, "dlg_raw": None,
                  "trk_mode": "none",   # 没有对话框说过类型之前:不读任务栏
                  "hunt": _keep_hunt}   # 整窗找框没找着的次数(节流档位,见 HUNT_GAPS)
            if _trk_seed:
                self.app.log(f"[{TAG}]任务栏框用表里量的那格 "
                             f"{tuple(_trk_seed)}(这个尺寸只扫这里,不整窗找)",
                             ui=False)
            self._slot[slot] = st
        dialog = track = None
        panel_gone = False      # 这一拍连面板都没判出来(而不是"有面板但没读出坐标")

        # ---- 快路 1:对话框(位置固定) ----
        # 量过分辨率的客户端:位置是死的(用户实测:所有对话框都在那一块),
        # 直接按表裁、只拿"这块地方够不够暗"当"现在有没有对话框"的判据 ——
        # 不用 panel_box 去猜(暗场景里它会跟身后的暗区糊成一片,实测分不开)。
        fixed = self.fixed_dialog(region)
        crop = self._grab(screen, fixed or self.dialog_rect(region), "对话框")
        if crop is not None:
            if fixed:
                # 位置是死的(表里量的那块是最宽的那种对话框,是个**上界**):
                # 先在框里按像素收紧到实际面板 —— 窄一点的对话框(纯文字那种)
                # 就不会把左边那片游戏世界一起读进来;收不出来(暗场景糊成一片)
                # 就整块当面板用,宁可多读也不漏字。
                tight = panel_box(crop)
                _pf = panel_frac(crop)          # 同一拍只算一次
                # **滞回**:已经在"有面板"状态时用低 0.05 的线,别让暗比在阈值边上
                # 抖一下就把面板判没了(2026-10-17 实测:第二遍重扫撞上 0.59 vs 0.60,
                # 新坐标就这么丢了)。
                _thr = (DIALOG_DARK_FRAC - 0.05 if st.get("dlg_on")
                        else DIALOG_DARK_FRAC)
                if tight and _pf >= _thr:
                    box = tight
                elif _pf >= _thr:
                    box = (0, 0, crop.shape[1], crop.shape[0])
                else:
                    box = None
            else:
                box = panel_box(crop)
            on = box is not None
            if on != st.get("dlg_on"):
                st["dlg_on"] = on
                # **只进文件,不进界面**(用户定的 2026-10-17):面板出现/消失是
                # 环境噪音(录像里、切场景时来回跳),界面上刷它没意义;
                # 查问题时 `keju.log` 里照样有。
                self.app.log(f"[{TAG}]对话框面板"
                             f"{'出现' if on else '消失'}"
                             f"(暗比 {panel_frac(crop):.2f})", ui=False)
            if box:
                self._stat["dlg"] += 1
                # 面板里的内容一变(点 NPC 翻页)就马上重读;没变才按 DIALOG_GAP
                # 的节奏兜底。**签名要用"上次读的时候那个框"**:panel_box 的边
                # 会抖 ±4 像素,拿当轮的框去算,光是抖动就有 18~35 的差,比"换了
                # 一段对话"(15~38)还大 —— 框固定住,抖动就没了。
                psig = panel_sig(crop, st.get("dlg_rect") or box)
                changed = (st.get("dlg_psig") is not None
                           and sig_diff(psig, st["dlg_psig"]) >= SIG_MIN)
                # 确认**不是铃铛任务**的对话框(买东西/闲聊那些):内容没变就别按
                # 节奏重读了 —— 真机上这种占八成,每次白烧一百多毫秒。
                due = (now - st.get("dlg_ts", 0.0) >= DIALOG_GAP
                       and st.get("dlg_bell", True))
                # **有待确认的新坐标时,0.3 秒就再读一遍**(用户定的"立刻马上再读一次,
                # 两次相同放行"):重扫那拍要是撞上面板闪一下/读花,别干等 2 秒的
                # `DIALOG_GAP` —— 而 `dlg_bell` 被那一拍置成 False 之后根本不会再读
                # (2026-10-17 实测:值挂着、红点一直不刷新)。TTL 到点 `dlg_pend`
                # 会被清掉,所以这里不会无限读。
                if (st.get("dlg_pend") is not None
                        and now - st.get("dlg_ts", 0.0) >= 0.3):
                    due = True
                if force or again or not st.get("dlg_seen") or changed or due:
                    # 只把面板**有字的那一截**喂给 OCR:不带身后的游戏世界,
                    # 也不带上方的任务栏(它那两行也会带坐标,混进来会被当成
                    # "对话框说的"),更不带面板下半截那片空白
                    part = panel_text_cut(crop, box)
                    blocks, ms = self._read(ocr, part, "对话框")
                    st["dlg_ts"] = now
                    if blocks is not None:
                        st["dlg_seen"] = True
                        # 对话框里那句可能是"踪迹在…"也可能是"去X(x,y)使用招魂帖",
                        # 两种都算对话框说的 —— 别只取一种把招魂帖那种漏掉
                        d, t, _w = scan_bell_parts(blocks, scoped=False)
                        dialog = d or t
                        # 这一拍面板上读到的**原文**:开新周期时拿它定任务类型
                        # (类型只由对话框给,见 `_publish` / `trk_plan`);另外它还要
                        # 过下面那道"话术门槛"
                        st["dlg_raw"] = "".join((b.get("text") or "")
                                                for b in blocks)
                        # **话术门槛**(用户定的 2026-10-16,表见 `BELL_WORDS`):
                        # 这一段文字里一个"铃铛任务的核心词"都没有 -> 里面的"图名+坐标"
                        # 当读花,不认。挡的是"面板收紧失败(整块当面板)时把下方聊天/
                        # 世界频道一起读进来"那种**静态行** —— 它两遍必然读成一样,
                        # "两遍一致"挡不住它。**只在对话框这条主路吃门槛**,任务栏那支
                        # 不吃(悬停那行单独读出来时没有核心词)。
                        if dialog and not has_bell_words(st["dlg_raw"]):
                            self._stat["dlg_gate"] += 1
                            self._note("话术门槛", f"面板里读到 {_spot(dialog)},"
                                       "但那一段里没有铃铛任务的核心词 —— 当读花,"
                                       "这一段不认", now, "话术门槛 ")
                            dialog = None
                        st["dlg_text"] = dialog
                        # hover 档(巧智魔/怯弱妖)的"收手话术"(用户定的 2026-10-16):
                        # 对话框里出现这些(见 `HOVER_STOP_WORDS`)说明追/逃那一段结束了
                        # -> 这个周期不再扫任务栏。**只有 hover 档有这条**,`none`/`item`
                        # 一个字都不动;也不拿它去推断类型什么的。
                        # (这一段读的原文跟"有没有坐标"无关:收手话术那几句都没有坐标,
                        #   被上面那道门槛挡下也不影响它 —— 见 `hover_stop` 的用例。)
                        stop = hover_stop(st["dlg_raw"])
                        if stop and st.get("trk_mode") == "hover":
                            st["trk_mode"] = "none"
                            self.app.log(f"[{TAG}]对话框出现收手话术({stop})"
                                         " —— 这个周期不再扫任务栏")
                        st["dlg_bell"] = bool(dialog)     # 这块面板是不是铃铛任务
                        if dialog:
                            # 界面上**不写这条**(用户定的 2026-10-17):报出目标时会有
                            # "对话框 巧智魔 朱紫国(59,52)" 那条,内容一模一样;
                            # 细节(块数/耗时/读到啥)留在文件里。
                            self._note("对话框", read_note(
                                "对话框条带", (part.shape[1], part.shape[0]),
                                len(blocks), ms, dialog, blocks), now, "识别 ",
                                ui=False)
                        else:
                            # 不是铃铛任务:不逐条刷日志,心跳里汇总(带一条样本)
                            self._stat["dlg_other"] += 1
                            st["dlg_sample"] = (part, blocks, ms)
                            # **公告对话框却没解析出坐标**:把原文整段记一笔(只进
                            # 文件,`_note` 自带 10 秒节流)。2026-10-17 16:59 实测:
                            # 「接下来你们遇到的将是一只狡猾的迷幻妖。想要抓住它,可」
                            # 只读到第一句、坐标那句没进 OCR —— 整轮新目标丢掉,红点
                            # 挂在上一轮(用户:"为什么不刷新")。心跳那行只留 26 个字,
                            # 看不出"字被裁掉了"还是"读花了",所以要原文。
                            _raw = st.get("dlg_raw") or ""
                            if has_bell_words(_raw) and any(
                                    w in _raw for w in ("迷幻妖", "梦魇魔",
                                                        "巧智魔", "怯弱妖",
                                                        "逐妖蛊虫")):
                                self._note("公告原文", _raw[:120], now,
                                           base="公告对话框只认出怪名、没坐标 —— "
                                                "原文: ", ui=False)
                        # 框和签名**一起**记:下一轮拿这个框算签名,形状才不会变
                        st["dlg_rect"] = box
                        st["dlg_psig"] = panel_sig(crop, box)
                else:
                    dialog = st.get("dlg_text")      # 面板还在、字没变:沿用上次读的
            else:
                st["dlg_seen"] = False
                st["dlg_text"] = None
                st["dlg_bell"] = True                 # 面板没了:下次按"要读"算
                panel_gone = True
                # **`dlg_pend` 别在这儿清**:面板闪一下(实测暗比 0.59 vs 阈值 0.60)
                # 就把待确认的新坐标扔了 —— 交给下面那个 `PEND_TTL`。
                # **签名和框留着**(别清):`panel_sig` 拿它当基准比"面板里的字变了
                # 没有"(变了当拍就重读),框固定住还能免掉 `panel_box` 边抖 ±4px
                # 带来的假变化。面板闪一下又回来时签名一样,不会白重读。

        # 对话框认到了**新的目标**:**立刻马上再读一次,两遍读到同一个值才放行**
        # (用户定的 2026-10-16 傍晚:「对话框里读出了新的目标后,立刻马上再读一次,
        # 两次相同放行」)。对话框里的目标永远是对的 —— 这条要防的是**我们自己读花**:
        # 实测踩过 23:51 把「建邺城(101,127)」读成「建邺城(24,108)」(两个都落在建邺城
        # 的范围内,`in_bounds` 挡不住),当场把红点挪到了错地方。
        # 规矩:读到和当前目标不一样的值 -> 记进 `st["dlg_pend"]`、**不覆盖**(报出去的
        # 目标不动)、`again=True` **当场**重扫一次同一块面板;第二遍还是这个值 ->
        # 采信并报出去(红点多花一次 ~180ms,买的是"不把读花报给用户");读回原值 ->
        # 刚才那次是读花,丢掉。第一遍读到的值**不进 `_cycle`**、也不更新界面。
        if dialog:
            cur = self._cycle.get(slot)
            if dialog == st.get("dlg_pend"):
                if cur:
                    self.app.log(f"[{TAG}]对话框改口: {_spot(dialog)}"
                                 "(同一个值连读两次),以它为准")
                else:
                    self.app.log(f"[{TAG}]对话框 {_spot(dialog)}"
                                 "(连着两遍读到一样),以它为准")
                st["dlg_pend"] = None
                st["dlg_gone"] = 0.0          # 这一拍读到了:TTL 计时归零
                # 开新周期要做的两件事(清任务栏那边的残留 + 拿对话框的文字定
                # 任务类型)**都由 `_publish` 在周期真的换了那一刻统一处理**,
                # 这里不碰状态。周期里的目标下一轮(0.15s 后)才看任务栏那块。
                if self._publish(slot, dialog, "对话框"):
                    return True
            elif dialog == cur:
                st["dlg_pend"] = None         # 又读回原值:刚才那次是读花
            elif not again:                   # 这一轮还没为第二遍回过头
                st["dlg_pend"] = dialog
                # **TTL 从"这一拍读不到"开始算**(2026-10-17 15:05 实测抓出来的):
                # `dlg_gone` 是"面板上次消失"的时刻,只要面板隔一阵就藏一下,它
                # 一直是老值 —— 不复位的话,新记下的 pend 会在下一拍"面板不见了"
                # 直接判超时(now - 老时刻 > 10 秒),等于单发就被扔了。
                # 真机就是这条把「西梁女国(99,36)」连读两次都丢了(两遍都写"先不覆盖")。
                st["dlg_gone"] = 0.0
                if cur:
                    # **只进文件**(用户定的 2026-10-17):这条是"第一遍不采信"的过程行,
                    # **每接一个新任务都会出现一次**,界面上留结果(紧跟的"以它为准"/
                    # "改口")就够了 —— 不然每轮两条、看着像在报错。
                    self.app.log(f"[{TAG}]对话框读到 {_spot(dialog)},和当前目标 "
                                 f"{_spot(cur)} 不一样 —— 先不覆盖,立刻重扫一次",
                                 ui=False)
                else:
                    self.app.log(f"[{TAG}]对话框读到 {_spot(dialog)} —— "
                                 "先不采信,立刻重扫一次(两遍一样才算)", ui=False)
                return self._scan(slot, region, screen, ocr, True, now,
                                  again=True)
        else:
            # 这一拍没读出目标(面板闪了一下 / 换成了没坐标的一句 / 没认出来):
            # **别立刻作废待确认的那个值** —— 2026-10-17 15:38:44 实测:第二遍重扫
            # 那一拍面板暗比 0.59(阈值 0.60)被判"消失",(108,26) 就这么丢了,红点
            # 一直不刷新。现在给个 TTL:面板消失/读不到**持续超过 `PEND_TTL`** 才作废
            # (TTL 之外它还挂着的话,下一句恰好读出同一个值就会**单发**命中,
            #  等于绕过"两遍一致" —— 所以必须有这个上限)。
            pend = st.get("dlg_pend")
            if again and panel_gone and pend:
                # 复读那一拍**面板已经关了**(用户手快/对话自动关):第二遍根本读不到,
                # 等下去也等不来"两遍一致",整轮任务就这么丢了(2026-10-17 16:06 实测:
                # 「宝象国(149,53)」刚读到、面板就没了,红点一直挂在上一轮)。
                # 对话框里的目标是权威的 —— 这一种情况**直接用第一遍的值**。
                st["dlg_pend"] = None
                st["dlg_gone"] = 0.0
                self.app.log(f"[{TAG}]对话框复读那一拍面板已经关了 —— 直接用第一遍"
                             f"读到的 {_spot(pend)}(两遍一致做不了)", ui=False)
                if self._publish(slot, pend, "对话框"):
                    return True
            if not st.get("dlg_gone"):
                st["dlg_gone"] = now
            if now - st["dlg_gone"] >= PEND_TTL:
                st["dlg_pend"] = None

        # ---- 快路 2:任务栏(只在"这轮任务需要它"时才读) ----
        # 用户定的规矩:只有逐妖蛊虫(用道具后任务栏换一条新坐标)、巧智魔、怯弱妖
        # 这3类任务才关心任务栏;其余(招魂帖/招魂幡/梦魇魔/迷幻妖)坐标对话框里就有
        # —— **一次都不读、也不去找框**。
        # **类型由对话框给**(`_publish` 里按 `trk_plan(对话框文字)` 写进 `trk_mode`):
        # 还没开过周期(没对话框说过类型)时默认 `none` —— 任务栏一次都不读。
        # 任务栏那份文字只用来**拿第二个坐标**,永远不参与定类型。
        # "还没有确定位置的框"时这一拍读的是**整窗**(找「任务追踪」表头)——
        # 定位到框就是它自己的事:整窗只出现在这条分支上(见下面那条看门狗)。
        mode = st.get("trk_mode", "none")
        rect_known = False
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
            track = st.get("trk_text")
        elif mode == "none":
            track = st.get("trk_text")        # 不读:沿用这个周期里已经拿到的
            self._stat["skip"] += 1
        elif (st.get("trk") is None and st.get("hunt_pause")
              and now - st["hunt_pause"] < HUNT_PAUSE):
            # 冷却中:**不整窗**(2~3 秒),只用"上次那个框"的位置做一次廉价小读
            # (~0.2 秒)。面板回来了就立刻恢复、不用等冷却走完 —— 2026-10-17 实测:
            # 面板回来时还在冷却里,白等半分钟,逐妖蛊虫的第二坐标就漏了。
            self._stat["skip"] += 1
            track = st.get("trk_text")
            hint = st.get("trk_hint")
            if hint and now - st.get("hint_ts", 0.0) >= 1.5:
                st["hint_ts"] = now
                blocks, _ms = self._read(
                    ocr, self._grab(screen, abs_rect(region, hint), "任务栏"),
                    "任务栏")
                if blocks and any(_is_hdr(b.get("text")) for b in blocks):
                    st["trk"] = hint          # 面板回来了、位置没变:框恢复
                    st["trk_hint"] = None
                    st["hunt_pause"] = None
                    st["hunt"] = 0
                    self.app.log(f"[{TAG}]面板回来了(位置没变) —— 框恢复,继续盯",
                                 ui=False)
        else:
            trk = st.get("trk")
            if trk:
                # 学到的框:只扫那一块;**超出扫描区就往内挪**(宽高不变,见 `fit_rect`)
                rect = abs_rect(region, trk)
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
            else:
                # 还没有框:**扫整窗去找**(不按比例猜一块 —— 任务栏在游戏里能随便
                # 拖,猜出来的位置没有依据;分辨率表里也**不存任务栏坐标**,所以
                # "确定位置的框"只可能来自"学到的")。只有逐妖蛊虫/巧智魔/怯弱妖
                # 这3类任务会走到这儿(其余类型在上面 mode=="none" 就短路了)。
                # 上面那条表头看门狗作废框之后,下一拍也落回这里 —— 重锚就是这段代码。
                rect = tuple(int(v) for v in region)
            rect_known = bool(trk)             # 有"确定位置"的框 = 学到一个了
            # 读的到底是哪块,日志里就写哪个名:没有学到的框时读的就是整个
            # region(整个客户端窗口),那一拍写"整窗"
            what = "任务栏" if rect_known else "整窗"
            # 鼠标停在任务栏那块**及其周围** = 悬停坐标可能出来了(巧智魔/怯弱妖)。
            # 只要求"压在框上"太严:玩家会把鼠标挪到面板的文字行、panel 的边角上。
            cur = cursor_pos()
            near = in_rect(cur, rect, grow=HOVER_GROW)
            # **hover 档:鼠标不接近就整支跳过**(用户定的 2026-10-16)—— 那行
            # 「在X(x,y)处」只有玩家把鼠标压到任务栏上才显示,没鼠标读它纯属白花
            # OCR。**连"还没框时的整窗找框"也一并跳过**(没鼠标就没有悬停行,早学到
            # 框没用;鼠标一接近,第一个 `near` 的那一拍自然会去找)。不打日志(省得
            # 刷屏,心跳里能看到节奏)。**item 档不受影响**:逐妖蛊虫的坐标是任务栏里
            # 直接写着的,跟鼠标无关,照旧 0.5s 盯。
            if mode == "hover" and not near:
                self._stat["skip"] += 1
                crop = None
                crop_rect = None
                # **鼠标和任务栏框对不上时,把两边坐标写进文件**(用户 2026-10-17 报
                # "鼠标移到任务栏还是没有快扫"时加的诊断):只看"跳过"数分不清是
                # "鼠标真不在附近"还是"框学歪了/窗口尺寸变了" —— 有这两组坐标一眼就知道。
                # 5 秒最多一条(鼠标一直在动,不节流会刷屏),只进 keju.log。
                if cur and now - st.get("hover_warn_ts", 0.0) >= 5.0:
                    st["hover_warn_ts"] = now
                    self.app.log(
                        f"[{TAG}]悬停:鼠标 {tuple(int(v) for v in cur)} 不在任务栏框 "
                        f"{tuple(int(v) for v in rect)} ±{HOVER_GROW} 里 —— 这一拍不读"
                        "(把鼠标挪进那个框;框不对就点「自动定位」重新找)", ui=False)
            else:
                # **悬停档永远往上多留一截**(用户定的 2026-10-16 上一条):那行画在
                # 「降妖伏魔」标题**上方**,不往上扩就永远落在裁剪之外。鼠标走近了才
                # 会读到(上面那道门),所以这里光标是真位置、`hover_rect` 的
                # ±260/±90 那圈也照旧带上;往上留的那 120px 才是必须的那一截
                # (224×180 -> 224×300)。
                crop_rect = (hover_rect(rect, cur, region)
                             if (mode == "hover" and rect_known) else rect)
                crop = self._grab(screen, crop_rect, what)
            if crop is not None:
                # 盯着看时 0.25 秒一读(悬停那一行可能只闪一下);重试时按
                # TRK_GAP/TRK_GAP_IDLE。**像素差分在这儿没用**:面板是半透明的,
                # 身后世界一直在动,同一段文字相邻两帧差分就有 8~50。
                gap = st.get("trk_gap", TRK_GAP)
                if not rect_known:
                    # 还没有学到的框:这一拍读的是**整窗**(用来找「任务追踪」表头)。
                    # 节流按"连着几次没找着"逐步放宽(见 `hunt_gap` / `HUNT_GAPS`),
                    # 学到框立刻回第一档 —— 一直找不到时别每 0.25s 就整窗扫一次。
                    gap = hunt_gap(st.get("hunt", 0))
                if force or again or now - st.get("trk_ts", 0.0) >= gap:
                    blocks, ms = self._read(ocr, crop, what)
                    st["trk_ts"] = now
                    if not rect_known:
                        # 这一拍读的是整窗,不是"框里读不到字" —— miss 归零。
                        # "找框"的次数也在这儿累加:**先当成"没学到"**,真学到了在
                        # 下面 learn 分支里归零(节流见 `HUNT_GAPS`)。
                        st["miss"] = 0
                        st["hunt"] = st.get("hunt", 0) + 1
                    if blocks is not None:
                        # ---- 唯一的作废判据:框里读到了字、却没有「任务追踪」表头 ----
                        # 框是"位置记忆"(学下来的框):玩家把任务栏拖走了,它就一直
                        # 指着旧地方(读回来的是身后的场景文字)。连着 TRK_NOHDR_MAX
                        # 次做不到表头就认定被拖走了 —— 把框作废,下一拍快路走
                        # "还没有框"那一支:读整窗重新定位(同一段代码)。
                        # **只认"读到了字"**:一个字都没读到是"面板被藏起来了"
                        # (实测约占一半时间,那是正常的,下面只记数不作废)。
                        # **表里量过的框不作废**(用户 2026-10-17:这个尺寸只扫这里):
                        # 面板被别的界面藏住时读到的是别处的字,那条判据会把框误作废,
                        # 接着就是 2~3 秒一次的整窗重锚(就是"卡死"那套)。量过的框
                        # 直接信表,面板藏了就等它回来(空读那条看门狗照旧记数)。
                        if rect_known and blocks and not st.get("trk_fixed"):
                            if any(_is_hdr(b.get("text")) for b in blocks):
                                st["trk_nohdr"] = 0
                            else:
                                st["trk_nohdr"] = st.get("trk_nohdr", 0) + 1
                                if st["trk_nohdr"] >= TRK_NOHDR_MAX:
                                    st["trk_nohdr"] = 0
                                    st["trk_hint"] = st["trk"]   # 记下老位置:
                                    # 冷却期间拿它做廉价小读,面板一回来就能立刻恢复
                                    st["trk"] = None
                                    self.app.log(
                                        f"[{TAG}]框里连着 {TRK_NOHDR_MAX} 次没读到"
                                        "「任务追踪」表头 —— 任务栏多半被拖走了,"
                                        "作废这个框;下一拍整窗重锚一次")
                        # 任务栏那行也可能是"去X(x,y)使用逐妖蛊虫"这种(用道具后
                        # 刷出来的新坐标)—— 它在 scan_bell_parts 里归到 dialog
                        # 那一类,只取 track 会把它整个丢掉。
                        # 鼠标停在任务栏上时**不做标题圈范围**:悬停行在标题上面,
                        # 而且标题常被读花("降双快通"/"降欢风衡"),一 scoped 就全丢。
                        # 读的是整窗那一拍就传 `wide=True`:大字面里混着聊天/别的
                        # 任务的行,两条"光秃秃的图名+坐标"兜底一律不用(见
                        # `scan_bell_parts` 的 docstring)。
                        scoped = not near
                        d3, t3, _w = scan_bell_parts(
                            blocks, scoped=scoped, wide=not rect_known)
                        # 取 d3 or t3 是**必须**的:任务栏那行"去X(x,y)使用逐妖蛊虫"
                        # 在 scan_bell_parts 里归到 dialog 那一类,只取 t3 会把它丢掉。
                        # 但它在这里只当"任务栏报的值"(带"见过两次"复核),**不**算
                        # "对话框说的" —— 用户定的:对话框只认上面面板带那条主路,
                        # 整窗读到的字不参与开周期。
                        got = d3 or t3
                        # **整窗那一拍只用来定位任务栏**(用户定的 2026-10-17):它读的
                        # 是整个窗口、字面太杂(里面就有对话框自己那条「去X(x,y)…」),
                        # 拿它取值/记历史/收手都会出错 —— 所以这一拍:不取值、不进
                        # "见过两次"的历史、不发布、也不收手,只交给下面的"学框"那一段。
                        hist = st.setdefault("trk_hist", [])
                        if rect_known:
                            hist.append(got)
                            del hist[:-TRK_HIST]
                        text = "".join((b.get("text") or "") for b in blocks)
                        hover = _hit(text, _RE_BELL_HOVER) is not None
                        # 大字面供值:**临时**统计行(量完可以删)—— 还没有确定
                        # 位置的框时这一拍读的就是整个 region(整个客户端窗口),
                        # 看看它到底供过几次值、每次是哪条文法命中的。被 wide
                        # 规则挡下的那些单独记一笔(同一套文法顺序判"本该哪条命中"),
                        # 好用真机日志量"收紧得够不够、会不会漏"。
                        # 都只进 keju.log(ui=False),不刷小窗那个日志框。
                        if got and not rect_known:
                            self.app.log(
                                f"[{TAG}]大字面供值: {_spot(got)}"
                                f"[机制={bell_form(text, wide=True) or '?'}]",
                                ui=False)
                        elif not rect_known:
                            wd, wt, _w = scan_bell_parts(
                                blocks, scoped=scoped, wide=False)
                            loose = wd or wt
                            if loose:
                                self.app.log(
                                    f"[{TAG}]大字面供值: {_spot(loose)}"
                                    f"[机制={bell_form(text) or '?'}"
                                    ",已被 wide 规则挡下]", ui=False)
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
                        # 还得**先知道任务栏在哪**(rect_known):框还没定位时这一拍读的
                        # 是整窗,随便一句"在X(x,y)处"都可能撞上来,不能单次就认;
                        # 而且那一拍**根本不该取值**(整窗只用来定位,见上面)。
                        if rect_known and got and (
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
                            st["trk_text"] = got   # 本周期认下来的那条(开新周期清)
                            # trk_last 跨周期留着:开新周期时用它当"屏幕上那条旧行"
                            # (`trk_stale`),防游戏的刷新延迟把红点带回旧坐标。
                            st["trk_last"] = got
                            if ok_re:
                                track = got
                        # 这一轮读完,决定下一轮还读不读、读多勤
                        if not blocks:
                            # 任务栏整块没显示(实测约一半时间):**只记数 + 留一条
                            # 诊断日志,永远不作废框、也不整窗**(用户定的 2026-10-16)。
                            # 空读不代表被拖走 —— 面板被游戏藏起来是正常的(战斗中/
                            # 切场景时它就不画),而且这三类任务要拿坐标时玩家本来就
                            # 得开着面板;作废+重锚一次要耗 8×0.25s ≈ 2 秒,过不了
                            # "快"这条红线。真要作废只有一条判据:"读到了字、却没有
                            # 「任务追踪」表头"(上面那条)。
                            # 但**"正盯着等坐标"的两种档不许慢下来**:
                            #   item(逐妖蛊虫):等用道具后刷出来的第二个坐标 ——
                            #     0.5s 一直盯到"同一个坐标连读两次"才收手;
                            #   hover(巧智魔/怯弱妖):等鼠标压上去才冒出来的那行,
                            #     只闪一下,同样不能退避(用 HOVER_GAP)。
                            # 一退避就可能正好漏掉它刚出现的那一下 —— 而这两种
                            # 一读不到字就退回 1.0s、而且**整段周期都不会再调回来**,
                            # 等于后面的等待全变慢了一倍。
                            st["miss"] = st.get("miss", 0) + 1
                            st["trk_gap"] = (watch_gap(mode) if mode != "none"
                                             else TRK_GAP_IDLE)
                            if st["miss"] >= TRK_MISS_MAX:
                                # 连着这么多次"一个字都没读到":写一条诊断日志就完,
                                # **不动那个框**(面板这会儿没显示而已)。计数归零,
                                # 免得每拍都写(它只是个"面板怎么老不开"的信号)。
                                st["miss"] = 0
                                self.app.log(
                                    f"[{TAG}]任务栏那块连着 {TRK_MISS_MAX} 次"
                                    "读不到字 —— 面板这会儿没显示(位置照旧留着,"
                                    "不作废)", ui=False)
                        else:
                            st["miss"] = 0
                            # **只有"学到框"的那些拍才有资格收手**(用户定的
                            # 2026-10-17):整窗那一拍只负责定位任务栏 —— 它一个字都
                            # 不取值,更不该拿它把这一轮收掉(收了就再也不会读了)。
                            if not rect_known:
                                pass
                            elif mode == "item":
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
                                             or st.get("trk_pub") == hist[-1])):
                                    st["trk_mode"] = "none"
                                    self.app.log(f"[{TAG}]任务栏新坐标连着读到"
                                                 f"两次,盯完(这轮不再读任务栏)")
                            elif (mode == "hover" and got and hover
                                  and got != self._cycle.get(slot)):
                                # 巧智魔/怯弱妖的"第二坐标"= **悬停那行** + **跟对话框
                                # 给的坐标不一样**才收手(用户定的 2026-10-17)。三条
                                # 都是被真机日志逼出来的:
                                #   ① 只看"读到一个坐标"不够 —— 还没学到框 / 框刚被
                                #      作废时那一拍读的是**整窗**,里面就有对话框自己
                                #      那条「去X(x,y)…」→ 当场收手,之后鼠标压上去也
                                #      不读(日志里"盯完 → 从整窗学到框 → 识别 整窗"
                                #      三行同秒出现,就是这么来的)。现在整窗那拍连值
                                #      都不取(见上面),外面还有 `rect_known` 兜着;
                                #   ② 命中的必须是**悬停那行**(`hover`) —— 任务栏里
                                #      别的坐标(比如别条任务的行)不算;
                                #   ③ 还得**≠ 对话框给的坐标**(`got != _cycle[slot]`):
                                #      相等就不是"第二坐标",这一轮接着盯。
                                #      (`_publish` 在这之后才跑,所以这里 `_cycle` 还是
                                #       对话框那条 —— 拿它当"对话框坐标"是准的。)
                                st["trk_mode"] = "none"
                                self.app.log(f"[{TAG}]任务栏坐标读到了(悬停那行),盯完"
                                             "(这轮不再读任务栏)")
                        learned = ""
                        if blocks and not rect_known:
                            # 就在这一小块里学到框了 —— 没有确定位置的框时,"这一
                            # 小块"就是整个 region(整窗里找到「任务追踪」表头 +
                            # 「降妖伏魔」标题就定得出框),这条就是整窗重锚本身。
                            box = track_rect(
                                blocks, (crop.shape[1], crop.shape[0]))
                            if box:
                                st["trk"] = (
                                    rect[0] - region[0] + box[0],
                                    rect[1] - region[1] + box[1],
                                    rect[0] - region[0] + box[2],
                                    rect[1] - region[1] + box[3])
                                st["trk_hist"] = []
                                st["trk_gap"] = watch_gap(mode)
                                st["hunt"] = 0     # 学到了:整窗找框的节流回第一档
                                st["hunt_pause"] = None   # 学到了:冷却解除
                                # 只进文件(用户定的 2026-10-17):界面上那一拍只说
                                # "整窗 定位到任务栏",框的具体坐标是给调参看的。
                                self.app.log(f"[{TAG}]从{what}学到框 "
                                             f"{tuple(int(v) for v in st['trk'])}",
                                             ui=False)
                                learned = (" 学到任务栏框 "
                                           f"{tuple(int(v) for v in st['trk'])}")
                            elif not rect_known:
                                # 学不到框时**写清是哪一道关没过**(2026-10-17):
                                # 以前只能看到"没学到",分不清"面板没显示"还是
                                # "面板在、但标题读花了" —— 这两种修法完全不同。
                                _hdr = any(_is_hdr(b.get("text")) for b in blocks)
                                learned = (" 没学到任务栏框(" + (
                                    "有「任务追踪」表头、没认出「降妖伏魔」标题"
                                    if _hdr else "整窗里没有「任务追踪」表头")
                                    + ")")
                                if st.get("hunt", 0) >= HUNT_PAUSE_AFTER:
                                    # 连着几次整窗都没学到框:面板压根没显示(被别的
                                    # 界面盖住/切场景),再扫也扫不到 —— 歇一会儿。
                                    st["hunt_pause"] = now
                                    st["hunt"] = 0
                                    self.app.log(
                                        f"[{TAG}]整窗连着 {HUNT_PAUSE_AFTER} 次都没"
                                        "学到任务栏框(面板这会儿没显示) —— 歇 "
                                        f"{HUNT_PAUSE:.0f} 秒再找,免得每次 2~3 秒的"
                                        "整窗 OCR 把机器拖住", ui=False)
                        # 界面上那一份(用户定的格式):整窗那一拍只说定位到没有;
                        # 任务栏那一拍说"类型 + 图名(坐标)",没读到坐标就写"未发现坐标"。
                        if not rect_known:
                            _ui = ("整窗 定位到任务栏" if learned
                                   and "学到任务栏框" in learned
                                   else "整窗 未定位到任务栏")
                        else:
                            _ui = " ".join(p for p in (
                                "任务栏", bell_kind(st.get("dlg_raw")),
                                ui_spot(got) or "未发现坐标") if p)
                        self._note(what, read_note(
                            what, (crop.shape[1], crop.shape[0]),
                            len(blocks), ms, got, blocks)
                            + (" 悬停" if near else "") + learned
                            + edge_note(crop_rect, region), now, "识别 ",
                            ui_text=_ui)

        # 兜底:对话框那条主路认到了新目标、但当拍**没报成**(面板带那条路提前
        # return 掉了,或者值越界/跟上次一样被 `_publish` 挡了)—— 这儿再走一次
        # `_publish`(周期真换了的话,残留清理 + 定类型都在里面)。
        # (整窗那一拍读到的字**不当"对话框说的"**:它只走任务栏那套判据,
        # 对话框只认面板带那条主路。)
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
                    and track != st.get("trk_stale")
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
                         "坐标范围内,当成数字读花,先不报", ui=False)
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
                st_ = self._slot.setdefault(slot, {})
                mode = trk_plan(st_.get("dlg_raw") or "")
                st_["trk_mode"] = mode
                st_["trk_gap"] = (watch_gap(mode) if mode != "none"
                                  else TRK_GAP)
                st_["trk_stale"] = st_.get("trk_last")
                st_["trk_hist"] = []
                st_["trk_pub"] = None
                st_["trk_text"] = None
                st_["dlg_pend"] = None
                # 新周期开始 = 玩家接了个新任务:**整窗找框的冷却/计数一并归零**,
                # 别让上一轮的冷却拖住这一轮(2026-10-17:实测面板回来时还在冷却里,
                # 白白等半分钟 -> 逐妖蛊虫的第二坐标就漏了)。
                st_["hunt_pause"] = None
                st_["hunt"] = 0
                # 只进文件(用户定的 2026-10-17):界面上那句"开新周期"不再刷
                # ("报出目标[来自对话框]"那条已经说明同一件事,周期分色也认它了)。
                self.app.log(f"[{TAG}]{CYCLE_LOG_MARK}:任务栏这轮{_plan_note(mode)}",
                             ui=False)
        if self._last.get(slot) == bell:
            return False
        self._last[slot] = bell
        if src == "任务栏":
            # 记下"这个周期里任务栏报出去的那条":逐妖蛊虫靠它判"新坐标已经到手,
            # 不用再盯了"(见 item 那段)。
            self._slot.setdefault(slot, {})["trk_pub"] = bell
        self.spot = bell
        self.target = f"{bell[0]} ({bell[1]},{bell[2]})"
        # 界面上换成短句(用户定的 2026-10-17):「对话框 巧智魔 朱紫国(59,52)」。
        # **来源是任务栏的那条不进界面** —— 任务栏那一拍的读数行已经写着
        # "任务栏 <类型> <图名>(坐标)" 了,再来一条就是重复。
        _ui = " ".join(p for p in (src, bell_kind(
            (self._slot.get(slot) or {}).get("dlg_raw")),
            ui_spot(bell)) if p)
        self.app.log(f"[{TAG}]妖魔位置: {bell[0]} ({bell[1]},{bell[2]})"
                     f"[来自{src}]",
                     ui=(src == "对话框"),
                     ui_text=(f"[{TAG}]{_ui}" if src == "对话框" else None))
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
            part, blocks, ms = st.pop("dlg_sample", (None, None, None))
            if blocks is not None:
                bits.append("样本:" + read_note(
                    "对话框", (part.shape[1], part.shape[0]), len(blocks),
                    ms, None, blocks))
        for slot, s2 in sorted(self._slot.items()):
            bits.append(f"槽{slot}: 任务栏"
                        + ("有框" if s2.get("trk") else "还没学到")
                        + f"/节奏{s2.get('trk_gap', TRK_GAP):.2f}s"
                        + ("/有坐标" if s2.get("trk_text") else ""))
        # **只进文件,不进界面**(用户定的 2026-10-17):心跳是"这 10 秒扫了几轮 /
        # 白烧了几次"的体检数字,界面上刷它只是噪音;要看就去 keju.log 里 grep
        # 「扫描心跳」(它自带那段时间的轮数/OCR 数/跳过数/样本)。
        self.app.log(f"[{TAG}]扫描心跳: " + " ".join(bits), ui=False)
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
                self.app.log(f"[{TAG}]出错: {e}", ui=False)
            time.sleep(max(0.0, self.interval() - (time.time() - t0)))
