"""对话框面板检测与内容签名(单文件可拷走复用)。

"这块画面里有没有半透明黑面板、面板在哪、里面的字变了没有" —— 只用
numpy,不认降妖伏魔的任务口径。
"""

# ---- 扫描范围与"便宜的门控":先花 1~2ms 判断要不要 OCR,再决定花那 200ms ----
# 游戏把对话框贴在窗口下方居中(底边≈0.85H,字越多越往上长),位置基本固定;
# 面板"暗且不彩"的像素占比远高于它身后那个一直在动的游戏世界 —— 实测 15 张真
# 截图(有面板 0.89~0.95 / 没面板 0.35~0.43),用这个当"有没有对话框"的判据,
# 1ms 出结果,不花 OCR 的钱。
DIALOG_BAND = (0.08, 0.34, 0.96, 0.90)   # 对话框可能出现的那块(占客户端窗口比)
DIALOG_PAD = 8                           # 按面板框裁字时往外留几个像素
# 对话框的字挤在面板**上半部分**(实测 2~3 行都在顶上):只读那一截就够,
# 面板下面大半是空的 —— 每次省三成时间,报点也更快。
DIALOG_TEXT_FRAC = 0.62
DIALOG_TEXT_MINH = 170
DIALOG_DARK, DIALOG_SAT = 105, 70        # "暗且不彩"的上限
DIALOG_DARK_FRAC = 0.60                  # 一行/一列里暗像素占比超过它才算面板
# 框**里面**的暗比:真对话框 0.82~0.94(实测 13 张图),而"夜里整条带子都暗"
# 那种假框只有 0.6~0.7 —— 真机日志里它每轮都骗我们去 OCR(读到的是客户端页签名),
# 一秒两三次,既慢又白烧显卡。
PANEL_MIN_DARK = 0.78
# **结构关**(2026-10-16 用户实测:进场打怪时战斗画面被当成面板,OCR 读回来的
# 是 冷昕T/血条 这些)。战斗画面同样能"一整块暗"(框内暗比实测 0.91),暗比
# 挡不住;但对话框是**文字行**——亮/彩像素只挤在少数几行里,战斗画面的人/怪/
# 血条摊满所有行(两张真图实测:对话框"有内容的行"占 0.23,战斗画面 0.77)。
DIALOG_BRIGHT = 130                      # "亮"的下限(文字笔画和血条都过它)
BUSY_ROW_FRAC = 0.08                     # 一行里"亮|彩"占比到这么多算"有内容"
PANEL_MAX_BUSY = 0.50                    # 有内容的行超过这个占比就不是面板
DIALOG_MIN_H = 160                       # 面板至少这么高(定稿框内真面板 176~220;
                                         # 老值 200 是按带子年代 244~405 调的,会把
                                         # 640 档 176 高的真面板拒掉 —— 2026-11-08)
# ---- 结构锚点(与配色无关,2026-11-12 用户提的口径) ----
# 对话框 = **一整块低频平坦的横条(空白区)+ 上面 2~3 排文字行**。暗色面板自带
# 3.2px 扫描线纹理、浅色面板是羊皮纸底,4× 块平均后两者都成了"近乎纯色",而
# 游戏世界还留着大尺度结构 —— 实测(真机夹具 + 浅色皮肤截图):暗色面板空白区
# 低频能量 4.5、世界 97;浅色面板空白带 92px 高、行平坦度 0.8+,同尺寸世界段
# 全部 < 0.5。颜色门控(暗比)继续当快路,这条只在暗比不够时兜底。
FLAT_SAMPLE = 4                          # 4× 块平均:抹掉扫描线/JPEG 噪声
FLAT_DIFF = 15                           # 相邻小格颜色差低于它算"同期平坦"
FLAT_ROW = 0.60                          # 一行里平坦小格占比,够它算"空白行"
FLAT_COL = 0.80                          # 空白带里一列的平坦占比,够它算"面板列"
FLAT_MIN_BLANK = 24                      # 空白带至少这么高(像素;40 -> 24:给
                                         # "字更多的对话框"留余量,真机最密的
                                         # 对话框空白带 144px、合成压测 12px 行距
                                         # 都能过,18 段世界对照 0 误报 —— 2026-11-13)
FLAT_MIN_W = 0.55                        # 空白带宽度下限(占这块画面;浅色面板 0.66~0.68)


