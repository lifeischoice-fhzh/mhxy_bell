"""共享的窗口基础设施:窗口摆位与动效、降妖伏魔小窗皮肤。

各窗口都从这里取,自己不重复实现。纯截屏在 screen.py,窗口通用件在
win_common.py(单文件可拷给新应用)、小窗皮肤在 ui/skin.py;本文件只做
再导出,`ui_widgets.XXX` 的既有引用不变。
"""
from screen import freeze_screen  # noqa: F401
from win_common import (centered_xy, dark_titlebar, hide_maximize,  # noqa: F401
                        hover_tip, pop_in, round_pts, set_place,
                        set_window_icon, stop_anim, win_origin)
from ui.skin import (BELL_SKINS, _shade, apply_bell_skin,  # noqa: F401
                     bell_image, bell_palette, chip_image, current_mode)
