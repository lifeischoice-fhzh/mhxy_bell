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
    """底行那句角色名;没定位到就写占位句(留空的话用户看不出是"没找到")。

    真实文本记在 `app.bell_client_text` 上:鼠标停到圆钮上时底行要临时换提示,
    移开再还原成它(见 `_hint`)。
    """
    app.bell_client_text = (name or "").strip() or CLIENT_NONE
    lbl = getattr(app, "bell_client_lbl", None)
    if lbl is not None and lbl.winfo_exists():
        lbl.configure(text=app.bell_client_text)


def _hint(app, text):
    """鼠标停在圆钮上:底行临时换一句说明;text 为空 = 还原角色名。

    提示用金色,和灰色的角色名分开 —— 同一个位置同一种颜色,看起来像"名字变了"
    (2026-10-21 用户提的)。
    """
    lbl = getattr(app, "bell_client_lbl", None)
    if lbl is None or not lbl.winfo_exists():
        return
    _stop_flash(app)                       # 手动划过就接管,别让提示定时器再改字
    c = ui_widgets.bell_palette(getattr(app, "bell_mode", None))
    if text:
        lbl.configure(text=text, fg=c["gold"])
    else:
        lbl.configure(text=getattr(app, "bell_client_text", "") or CLIENT_NONE,
                      fg=c["sub"])


def _stop_flash(app):
    """撤掉底行还没到点的就地提示(不还原文字,还原是下一次写底行的事)。"""
    aid = getattr(app, "_bell_flash", None)
    app._bell_flash = None
    if aid:
        try:
            app.bell_client_lbl.after_cancel(aid)
        except Exception:
            pass


def flash_foot(app, text, color="red", ms=FLASH_MS):
    """底行就地换一句提示(默认红字),到点还原角色名 —— **不弹模态框**。

    用户 2026-10-21 定的:点一下 ↻ 就弹个要点「确定」的框是打断游戏;
    提示放底行,瞥一眼就够,也不多占控件。
    """
    lbl = getattr(app, "bell_client_lbl", None)
    if lbl is None or not lbl.winfo_exists():
        return
    _stop_flash(app)
    c = ui_widgets.bell_palette(getattr(app, "bell_mode", None))
    lbl.configure(text=text, fg=c[color])

    def done():
        app._bell_flash = None
        try:
            if not lbl.winfo_exists():
                return
            cc = ui_widgets.bell_palette(getattr(app, "bell_mode", None))
            lbl.configure(text=getattr(app, "bell_client_text", "")
                          or CLIENT_NONE, fg=cc["sub"])
        except Exception:
            pass

    app._bell_flash = lbl.after(ms, done)


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
    BG, TXT, SUB, GOLD, PAPER = (c["bg"], c["txt"], c["sub"], c["gold"],
                                 c["paper"])

    app.bell_win = tk.Toplevel(app.root)
    app.bell_win.title("降妖伏魔 · 妖魔位置")
    app.bell_win.configure(bg=BG)
    app.bell_win.attributes("-topmost", True)
    app.bell_win.resizable(False, False)
    # 标题栏:颜色要**窗口显示出来以后**再设才生效(建窗那一下设了会被系统盖回去);
    # 最大化按钮也在这里去掉,只留最小化 + 关闭。所以每次 <Map> 都刷一遍。
    def _dress(_e=None):
        ui_widgets.dark_titlebar(
            app.bell_win, ui_widgets.bell_palette(app.bell_mode)["titlebar"])
        ui_widgets.hide_maximize(app.bell_win)

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

    # 底行:左边「角色名 + 紧跟的 ↻(换客户端)」,右下角「☀/☾(切主题)」。
    # 最小化/关闭走系统标题栏(不再放底行,重复)。
    foot = tk.Frame(body, bg=BG)
    foot.pack(fill="x", padx=PAD, pady=(12, 12))
    app.bell_foot = foot
    app.bell_theme_btn = ttk.Button(foot, text="", width=0,
                                    style="BellTheme.TButton",
                                    command=app.on_toggle_theme)
    app.bell_theme_btn.pack(side="right")
    app.bell_client_lbl = tk.Label(foot, text="", bg=BG, fg=SUB, anchor="w",
                                   font=(c["font"], CLIENT_PT))
    app.bell_client_lbl.pack(side="left")
    # width=0:按 28x28 的图走自然尺寸(不写这行,ttk 会按主题默认宽 77px 摆)
    app.bell_locate_btn = ttk.Button(foot, text="", width=0,
                                     style="BellIcon.TButton",
                                     command=app.on_locate_clients)
    app.bell_locate_btn.pack(side="left", padx=(8, 0))
    # 圆钮都没有文字:鼠标停上去时,**底行左侧那行字**临时换成它在干什么,
    # 移开还原角色名(Tk 没有内置 tooltip,这是最省事又不加控件的做法)
    app.bell_locate_btn.bind("<Enter>", lambda _e: _hint(app, "换客户端"))
    app.bell_locate_btn.bind("<Leave>", lambda _e: _hint(app, ""))
    app.bell_theme_btn.bind("<Enter>", lambda _e: _hint(
        app, "深色模式" if app.bell_mode == "b" else "明亮模式"))
    app.bell_theme_btn.bind("<Leave>", lambda _e: _hint(app, ""))
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


