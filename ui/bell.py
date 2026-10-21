"""降妖伏魔小窗:妖魔位置大字 + 底图红点(客户端同款:深靛蓝面板 + 金字 + 宋体)。

build_bell 只建控件;draw_bell 只碰画布(底图缩放/红点按 tools.bell 的标定算,
方向 ui→tools,允许);抽屉只摆控件,动作都回到 App(app.on_map_import /
app.on_map_btn / app.on_map_detail)。**采集只是从界面移除**(用户定的
2026-10-20,底图内置):抽屉控件与回调全保留,要开放时把「地图采集」按钮
加回去、command 指回 on_map_import 就行。日志区已整个撤掉(2026-10-21),
日志只进 bell.log。皮肤见 ui/widgets.apply_bell_skin(配色/字体对齐客户端)。
扫描范围全自动:客户端窗口自动定位,不支持的分辨率由 gui 弹窗提醒。
"""
from tools import bell as tools_bell
from ui import widgets as ui_widgets

# ---- 降妖伏魔小窗 ----
BELL_W, BELL_H = 400, 280           # 底图画布尺寸(卡片宽度跟着它走)
DRAWER_W = 300                      # 右侧「地图采集」抽屉宽度(入口已撤,代码保留)
DETAIL_W, DETAIL_H = DRAWER_W - 44, 210     # 抽屉详情页的地图预览区


def set_coord(app, text):
    """重画坐标那行(**圆角牌 + 白字黑边**,见 `ui_widgets.bell_coord`)。

    纯控件更新:不动任何扫描状态。图片挂在 app 上留引用(Tk 图没人持有会被回收)。
    调用点:`build_bell`(建控件时)和 `gui._drain_logs`(`bell_var.set` 之后各一次)。
    """
    lbl = getattr(app, "bell_coord", None)
    if lbl is None or not lbl.winfo_exists():
        return
    img = ui_widgets.bell_coord(text or "")
    app.bell_coord_img = img
    app.bell_coord_text = text or ""        # 记下当前显示的字(测试/排查用)
    lbl.configure(image=img)


