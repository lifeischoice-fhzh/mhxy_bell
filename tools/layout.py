"""量框命令行:`python main.py --layout`(画布口径)。

在整块游戏画布上找对话框面板,换算成占画比打印;按标定把定稿比例框画到
标注图上存进 docs/layout/。只在命令行模式用,主程序运行时不加载。
"""
import os

from tools.maps import BASE_DIR


# ---- 量框:python main.py --layout(画布口径;存定稿比例框到 docs/layout/) ----
# 对话框/任务栏的真机量测都对着**画布**(WSGAME,纯游戏画面):对话框量出来
# 换算成占画比,直接可填 client_common 的 DLG_RATIOS;任务栏框靠用户在整屏
# 截图上手框(面板能被拖走,机器量不准),框完四边 ÷ 画布尺寸得占画比,填
# TRK_BOXES(与对话框同构,别再存像素)。
# **每档定稿/复核都存一张标注图**到 `docs/layout/<版式>_<WxH>_缩放<N>.png`
# (画蓝框 = 对话框定稿比例框,2026-11-12 用户要求的存档,方便后续查看;
# 版式 "tab"=多标签、"win"=独立窗口;文件名就是「版式_分辨率_缩放」)。
# 老的 bell_layouts.json(按窗口尺寸查 dlg/trk)随 trk 进 common 整体退役
# (2026-11-12;git 历史可找回)。
def _longest_run(idx):
    """一维下标数组里**最长连续段**的 (起,止)（闭区间）；空返回 None。

    给 `cmd_layout` 的投影用:对话框是一整块连续的同色区,散落在别处的暗色
    UI(小地图边框之类)不该把量出来的框拉长。
    """
    import numpy as np
    idx = np.asarray(idx)
    if idx.size == 0:
        return None
    breaks = np.where(np.diff(idx) != 1)[0]
    starts = np.concatenate(([0], breaks + 1))
    ends = np.concatenate((breaks, [idx.size - 1]))
    lens = ends - starts
    i = int(np.argmax(lens))
    return int(idx[starts[i]]), int(idx[ends[i]])


