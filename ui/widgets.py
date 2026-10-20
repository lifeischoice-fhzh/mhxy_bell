"""共享的窗口基础设施:全屏冻结截图、窗口摆位与动效、降妖伏魔小窗皮肤。

各窗口都从这里取,自己不重复实现。
"""


def freeze_screen():
    """全屏冻结截图(主显示器),返回 PIL RGB 图。"""
    from PIL import Image
    import mss
    import numpy as np

    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[1])
    arr = np.asarray(shot)
    return Image.fromarray(arr[:, :, :3][:, :, ::-1])


# ---- 窗口摆位与动效:所有窗口都走这一份,切来切去才不会"到处乱飞" ----
FADE_MS, FADE_STEP_MS = 160, 25      # 淡入淡出时长 / 每帧间隔(Windows 的定时器
#                                      粒度就是 ~16ms,帧太密反而拖长总时长)
POP_PX, POP_MS = 18, 200             # 弹出时从偏下这么多像素滑到位 / 时长
TITLE_H = 28                         # 大致标题栏高度:居中时往上让一点


def win_origin(win):
    """窗口的"摆放坐标" (x, y) —— 和 `geometry("+x+y")` 同一套。

    别拿 `winfo_rootx/rooty` 当摆放坐标:那是**客户区**的屏幕坐标,和 geometry
    差一个标题栏+边框(这台机器 125% 缩放下差 9/38),拿它去摆窗每切一次就漂一点。
    """
    try:
        return (int(win.winfo_x()), int(win.winfo_y()))
    except Exception:
        return None


def window_box(win):
    """窗口的屏幕矩形 (x, y, 宽, 高);还没映射时用请求尺寸兜底。"""
    try:
        w, h = win.winfo_width(), win.winfo_height()
        if w <= 1 or h <= 1:
            w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        return (win.winfo_rootx(), win.winfo_rooty(), w, h)
    except Exception:
        return None


def centered_xy(size, screen, ref=None):
    """(宽,高) 要摆到屏幕(或 ref 矩形)正中的左上角坐标,自动夹进屏幕内。"""
    w, h = int(size[0]), int(size[1])
    sw, sh = int(screen[0]), int(screen[1])
    if ref:
        x = int(ref[0]) + (int(ref[2]) - w) // 2
        y = int(ref[1]) + (int(ref[3]) - h) // 2
    else:
        x = (sw - w) // 2
        y = (sh - h) // 2 - TITLE_H // 2
    return (max(0, min(x, max(0, sw - w))), max(0, min(y, max(0, sh - h))))


def place(win, xy):
    """把窗口摆到指定左上角(不改变大小)。"""
    try:
        win.geometry(f"+{int(xy[0])}+{int(xy[1])}")
    except Exception:
        pass


def set_place(win, size=None, ref=None, screen=None):
    """决定这个窗口摆哪(记在 win.p_xy 上,并立刻摆好),返回 (x, y)。

    size 不给就用窗口的请求尺寸。所有主窗都居中 —— 这是一个应用,不各摆各的。
    """
    if screen is None:
        screen = (win.winfo_screenwidth(), win.winfo_screenheight())
    if size is None:
        size = (win.winfo_reqwidth(), win.winfo_reqheight())
    xy = centered_xy(size, screen, ref)
    win.p_xy = xy
    place(win, xy)
    return xy


def stop_anim(win):
    """把还没跑完的动效停掉。

    销毁窗口前叫一声:`after` 的回调是挂在 Tk 命令上的,窗口先没了、回调还在排队,
    Tk 删命令时会抛 "can't delete Tcl command"。
    """
    aid = getattr(win, "_anim_after", None)
    if aid:
        try:
            win.after_cancel(aid)
        except Exception:
            pass
        win._anim_after = None


