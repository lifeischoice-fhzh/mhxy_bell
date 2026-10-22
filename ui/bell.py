"""降妖伏魔小窗:地名 + 坐标 + 底图红点(深色 HUD,2026-10-21 用户选的 A 方案)。

界面只有四样东西:地名、坐标、地图上的红点、角色名。**不出现"监听/定位"这类
交代程序在干什么的文案**(用户定的 2026-10-21):换客户端收成右下角一个无文字的
↻;没有目标时画布上只写「暂无目标」。坐标用等宽数字(位数对齐),地名用雅黑。

build_bell 只建控件;draw_bell 只碰画布(底图缩放/红点按 tools.bell 的标定算,
方向 ui→tools,允许);抽屉只摆控件,动作都回到 App(app.on_map_import /
app.on_map_btn / app.on_map_detail)。**采集只是从界面移除**(用户定的
2026-10-20,底图内置):抽屉控件与回调全保留,要开放时把「地图采集」按钮
加回去、command 指回 on_map_import 就行。日志只进 bell.log。
"""
import re

import core
from tools import bell as tools_bell
from ui import widgets as ui_widgets

# ---- 降妖伏魔小窗 ----
PAD = 14                            # 窗口左右留白(地图 380 + 两边 14)
MAP_W = 380                         # 画框宽固定
# 画框高固定:380x300(比例 1.27)。比 400x280 更竖一档 —— 长寿村能从 214 宽
# 长到 229,代价是建邺城那种 2:1 的图上下的留边更多。换图时窗口**不跳高度**
# (2026-10-21 用户定的:长寿村把窗口撑到 696 太突兀)。底图在框里等比居中。
MAP_H = 300
NAME_PT, NAME_MIN_PT = 20, 12       # 地名字号(磅);太长就往下缩,缩到这么多为止
NUM_PT = 22                         # 坐标字号(磅)
CLIENT_PT = 11                      # 底行角色名字号(磅)
CLIENT_NONE = "暂未找到客户端"       # 没定位到时的占位句(底行不留空,用户看不出是没找到)
EMPTY_TEXT = "暂无目标"              # 没有目标时占**地名位**(画布留空,不写字)
PULSE_FRAMES = (11, 13, 15, 15, 13, 11, 9, 8)   # 新目标:红点放大再回弹(半径,px)
PULSE_MS = 25                                    # 每帧间隔,全程 ~175ms
FLASH_MS = 1600                      # 底行就地提示停留时长(到点还原角色名)
CHIP_H = 30                          # 框高度(收起时)
CHIP_R = CHIP_H // 2                 # 圆角档:药丸和列表面板共用这一档(15)
CHIP_PAD = 12                        # 框内文字左右留白
CHIP_CHARS = 7                       # 框宽按 7 个字定(2026-10-22 用户定的)
ROW_H = 24                           # 展开后每行名字的高度
MENU_MAX_ROWS = 6                    # 展开最多列几台
MENU_GAP = 4                         # 面板和框之间的缝
MENU_PAD_V = 5                       # 面板上下留白
CHIP_GAP = 7                         # (留用)名字和右侧元素的间距
CHIP_W_FALLBACK = 156                # 取不到字体时的兜底宽
DRAWER_W = 300                       # 右侧「地图采集」抽屉宽度(入口已撤,代码保留)
DETAIL_W, DETAIL_H = DRAWER_W - 44, 210     # 抽屉详情页的地图预览区
_CHIP_W = {}                         # (字体, 字号) -> 药丸宽;算一次就够


def _chip_font(app):
    """药丸/列表共用的字体对象(按当前皮肤的字族建)。"""
    import tkinter.font as tkfont
    c = ui_widgets.bell_palette(getattr(app, "bell_mode", None))
    return tkfont.Font(root=app.bell_win, font=(c["font"], CLIENT_PT))


