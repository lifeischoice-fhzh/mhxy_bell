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
FADE_STEP_MS = 25                    # 淡入每帧间隔(Windows 的定时器粒度就是
#                                     ~16ms,帧太密反而拖长总时长)
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


def dark_titlebar(win, color="#0f1116"):
    """Windows 10/11:把标题栏刷成深色(和窗口底一致);color=None = 恢复系统浅色。

    不改的话是一条亮的系统标题栏压在近黑窗口上,特别突兀;切回明亮主题时得把
    它还原成系统的白标题栏。属性不支持就静默跳过(DWM 属性号 Win10 20H1 前后
    改过一次,两个都试)。
    """
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        val = ctypes.c_int(0 if color is None else 1)
        for attr in (20, 19):                 # DWMWA_USE_IMMERSIVE_DARK_MODE
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
        if color is None:
            # DWMWA_CAPTION_COLOR = DWMWA_COLOR_DEFAULT(0xFFFFFFFF) -> 跟随系统
            cref = ctypes.c_int(-1)
        else:
            # DWMWA_CAPTION_COLOR(只 Win11 有):COLORREF = 0x00BBGGRR
            rgb = (int(color[1:3], 16), int(color[3:5], 16),
                   int(color[5:7], 16))
            cref = ctypes.c_int(rgb[0] | (rgb[1] << 8) | (rgb[2] << 16))
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, 35, ctypes.byref(cref), ctypes.sizeof(cref))
    except Exception:
        pass


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


# ---- 降妖伏魔小窗皮肤:两套(2026-10-21 用户选的 A 深色 / B 明亮) ----
# A=深色 HUD(默认):单面色板,**没有卡片套卡片**,地图就是主体,金色只给坐标,
# 红色只给红点。B=明亮:同样的版面,白底深字,坐标用近黑。
# 小字用雅黑(宋体在 10px 会糊),坐标用等宽数字(位数一眼对齐)。
# 界面上不出现"监听/定位"这类交代程序在干什么的文案(用户定的 2026-10-21)。
# Tk 给不了圆角,按钮/小牌这些圆角外形是**用 PIL 现画成图**再塞进 ttk 的
# (`_round_img` / `_btn_images` / `_icon_images`)。
# **样式名一律带 `Bell` 前缀**,不会跟别处的 ttk 样式撞名。
BELL_SKINS = {
    "a": {
        "bg": "#0f1116",          # 窗口底:近黑
        "card": "#0f1116",        # 单面色(抽屉/弹窗也拿它当底)
        "paper": "#0f1116",       # 画布底:和窗口底同色 —— 底图比画框窄/矮时,留边
        #                           就是窗口底色,不该出现一块"另一个颜色"的框
        "line": "#232936",        # 分隔线/细边
        "map_edge": "#232936",    # 地图那圈 1px 描边(深色下几乎看不见)
        "btn": "#20242e",         # 按钮底
        "btn_line": "#333a4a",
        "gold": "#f0c05a",        # 金:坐标(全窗唯一强调色)
        "gold_line": "#b8933f",
        "gold_txt": "#1a1206",
        "green": "#5fd18a",       # 亮绿:强调(抽屉小标题)
        "red": "#ff6a52",         # 珊瑚红:异常提示
        "yellow": "#f0c05a",      # 同金:数值(pick_client 选中行)
        "dot": "#ff3b30",         # 红点
        "dot_ring": "#ffffff",
        "txt": "#e9ecf2",         # 主文字
        "sub": "#7d8798",         # 次要灰
        "titlebar": "#0f1116",    # 标题栏(深色模式下强制刷成同色)
        "font": "Microsoft YaHei UI",
        "font_num": "Consolas",   # 坐标:等宽数字
    },
    "b": {
        "bg": "#ffffff",          # 窗口底:白
        "card": "#ffffff",
        "paper": "#ffffff",       # 画布底:同窗口底(留边融进白底,只靠 1px 描边分界)
        "line": "#e4e7ec",
        "map_edge": "#d8dde5",    # 白底上的地图边界:比 line 再深一档才看得见
        "btn": "#f4f5f7",
        "btn_line": "#dfe3e9",
        "gold": "#111827",        # 坐标:近黑(明亮模式下不用金色)
        "gold_line": "#c7ccd4",
        "gold_txt": "#ffffff",
        "green": "#16a34a",
        "red": "#dc2626",
        "yellow": "#111827",
        "dot": "#ef4444",
        "dot_ring": "#ffffff",
        "txt": "#141922",
        "sub": "#6b7280",
        "titlebar": None,         # None = 恢复系统标题栏(白)
        "font": "Microsoft YaHei UI",
        "font_num": "Consolas",
    },
}
_BELL_MODE = "a"              # 当前生效的模式("a" 深色 / "b" 明亮)