def _animate(win, frames, step_ms=FADE_STEP_MS, done=None):
    """逐帧跑 frames,跑完调 done。

    单帧出异常**不能**让整段动画断掉:断了的话收尾动作(隐藏/销毁窗口)就不执行,
    窗口会一直挂在屏幕上 —— 这种"偶尔没淡出"最容易被当成玄学。
    """
    stop_anim(win)

    def run(i):
        win._anim_after = None
        if not win.winfo_exists():
            return
        if i >= len(frames):
            if done:
                try:
                    done()
                except Exception:
                    pass
            return
        try:
            frames[i]()
        except Exception:
            pass
        win._anim_after = win.after(step_ms, lambda: run(i + 1))
    run(0)


def pop_in(win, xy=None, offset=(0, POP_PX), ms=POP_MS, show=True):
    """淡入 + 轻微滑入(默认从下方 offset 像素滑到位),像"浮"出来。

    show=True 时它负责把窗口显示出来,而且**顺序是"先全透明、再显示"** ——
    反过来(先显示再设透明)中间会画出一帧满不透明的窗,看起来就是"闪一下再淡入",
    窗口越大越明显(大窗一眼就能看出来,小窗几乎看不出来)。

    xy 不给就用窗口现在的位置;`offset=None` 是纯淡入,一个 geometry 都不动 ——
    迷你窗那种位置由别人随时校正的必须用这个。
    平台不支持 -alpha 就直接显示,不折腾。
    """
    if offset is None:
        if show:
            try:
                win.attributes("-alpha", 0.0)
            except Exception:
                pass
            try:
                win.deiconify()
            except Exception:
                pass
        try:
            win.attributes("-alpha", 0.0)
        except Exception:
            return
        steps = max(1, ms // FADE_STEP_MS)

        def fade(k=0):
            win.attributes("-alpha", min(1.0, (k + 1) / float(steps)))
        _animate(win, [lambda k=i: fade(k) for i in range(steps)])
        return
    if xy is None:
        try:
            xy = (win.winfo_rootx(), win.winfo_rooty())
        except Exception:
            xy = (0, 0)
    if show:
        try:
            win.attributes("-alpha", 0.0)
        except Exception:
            pass
        try:
            win.deiconify()
        except Exception:
            pass
    try:
        win.attributes("-alpha", 0.0)
    except Exception:                     # 不支持透明度:直接摆到位
        return
    steps = max(1, ms // FADE_STEP_MS)
    frames = []
    for i in range(1, steps + 1):
        k = i / float(steps)

        def frame(k=k):
            win.attributes("-alpha", min(1.0, k))
            win.geometry("+{}+{}".format(
                int(xy[0] + offset[0] * (1 - k)),
                int(xy[1] + offset[1] * (1 - k))))
        frames.append(frame)

    def done():
        try:
            win.geometry(f"+{int(xy[0])}+{int(xy[1])}")
        except Exception:
            pass
    _animate(win, frames, done=done)


def fade_out(win, then=None, ms=FADE_MS):
    """淡出,完了执行 then(一般是 destroy / withdraw)。"""
    try:
        if not win.winfo_exists():
            raise RuntimeError("窗口没了")
        win.attributes("-alpha", 1.0)
    except Exception:
        if then:
            then()
        return
    steps = max(1, ms // FADE_STEP_MS)
    frames = []
    for i in range(1, steps + 1):
        k = i / float(steps)

        def frame(k=k):
            win.attributes("-alpha", max(0.0, 1.0 - k))
        frames.append(frame)
    _animate(win, frames, done=then)


# ---- 统一外观:主页窗口用这一套扁平卡片风(降妖伏魔小窗另有 Q版皮肤) ----
BG, CARD = "#f0f3f8", "#ffffff"
ACCENT, TXT, SUB = "#2f6fb0", "#1f2a3a", "#7b8794"
BORDER = "#e2e8f0"


def apply_theme():
    """配好 ttk 主题与共用样式(扁平卡片风),返回调色板。

    ttk.Style 是全局的,但样式得有人在窗口显示**之前**配过;每个功能窗口
    各调一次(幂等),这样单进哪个功能都不会缺样式。
    """
    from tkinter import ttk
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    font_base = ("Microsoft YaHei UI", 10)
    style.configure(".", background=CARD, foreground=TXT, font=font_base)
    style.configure("TFrame", background=CARD)
    style.configure("TLabel", background=CARD, foreground=TXT)
    style.configure("Hint.TLabel", background=CARD, foreground=SUB,
                    font=("Microsoft YaHei UI", 9))
    style.configure("Section.TLabel", background=CARD, foreground=ACCENT,
                    font=("Microsoft YaHei UI", 10, "bold"))
    style.configure("Big.TLabel", background=CARD, foreground=ACCENT,
                    font=("Microsoft YaHei UI", 17, "bold"))
    style.configure("Footnote.TLabel", background=CARD, foreground=SUB,
                    font=("Microsoft YaHei UI", 8))
    style.configure("OK.TLabel", background=CARD, foreground="#2f9e5f",
                    font=("Microsoft YaHei UI", 9))
    style.configure("TButton", background="#e9edf3", foreground=TXT,
                    borderwidth=0, focusthickness=0, padding=(10, 5))
    style.map("TButton", background=[("active", "#dbe3ee"),
                                     ("pressed", "#ccd6e4")])
    style.configure("Accent.TButton", background=ACCENT, foreground="#ffffff")
    style.map("Accent.TButton", background=[("active", "#3c81c6"),
                                            ("pressed", "#255d97")])
    style.configure("Danger.TButton", background="#f6e8e8", foreground="#a03535")
    style.map("Danger.TButton", background=[("active", "#efd9d9")])
    style.configure("TCheckbutton", background=CARD, foreground=TXT,
                    focusthickness=0)
    style.map("TCheckbutton", background=[("active", CARD)])
    style.configure("TSpinbox", fieldbackground="#ffffff", borderwidth=1,
                    arrowsize=13)
    style.configure("Slot.TLabel", background="#f7f9fc", foreground=SUB,
                    font=("Microsoft YaHei UI", 9))
    style.configure("SlotClose.TButton", background="#f7f9fc",
                    foreground="#9aa4b2", borderwidth=0, padding=(2, 2))
    style.map("SlotClose.TButton",
              background=[("active", "#f0d9d9")],
              foreground=[("active", "#c0392b")])
    style.configure("Horizontal.TScale", background=CARD,
                    troughcolor="#dfe5ee", borderwidth=0)
    return {"bg": BG, "card": CARD, "accent": ACCENT, "txt": TXT, "sub": SUB,
            "border": BORDER}


# ---- 降妖伏魔小窗皮肤(按用户给的梦幻西游客户端截图对齐,2026-10-21) ----
# 深靛蓝半透明面板 + 米白正文 + 亮黄数值 + 砖红圆角按钮(「确认加点/升级/技能」
# 那排)+ 地图框金边。字体用宋体 —— 客户端的 UI 字就是位图宋体的观感。
# Tk 给不了圆角,按钮/牌子这些圆角外形是**用 PIL 现画成图**再塞进 ttk 的
# (`_round_img` / `_btn_images`,以及给 ui/bell.py 用的 `bell_image()`)。
# **样式名一律带 `Bell` 前缀**,跟 `apply_theme()` 那套不撞名 —— 两套皮肤互不踩脚。
BELL_SKIN = {
    "bg": "#141830",          # 窗口底:深靛蓝
    "card": "#20264c",        # 面板:深靛蓝(游戏半透明面板的近似色)
    "btn": "#c05a50",         # 按钮:砖红(「确认加点」那排的圆角钮)
    "paper": "#10142c",       # 画布底:比面板更深一档
    "line": "#6a6fae",        # 冷紫细边(面板描边)
    "gold": "#e0b95c",        # 金:地图框/坐标牌描边
    "gold_txt": "#2a1c06",
    "green": "#a4e05a",       # 亮绿:强调(抽屉小标题)
    "jade": "#57c98b",        # 草绿:肯定态高亮(BellAccent.TButton)
    "red": "#ff6a52",         # 珊瑚红:异常提示
    "yellow": "#ffe37a",      # 亮黄:数值
    "txt": "#f2eede",         # 米白正文(游戏正文色)
    "sub": "#9aa2cc",         # 次要灰紫
    "stroke": "#0a0e1e",      # 字的深色描边(游戏里的字都有)
    "font": "宋体",           # 客户端的位图宋体观感
    "font_big": "宋体",       # 大字坐标:同字体 + 黑描边(游戏数值的样子)
}

_BELL_TK = None               # 皮肤是"每个 Tk 解释器一份"的(测试会新建 root)
_BELL_IMGS = {}               # PIL 画的圆角图:得留引用,不然被 GC 掉图就没了


def _round_pil(w, h, radius, fill, outline, width=3, gloss=None):
    """PIL 版圆角矩形(要往上压字的那种图,得先拿 PIL 对象再画字)。

    Tk 给不了圆角,只能用 PIL 画好当图片用。超采样 4 倍再缩,圆角边才不毛。
    """
    from PIL import Image, ImageDraw
    s = 4
    img = Image.new("RGBA", (w * s, h * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, w * s - 1, h * s - 1], radius=radius * s,
                        fill=fill, outline=outline, width=int(width * s))
    if gloss:
        pad = int((width + 2) * s)
        d.rounded_rectangle([pad, pad, w * s - pad, int(h * s * 0.56)],
                            radius=max(2, (radius - width) * s), fill=gloss)
    return img.resize((w, h), Image.LANCZOS)


def _round_img(w, h, radius, fill, outline, width=3, gloss=None):
    """同上,直接给一张 Tk 能用的 PhotoImage。"""
    from PIL import ImageTk
    return ImageTk.PhotoImage(
        _round_pil(w, h, radius, fill, outline, width, gloss))


def _bell_imgs():
    """拿"当前 Tk 解释器"的图片缓存(换了解释器就清空重建,测试里会有多个 root)。

    这些 PhotoImage **必须留着引用**:Tk 图没人持有就销毁,样式元素/Label 会指向
    空图(表现是按钮突然退回"没底色的文字",第一次渲染时还看不出来)。
    """
    from tkinter import ttk
    global _BELL_TK, _BELL_IMGS
    tk_ = ttk.Style().tk
    if _BELL_TK is not tk_:
        _BELL_TK, _BELL_IMGS = tk_, {}
    return _BELL_IMGS


def _bell_pil_font(kind, size):
    """挑一个字体文件给 PIL(PIL 只认文件,给家族名找不到)。"""
    from PIL import ImageFont
    for path in BELL_FONT_FILES.get(kind, ()):
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _shade(color, k):
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(max(0, min(255, v + k)) for v in (r, g, b))


def _btn_images(fill, outline, gloss=(255, 255, 255, 95)):
    """一个按钮的**三态**圆角图:常态 / 悬停(亮一点)/ 按下(暗一点)。"""
    return [_round_img(96, 40, 14, _shade(fill, k), outline, 3, gloss)
            for k in (0, 18, -24)]


def bell_image(kind, w, h):
    """给 ui/bell.py 用的圆角底图(带缓存):plaque=金标题牌,chip=小圆牌。"""
    from PIL import ImageTk
    imgs = _bell_imgs()
    key = (kind, w, h)
    got = imgs.get(key)
    if got is not None:
        return got
    c = BELL_SKIN
    if kind == "plaque":
        img = _round_pil(w, h, 16, c["gold"], "#8a6a24", 3,
                         (255, 255, 255, 110))
    else:                                    # "chip":小圆牌(抽屉小标题)
        img = _round_pil(w, h, 13, c["card"], c["line"], 2, None)
    out = ImageTk.PhotoImage(img)
    imgs[key] = out
    return out


# PIL 要字体**文件**,给家族名它找不到。客户端的 UI 字是位图宋体的观感
# (用户定的 2026-10-21),所以两档都走 simsun;机器上没有就顺着往下退,
# 最后退到 PIL 自带点阵字。
BELL_FONT_FILES = {
    "font_big": ("C:/Windows/Fonts/simsun.ttc", "C:/Windows/Fonts/msyh.ttc"),
    "font": ("C:/Windows/Fonts/simsun.ttc", "C:/Windows/Fonts/msyh.ttc"),
}


def bell_coord(text, w=424, h=68, size=32):
    """坐标牌 = **圆角深色牌 + 一行带黑边的亮黄大字**(合成一张图,Label 直接用)。

    为什么不拆成"图 + 文字":游戏里的字是"白字黑边",Tk 画不出描边,只能整张画。
    字一变就得重画(调用点 `ui/bell.set_coord`)。缓存只留最近一张 —— 每换一个
    目标就是一张新图,留着不放会越积越多。
    """
    from PIL import ImageDraw, ImageTk
    c = BELL_SKIN
    imgs = _bell_imgs()
    key = ("coord", text, w, h, size)
    got = imgs.get(key)
    if got is not None:
        return got
    for k in [k for k in imgs if k[0] == "coord"]:
        imgs.pop(k, None)                    # 上一张坐标图没人用了,扔掉
    img = _round_pil(w, h, 22, c["paper"], c["gold"], 3, (255, 255, 255, 34))
    ImageDraw.Draw(img).text(
        (w // 2, h // 2), text, font=_bell_pil_font("font_big", size),
        fill=c["yellow"], anchor="mm", stroke_width=max(2, size // 12),
        stroke_fill=c["stroke"])
    out = ImageTk.PhotoImage(img)
    imgs[key] = out
    return out


def apply_bell_skin():
    """配好降妖伏魔小窗那套客户端风样式(幂等),返回调色板。

    调用点在 `ui/bell.py:build_bell`(**建控件之前**)。样式名一律 `Bell*`,
    和 `apply_theme()` 那套不撞名,所以两套皮肤可以各长各的样。`ttk` 的元素和
    图片都是**按 Tk 解释器**存的,新建 root 会重建一遍(测试里跑多个 App)。
    """
    global _BELL_TK, _BELL_IMGS
    from tkinter import ttk
    c = BELL_SKIN
    ui_font = c["font"]
    style = ttk.Style()
    try:
        style.theme_use("clam")
    except Exception:
        pass
    if _BELL_TK is not style.tk:
        _BELL_TK, _BELL_IMGS = style.tk, {}
        # 圆角按钮:自造一个"图片底"元素(ttk 的 9 宫格拉伸),再套回标准按钮布局 ——
        # 这样 `winfo_class()` 还是 TButton,`cget("text")` / `invoke()` 全照旧能用。
        for name, fill, outline, fg, gloss in (
                ("Bell.TButton", c["btn"], "#6e2a24", "#ffffff",
                 (255, 255, 255, 70)),
                ("BellGold.TButton", c["gold"], "#8a6a24", c["gold_txt"],
                 (255, 255, 255, 120)),
                ("BellAccent.TButton", c["jade"], "#2e7d55", "#ffffff",
                 (255, 255, 255, 90)),
                ("BellGhost.TButton", "#1b2f44", "#33506b", c["sub"],
                 None)):
            el = name.replace(".", "_")
            try:
                # **图片得自己留着引用**:Tk 图没人持有就销毁,样式元素会指向空图
                # (表现是按钮突然退回"没底色的文字",第一次渲染时还看不出来)。
                imgs = _btn_images(fill, outline, gloss)
                _BELL_IMGS[("btn", name)] = imgs
                style.element_create(el, "image", *imgs, border=14,
                                     sticky="nswe")
                style.layout(name, [(el, {"sticky": "nswe", "children": [
                    ("Button.padding", {"sticky": "nswe", "children": [
                        ("Button.label", {"sticky": "nswe"})]})]})])
            except Exception:
                pass                          # 这个解释器里已经配过了
            style.configure(name, background=fill, foreground=fg,
                            borderwidth=0, focusthickness=0,
                            font=(ui_font, 10, "bold"), padding=(18, 6))
    style.configure("Bell.TFrame", background=c["card"])
    style.configure("Bell.TLabel", background=c["card"], foreground=c["txt"],
                    font=(ui_font, 10))
    style.configure("BellSection.TLabel", background=c["card"],
                    foreground=c["green"], font=(ui_font, 11, "bold"))
    style.configure("BellHint.TLabel", background=c["card"],
                    foreground=c["sub"], font=(ui_font, 9))
    style.configure("BellFoot.TLabel", background=c["card"],
                    foreground=c["sub"], font=(ui_font, 8))
    return dict(c)