def chip_width(app):
    """药丸宽度 = 左右留白 + 7 个字的宽(2026-10-22 用户定的:「最多显示7个字」)。

    按真实字体量,不写死像素 —— 换台缩放比例不同的机器也正好是 7 个字。
    """
    try:
        c = ui_widgets.bell_palette(getattr(app, "bell_mode", None))
        key = (c["font"], CLIENT_PT)
        w = _CHIP_W.get(key)
        if not w:
            w = int(_chip_font(app).measure("字" * CHIP_CHARS)) + CHIP_PAD * 2
            _CHIP_W[key] = w
        return w
    except Exception:
        return CHIP_W_FALLBACK
DRAWER_W = 300                      # 右侧「地图采集」抽屉宽度(入口已撤,代码保留)
DETAIL_W, DETAIL_H = DRAWER_W - 44, 210     # 抽屉详情页的地图预览区


def set_coord(app, text):
    """把「地名 + 坐标」写进头部两行(纯控件更新,不动任何扫描状态)。

    text 是 `BellTool.target` 的原文("建邺城 (34,91)");拆成一左一右两个控件,
    一眼看得出"哪张图、哪一格"。调用点:`build_bell` 和 `gui._drain_logs`
    (`bell_var.set` 之后各一次)。
    """
    name, x, y = _split_target(text or "")
    lbl = getattr(app, "bell_name", None)
    num = getattr(app, "bell_coord", None)
    # 没目标:占位句放**地名位**(灰),画布留空 —— 别在画布中间再写一句,
    # 那样看起来像卡片上开了个洞(用户 2026-10-21 定的)
    app.bell_idle = not name
    c = ui_widgets.bell_palette(getattr(app, "bell_mode", None))
    if lbl is not None and lbl.winfo_exists():
        lbl.configure(text=name or EMPTY_TEXT,
                      fg=c["sub"] if app.bell_idle else c["txt"])
    if num is not None and num.winfo_exists():
        num.configure(text="" if x is None else f"{x}, {y}")
    _fit_name(app)


def _fit_name(app):
    """地名太长就缩字号,保证**整串都显示出来**(不省略、不截断)。

    字号是磅值,20pt 在 100% 下重排成四十来像素高 —— 行高必须由控件自己撑,
    别写死(写死 30px 就会把字上下裁掉,用户 2026-10-21 报"地图名显示不全")。
    横向也在这里兜:地名 + 坐标 + 间距超过窗口宽就一级级缩地名,缩到 12pt 为止。
    """
    lbl = getattr(app, "bell_name", None)
    num = getattr(app, "bell_coord", None)
    if lbl is None or num is None:
        return
    c = ui_widgets.bell_palette(getattr(app, "bell_mode", None))
    try:
        import tkinter.font as tkfont
        avail = MAP_W - 16                       # 给"地名 / 坐标"之间留条缝
        num_w = tkfont.Font(font=(c["font_num"], NUM_PT)).measure(
            num.cget("text"))
        size = NAME_PT
        while size > NAME_MIN_PT:
            if tkfont.Font(font=(c["font"], size)).measure(
                    lbl.cget("text")) + num_w <= avail:
                break
            size -= 1
        lbl.configure(font=(c["font"], size))
    except Exception:
        pass


def set_client(app, name):
    """底行框里那句角色名;没定位到就写占位句(留空看不出是"没找到")。"""
    app.bell_client_text = (name or "").strip() or CLIENT_NONE
    _draw_chip(app)


def _chip_parts(app):
    """底行框这一拍画什么:(色板, 文字, 字色)。

    正在就地提示 -> 红字;按着不放 -> 金字(点击感);平时 -> 灰字。
    """
    c = ui_widgets.bell_palette(getattr(app, "bell_mode", None))
    tip = getattr(app, "_bell_flash_text", "")
    text = tip or getattr(app, "bell_client_text", "") or CLIENT_NONE
    if tip:
        fg = c["red"]
    elif getattr(app, "_bell_chip_press", False):
        fg = c["gold"]
    else:
        fg = c["sub"]
    return c, text, fg


def _fit_text(font, text, max_px):
    """文字超过 max_px 就末尾加省略号(框宽定死,长名字不能撑破)。"""
    if font.measure(text) <= max_px:
        return text
    out = text
    while out and font.measure(out + "…") > max_px:
        out = out[:-1]
    return (out + "…") if out else "…"


