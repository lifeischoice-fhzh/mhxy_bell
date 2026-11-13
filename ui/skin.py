"""降妖伏魔小窗皮肤:两套色板 + PIL 画的圆角图/图标 + ttk 样式。

纯界面皮,只依赖 tkinter/PIL;窗口通用件在 win_common.py。
"""

# ---- 降妖伏魔小窗皮肤:两套(2026-10-21 用户选的 A 深色 / B 明亮) ----
# A=深色 HUD(默认):单面色板,**没有卡片套卡片**,地图就是主体,金色只给坐标,
# 红色只给红点。B=明亮:同样的版面,白底深字,坐标用近黑。
# 小字用雅黑(宋体在 10px 会糊),坐标用等宽数字(位数一眼对齐)。
# 界面上不出现"监听/定位"这类交代程序在干什么的文案(用户定的 2026-10-21)。
# Tk 给不了圆角,按钮/小牌这些圆角外形是**用 PIL 现画成图**再塞进 ttk 的
# (`_round_img` / `_icon_images`)。
# **样式名一律带 `Bell` 前缀**,不会跟别处的 ttk 样式撞名。
BELL_SKINS = {
    "a": {
        "bg": "#0f1116",          # 窗口底:近黑
        "card": "#0f1116",        # 单面色(抽屉/弹窗也拿它当底)
        "paper": "#0f1116",       # 画布底:和窗口底同色 —— 底图比画框窄/矮时,留边
        #                           就是窗口底色,不该出现一块"另一个颜色"的框
        "line": "#232936",        # 分隔线/细边
        "map_edge": "#232936",    # 地图那圈 1px 描边(深色下几乎看不见)
        "win_edge": "#2a3242",    # 窗口最外那圈 1px:深色底压在深色场景上时,
        #                           只靠系统阴影分不清窗口到哪儿为止
        "btn": "#20242e",         # 按钮底
        "btn_line": "#333a4a",
        "gold": "#f0c05a",        # 金:坐标(全窗唯一强调色)
        "gold_line": "#b8933f",
        "gold_txt": "#1a1206",
        "green": "#5fd18a",       # 亮绿:强调(抽屉小标题)
        "red": "#ff6a52",         # 珊瑚红:异常提示
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
        "win_edge": "#e4e7ec",    # 窗口最外那圈 1px(白底用浅灰,别抢眼)
        "btn": "#f4f5f7",
        "btn_line": "#dfe3e9",
        "gold": "#111827",        # 坐标:近黑(明亮模式下不用金色)
        "gold_line": "#c7ccd4",
        "gold_txt": "#ffffff",
        "green": "#16a34a",
        "red": "#dc2626",
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


def chip_image(w, h, pressed=False, radius=None):
    """底行「角色名 ▾」那个圆角框的底图(按尺寸缓存,按下时暗一档)。

    radius 不给就当胶囊(h/2);展开成列表时传 14(上下圆角别跟着变大)。
    """
    from PIL import ImageTk
    imgs = _bell_imgs()
    rr = max(2, int(radius if radius is not None else int(h) // 2))
    key = (current_mode(), "chip", int(w), int(h), rr, bool(pressed))
    got = imgs.get(key)
    if got is None:
        c = bell_palette()
        fill = _shade(c["btn"], -18 if pressed else 0)
        got = ImageTk.PhotoImage(
            _round_pil(int(w), int(h), rr, fill, c["btn_line"], 1, None))
        imgs[key] = got
    return got


def _icon_pil(fg, glyph, size=30, face=None, line=None):
    """主题钮的字形:**圆形底**(2026-10-22 用户定的:黑白切换钮用圆形)+ 字。

    face/line 是圆底的填充/描边(拿皮肤里的 btn / btn_line);按下换金色字
    (见 `_icon_images`),圆底不变、悬停也不变 —— 点击感只靠字色给。
    """
    from PIL import Image, ImageDraw, ImageFont
    s = 4
    img = Image.new("RGBA", (size * s, size * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if face:
        d.ellipse((s // 2, s // 2, size * s - s // 2, size * s - s // 2),
                  fill=face, outline=line, width=s)
    font = None
    for path in ("C:/Windows/Fonts/seguisym.ttf",
                 "C:/Windows/Fonts/msyh.ttc"):
        try:
            font = ImageFont.truetype(path, 13 * s)
            break
        except Exception:
            continue
    if font is not None:
        d.text((size * s // 2, size * s // 2), glyph, font=font, fill=fg,
               anchor="mm")
    else:                                    # 一个字体都没有:画个圈
        d.arc([8 * s, 8 * s, (size - 8) * s, (size - 8) * s], 40, 300,
              fill=fg, width=2 * s)
    return img.resize((size, size), Image.LANCZOS)


def _icon_images(glyph, palette):
    """主题钮的**三态**图:常态灰字 / 悬停不变 / **按下金字**(点击感)。

    圆底三态都一样(用户 2026-10-22:悬停不换背景)。
    """
    from PIL import ImageTk
    c = palette
    return [ImageTk.PhotoImage(_icon_pil(fg, glyph, face=c["btn"],
                                         line=c["btn_line"]))
            for fg in (c["sub"], c["sub"], c["gold"])]


_BTN_SPECS = (                # (样式名, 元素标签, 底色, 描边, 字色, 高光, 内边距, 图元 border)
    ("Bell.TButton", "Btn", "btn", "btn_line", "txt", (255, 255, 255, 26),
     (16, 0), 14),
    ("BellGold.TButton", "Gold", "gold", "gold_line", "gold_txt",
     (255, 255, 255, 110), (16, 0), 14),
    ("BellGhost.TButton", "Ghost", "btn", "btn_line", "sub", None,
     (16, 0), 14),
)
_ICON_SPECS = (               # (样式名, 元素标签, 字形:显示"切过去"的那个模式)
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
            glyph = glyphs[m] if isinstance(glyphs, dict) else glyphs
            imgs = _icon_images(glyph, pal)
            _BELL_IMGS[("btn", key)] = imgs
            _ensure(key, imgs, 1)     # 透明底图:border 大了会按 3x3 采样把字形切块

    # 把样式指向当前模式那套元素,并配上颜色
    for name, tag, fill_k, line_k, fg_k, gloss, pad, border in _BTN_SPECS:
        el = f"Bell{tag}_{_BELL_MODE}"
        _layout(name, el)
        # background 用窗口底色:圆角图的四个角是透明的,露出来的就是它。
        # 填按钮自己的颜色的话,方块底会在圆角外面显形(踩过)。
        style.configure(name, background=c["bg"], foreground=c[fg_k],
                        borderwidth=0, focusthickness=0,
                        font=(ui_font, 10, "bold"), padding=pad)
    # 无文字的图标按钮(28x28):没有内边距,字号压到 1pt ——
    # 空标签会按 TkDefaultFont 的行高把按钮撑成 28x40,图跟着纵向拉伸。
    for name, tag, _glyphs in _ICON_SPECS:
        el = f"Bell{tag}_{_BELL_MODE}"
        _layout(name, el)
        style.configure(name, background=c["bg"], borderwidth=0,
                        focusthickness=0, padding=(0, 0), font=(ui_font, 1))
        # **必须把 active/pressed 的背景也钉成窗口底色**:clam 的 TButton 在
        # map 里给悬停/按下配了亮一档的底,图片透明后那圈方块就露出来了
        # (2026-10-22 用户截图:悬停时图标后面多一块浅灰)。
        style.map(name,
                  background=[("active", c["bg"]), ("pressed", c["bg"]),
                              ("disabled", c["bg"])],
                  foreground=[("active", c["sub"]), ("pressed", c["sub"])])
    style.configure("Bell.TFrame", background=c["card"])
    style.configure("Bell.TLabel", background=c["card"], foreground=c["txt"],
                    font=(ui_font, 10))
    style.configure("BellSection.TLabel", background=c["card"],
                    foreground=c["green"], font=(ui_font, 11, "bold"))
    style.configure("BellFoot.TLabel", background=c["card"],
                    foreground=c["sub"], font=(ui_font, 8))
    _BELL_APPLIED = _BELL_MODE
    return dict(c)