def panel_text_cut(crop, box):
    """面板里"真有字"的那一截:上半部分(留够 2~5 行的余量)。

    读整个面板的话,下面大半是空的 —— 白花的像素。裁到文字带之后每次 OCR
    省三成时间,而且面板一出现就能更快报点。
    """
    keep = max(DIALOG_TEXT_MINH, int((box[3] - box[1]) * DIALOG_TEXT_FRAC))
    return _cut(crop, (box[0], box[1], box[2], min(box[3], box[1] + keep)))


def _cut(arr, box, pad=DIALOG_PAD):
    """按 (x0,y0,x1,y1) 裁一块,往外留 pad,裁到画面里。"""
    h, w = arr.shape[:2]
    x0 = max(0, int(box[0]) - pad)
    y0 = max(0, int(box[1]) - pad)
    x1 = min(w, int(box[2]) + pad)
    y1 = min(h, int(box[3]) + pad)
    return arr[y0:y1, x0:x1]


def _dark_of(rgb):
    """整块画面的"暗且不彩"掩码(**::2 半分辨率采样**,panel_frac / panel_box 共用)。

    掩码里的 astype/max/min 是门控最贵的纯 numpy 活(900x460 的对话框带上全
    分辨率 14ms,::2 只要 3.6ms);同一拍里 panel_frac 和 panel_box 要的正是
    同一个东西 —— 算一遍传来传去。缩样后暗比的偏差实测 ~0.001(0.7500 对
    0.7512),对 0.60/0.78 两道门槛的余量(假框 0.35~0.43 / 真面板 0.82~0.94)
    毫无影响;panel_box 里用掩码切片时坐标记得 //2。
    """
    import numpy as np
    a = np.asarray(rgb)
    if a.ndim != 3 or a.shape[2] < 3 or not a.size:
        return None
    a = a[::2, ::2].astype(np.int16)
    mx = a.max(axis=2)
    return (mx < DIALOG_DARK) & ((mx - a.min(axis=2)) < DIALOG_SAT)


def panel_frac(rgb):
    """这块画面里"暗且不彩"的像素占比(对话框那种半透明黑面板很高)。"""
    dark = _dark_of(rgb)
    return 0.0 if dark is None else float(dark.mean())