def _draw_chip(app):
    """画底行那个圆角药丸:只有角色名,没有三角(2026-10-22 用户定的)。

    **宽度按 7 个字定死**(`chip_width`),名字太长末尾省略;圆角是 PIL 画的图
    (`ui_widgets.chip_image`,按尺寸缓存)。列表展开与否不影响药丸本身。
    """
    cv = getattr(app, "bell_client_chip", None)
    if cv is None or not cv.winfo_exists():
        return
    try:
        c, text, fg = _chip_parts(app)
        f_name = _chip_font(app)
        w = chip_width(app)
        cv.configure(width=w, height=CHIP_H)
        cv.delete("all")
        cv.create_image(0, 0, anchor="nw", image=ui_widgets.chip_image(
            w, CHIP_H, bool(getattr(app, "_bell_chip_press", False))))
        app._bell_chip_text_item = cv.create_text(
            CHIP_PAD, CHIP_H // 2,
            text=_fit_text(f_name, text, w - CHIP_PAD * 2), anchor="w",
            fill=fg, font=(c["font"], CLIENT_PT))
    except Exception:
        pass


def _chip_press(app, down):
    """框的按下/抬起视觉(抬起后由绑定去调 `_chip_release`)。"""
    app._bell_chip_press = bool(down)
    _draw_chip(app)


def _chip_release(app):
    """点一下药丸:列表开着就收起,没开就重新找一遍并列出来(开/关一个点)。"""
    if getattr(app, "_bell_menu_open", False):
        close_client_menu(app)
        return
    app.on_locate_clients()


def _stop_flash(app):
    """撤掉还没到点的底行提示(定时器 + 文案一起清)。"""
    aid = getattr(app, "_bell_flash", None)
    app._bell_flash = None
    app._bell_flash_text = ""
    if aid:
        try:
            app.bell_client_chip.after_cancel(aid)
        except Exception:
            pass


def flash_foot(app, text, ms=FLASH_MS):
    """底行框里临时写一句提示(红字),到点还原角色名 —— **不弹模态框**。

    用户 2026-10-21 定的:点一下 ↻ 就弹个要点「确定」的框是打断游戏;
    提示放底行,瞥一眼就够,也不多占控件。
    """
    cv = getattr(app, "bell_client_chip", None)
    if cv is None or not cv.winfo_exists():
        return
    _stop_flash(app)
    app._bell_flash_text = text
    _draw_chip(app)

    def done():
        app._bell_flash = None
        app._bell_flash_text = ""
        try:
            _draw_chip(app)
        except Exception:
            pass

    app._bell_flash = cv.after(ms, done)


def _split_target(text):
    """「建邺城 (34,91)」-> ("建邺城", 34, 91);拆不开就整串当地名。"""
    m = re.match(r"^(.*?)\s*\(\s*(-?\d+)\s*,\s*(-?\d+)\s*\)\s*$", text or "")
    if not m:
        return (text or "").strip(), None, None
    return m.group(1).strip(), int(m.group(2)), int(m.group(3))