def build_bell(app):
    """建降妖伏魔小窗(app.bell_win / bell_var / bell_canvas / bell_drawer ...)。"""
    import tkinter as tk
    from tkinter import ttk

    c = ui_widgets.apply_bell_skin()
    BG, CARD = c["bg"], c["card"]
    LINE, PAPER, GOLD = c["line"], c["paper"], c["gold"]
    FONT = c["font"]

    app.bell_win = tk.Toplevel(app.root)
    app.bell_win.title("降妖伏魔 · 妖魔位置")
    app.bell_win.configure(bg=BG)
    app.bell_win.attributes("-topmost", True)
    app.bell_win.resizable(False, False)

    body = tk.Frame(app.bell_win, bg=BG)      # 卡片在左,抽屉在右
    body.pack(fill="both", expand=True)
    app.bell_body = body

    # 卡片高度由内容定(写死高度会把底下的按钮裁掉),宽度由 400px 画布定;
    # 2px 冷色细边 = 游戏面板那圈边(金留给地图框)。side="left" 是给右侧抽屉
    # 留的位置(toggle_drawer 往右拉,窗口随之拉宽)
    card = tk.Frame(body, bg=CARD, highlightthickness=2,
                    highlightbackground=LINE)
    card.pack(side="left", padx=(12, 0), pady=(12, 10))

    # 坐标:深色圆角牌上压一行**带黑边的亮黄大字**(游戏数值的样子;
    # Tk 画不出描边,这张字图是 PIL 画的,字一变就重画 —— 见 `set_coord`)
    app.bell_var = tk.StringVar(value="等待铃铛任务提示…")
    app.bell_coord_img = None
    app.bell_coord = tk.Label(card, bg=CARD, bd=0, highlightthickness=0)
    app.bell_coord.pack(padx=12, pady=(10, 8))
    set_coord(app, app.bell_var.get())

    # 地图:外面套一圈金框(游戏里地图窗也是金边)
    shot = tk.Frame(card, bg=GOLD)
    shot.pack(padx=12)
    app.bell_canvas = tk.Canvas(shot, width=BELL_W, height=BELL_H,
                                bg=PAPER, highlightthickness=0)
    app.bell_canvas.pack(padx=3, pady=3)
    # 只在"没底图/读不了/等坐标"这类状态下才写字,平时是空的
    app.bell_hint = ttk.Label(card, text="", style="BellHint.TLabel",
                              anchor="center")
    app.bell_hint.pack(fill="x", padx=16, pady=(6, 8))

    # 底下就一颗「自动定位」(游戏「确认加点」那排的砖红圆角钮):定位到哪台
    # 客户端,按钮上就写它的角色名;没定位到还是「自动定位」。**宽度随文字走**
    # (写死宽度会把长角色名挤到贴边/显示不全),两边留出余量。监听常开(没有
    # 开关按钮)、日志区已撤(2026-10-21)、采集入口已撤 —— 界面上就不摆它们。
    locate_txt = tools_bell.client_name(
        str(app._get("bell_client", "") or "")) or "自动定位"
    app.bell_locate_btn = ttk.Button(card, text=locate_txt,
                                     style="Bell.TButton",
                                     command=app.on_locate_clients)
    app.bell_locate_btn.pack(pady=(6, 14), padx=24)

    # ---- 右侧抽屉(采集的界面入口已撤,控件照建:开抽屉走 `toggle_drawer`) ----
    app.bell_drawer = tk.Frame(body, bg=CARD, highlightthickness=3,
                               highlightbackground=LINE,
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


def draw_bell(app):
    """把当前妖魔位置画到底图上(没有底图就只放大字坐标)。"""
    c = getattr(app, "bell_canvas", None)
    if c is None or not c.winfo_exists():
        return
    spot = app.engine.bell_tool.ui_state()["spot"]
    if app._bell_spot == spot and c.find_all():
        return
    c.delete("all")
    app._bell_spot = spot
    sk = ui_widgets.apply_bell_skin()
    if not spot:
        c.create_text(BELL_W // 2, BELL_H // 2, text="等待铃铛任务提示",
                      fill=sk["sub"], font=(sk["font"], 12))
        app.bell_hint.configure(text="")
        return
    name, x, y = spot
    path = tools_bell.map_asset(name)
    if not path:
        c.create_text(BELL_W // 2, BELL_H // 2,
                      text=(f"{name}\n{x}, {y}" if x is not None else name),
                      fill=sk["yellow"], justify="center",
                      font=(sk["font_big"], 22))
        app.bell_hint.configure(text=f"内置底图缺「{name}」"
                                     "(data/maps 里没有这张)")
        return
    try:
        import os

        from PIL import Image, ImageTk
        # 底图解码 + 缩放缓存:每换一个点就重新读盘/重采样没意义(底图不变)
        key = (path, os.path.getmtime(path))
        got = getattr(app, "_bell_base", None)
        if not got or got[0] != key:
            img = Image.open(path).convert("RGB")
            ratio = min(BELL_W / img.width, BELL_H / img.height)
            disp = img.resize((max(1, int(img.width * ratio)),
                               max(1, int(img.height * ratio))), Image.LANCZOS)
            got = (key, ImageTk.PhotoImage(disp), ratio, disp.width,
                   disp.height, img.size)
            app._bell_base = got
            app._bell_base_photo = got[1]      # Tk 的图得留引用,别被回收
        _k, photo, ratio, dw, dh, src = got
        app._bell_photo = photo
        ox = (BELL_W - dw) // 2
        oy = (BELL_H - dh) // 2
        c.create_image(ox, oy, image=photo, anchor="nw")
        if x is None or y is None:
            app.bell_hint.configure(text="")   # 只有图没坐标:什么也不画、也不写字
            return
        fx, fy = tools_bell.map_pixel(name, x, y)
        dx = min(max(ox + fx * ratio, ox), ox + dw)
        dy = min(max(oy + fy * ratio, oy), oy + dh)
        if not (ox <= ox + fx * ratio <= ox + dw
                and oy <= oy + fy * ratio <= oy + dh):
            # 夹边这事儿不能悄悄做:坐标落到底图外面 = 底图/坐标范围对不上,
            # 得让用户在日志里看见,不然只会觉得"点怎么画到边上了"
            app.log(f"[铃铛]{name} ({x},{y}) 落到底图外面了(底图 {src[0]}x"
                    f"{src[1]}),点已夹到边上 —— 重新采一次这张底图")
        # 就一个红圆点(用户要求):外圈浅色描边,压在任何底图上都看得见
        c.create_oval(dx - 8, dy - 8, dx + 8, dy + 8, fill="#ff2d2d",
                      outline="#ffffff", width=2)
        app.bell_hint.configure(text="")
    except Exception as err:
        c.create_text(BELL_W // 2, BELL_H // 2, text=f"{name}\n{x}, {y}",
                      fill=sk["yellow"], justify="center",
                      font=(sk["font_big"], 22))
        app.bell_hint.configure(text=f"底图读取失败:{err}")
