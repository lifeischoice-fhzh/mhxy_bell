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
PAD = 14                            # 窗口左右留白(地图 400 + 两边 14)
MAP_W = 400                         # 地图宽固定;高度按底图长宽比算,不写死
MAP_H = 199                         # 没有底图/没目标时的兜底高度(2:1)
NAME_PT, NAME_MIN_PT = 20, 12       # 地名字号(磅);太长就往下缩,缩到这么多为止
NUM_PT = 22                         # 坐标字号(磅)
DRAWER_W = 300                      # 右侧「地图采集」抽屉宽度(入口已撤,代码保留)
DETAIL_W, DETAIL_H = DRAWER_W - 44, 210     # 抽屉详情页的地图预览区


def set_coord(app, text):
    """把「地名 + 坐标」写进头部两行(纯控件更新,不动任何扫描状态)。

    text 是 `BellTool.target` 的原文("建邺城 (34,91)");拆成一左一右两个控件,
    一眼看得出"哪张图、哪一格"。调用点:`build_bell` 和 `gui._drain_logs`
    (`bell_var.set` 之后各一次)。
    """
    app.bell_coord_text = text or ""    # 记下当前显示的原文(测试/排查用)
    name, x, y = _split_target(app.bell_coord_text)
    lbl = getattr(app, "bell_name", None)
    num = getattr(app, "bell_coord", None)
    if lbl is not None and lbl.winfo_exists():
        lbl.configure(text=name or "")
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
    # 标题栏颜色:**窗口真正显示出来以后**再设才生效(建窗那一下设了会被系统盖回去),
    # 所以除了现在试一次,每次 <Map>(显示/重新显示)都再刷一遍。
    ui_widgets.dark_titlebar(app.bell_win, c["titlebar"])
    app.bell_win.bind(
        "<Map>", lambda _e: ui_widgets.dark_titlebar(
            app.bell_win, ui_widgets.bell_palette(app.bell_mode)["titlebar"]))

    body = tk.Frame(app.bell_win, bg=BG)      # 卡片在左,抽屉在右
    body.pack(fill="both", expand=True)
    app.bell_body = body

    # 地名行:地名在左、坐标在右。**行高让内容撑**(字号是磅值,写死高度会把字裁掉)
    head = tk.Frame(body, bg=BG)
    head.pack(fill="x", padx=PAD, pady=(12, 10))
    head.columnconfigure(0, weight=1)
    app.bell_head = head
    app.bell_var = tk.StringVar(value="")
    app.bell_coord_text = ""
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
    # 从左往右 pack:角色名只占文字的宽度,↻ 自动跟在它后面 —— 名字多长,按钮
    # 就跟到哪(不用算 x);☀/☾ 先从右边占位,名字再长也挤不掉它。
    foot = tk.Frame(body, bg=BG)
    foot.pack(fill="x", padx=PAD, pady=(12, 12))
    app.bell_foot = foot
    app.bell_theme_btn = ttk.Button(foot, text="", width=0,
                                    style="BellTheme.TButton",
                                    command=app.on_toggle_theme)
    app.bell_theme_btn.pack(side="right")
    app.bell_client_lbl = tk.Label(foot, text="", bg=BG, fg=SUB, anchor="w",
                                   font=(c["font"], 10))
    app.bell_client_lbl.pack(side="left")
    # width=0:按 28x28 的图走自然尺寸(不写这行,ttk 会按主题默认宽 77px 摆)
    app.bell_locate_btn = ttk.Button(foot, text="", width=0,
                                     style="BellIcon.TButton",
                                     command=app.on_locate_clients)
    app.bell_locate_btn.pack(side="left", padx=(8, 0))

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
    ui_widgets.set_place(app.bell_win)     # 大小由内容定,这里只定位置(居中)
    return app.bell_win


