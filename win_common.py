"""窗口通用件(单文件可拷走复用到别的 Tk 应用)。

窗口摆位/记住上次位置、标题栏深浅色、去掉最大化、精确尺寸图标、
淡入与滑入动效。只依赖 tkinter/ctypes,不认任何应用口径。
"""

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


def usable_xy(xy, size, screen):
    """存下来的窗口位置还能不能用:得留一条标题栏在屏幕里,不然拖都拖不回来。

    返回 (x, y) 或 None(位置坏了/屏幕换了)。
    """
    if not isinstance(xy, (list, tuple)):
        return None
    try:
        x, y = int(xy[0]), int(xy[1])
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    w = int(size[0])
    sw, sh = int(screen[0]), int(screen[1])
    if -w + 120 <= x <= sw - 120 and 0 <= y <= sh - 30:
        return (x, y)
    return None


def set_place(win, size=None, ref=None, screen=None, pos=None):
    """决定这个窗口摆哪(记在 win.p_xy 上,并立刻摆好),返回 (x, y)。

    size 不给就用窗口的请求尺寸。`pos` 是上次退出时存的位置:还在屏幕里就
    摆回原处(用户 2026-10-21 要求:别每次启动都压回屏幕正中),否则居中。
    """
    if screen is None:
        screen = (win.winfo_screenwidth(), win.winfo_screenheight())
    if size is None:
        size = (win.winfo_reqwidth(), win.winfo_reqheight())
    xy = usable_xy(pos, size, screen) if pos else None
    if xy is None:
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


def hide_maximize(win):
    """让标题栏右上角只剩最小化 + 关闭(用户 2026-10-21 定的)。

    Tk 的 `resizable(False, False)` 本身就把 `WS_MAXIMIZEBOX` 清了(只是把它
    置灰),这里再清一遍 + `SWP_FRAMECHANGED` 让非客户区重画。
    **实测(Win11 24H2 26100)清完那颗按钮只会更灰、不会消失** —— 原生
    `CreateWindowEx` 建一个没有 `WS_MAXIMIZEBOX` 的窗口也一样,所以那不是本
    应用的问题;真要它消失得自绘标题栏,代价是丢任务栏图标和最小化,不做。
    保留这个函数:系统上按钮确实点不动,别的 Windows 版本也许能真删掉。
    """
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id()) or win.winfo_id()
        gwl_style, ws_maximizebox = -16, 0x00010000
        style = ctypes.windll.user32.GetWindowLongW(hwnd, gwl_style)
        ctypes.windll.user32.SetWindowLongW(hwnd, gwl_style,
                                            style & ~ws_maximizebox)
        # SWP_NOSIZE|SWP_NOMOVE|SWP_NOZORDER|SWP_FRAMECHANGED
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x1 | 0x2 | 0x4 | 0x20)
    except Exception:
        pass


_ICON_CACHE = {}