_BELL_TK = None               # 皮肤是"每个 Tk 解释器一份"的(测试会新建 root)
_BELL_IMGS = {}               # PIL 画的圆角图:得留引用,不然被 GC 掉图就没了
_BELL_ELEMS = set()           # 这个解释器里已经建过的 ttk 元素(两种模式各一套)
_BELL_APPLIED = None          # 当前已经生效的模式(None = 还没配过)


def bell_palette(mode=None):
    """取一套色板(mode 不给就取当前生效的)。"""
    return BELL_SKINS.get(mode or _BELL_MODE, BELL_SKINS["a"])


def current_mode():
    """当前生效的皮肤模式("a" 深色 / "b" 明亮)。"""
    return _BELL_MODE


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


def _shade(color, k):
    r, g, b = (int(color[i:i + 2], 16) for i in (1, 3, 5))
    return "#%02x%02x%02x" % tuple(max(0, min(255, v + k)) for v in (r, g, b))


def _btn_images(fill, outline, gloss=(255, 255, 255, 95)):
    """一个按钮的**三态**圆角图:常态 / 悬停(亮一点)/ 按下(暗一点)。"""
    return [_round_img(96, 40, 14, _shade(fill, k), outline, 3, gloss)
            for k in (0, 16, -20)]


def bell_image(w, h):
    """给 ui/bell.py 抽屉小标题用的圆角底图(带缓存的 PhotoImage)。"""
    from PIL import ImageTk
    imgs = _bell_imgs()
    key = (current_mode(), w, h)
    got = imgs.get(key)
    if got is not None:
        return got
    c = bell_palette()
    out = ImageTk.PhotoImage(
        _round_pil(w, h, 13, c["card"], c["line"], 1, None))
    imgs[key] = out
    return out