def build_bell(app):
    """建降妖伏魔小窗(app.bell_win / bell_name / bell_coord / bell_locate_btn)。

    版面从上到下只有四块:地名行、地图、底行(角色名 + ☀/☾ + ↻)。没有卡片、
    没有金框、没有状态行 —— 地图就是主体。皮肤模式(app.bell_mode)从配置读。
    """
    import tkinter as tk
    from tkinter import ttk

    mode = str(app._get("ui_mode", "a") or "a")
    c = ui_widgets.apply_bell_skin(mode)
    app.bell_mode = ui_widgets.current_mode()
    BG, TXT, GOLD, PAPER = c["bg"], c["txt"], c["gold"], c["paper"]

    app.bell_win = tk.Toplevel(app.root)
    app.bell_win.title("降妖伏魔 · 妖魔位置")
    app.bell_win.configure(bg=BG)
    app.bell_win.attributes("-topmost", True)
    app.bell_win.resizable(False, False)
    # 标题栏 + 任务栏(最小化时)用同一把图标:金铃铛 + 红点(data/bell.ico)。
    # **别在这里调 `iconbitmap`**:它走 LoadImage(LR_DEFAULTSIZE)=32px 那一档,
    # 而且 Tk 会在窗口映射后再盖一次,把 `_dress` 挂上去的精确尺寸 HICON 顶掉
    # —— 任务栏把 32px 缩到 30px,边缘就糊了(2026-10-22 用户拿旁边 Chrome/微信
    # 对比:"你看糊不糊")。图标统一由 `_dress` 里的 `set_window_icon` 负责。
    # 标题栏:颜色要**窗口显示出来以后**再设才生效(建窗那一下设了会被系统盖回去);
    # 最大化按钮也在这里去掉,只留最小化 + 关闭。所以每次 <Map> 都刷一遍。
    def _dress(_e=None):
        ui_widgets.dark_titlebar(
            app.bell_win, ui_widgets.bell_palette(app.bell_mode)["titlebar"])
        ui_widgets.hide_maximize(app.bell_win)
        ui_widgets.set_window_icon(app.bell_win, core.ICON_PATH)

    _dress()
    app.bell_win.bind("<Map>", _dress)

    # 1px 描边:深色底压在深色场景上时,只靠系统阴影分不清窗口边界(2026-10-21)
    body = tk.Frame(app.bell_win, bg=BG, highlightthickness=1,
                    highlightbackground=c["win_edge"])
    body.pack(fill="both", expand=True)
    app.bell_body = body

    # 地名行:地名在左、坐标在右。**行高让内容撑**(字号是磅值,写死高度会把字裁掉)
    head = tk.Frame(body, bg=BG)
    head.pack(fill="x", padx=PAD, pady=(12, 10))
    head.columnconfigure(0, weight=1)
    app.bell_head = head
    app.bell_var = tk.StringVar(value="")
    app.bell_name = tk.Label(head, text="", bg=BG, fg=TXT, anchor="w",
                             font=(c["font"], NAME_PT))
    app.bell_name.grid(row=0, column=0, sticky="w")
    app.bell_coord = tk.Label(head, text="", bg=BG, fg=GOLD, anchor="e",
                              font=(c["font_num"], NUM_PT))
    app.bell_coord.grid(row=0, column=1, sticky="e")
    set_coord(app, "")

    # 地图:没有框、没有金边 —— 图本身就是主体,红点直接压在图上
    app.bell_canvas = tk.Canvas(body, width=MAP_W, height=MAP_H, bg=PAPER,
                                highlightthickness=0, bd=0)
    app.bell_canvas.pack(padx=PAD)

    # 底行:左下角「角色名」圆角药丸(定宽 7 个字,无三角),点一下 = 重新定位
    # 并把客户端列成浮层(2026-10-22 用户定的方案 E);右下角 ☀/☾ 切主题。
    # 最小化/关闭走系统标题栏。
    foot = tk.Frame(body, bg=BG)
    foot.pack(fill="x", padx=PAD, pady=(12, 12))
    app.bell_foot = foot
    app.bell_theme_btn = ttk.Button(foot, text="", width=0,
                                    style="BellTheme.TButton",
                                    command=app.on_toggle_theme)
    app.bell_theme_btn.pack(side="right")
    chip = tk.Canvas(foot, bg=BG, highlightthickness=0, bd=0, height=CHIP_H,
                     width=chip_width(app), cursor="hand2")
    chip.pack(side="left")
    app.bell_client_chip = chip
    app._bell_chip_press = False
    app._bell_flash_text = ""
    app._bell_menu_open = False
    # 按下变金;抬起:列表开着 -> 收起,没开 -> 重新定位一次并列出来
    chip.bind("<Button-1>", lambda _e: _chip_press(app, True))
    chip.bind("<ButtonRelease-1>",
              lambda _e: (_chip_press(app, False), _chip_release(app)))
    chip.bind("<Leave>", lambda _e: _chip_press(app, False))
    set_client(app, "")

    # ---- 右侧抽屉(采集的界面入口已撤,控件照建:开抽屉走 `toggle_drawer`) ----
    app.bell_drawer = tk.Frame(body, bg=BG, highlightthickness=1,
                               highlightbackground=c["line"],
                               width=DRAWER_W)
    app.bell_drawer.pack_propagate(False)
    app.bell_drawer_open = False
    _build_drawer(app)

    app.bell_win.protocol("WM_DELETE_WINDOW", app.on_close)   # 单窗应用:× = 退出
    app._bell_photo = None
    app._bell_spot = None
    # 位置:存过(上次退出时记的)就摆回原处,没有/坏了才居中(2026-10-21)。
    # 先 update_idletasks:不然 winfo_reqwidth 还是 Toplevel 的默认 200x200,居中会算歪。
    app.bell_win.update_idletasks()
    ui_widgets.set_place(app.bell_win, pos=app._get("bell_pos"))
    return app.bell_win


