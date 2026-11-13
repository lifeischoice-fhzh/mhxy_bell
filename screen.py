"""屏幕截屏(单文件可拷走复用)。

`Screen`:mss 的区域截图(BGR),给识别用;
`freeze_screen`:主显示器整屏冻结成 PIL RGB 图,给界面/录制用。
只依赖 mss / numpy / PIL,不碰配置、不建 OCR 引擎。
"""
import threading

try:
    import numpy as np
except ImportError:  # main() 会给出友好提示
    np = None


class Screen:
    """mss 截图封装。region 为主显示器内的相对物理像素。

    mss 实例按线程各建一个:GDI DC 是线程亲和资源(实例创建时缓存),
    在 Engine 线程建、拿到工具线程里用会失效,所以谁第一次 grab 谁
    自己惰性建(threading.local 每线程各存一份)。
    """

    def __init__(self):
        self._local = threading.local()

    @property
    def _sct(self):
        sct = getattr(self._local, "sct", None)
        if sct is None:
            import mss
            sct = mss.mss()
            self._local.sct = sct
        return sct

    def grab(self, region=None):
        sct = self._sct
        mon = sct.monitors[1]
        if region:
            x1, y1, x2, y2 = region
            box = {"left": mon["left"] + int(x1), "top": mon["top"] + int(y1),
                   "width": max(1, int(x2 - x1)), "height": max(1, int(y2 - y1))}
        else:
            box = dict(mon)
        shot = sct.grab(box)
        arr = np.asarray(shot)          # BGRA
        return np.ascontiguousarray(arr[:, :, :3])  # BGR


def freeze_screen():
    """全屏冻结截图(主显示器),返回 PIL RGB 图。"""
    from PIL import Image
    import mss

    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[1])
    arr = np.asarray(shot)
    return Image.fromarray(arr[:, :, :3][:, :, ::-1])
