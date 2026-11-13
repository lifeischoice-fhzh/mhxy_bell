"""梦幻西游客户端窗口:本应用(降妖伏魔)特有的窗口口径。

通用探测(窗口/游戏画布枚举、游戏分辨率折算、档位表、角色名抠取)都在
client_common.py —— 那边是单文件可拷给别的应用的(与 keju 同源);本文件
只留本应用特有的口径:认不认某一档(supported_res)、支持档文案
(supported_res_text)。这里 re-export client_common 的全部
公开名,core.XXX 的既有引用与测试补丁语义不变。顶层不 import core。
"""

from client_common import (CANVAS_WINDOW_CLASS,  # noqa: F401
                           CLIENT_MIN_H, CLIENT_MIN_W,
                           CLIENT_WINDOW_CLASS, CLIENT_WINDOW_TITLE,
                           DLG_RATIOS, GAME_RES_STEPS,
                           SUPPORTED_RES, TRK_BOXES, box_of, canvas_game_res,
                           client_canvas, client_name, client_size_info,
                           dialog_rect, draw_box, find_client_canvases,
                           find_client_windows, ratio_of, trk_rect)


def supported_res(res):
    """这个**游戏设置分辨率**(画布口径)本应用认不认 —— 精确匹配,没有容差。

    三档:640×480 / 800×600 / 1024×768(2026-11-12 用户定的,1024 与 keju
    对齐重新加入)。判定只认画布折算出来的精确值(见 `canvas_game_res`),
    窗口拉伸/Windows 缩放都不参与 —— 档位表本体 `SUPPORTED_RES` 在
    client_common(两边共用同一份),这里只包"本应用认不认"这一层。
    """
    return (int(res[0]), int(res[1])) in SUPPORTED_RES


def supported_res_text():
    """「640×480 / 800×600 / 1024×768」这样的支持档文案,日志与弹框共用。"""
    return " / ".join(f"{w}×{h}" for w, h in sorted(SUPPORTED_RES))