def _icon_pil(fill, outline, fg, glyph, size=28):
    """圆形图标按钮:灰底圆 + 一个字形(↻ 换客户端 / ☀ 切明亮 / ☾ 切深色)。"""
    from PIL import ImageDraw, ImageFont
    img = _round_pil(size, size, size // 2, fill, outline, 1, None)
    d = ImageDraw.Draw(img)
    font = None
    for path in ("C:/Windows/Fonts/seguisym.ttf",
                 "C:/Windows/Fonts/msyh.ttc"):
        try:
            font = ImageFont.truetype(path, 14)
            break
        except Exception:
            continue
    if font is not None:
        d.text((size // 2, size // 2 - 1), glyph, font=font, fill=fg,
               anchor="mm")
    else:                                    # 一个字体都没有:画个圈
        d.arc([8, 8, size - 8, size - 8], 40, 300, fill=fg, width=2)
    return img


def _icon_images(glyph, palette):
    """图标按钮的**三态**图(常态 / 悬停 / 按下)。"""
    from PIL import ImageTk
    c = palette
    return [ImageTk.PhotoImage(
        _icon_pil(_shade(c["btn"], k), c["btn_line"],
                  c["txt"] if k >= 0 else c["sub"], glyph))
        for k in (0, 16, -20)]


_BTN_SPECS = (                # (样式名, 元素标签, 底色, 描边, 字色, 高光, 内边距)
    ("Bell.TButton", "Btn", "btn", "btn_line", "txt", (255, 255, 255, 26),
     (16, 0), 14),
    ("BellGold.TButton", "Gold", "gold", "gold_line", "gold_txt",
     (255, 255, 255, 110), (16, 0), 14),
    ("BellGhost.TButton", "Ghost", "btn", "btn_line", "sub", None,
     (16, 0), 14),
)
_ICON_SPECS = (               # (样式名, 元素标签, 字形:显示"切过去"的那个模式)
    ("BellIcon.TButton", "Icon", None),        # ↻:换客户端,两种模式都一样
    ("BellTheme.TButton", "Theme", {"a": "☀", "b": "☾"}),
)


def apply_bell_skin(mode=None):
    """配好降妖伏魔小窗的样式(幂等),返回**当前模式**的调色板。

    mode="a" 深色 / "b" 明亮;不给就沿用上一次生效的模式。
    两种模式的 ttk 元素都在第一次调用时建好(各一套图),之后切换只改
    `style.layout(...)` 指向哪一套 + `style.configure(...)` 的颜色 —— 控件不用重建。
    `ttk` 的元素和图片都是**按 Tk 解释器**存的,新建 root 会重建一遍(测试里多个 App)。
    """
    global _BELL_TK, _BELL_IMGS, _BELL_MODE, _BELL_APPLIED
    from tkinter import ttk
    if mode in BELL_SKINS:
        _BELL_MODE = mode
    c = bell_palette()
    ui_font = c["font"]
    style = ttk.Style()
    if _BELL_TK is style.tk and _BELL_APPLIED == _BELL_MODE:
        return dict(c)              # 同一套已经配过:别每次重画图片(Tk 调用很贵)
    try:
        style.theme_use("clam")
    except Exception:
        pass
    if _BELL_TK is not style.tk:
        _BELL_TK, _BELL_IMGS = style.tk, {}
        _BELL_ELEMS.clear()
        _BELL_APPLIED = None

    def _ensure(el, imgs, border):
        """建一次图片元素;已经建过就跳过(元素名按模式分开,互不覆盖)。"""
        if el in _BELL_ELEMS:
            return True
        try:
            # 状态图要写成 (状态, 图) —— 顺序反了会报 "Invalid state name",
            # 直接被 except 吞掉,按钮就退回方角纯色块(踩过)。
            style.element_create(el, "image", imgs[0], ("active", imgs[1]),
                                 ("pressed", imgs[2]), border=border,
                                 sticky="nswe")
            _BELL_ELEMS.add(el)
            return True
        except Exception:
            return False

    def _layout(name, el):
        style.layout(name, [(el, {"sticky": "nswe", "children": [
            ("Button.padding", {"sticky": "nswe", "children": [
                ("Button.label", {"sticky": "nswe"})]})]})])

    # 两种模式的图片元素都建好(切模式时只换指向,不重建)
    for m, pal in BELL_SKINS.items():
        for name, tag, fill_k, line_k, fg_k, gloss, _pad, border in _BTN_SPECS:
            key = f"Bell{tag}_{m}"
            if key in _BELL_ELEMS:
                continue
            imgs = [_round_img(96, 40, 14, _shade(pal[fill_k], k), pal[line_k],
                               3, gloss) for k in (0, 16, -20)]
            # **图片得自己留着引用**:Tk 图没人持有就销毁,样式元素会指向空图。
            _BELL_IMGS[("btn", key)] = imgs
            _ensure(key, imgs, border)
        for name, tag, glyphs in _ICON_SPECS:
            key = f"Bell{tag}_{m}"
            if key in _BELL_ELEMS:
                continue
            imgs = _icon_images(glyphs[m] if glyphs else "↻", pal)
            _BELL_IMGS[("btn", key)] = imgs
            _ensure(key, imgs, 10)

    # 把样式指向当前模式那套元素,并配上颜色
    for name, tag, fill_k, line_k, fg_k, gloss, pad, border in _BTN_SPECS:
        el = f"Bell{tag}_{_BELL_MODE}"
        _layout(name, el)
        # background 用窗口底色:圆角图的四个角是透明的,露出来的就是它。
        # 填按钮自己的颜色的话,方块底会在圆角外面显形(踩过)。
        style.configure(name, background=c["bg"], foreground=c[fg_k],
                        borderwidth=0, focusthickness=0,
                        font=(ui_font, 10, "bold"), padding=pad)
    # 无文字的圆形图标按钮(28x28):没有内边距,字号压到 1pt ——
    # 空标签会按 TkDefaultFont 的行高把按钮撑成 28x40,圆角图跟着纵向拉伸。
    for name, tag, _glyphs in _ICON_SPECS:
        el = f"Bell{tag}_{_BELL_MODE}"
        _layout(name, el)
        style.configure(name, background=c["bg"], borderwidth=0,
                        focusthickness=0, padding=(0, 0), font=(ui_font, 1))
    style.configure("Bell.TFrame", background=c["card"])
    style.configure("Bell.TLabel", background=c["card"], foreground=c["txt"],
                    font=(ui_font, 10))
    style.configure("BellSection.TLabel", background=c["card"],
                    foreground=c["green"], font=(ui_font, 11, "bold"))
    style.configure("BellFoot.TLabel", background=c["card"],
                    foreground=c["sub"], font=(ui_font, 8))
    _BELL_APPLIED = _BELL_MODE
    return dict(c)