def _build_drawer(app):
    """抽屉:六张地图,每张一个按钮 —— 没采=「采集」,采过=「已采集」(点了看图)。"""
    import tkinter as tk
    from tkinter import ttk

    c = ui_widgets.apply_bell_skin()

    drawer = app.bell_drawer

    head = ttk.Frame(drawer, style="Bell.TFrame", padding=(12, 10, 12, 4))
    head.pack(fill="x")
    tk.Label(head, image=ui_widgets.bell_image(122, 32),
             text="◆ 地图采集", compound="center", bg=c["card"],
             fg=c["green"], font=(c["font"], 11, "bold")).pack(side="left")
    ttk.Button(head, text="✕", width=3, style="BellGhost.TButton",
               command=app.on_map_import).pack(side="right")
    ttk.Label(drawer, text="先在游戏里按 Tab 打开那张地图,再点「采集」",
              style="BellFoot.TLabel", wraplength=DRAWER_W - 30,
              justify="left").pack(anchor="w", padx=12, pady=(0, 6))

    app.bell_rows = {}
    for name in tools_bell.BELL_MAP_NAMES:
        row = ttk.Frame(drawer, style="Bell.TFrame", padding=(12, 3))
        row.pack(fill="x")
        ttk.Label(row, text=name, width=9, anchor="w",
                  style="Bell.TLabel").pack(side="left")
        btn = ttk.Button(row, text="采集", width=8, style="Bell.TButton",
                         command=lambda n=name: app.on_map_btn(n))
        btn.pack(side="right")
        app.bell_rows[name] = btn

    # ---- 详情页(同一块地方切过去:只显示地图) ----
    app.bell_drawer_detail = ttk.Frame(drawer, style="Bell.TFrame")
    dhead = ttk.Frame(app.bell_drawer_detail, style="Bell.TFrame",
                      padding=(12, 8, 12, 4))
    dhead.pack(fill="x")
    ttk.Button(dhead, text="← 返回", width=8, style="Bell.TButton",
               command=lambda: show_list(app)).pack(side="left")
    shot_frame = tk.Frame(app.bell_drawer_detail, bg=c["line"])
    shot_frame.pack(padx=12, pady=6)
    app.bell_detail_shot = tk.Canvas(shot_frame,
                                     width=DETAIL_W, height=DETAIL_H,
                                     bg=c["paper"], highlightthickness=0)
    app.bell_detail_shot.pack(padx=3, pady=3)
    app.bell_detail_photo = None
    app.bell_detail_name = ""


def close_client_menu(app):
    """收起展开的角色名列表(选完 / 再点一次药丸 / 切主题都走这里,幂等)。"""
    f = getattr(app, "bell_pick", None)
    app.bell_pick = None
    if f is not None:
        try:
            f.destroy()
        except Exception:
            pass
    app._bell_menu_open = False
    _draw_chip(app)