def set_window_icon(win, path):
    """给窗口挂**精确尺寸**的真 HICON(标题栏 / 任务栏),绕开 Tk 那次缩放。

    **别再给这扇窗调 `wm iconbitmap`**:它走 `LoadImage(LR_DEFAULTSIZE)` 取 32px
    那一档,而且 Tk 会在窗口映射后再盖一次,把这里挂的图标顶掉 —— 任务栏只好
    把 32px 缩到 30px,边缘就糊了(2026-10-22 用户拿旁边 Chrome/微信对比:
    "你看糊不糊")。这里自己 LoadImage:标题栏 16、任务栏 24(逻辑像素,按真实
    缩放换算),再 WM_SETICON 挂上去。句柄按 (路径, 尺寸) 缓存 —— `_dress`
    每次 <Map> 都调,不缓存会一遍遍泄漏。
    """
    try:
        import ctypes
        from ctypes import wintypes
        u = ctypes.WinDLL("user32", use_last_error=True)
        u.GetParent.argtypes = [wintypes.HWND]
        u.GetParent.restype = wintypes.HWND
        u.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR,
                                 wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                 wintypes.UINT]
        u.LoadImageW.restype = wintypes.HANDLE
        u.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                   wintypes.WPARAM, wintypes.LPARAM]
        u.SendMessageW.restype = wintypes.LPARAM
        hwnd = u.GetParent(win.winfo_id()) or win.winfo_id()
        # **本进程是 DPI 不感知的**(Tk 看到 1536x864、实际 1920x1080):
        # GetDpiForWindow / GetDpiForSystem 对这种窗口一律返回 96(把线程临时
        # 切到 PMv2 也没用,窗口的 awareness 建的时候就定了)—— 于是只拿到
        # 24px 的图,任务栏再放大到 30px,糊就是这么来的。真实缩放比问 shcore
        # (`GetScaleFactorForMonitor` 报的是系统那档 100/125/150,和进程的
        # awareness 无关)。
        dpi = 96
        try:
            import ctypes as _ct
            shcore = _ct.WinDLL("shcore")
            u.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
            u.MonitorFromWindow.restype = wintypes.HMONITOR
            shcore.GetScaleFactorForMonitor.argtypes = [
                wintypes.HMONITOR, _ct.POINTER(_ct.c_int)]
            hmon = u.MonitorFromWindow(hwnd, 2)   # MONITOR_DEFAULTTONEAREST
            scale = _ct.c_int(100)
            if shcore.GetScaleFactorForMonitor(hmon, _ct.byref(scale)) == 0:
                dpi = int(round(96 * (scale.value or 100) / 100.0))
        except Exception:
            dpi = 96
        px = lambda n: max(4, int(round(n * dpi / 96.0)))   # noqa: E731

        def _hicon(size):
            key = (str(path), size)
            h = _ICON_CACHE.get(key)
            if h:
                return h
            # LR_LOADFROMFILE(0x10) | LR_DEFAULTCOLOR:按请求的像素尺寸取那一档
            h = u.LoadImageW(None, str(path), 1, size, size, 0x10)
            if h:
                _ICON_CACHE[key] = h
            return h

        # ICON_SMALL=0(标题栏) / ICON_BIG=1(Alt-Tab、任务栏) / ICON_SMALL2=2
        for idx, size in ((0, px(16)), (1, px(24)), (2, px(24))):
            h = _hicon(size)
            if h:
                u.SendMessageW(hwnd, 0x0080, idx, h)   # WM_SETICON
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


def round_pts(x1, y1, x2, y2, r):
    """圆角矩形轮廓点列(`create_polygon` + `smooth=True` 一次画圆)。"""
    r = min(r, (x2 - x1) / 2, (y2 - y1) / 2)
    return (x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
            x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
            x1, y2, x1, y2 - r, x1, y1 + r, x1, y1)


def hover_tip(root, text, anchor, font=("Microsoft YaHei UI", 10),
              bg="#20242e", outline="#333a4a", fg="#e9ecf2",
              transparent="#010101", height=26, gap=6, min_w=72):
    """在某控件**上方**浮一条圆角小提示,返回 Toplevel(let 调用方 destroy)。

    无边框 + 置顶 + 四角用 `-transparentcolor` 抠圆(应用只跑 Windows);
    宽度按文案实测自适应。**文案变了就销毁重建**,别拿同一个窗口改字 ——
    宽度不重算会裁字。取不到 anchor 坐标时返回 None(不抛)。
    """
    import tkinter as tk
    from tkinter import font as tkfont
    try:
        x = int(anchor.winfo_rootx())
        y = int(anchor.winfo_rooty())
    except Exception:
        return None
    tip = tk.Toplevel(root)
    try:
        tip.wm_overrideredirect(True)
        tip.wm_attributes("-topmost", True)
        tip.wm_attributes("-transparentcolor", transparent)
    except Exception:
        pass
    tip.configure(bg=transparent)
    f = tkfont.Font(root=root, font=font)
    w = max(int(min_w), int(f.measure(text)) + 26)
    h = int(height)
    cv = tk.Canvas(tip, width=w, height=h, highlightthickness=0,
                   bg=transparent)
    cv.pack()
    cv.create_polygon(round_pts(1, 1, w - 1, h - 1, h // 2), smooth=True,
                      fill=bg, outline=outline, width=1)
    cv.create_text(w / 2, h / 2, text=text, font=font, fill=fg, anchor="c")
    try:
        tip.wm_geometry(f"+{x}+{y - h - int(gap)}")
    except Exception:
        pass
    return tip