def pick_client(parent, choices, current=""):
    """弹个小列表让用户选哪台客户端(多开时用)。根据角色名认。

    choices = [(角色名, 标题, 矩形)];返回选中的下标,取消返回 None。
    """
    import tkinter as tk
    from tkinter import ttk

    c = ui_widgets.apply_bell_skin()
    win = tk.Toplevel(parent)
    win.title("选一个客户端")
    win.configure(bg=c["bg"])
    win.resizable(False, False)
    win.transient(parent)
    ttk.Label(win, text="检测到多个客户端,选一个给降妖伏魔用:",
              style="BellSection.TLabel").pack(anchor="w", padx=14, pady=(12, 6))
    box = tk.Listbox(win, height=min(8, len(choices)), width=34,
                     font=(c["font"], 10),
                     activestyle="none", exportselection=False,
                     relief="flat", highlightthickness=2,
                     highlightbackground=c["line"], bg=c["paper"],
                     fg=c["txt"], selectbackground=c["btn"],
                     selectforeground=c["yellow"])
    for i, (name, title, rect) in enumerate(choices):
        box.insert("end", f"{name}    {rect[2]-rect[0]}x{rect[3]-rect[1]}")
        if current and (title == current or name == current):
            box.selection_set(i)
            box.see(i)
    if not box.curselection():
        box.selection_set(0)
    box.pack(fill="both", expand=True, padx=14)
    out = {"i": None}

    def ok():
        sel = box.curselection()
        out["i"] = int(sel[0]) if sel else None
        win.destroy()

    row = ttk.Frame(win, style="Bell.TFrame", padding=(14, 10))
    row.pack(fill="x")
    ttk.Button(row, text="就用这台", style="BellGold.TButton",
               command=ok).pack(side="right")
    ttk.Button(row, text="取消", style="Bell.TButton",
               command=win.destroy).pack(side="right", padx=(0, 8))
    box.bind("<Double-Button-1>", lambda _e: ok())
    win.bind("<Return>", lambda _e: ok())
    ui_widgets.set_place(win)
    win.grab_set()
    parent.wait_window(win)
    return out["i"]


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
    app.bell_client_lbl.configure(bg=c["bg"])
    if not getattr(app, "_bell_flash", None):     # 正在提示:字色留给提示自己
        app.bell_client_lbl.configure(fg=c["sub"])
    app.bell_canvas.configure(bg=c["paper"])
    ui_widgets.dark_titlebar(win, c["titlebar"])
    app._bell_spot = object()          # 逼重画:画布底/文字色/红点都要跟着换
    draw_bell(app)


def draw_bell(app):
    """把当前妖魔位置画到底图上。**画框固定 400x280**,底图按比例居中(换图窗口不跳)。"""
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
