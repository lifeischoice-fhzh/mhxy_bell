"""从截图里找游戏地图窗口(单文件可拷走复用)。

两条互补的路:整块彩色区(find_color_blob,快)和地图窗深色外框
(find_map_frame,灰石头城那种彩色块认不出来的靠它);find_map_rect 是
对外的合口。纯 numpy,不碰文件与 core。
"""
# 录入地图时用的判据(纯函数,好离线测)
MAP_RECT_MIN, MAP_RECT_MAX = 160, 1500   # 地图矩形的边长合理区间
MAP_RECT_FILL = 0.55                     # 连通块占自己外接框的比例(更低的是一圈描边/碎块)
MAP_RECT_TOL = 0.03                      # 外接框长宽比与坐标范围比例的允许偏差
MAP_RECT_TIGHT = 0.04                    # 偏差够小就不再试后面的彩色度档
MAP_SAT_LEVELS = (35, 25, 45, 55)        # 逐级试的"彩色度"(六张图在 35 档命中最多)


def _band(cover, frac):
    """覆盖比例 ≥ frac 的最长连续段 -> (起点, 终点);没有返回 None。"""
    best = None
    start = None
    for i, v in enumerate(cover >= frac):
        if v:
            if start is None:
                start = i
        elif start is not None:
            if best is None or i - start > best[1] - best[0]:
                best = (start, i - 1)
            start = None
    if start is not None and (best is None
                              or len(cover) - start > best[1] - best[0]):
        best = (start, len(cover) - 1)
    return best


def _components(mask, min_side, max_side):
    """mask 里边长落在区间内的连通块 -> [(像素数, x0, y0, x1, y1)]。"""
    import collections

    import numpy as np
    h, w = mask.shape
    seen = np.zeros((h, w), bool)
    out = []
    for y in range(h):
        if not mask[y].any():
            continue
        for x in range(w):
            if not mask[y, x] or seen[y, x]:
                continue
            dq = collections.deque([(x, y)])
            seen[y, x] = True
            n = 0
            minx = maxx = x
            miny = maxy = y
            while dq:
                cx, cy = dq.popleft()
                n += 1
                if cx < minx:
                    minx = cx
                elif cx > maxx:
                    maxx = cx
                if cy < miny:
                    miny = cy
                elif cy > maxy:
                    maxy = cy
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1),
                               (cx, cy - 1)):
                    if (0 <= nx < w and 0 <= ny < h and mask[ny, nx]
                            and not seen[ny, nx]):
                        seen[ny, nx] = True
                        dq.append((nx, ny))
            bw, bh = maxx - minx + 1, maxy - miny + 1
            if min_side <= bw <= max_side and min_side <= bh <= max_side:
                out.append((n, minx, miny, maxx, maxy))
    return out


def find_color_blob(rgb, want_ratio=None, min_side=MAP_RECT_MIN,
                    max_side=MAP_RECT_MAX):
    """按"整块彩色区"找地图本体(快,六张图里五张能直接命中)。

    地图窗口画的就是**一张整块的图**:某个彩色度档下它会连成一整个连通块,外接框
    刚好是图本身(实测六张图的原始截图误差 ≤1px);窗口周围被挡住的场景要么碎成
    小块、要么彩色度不够连不起来。

    want_ratio = 这张地图坐标范围的长宽比(get 自 bounds.json)—— 给了就挑"外接框
    比例离它最近"的那块,顺带验一下截到的确实是这张图;没给就挑面积最大的那块。

    连通块的外接框有时会连上周围一小片场景(彩色度低的地图会这样),所以每块再按
    "行/列覆盖比例"裁一次,原框和裁剪框都当候选。
    """
    import numpy as np
    a = np.asarray(rgb).astype(np.int16)
    if a.ndim != 3 or a.shape[2] < 3:
        return None
    sat = a.max(axis=2) - a.min(axis=2)
    best = None
    for th in MAP_SAT_LEVELS:
        mask = sat > th
        for n, minx, miny, maxx, maxy in _components(mask, min_side, max_side):
            bw, bh = maxx - minx + 1, maxy - miny + 1
            if n / float(bw * bh) < MAP_RECT_FILL:
                continue
            cands = [(minx, miny, maxx, maxy)]
            sub = mask[miny:maxy + 1, minx:maxx + 1]
            rb, cb = _band(sub.mean(axis=1), 0.5), _band(sub.mean(axis=0), 0.5)
            if rb and cb:
                x0, y0 = minx + cb[0], miny + rb[0]
                x1, y1 = minx + cb[1], miny + rb[1]
                trim = (x1 - x0 + 1) * (y1 - y0 + 1)
                if (trim / float(n) >= 0.6
                        and min_side <= x1 - x0 + 1 <= max_side
                        and min_side <= y1 - y0 + 1 <= max_side):
                    cands.append((x0, y0, x1, y1))
            for box in cands:
                bw, bh = box[2] - box[0] + 1, box[3] - box[1] + 1
                ratio = bw / float(bh)
                if want_ratio:
                    err = abs(ratio / want_ratio - 1)
                    if err > MAP_RECT_TOL:
                        continue
                elif not 0.5 <= ratio <= 2.5:
                    continue
                else:
                    err = 0.0
                key = (round(err, 4), -(bw * bh))
                if best is None or key < best[0]:
                    best = (key, box)
        if best and best[0][0] <= MAP_RECT_TIGHT:
            break
    return best[1] if best else None


