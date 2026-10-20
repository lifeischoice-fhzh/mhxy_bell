"""真机截图离线校验:docs/shots/ 里的整图 -> 圈对话框带 -> 找面板 -> 裁文字带 ->
OCR -> 解析,拿 `expected.json` 里那张表逐张对数。

跑法(改了 det 参数 / 解析口径之后跑一次):

    .venv/Scripts/python.exe check_shots.py
    .venv/Scripts/python.exe check_shots.py --ab    # 顺带把 480/min 那档也量出来

**为什么不并进 tests.py**:那条红线是"回归里不许建真引擎"(ONNX/DirectML 收不干
净,会在后面的组随机时刻初始化 native 层 -> 偶发段错误)。这是一个独立进程,建
真引擎是安全的;tests.py 那边只查 `expected.json` 和文件在不在(不跑 OCR)。
"""
import argparse
import json
import os
import statistics
import time

import numpy as np
from PIL import Image

import tools.bell as tb

HERE = os.path.dirname(os.path.abspath(__file__))
SHOTS = os.path.join(HERE, "docs", "shots")
EXPECT = os.path.join(SHOTS, "expected.json")


def find_part(rgb):
    """按 App 的兜底口径截一块:DIALOG_BAND 圈范围 -> panel_box 找面板 ->
    panel_text_cut 只留"有字的那一截"。

    截图的分辨率都不是表里那两档(1011~1029 宽),所以这里走的是
    `dialog_rect()` 的按比例兜底,和真机上不支持的尺寸同一条路。
    """
    band = tb.rel_rect((0, 0, rgb.shape[1], rgb.shape[0]), tb.DIALOG_BAND)
    crop = rgb[band[1]:band[3], band[0]:band[2]]
    box = tb.panel_box(crop)
    if not box:
        return None
    return tb.panel_text_cut(crop, box)


def read_once(ocr, part, limit, limit_type=None):
    t0 = time.time()
    if limit_type:
        blocks = ocr.recognize_blocks(part, limit_side=limit,
                                      limit_type=limit_type)
    else:
        blocks = ocr.recognize_blocks(part, limit_side=limit)
    return blocks, (time.time() - t0) * 1000


def read_median(ocr, part, limit, limit_type=None, reps=3):
    read_once(ocr, part, limit, limit_type)          # 预热
    ts = []
    for _ in range(reps):
        blocks, ms = read_once(ocr, part, limit, limit_type)
        ts.append(ms)
    return blocks, statistics.median(ts)


def parse(blocks):
    d, t, _w = tb.scan_bell_parts(blocks or [], scoped=False)
    return d or t


def fmt(spot):
    return f"{spot[0]}({spot[1]},{spot[2]})" if spot else "没认到"


def main() -> int:
    ap = argparse.ArgumentParser(description="真机截图离线校验")
    ap.add_argument("--ab", action="store_true",
                    help="顺带量一遍改前的 480/min 档(对比用,不参与判分)")
    args = ap.parse_args()

    with open(EXPECT, encoding="utf-8") as f:
        shots = [s for s in json.load(f)["shots"] if s.get("kind") != "taskbar"]
    import core
    ocr = core.Ocr(lambda m: print(m))
    ocr.warmup()
    if not ocr.ok:
        print(f"OCR 不可用: {ocr.err or '预热失败'}")
        return 2

    bad = 0
    t_all = time.time()
    for s in shots:
        path = os.path.join(SHOTS, s["file"])
        rgb = np.asarray(Image.open(path).convert("RGB"))[:, :, ::-1].copy()
        part = find_part(rgb)
        want = (s["map"], s["x"], s["y"])
        if part is None:
            bad += 1
            print(f"✗ {s['monster']:6} {s['file']}: 没找到对话框面板"
                  f"(应有 {fmt(want)})")
            continue
        blocks, ms = read_median(ocr, part, tb.DLG_LIMIT_SIDE,
                                 tb.DLG_LIMIT_TYPE)
        got = parse(blocks)
        ok = got == want
        bad += 0 if ok else 1
        line = (f"{'✓' if ok else '✗'} {s['monster']:6} "
                f"{part.shape[1]}x{part.shape[0]:<5} {ms:5.0f}ms  "
                f"{fmt(got)}"
                f"{'' if ok else '  应为 ' + fmt(want)}")
        if args.ab:
            _b2, ms2 = read_median(ocr, part, tb.OCR_LIMIT)
            line += f"   [480/min {ms2:.0f}ms]"
        print(line)
    print(f"\n结果: {len(shots) - bad}/{len(shots)} 通过"
          f"(耗时 {time.time() - t_all:.1f}s,设备 {getattr(ocr, 'device', '?')})")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