def _build_drawer(app):
    """抽屉:六张地图,每张一个按钮 —— 没采=「采集」,采过=「已采集」(点了看图)。"""
    import tkinter as tk
    from tkinter import ttk

    c = ui_widgets.apply_bell_skin()

    drawer = app.bell_drawer

    head = ttk.Frame(drawer, style="Bell.TFrame", padding=(12, 10, 12, 4))
    head.pack(fill="x")
    tk.Label(head, image=ui_widgets.bell_image("chip", 122, 32),
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
    except Exception:
        pass
    app.bell_name.configure(bg=c["bg"], fg=c["txt"])
    app.bell_coord.configure(bg=c["bg"], fg=c["gold"])
    app.bell_client_lbl.configure(bg=c["bg"], fg=c["sub"])
    app.bell_canvas.configure(bg=c["paper"])
    ui_widgets.dark_titlebar(win, c["titlebar"])
    app._bell_spot = object()          # 逼重画:画布底/文字色/红点都要跟着换
    draw_bell(app)


def draw_bell(app):
    """把当前妖魔位置画到底图上;画布高度跟着底图长宽比走(不留死带)。"""
    c = getattr(app, "bell_canvas", None)
    if c is None or not c.winfo_exists():
        return
    spot = app.engine.bell_tool.ui_state()["spot"]
    if app._bell_spot == spot and c.find_all():
        return
    c.delete("all")
    app._bell_spot = spot
    sk = ui_widgets.bell_palette(getattr(app, "bell_mode", None))
    if not spot:
        _set_map_h(app, MAP_H)
        c.create_text(MAP_W // 2, MAP_H // 2, text="暂无目标",
                      fill=sk["sub"], font=(sk["font"], 12))
        return
    name, x, y = spot
    path = tools_bell.map_asset(name)
    if not path:
        _set_map_h(app, MAP_H)
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
            # 宽度定死 400,高度由底图长宽比决定 —— 写死高度会在上下留死带
            ratio = MAP_W / float(img.width)
            disp = img.resize((MAP_W, max(1, round(img.height * ratio))),
                              Image.LANCZOS)
            got = (key, ImageTk.PhotoImage(disp), ratio, disp.width,
                   disp.height, img.size)
            app._bell_base = got
            app._bell_base_photo = got[1]      # Tk 的图得留引用,别被回收
        _k, photo, ratio, dw, dh, src = got
        _set_map_h(app, dh)
        app._bell_photo = photo
        c.create_image(0, 0, image=photo, anchor="nw")
        if x is None or y is None:
            return                             # 只有图没坐标:什么也不画
        fx, fy = tools_bell.map_pixel(name, x, y)
        px_, py_ = fx * ratio, fy * ratio
        if not (0 <= px_ <= dw and 0 <= py_ <= dh):
            # 夹边这事儿不能悄悄做:坐标落到底图外面 = 底图/坐标范围对不上,
            # 得让用户在日志里看见,不然只会觉得"点怎么画到边上了"
            app.log(f"[铃铛]{name} ({x},{y}) 落到底图外面了(底图 {src[0]}x"
                    f"{src[1]}),点已夹到边上 —— 重新采一次这张底图")
        dx = min(max(px_, 0), dw)
        dy = min(max(py_, 0), dh)
        # 就一个红圆点(用户要求):外圈白描边,压在任何底图上都看得见
        c.create_oval(dx - 8, dy - 8, dx + 8, dy + 8, fill=sk["dot"],
                      outline=sk["dot_ring"], width=2)
    except Exception as err:
        c.delete("all")
        _set_map_h(app, MAP_H)
        c.create_text(MAP_W // 2, MAP_H // 2, text=f"底图读取失败:{err}",
                      fill=sk["red"], font=(sk["font"], 12))


def _set_map_h(app, h):
    """画布高度 = 这张底图按 400 宽缩放后的高度(别用固定高,上下会留死带)。"""
    c = app.bell_canvas
    h = max(120, int(h))
    try:
        if int(c.cget("height")) == h:
            return
        c.configure(height=h)
    except Exception:
        return
    _keep_on_screen(app)


def _keep_on_screen(app):
    """窗高变了以后把窗口夹回屏幕内(高的地图会长到屏幕外,底行就点不到)。"""
    win = getattr(app, "bell_win", None)
    try:
        win.update_idletasks()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        w, h = win.winfo_width(), win.winfo_height()
        x, y = win.winfo_x(), win.winfo_y()
        nx = max(0, min(x, max(0, sw - w)))
        ny = max(0, min(y, max(0, sh - h)))
        if (nx, ny) != (x, y):
            ui_widgets.place(win, (nx, ny))
    except Exception:
        pass