def _panel_box_loose(crop):
    """量框用的面板查找:**自适应取底色** + 行/列投影,返回画布内像素框或 None。

    不走 `panel_box`:它的宽度线(0.72W)/暗比三关是给"收紧后的框"调的,对着
    整块画布量时,547px 的对话框只占 1024 档画布的 0.53W,必被拒;暗场景里
    "暗且不彩"更是到处都是(2026-11-12 真机踩过)。这里按"面板是画面里最大
    的一块均匀色"建模:中部横带(0.30H~0.92H)取暗且低饱和像素的量化众数当
    底色,行投影取最长连续段、再在段内收紧列。阈值都比识别松 —— 量出来
    的人眼对着屏幕/标注图核一遍。
    """
    import numpy as np
    H, W = crop.shape[:2]
    band = crop[int(H * 0.30):int(H * 0.92)]
    darkish = band[(band.max(axis=2) < 110)
                   & (band.max(axis=2) - band.min(axis=2) < 40)]
    if darkish.shape[0] < 500:
        return None
    q = (darkish // 8).astype(np.int32)
    key = q[:, 0] * 10000 + q[:, 1] * 100 + q[:, 2]
    vals, cnts = np.unique(key, return_counts=True)
    top = int(vals[np.argmax(cnts)])
    base = np.asarray([(top // 10000) * 8 + 4,
                       (top // 100 % 100) * 8 + 4,
                       (top % 100) * 8 + 4])
    mask = (np.abs(crop.astype(np.int16)
                   - base.astype(np.int16)).sum(axis=2) <= 100)
    rr = _longest_run(np.where(mask.mean(axis=1) >= 0.5)[0])
    if not rr or rr[1] - rr[0] < H * 0.10:
        return None
    cc = _longest_run(
        np.where(mask[rr[0]:rr[1] + 1].mean(axis=0) >= 0.5)[0])
    if not cc or cc[1] - cc[0] < W * 0.25:
        return None
    return [cc[0], rr[0], cc[1] + 1, rr[1] + 1]


def cmd_layout() -> int:
    """命令行:`python main.py --layout` —— 量当前**画布**上对话框的位置。

    必须当下开着铃铛对话框才量得到(靠像素找面板)。量出来换算成占画布的
    比例打印 —— 直接可填 client_common.DLG_RATIOS(两版式共用一套);顺带打印
    画布矩形和游戏分辨率,手框任务栏后四边 ÷ 画布尺寸即占画比(填
    TRK_BOXES)。**同时存
    一张标注图**到 `docs/layout/<版式>_<WxH>_缩放<N>.png`(红框 = 任务栏框
    `TRK_BOXES`、蓝框 = 对话框定稿比例框 `DLG_RATIOS`;哪张没定稿就不画那张)
    —— 每档定稿/复核都留档,方便后续查看。版式 "tab" = 多标签版、
    "win" = 独立窗口版。**面板没开也存图**(表框本身不依赖面板),只是不打印
    检测值。
    """
    import core
    import numpy as np
    from PIL import Image
    core._dpi_aware()          # 和主程序同一套:量出来的是**物理像素**,才对得上
    sc = core.Screen()
    try:
        canvases, _mini = core.find_client_canvases()
    except Exception:
        canvases = []
    if not canvases:
        print("没找到客户端(游戏没开/被最小化/还没进角色 —— 登录窗没有画布)")
        return 1
    for _title, res, rect, _ratio, mode in canvases:
        cw = int(rect[2]) - int(rect[0])
        ch = int(rect[3]) - int(rect[1])
        gw, gh = int(res[0]), int(res[1])
        scale = round(cw / max(1, gw) * 100)
        mode_cn = {"tab": "多标签", "win": "独立窗口"}.get(mode, mode)
        print(f"  画布 {rect}  游戏分辨率 {gw}×{gh}  缩放≈{scale}%  "
              f"版式 {mode_cn}({mode});任务栏框:手框四边 ÷ 画布尺寸填 "
              f"TRK_BOXES")
        try:
            crop = sc.grab([int(v) for v in rect])
            box = _panel_box_loose(crop)
        except Exception:
            crop = box = None
        if crop is None:
            print("    截图失败 —— 看不到画面,标注图没存")
            continue
        if not box:
            print("    对话框:没看到面板 —— 先把一个铃铛对话框打开再跑")
        else:
            print(f"    对话框 dlg 像素框={box}  占画比 ≈ "
                  f"{core.ratio_of([0, 0, cw, ch], box)}"
                  f"  尺寸 {box[2] - box[0]}×{box[3] - box[1]}")
        # 存标注图:**红框 = 任务栏框(TRK_BOXES)、蓝框 = 对话框定稿比例框
        # (DLG_RATIOS)**(2026-11-12 用户定的存档口径),哪张没定稿就不画那张;
        # 检测值只进打印。画框走 common 的 draw_box(纯 numpy 切片),它要
        # **RGB** 数组,而 core.Screen.grab 给的是 BGR,先翻过来再画。
        out = np.ascontiguousarray(crop[:, :, ::-1])
        canvas = [0, 0, cw, ch]
        trk_rat = core.TRK_BOXES.get((gw, gh))
        trk_box = core.box_of(canvas, trk_rat)
        if trk_box:
            core.draw_box(out, canvas, trk_rat, (255, 0, 0))
            print(f"    任务栏框({trk_rat})={tuple(trk_box)}")
        else:
            print(f"    该档 {gw}×{gh} 还没有任务栏框 —— TRK_BOXES 补一行才画红框")
        rat = core.DLG_RATIOS.get((gw, gh))
        fix = core.box_of(canvas, rat)
        if fix:
            core.draw_box(out, canvas, rat, (40, 80, 255))
            if box:
                print(f"    定稿比例框({rat})={tuple(fix)}  "
                      f"偏差 左{fix[0]-box[0]} 上{fix[1]-box[1]} "
                      f"右{fix[2]-box[2]} 下{fix[3]-box[3]}")
            else:
                print(f"    定稿比例框({rat})={tuple(fix)}")
        else:
            print(f"    该档比例还没定稿 —— 上表占画比核对人眼后填 "
                  f"client_common.DLG_RATIOS 再跑一次即出蓝框")
        out_dir = os.path.join(BASE_DIR, "docs", "layout")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir,
                            f"{mode_cn}_{gw}x{gh}_缩放{scale}.png")
        Image.fromarray(out).save(path)
        print(f"    已存标注图 {path}(红=任务栏框、蓝=对话框比例框)")
    return 0