def panel_box(rgb, dark=None):
    """对话框那块深色面板在画面里的外接框(相对这块画面);没有返回 None。

    dark:调用方同一拍里已经为 `panel_frac` 算过一次的暗掩码(见 `_dark_of`,
    **::2 半分辨率**,切片时坐标 //2)—— 递进来就省掉这里两遍全分辨率的
    max/min(面板开着时一轮省 25~40ms)。

    面板是"暗且不彩"的一整块:先在 1/4 缩略图上按**行**找"这一行里暗像素占比
    够高"的范围,再在这个范围里按**列**找。比只看整块占比多给一样东西 ——
    面板**在哪**:于是 OCR 只喂面板那一块,既不带身后一直在动的游戏世界,也不带
    上方任务栏那两行(它也会带坐标,混进来会被当成"对话框说的")。
    """
    import numpy as np
    a = np.asarray(rgb)
    if a.ndim != 3 or a.shape[2] < 3 or not a.size:
        return None
    if dark is None:
        dark = _dark_of(a)
        if dark is None:
            return None
    h, w = a.shape[:2]
    small = a[::4, ::4].astype(np.int16)
    mx = small.max(axis=2)
    mn = small.min(axis=2)
    small_dark = (mx < DIALOG_DARK) & ((mx - mn) < DIALOG_SAT)
    rows = np.nonzero(small_dark.mean(axis=1) >= DIALOG_DARK_FRAC)[0]
    if not rows.size:
        return None
    y0, y1 = int(rows[0]), int(rows[-1]) + 1
    cols = np.nonzero(small_dark[y0:y1].mean(axis=0) >= DIALOG_DARK_FRAC)[0]
    if not cols.size:
        return None
    box = (int(cols[0]) * 4, y0 * 4,
           min(w, (int(cols[-1]) + 1) * 4), min(h, y1 * 4))
    # 面板是一条**横贯窗口的大横条**(定稿框内真面板 176~220 高;带子年代实测
    # 868~902 x 244~405):只够半屏宽的多半是游戏世界里的一坨暗色建筑(实测误报
    # 0.27~0.36W),太矮的(实测误报 800x50~150)是地图窗边框/UI 黑条之类 —— 两条
    # 都卡住。**宽度下限 0.6 -> 0.72**(2026-11-07 真机):鼠标停在旗子上冒出的
    # tooltip 只有 373/573 ≈ 0.65W,擦着 0.6 的旧线被当成对话框,把任务翻成了旗子
    # 坐标(见 BELL_WORDS 那条);定稿框本来就是按真框定的,0.72 离真面板还有余量。
    # 高度下限 200 -> 160(2026-11-08,见 DIALOG_MIN_H 那行)。
    if box[2] - box[0] < 0.72 * w or box[3] - box[1] < DIALOG_MIN_H:
        return None
    # 最后三关:①整条带子大部分是暗的(真对话框盖住条带 0.61~0.95;游戏世界里
    # 凑巧"又宽又高"的暗块只有 0.29~0.58);②**框里面**得更暗(真对话框 0.82~0.94,
    # "夜里整条带子都暗"的假框 0.6~0.7);③**结构**:框里的亮/彩像素得挤在少数
    # 几行(那是文字),摊满所有行的是战斗画面的人/怪/血条(见 PANEL_MAX_BUSY 处
    # 的注释,两张真图实测 0.23 对 0.77)。
    if float(dark.mean()) < DIALOG_DARK_FRAC:
        return None
    if float(dark[box[1] // 2:box[3] // 2,
                  box[0] // 2:box[2] // 2].mean()) < PANEL_MIN_DARK:
        return None
    content = ((mx[y0:y1, int(cols[0]):int(cols[-1]) + 1] >= DIALOG_BRIGHT)
               | ((mx[y0:y1, int(cols[0]):int(cols[-1]) + 1]
                   - mn[y0:y1, int(cols[0]):int(cols[-1]) + 1]) >= DIALOG_SAT))
    busy = (content.mean(axis=1) >= BUSY_ROW_FRAC).mean()
    if busy >= PANEL_MAX_BUSY:
        return None
    return box




def flat_panel_box(rgb):
    """按**结构**找对话框面板(不认配色):低频平坦的空白带 + 上面的文字行。

    做法:4× 块平均(把面板自带的细纹理/JPEG 噪声抹平,世界的大尺度结构
    还在)→ 逐行算"平坦小格占比" → 找最长的一段连续平坦行(面板空白区)
    → 这一段的列范围(面板左右)→ 空白带往上到框顶都是文字区。
    返回相对这块画面的 (x0,y0,x1,y1);找不到返回 None。

    为什么不用"暗比"就够:游戏里可以换对话框皮肤(浅色羊皮纸底),暗比
    直接为 0;而世界画面里也没有"一大块低频平坦横条"。纯 numpy,一块
    552×180 的定稿框约 0.3ms。
    """
    import numpy as np
    a = np.asarray(rgb)
    if a.ndim != 3 or a.shape[2] < 3 or not a.size:
        return None
    k = FLAT_SAMPLE
    h, w = a.shape[0] // k * k, a.shape[1] // k * k
    if h < 8 * k or w < 12 * k:
        return None
    s = a[:h, :w].reshape(h // k, k, w // k, k, 3).mean(axis=(1, 3))
    d = np.abs(np.diff(s.astype(np.float32), axis=1)).sum(axis=2)
    flat = d < FLAT_DIFF                      # (h/k, w/k-1)
    rowf = flat.mean(axis=1)
    # ① 最长的一段连续"平坦行" = 面板空白区
    best = cur = bs = bo = 0
    for i, ok in enumerate(rowf >= FLAT_ROW):
        if ok:
            if cur == 0:
                bs = i
            cur += 1
            if cur > best:
                best, bo = cur, bs
        else:
            cur = 0
    if best * k < FLAT_MIN_BLANK:
        return None
    y0, y1 = bo, bo + best
    # 空白带得一直落到画面下缘(定稿框的下边离面板底只有 ~17px):游戏世界
    # 里半截平坦的路面/地板位置随机 —— 实测浅色截图 640 档左下角那块世界
    # 平坦带只到框高的 57%,这条把它挡掉
    if y1 * k < 0.72 * h:
        return None
    # ② 这一段的列范围 = 面板左右
    cols = np.nonzero(flat[y0:y1].mean(axis=0) >= FLAT_COL)[0]
    if not cols.size:
        return None
    x0, x1 = int(cols[0]), int(cols[-1]) + 1
    if (x1 - x0) * k < FLAT_MIN_W * w:
        return None
    # ③ 空白带上方得真有"文字行"(面板里的字):让平坦度落在 0.05~0.75 的小行
    #    至少 2 行。天空/雪地/白墙那种纯平画面,上方要么全平(1.0)、要么全是
    #    世界纹理(<0.05 很少),过不了这一关 —— 真机夹具的世界段全部被这条挡掉。
    #    从**框顶**看起,不设窗口:对话框的文字顶格排版,第一行固定就压在框顶
    #    附近(定稿框 48% 只切面板边框,2026-11-13 用户指正),这段最多也就
    #    ~110px,截 80px 反而会把第一行漏出统计窗口外。
    above = flat[:y0, x0:x1].mean(axis=1) if y0 else np.array([])
    if not above.size or int(((above >= 0.05) & (above <= 0.75)).sum()) < 2:
        return None
    # ④ 空白带往上到框顶都是文字区(返回的框要盖住全部文字行,OCR 只裁
    #    "框顶 62%",字在这段里就跑不掉)
    return (x0 * k, 0, x1 * k, min(h, y1 * k))


SIG_GRID = (24, 48)                      # 面板内容签名的采样格(行, 列)


def panel_sig(rgb, box, grid=SIG_GRID):
    """面板**里面**的内容签名(定长小图)。**先按亮度二值化再采样**。

    为什么二值化(2026-10-17 用户报"又卡死了"后改的):游戏的面板是**半透明**的,
    身后的世界一直在动 —— 直接采原始像素,背景一动签名就变,门控把"背景在动"
    当成"换了一段话",于是**每 10 秒读 8~12 次**(一半还是"非铃铛对话"白烧),
    GPU 一直被占着,游戏一卡一卡。二值化后进签名的只有"哪些像素亮"(= 文字笔画
    的位置),背景明暗怎么变都不影响;真翻页(字换了)掩码照样变 ✔。
    采样成固定 24x48 是为了让签名跟面板大小无关:框的边缘会抖 ±4 像素;
    返回值和老签名同形 (24,48,3),`sig_diff`/`SIG_MIN` 一个字不用改。
    """
    import numpy as np
    a = np.asarray(rgb)
    if a.ndim != 3 or not a.size:
        return None
    h, w = a.shape[:2]
    x0 = max(0, min(int(box[0]), w - 1))
    y0 = max(0, min(int(box[1]), h - 1))
    x1 = max(x0 + 1, min(int(box[2]), w))
    y1 = max(y0 + 1, min(int(box[3]), h))
    sub = a[y0:y1, x0:x1]
    mask = (sub.max(axis=2) >= DIALOG_BRIGHT).astype(np.uint8) * 255
    sh, sw = mask.shape[:2]
    ys = np.linspace(0, sh - 1, grid[0]).astype(int)
    xs = np.linspace(0, sw - 1, grid[1]).astype(int)
    return np.repeat(mask[ys][:, xs][:, :, None], 3, axis=2)


def sig_diff(a, b):
    """两个签名差多少(平均绝对差);缺一个或形状不同就当"变了"。"""
    import numpy as np
    if a is None or b is None:
        return 999.0
    if getattr(a, "shape", None) != getattr(b, "shape", None):
        return 999.0
    return float(np.abs(a.astype(np.int16) - b.astype(np.int16)).mean())


def read_note(what, size, nblock, ms, got=None, blocks=None):
    """一行"识别过程"日志:扫了哪块、多大、几个文字块、多久、认到了什么。

    读到的原文**两边都带上**。没认到时最想知道"它到底读成了啥"(出过一次
    "任务栏一直没认到",当初没写字,事后完全看不出原因);认到的时候也要 ——
    不然"建邺城(101,127) 是怎么变成建邺城(24,108) 的"只能靠猜(实测踩过)。
    """
    w, h = int(size[0]), int(size[1])
    seen = " ".join((b.get("text") or "") for b in (blocks or []))[:26]
    if got:
        tail = f"{got[0]}({got[1]},{got[2]})"
        if seen:
            tail += f" 读到:{seen}"
    else:
        tail = f"没认到({seen})" if seen else "一个字都没读到"
    return f"{what} {w}x{h} 块{nblock} {ms:.0f}ms → {tail}"