def _menu_click(app, event):
    """列表里点哪一行 -> 交给 app.on_pick_client(i)。"""
    idx = int((event.y - MENU_PAD_V) // ROW_H)
    n = min(len(getattr(app, "_bell_pick_choices", []) or []), MENU_MAX_ROWS)
    if 0 <= idx < n:
        app.on_pick_client(idx)


def show_client_menu(app, choices):
    """点药丸:一块**和药丸同宽**的面板从它头上浮出来,盖在地图上(方案 E)。

    面板里**只有客户端行**,几个列几个(不再有"当前名字"那格);每行名字左对齐,
    **当前选中的那台在最右边带一个金点**、字也提亮;悬停整行亮一档(菜单的常规
    反馈)。行距统一 `ROW_H`,只写角色名、不显示客户端大小,字号和
    「暂未找到客户端」一致。超过 6 台只列 6 台;窗口尺寸从头到尾不变。
    """
    import tkinter as tk

    close_client_menu(app)
    c = ui_widgets.apply_bell_skin()
    rows = list(choices[:MENU_MAX_ROWS])
    n = len(rows)
    foot = app.bell_foot
    chip = app.bell_client_chip
    x = foot.winfo_x() + chip.winfo_x()
    chip_top = foot.winfo_y() + chip.winfo_y()
    w = chip.winfo_width() or chip_width(app)
    f = _chip_font(app)
    h = MENU_PAD_V * 2 + ROW_H * n
    y = chip_top - MENU_GAP - h
    want = str(app._get("bell_client") or "")
    hover_bg = ui_widgets._shade(c["btn"], 16)

    cv = tk.Canvas(app.bell_body, bg=c["bg"], highlightthickness=0, bd=0,
                   width=w, height=h, cursor="hand2")
    cv.place(x=x, y=y, width=w, height=h)

    def render(hover):
        cv.delete("all")
        cv.create_image(0, 0, anchor="nw", image=ui_widgets.chip_image(
            w, h, radius=CHIP_R))
        if 0 <= hover < n:
            cv.create_rectangle(CHIP_R - 10, MENU_PAD_V + ROW_H * hover,
                                w - (CHIP_R - 10),
                                MENU_PAD_V + ROW_H * (hover + 1),
                                fill=hover_bg, outline="")
        for k, (who, title, _r) in enumerate(rows):
            cy = MENU_PAD_V + ROW_H * k + ROW_H // 2
            cur = bool(title) and title == want
            cv.create_text(CHIP_PAD, cy,
                           text=_fit_text(f, who, w - CHIP_PAD * 2 - 12),
                           anchor="w", fill=c["txt"] if cur else c["sub"],
                           font=(c["font"], CLIENT_PT))
            if cur:                  # 当前那台:金点顶到最右边
                cx = w - CHIP_PAD - 3
                cv.create_oval(cx - 3, cy - 3, cx + 3, cy + 3,
                               fill=c["gold"], outline="")

    def hover_of(y):
        k = int((y - MENU_PAD_V) // ROW_H)
        return k if 0 <= k < n else -1

    state = {"k": -1}

    def on_move(e):
        k = hover_of(e.y)
        if k != state["k"]:
            state["k"] = k
            render(k)

    def on_leave(_e):
        if state["k"] != -1:
            state["k"] = -1
            render(-1)

    render(-1)
    app.bell_pick = cv
    cv.tk.call("raise", str(cv))   # Canvas 的 .lift() 是 tag_raise,提控件要这么叫
    cv.bind("<Button-1>", lambda e: _menu_click(app, e))
    cv.bind("<Motion>", on_move)
    cv.bind("<Leave>", on_leave)
    app._bell_menu_open = True


def refresh_drawer(app):
    """按采集状态刷按钮:没采=「采集」,采过=「已采集」(点了看图)。"""
    for name, btn in getattr(app, "bell_rows", {}).items():
        if tools_bell.map_asset(name):
            btn.configure(text="已采集")
        else:
            btn.configure(text="采集")


def show_list(app):
    """抽屉切回"地图列表"页。"""
    app.bell_drawer_detail.pack_forget()
    refresh_drawer(app)


def show_detail(app, name):
    """抽屉切到"某张地图"页:只显示地图本身。"""
    app.bell_detail_name = name
    app.bell_drawer_detail.pack(fill="both", expand=True)
    path = tools_bell.map_asset(name)
    shot = app.bell_detail_shot
    shot.delete("all")
    app.bell_detail_photo = None
    c = ui_widgets.apply_bell_skin()
    if not path:
        shot.create_text(DETAIL_W // 2, DETAIL_H // 2,
                         text=f"还没采「{name}」", fill=c["sub"],
                         font=("Microsoft YaHei UI", 11))
        return
    try:
        from PIL import Image, ImageTk
        img = Image.open(path).convert("RGB")
    except Exception as err:
        shot.create_text(DETAIL_W // 2, DETAIL_H // 2, text=f"底图读不了:{err}",
                         fill=c["red"], font=("Microsoft YaHei UI", 10))
        return
    k = min(DETAIL_W / img.width, DETAIL_H / img.height, 1.0)
    disp = img.resize((max(1, int(img.width * k)),
                       max(1, int(img.height * k))), Image.LANCZOS)
    app.bell_detail_photo = ImageTk.PhotoImage(disp)
    shot.create_image(DETAIL_W // 2, DETAIL_H // 2,
                      image=app.bell_detail_photo)


def toggle_drawer(app):
    """「地图采集」入口(已撤):拉出/收起右侧抽屉(窗口随之拉长/缩回)。

    没有界面入口了,但功能是完整的 —— 要开放时在顶栏加一颗按钮、command
    指回 `app.on_map_import` 即可(抽屉建窗时已经建好,只是不显示)。
    """
    if app.bell_drawer_open:
        app.bell_drawer.pack_forget()
        app.bell_drawer_open = False
    else:
        app.bell_drawer.pack(side="right", fill="y",
                             padx=(6, 12), pady=(12, 10))
        app.bell_drawer_open = True
        refresh_drawer(app)


def _stop_pulse(app):
    """停掉还没跑完的红点回弹(重画/切主题/窗口销毁前)。"""
    aid = getattr(app, "_bell_pulse", None)
    app._bell_pulse = None
    if not aid:
        return
    try:
        app.bell_canvas.after_cancel(aid)
    except Exception:
        pass


def _pulse_maybe(app, c, item, dx, dy, target):
    """**新目标**才做一次放大-回弹;同值重画/切主题不触发。

    判据放在 `_bell_last_target`:主题切换会故意把 `_bell_spot` 设成哨兵逼重画,
    拿它判断就会每次都弹一下。
    """
    if getattr(app, "_bell_last_target", None) == target:
        return
    app._bell_last_target = target
    _pulse(app, c, item, dx, dy)


def _pulse(app, c, item, dx, dy):
    """红点放大再回弹:8 帧、约 175ms(画布没有缓动,手搓半径)。"""
    def step(i):
        app._bell_pulse = None
        try:
            if not c.winfo_exists():
                return
            r = PULSE_FRAMES[i] if i < len(PULSE_FRAMES) else 8
            c.coords(item, dx - r, dy - r, dx + r, dy + r)
        except Exception:
            return
        if i + 1 < len(PULSE_FRAMES):
            try:
                app._bell_pulse = c.after(PULSE_MS, lambda: step(i + 1))
            except Exception:
                app._bell_pulse = None
    step(0)


def apply_theme(app, mode=None):
    """切换深色 / 明亮:重配样式,再把 tk 控件的颜色换掉(ttk 按钮靠样式自动变)。

    只改颜色,不重建窗口 —— 版面、尺寸、位置都不动。调用点:
    `gui.App.on_toggle_theme`(底行那颗 ☀/☾)。
    """
    c = ui_widgets.apply_bell_skin(mode)
    app.bell_mode = ui_widgets.current_mode()
    win = getattr(app, "bell_win", None)
    if win is None or not win.winfo_exists():
        return
    close_client_menu(app)     # 浮层颜色是开层时刷死的,切主题直接收掉
    win.configure(bg=c["bg"])
    for name in ("bell_body", "bell_head", "bell_foot", "bell_drawer"):
        f = getattr(app, name, None)
        if f is not None and f.winfo_exists():
            f.configure(bg=c["bg"])
    try:
        app.bell_drawer.configure(highlightbackground=c["line"])
        app.bell_body.configure(highlightbackground=c["win_edge"])
    except Exception:
        pass
    app.bell_name.configure(bg=c["bg"],
                            fg=c["sub"] if getattr(app, "bell_idle", True)
                            else c["txt"])
    app.bell_coord.configure(bg=c["bg"], fg=c["gold"])
    try:
        app.bell_client_chip.configure(bg=c["bg"])
    except Exception:
        pass
    _draw_chip(app)                     # 框的底图/字色按新皮肤重画
    app.bell_canvas.configure(bg=c["paper"])
    ui_widgets.dark_titlebar(win, c["titlebar"])
    app._bell_spot = object()          # 逼重画:画布底/文字色/红点都要跟着换
    draw_bell(app)


def draw_bell(app):
    """把当前妖魔位置画到底图上。**画框固定 380x300**,底图等比缩进后居中(换图窗口不跳高)。"""
    c = getattr(app, "bell_canvas", None)
    if c is None or not c.winfo_exists():
        return
    spot = app.engine.bell_tool.ui_state()["spot"]
    # 没目标必须每次都走到下面那句 delete:画布上可能还挂着上一次的图/点
    if spot and app._bell_spot == spot and c.find_all():
        return
    _stop_pulse(app)
    c.delete("all")
    app._bell_spot = spot
    sk = ui_widgets.bell_palette(getattr(app, "bell_mode", None))
    if not spot:
        return                                 # 占位句在地名位(set_coord),画布留空
    name, x, y = spot
    path = tools_bell.map_asset(name)
    if not path:
        c.create_text(MAP_W // 2, MAP_H // 2, text=f"缺「{name}」底图",
                      fill=sk["sub"], font=(sk["font"], 12))
        return
    try:
        import os

        from PIL import Image, ImageTk
        # 底图解码 + 缩放缓存:每换一个点就重新读盘/重采样没意义(底图不变)
        key = (path, os.path.getmtime(path))
        got = getattr(app, "_bell_base", None)
        if not got or got[0] != key:
            img = Image.open(path).convert("RGB")
            # 等比缩进画框(不是拉伸):取宽/高两个比例里小的那个,再居中
            ratio = min(MAP_W / float(img.width), MAP_H / float(img.height))
            dw = max(1, round(img.width * ratio))
            dh = max(1, round(img.height * ratio))
            got = (key, ImageTk.PhotoImage(img.resize((dw, dh), Image.LANCZOS)),
                   ratio, dw, dh, img.size, (MAP_W - dw) // 2, (MAP_H - dh) // 2)
            app._bell_base = got
            app._bell_base_photo = got[1]      # Tk 的图得留引用,别被回收
        _k, photo, ratio, dw, dh, src, ox, oy = got
        app._bell_photo = photo
        c.create_image(ox, oy, image=photo, anchor="nw")
        # 1px 内描边:浅色模式下白底和彩图之间有个边界,深色下几乎看不见
        c.create_rectangle(ox, oy, ox + dw - 1, oy + dh - 1,
                           outline=sk["map_edge"])
        if x is None or y is None:
            return                             # 只有图没坐标:什么也不画
        fx, fy = tools_bell.map_pixel(name, x, y)
        px_, py_ = fx * ratio, fy * ratio
        if not (0 <= px_ <= dw and 0 <= py_ <= dh):
            # 夹边这事儿不能悄悄做:坐标落到底图外面 = 底图/坐标范围对不上,
            # 得让用户在日志里看见,不然只会觉得"点怎么画到边上了"
            app.log(f"[铃铛]{name} ({x},{y}) 落到底图外面了(底图 {src[0]}x"
                    f"{src[1]}),点已夹到边上 —— 重新采一次这张底图")
        dx = min(max(ox + px_, ox), ox + dw)
        dy = min(max(oy + py_, oy), oy + dh)
        # 就一个红圆点(用户要求):外圈白描边,压在任何底图上都看得见
        item = c.create_oval(dx - 8, dy - 8, dx + 8, dy + 8, fill=sk["dot"],
                            outline=sk["dot_ring"], width=2)
        _pulse_maybe(app, c, item, dx, dy, (name, x, y))
    except Exception as err:
        c.delete("all")
        c.create_text(MAP_W // 2, MAP_H // 2, text=f"底图读取失败:{err}",
                      fill=sk["red"], font=(sk["font"], 12))