# ---- 兜底:地图窗那圈深色外框(灰石头城那种彩色块法认不出来的,靠它) ----
MAP_FRAME_DARK = 95        # 外框的"深"上限(max(RGB))
MAP_FRAME_SAT = 70         # 外框的彩度上限(发黑的才要)
MAP_FRAME_MIN_RUN = 120    # 框线至少这么长(min_side 的三分之二上下)
MAP_FRAME_SIDE = 0.5       # 框线两侧至少有一侧"亮"到这个程度以下:是线不是深色块
MAP_FRAME_TOL = 0.12       # 外框比地图本体多一圈边,长宽比会漂,所以放宽


def _runs(mask, axis, min_run):
    """沿 axis 逐行/逐列找"细深色段" -> [(位置, 段长, 段起, 段止)]。

    细=这一段的外面至少有一侧是亮的(不是一大片深色):地图窗的描边就是这种线。
    """
    n = mask.shape[axis]
    out = []
    for i in range(n):
        line = mask[i] if axis == 0 else mask[:, i]
        best = cur = 0
        start = best_s = 0
        for j, val in enumerate(line):
            if val:
                if cur == 0:
                    start = j
                cur += 1
                if cur > best:
                    best, best_s = cur, start
            else:
                cur = 0
        if best < min_run:
            continue
        s, e = best_s, best_s + best - 1
        if axis == 0:
            up = float(mask[i - 1, s:e + 1].mean()) if i > 0 else 0.0
            dn = float(mask[i + 1, s:e + 1].mean()) if i + 1 < n else 0.0
        else:
            up = float(mask[s:e + 1, i - 1].mean()) if i > 0 else 0.0
            dn = float(mask[s:e + 1, i + 1].mean()) if i + 1 < n else 0.0
        if min(up, dn) < MAP_FRAME_SIDE:
            out.append((i, best, s, e))
    return out


def _overlap(a, b):
    """两个区间 [起,止] 的重叠长度。"""
    return max(0, min(a[1], b[1]) - max(a[0], b[0]) + 1)


def find_map_frame(rgb, want_ratio=None, min_side=MAP_RECT_MIN,
                   max_side=MAP_RECT_MAX):
    """按"地图窗的深色外框"找地图**窗口**,返回 (x0,y0,x1,y1);找不到 None。

    外框跟地图本身配色无关(灰石头城也有),所以彩色块法认不出来的图靠它。
    判据:上/下两条横线的**跨度基本重合**(拐角那几像素会被别的东西打断,所以
    只要求重叠够多)、左右两条竖线同理,四条线框出的矩形边长在区间内、长宽比
    接近 want_ratio(外框比图本体多一圈边,这里只粗筛 ±12%:真正的比例核对
    在裁出地图本体之后)。
    """
    import numpy as np
    a = np.asarray(rgb).astype(np.int16)
    if a.ndim != 3 or a.shape[2] < 3:
        return None
    v = a.max(axis=2)
    mask = (v < MAP_FRAME_DARK) & ((v - a.min(axis=2)) < MAP_FRAME_SAT)
    rows = _runs(mask, 0, MAP_FRAME_MIN_RUN)
    cols = _runs(mask, 1, MAP_FRAME_MIN_RUN)
    best = None
    for t, tl, ts0, ts1 in rows:
        for b, bl, bs0, bs1 in rows:
            if b <= t:
                continue
            bh = b - t + 1
            if not (min_side <= bh <= max_side):
                continue
            if _overlap((ts0, ts1), (bs0, bs1)) < 0.85 * min(tl, bl):
                continue                                   # 上下不是同一条窗框
            bw_exp = (tl + bl) / 2.0
            if not (min_side <= bw_exp <= max_side):
                continue
            if want_ratio and abs(bw_exp / bh / want_ratio - 1) > MAP_FRAME_TOL:
                continue
            for l, ll, ls0, ls1 in cols:
                if ll < 0.9 * bh or not (t - 8 <= ls0 and ls1 <= b + 8):
                    continue
                for r, rl, rs0, rs1 in cols:
                    if r <= l or rl < 0.9 * bh:
                        continue
                    if not (t - 8 <= rs0 and rs1 <= b + 8):
                        continue
                    bw = r - l + 1
                    if abs(bw - bw_exp) > 0.05 * bw_exp:
                        continue
                    err = (abs(bw / float(bh) / want_ratio - 1)
                           if want_ratio else 0.0)
                    key = (round(err, 3), -(bw * bh))
                    if best is None or key < best[0]:
                        best = (key, (l, t, r, b))
    return best[1] if best else None


def find_map_rect(rgb, want_ratio=None, min_side=MAP_RECT_MIN,
                  max_side=MAP_RECT_MAX):
    """在整屏截图里找游戏地图那一块,返回 (x0,y0,x1,y1);找不到返回 None。

    先按整块彩色区找(快);找不到再找地图窗的深色外框,在框内重找一次本体 ——
    两条路是互补的:彩色块法在灰石头城(建邺城)上会失败,外框法在竖长图
    (长寿村)上会失败,合起来六张都稳。实测(把官方的地图窗截图贴进真游戏
    截图做的全屏模拟):六张全部命中,与地图本体差 ≤1px;没开地图的真截图全拒。
    """
    import numpy as np
    rect = find_color_blob(rgb, want_ratio, min_side, max_side)
    if rect:
        return rect
    frame = find_map_frame(rgb, want_ratio, min_side, max_side)
    if not frame:
        return None
    x0, y0, x1, y1 = frame
    inner = np.asarray(rgb)[y0:y1 + 1, x0:x1 + 1]
    got = find_color_blob(inner, want_ratio, min_side, max_side)
    if not got:
        return None
    return (got[0] + x0, got[1] + y0, got[2] + x0, got[3] + y0)
