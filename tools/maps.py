"""地图底图与坐标标定(单文件可拷走复用)。

底图查找(data/maps/<中文名|拼音>.*)、坐标范围(bounds.json)、游戏坐标 ->
底图像素的标定(calib.json)、画面文字里出现过的地图名。数据根目录跟主程序
同一套规则(打包后跟着可执行文件走);**不 import core**(工具层红线)。
"""
import json
import os
import sys

if getattr(sys, "frozen", False):          # PyInstaller 打包后
    BASE_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ---- 底图:data/maps/ 下按地图名或拼音名放图(png/jpg) ----
MAP_DIR = os.path.join(BASE_DIR, "data", "maps")
MAP_CALIB_PATH = os.path.join(MAP_DIR, "calib.json")
MAP_BOUNDS_PATH = os.path.join(MAP_DIR, "bounds.json")
MAP_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
# 拼音名对应 24 张老图集里的文件名(只有这几张收得到)
MAP_STEMS = {
    "长寿村": ("changshoucun", "changshoujiaowai"),
    "傲来国": ("aolaiguo",),
    "朱紫国": ("zhuziguo",),
    "建邺城": ("jianye",),
    "西梁女国": ("xiliangnvguo",),
    "宝象国": ("baoxiangguo",),
}


def map_asset(name: str):
    """找地图底图:先按中文名找,再按拼音名找;都没有返回 None。"""
    stems = [name] + list(MAP_STEMS.get(name, ()))
    for stem in dict.fromkeys(stems):
        for ext in MAP_EXTS:
            p = os.path.join(MAP_DIR, stem + ext)
            if os.path.exists(p):
                return p
    return None


BELL_MAPS = ("长寿村", "傲来国", "朱紫国", "建邺城",
             "西梁女国", "西凉女国", "宝象国")
# 官方名(没有"西凉"这个别名):采集底图/写标定都按这个列表来
BELL_MAP_NAMES = ("长寿村", "傲来国", "朱紫国", "建邺城",
                  "西梁女国", "宝象国")

_BELL_CANON = {
    "长寿": "长寿村", "常寿": "长寿村", "长寿郊外": "长寿村",
    "傲来": "傲来国", "敖来": "傲来国", "傲莱": "傲来国",
    "朱紫": "朱紫国", "珠紫": "朱紫国", "朱柴": "朱紫国",
    "建邺": "建邺城", "建业": "建邺城", "建邮": "建邺城", "建邦": "建邺城",
    "西梁": "西梁女国", "西凉": "西梁女国", "西粱": "西梁女国",
    "宝象": "宝象国", "宝像": "宝象国",
}


def canon_map(name: str) -> str:
    """把 OCR 认出来的地图名归一到官方写法(认不出就原样返回)。

    归一表按前缀匹配:"建邮城" 命中 "建邮" -> "建邺城"。
    """
    name = (name or "").strip()
    for wrong in sorted(_BELL_CANON, key=len, reverse=True):
        if name.startswith(wrong) or name == wrong:
            return _BELL_CANON[wrong]
    return name


def map_ratio(name):
    """这张地图坐标范围的长宽比(用来核对"截到的是不是它");没范围返回 None。"""
    try:
        min_x, min_y, max_x, max_y = [float(v)
                                      for v in load_map_bounds().get(name)]
    except Exception:
        return None
    if max_x <= min_x or max_y <= min_y:
        return None
    return (max_x - min_x) / (max_y - min_y)


def map_names_in(blocks, names=BELL_MAP_NAMES):
    """画面里的文字块出现过的地图名(去重、别名归一)。

    只用来核对"现在打开的是不是这张图":游戏 HUD 一直写着当前地图名,所以录那张
    图时它一定在;任务追踪/聊天里提到别的地图名也拦得住。地图窗口里那些**邻近**
    地图的标注(比如"解阳山""丝绸之路")不在 BELL_MAP_NAMES 里,不会被算进来。
    """
    found = []
    for b in blocks:
        text = (b.get("text") or "").strip()
        if not text:
            continue
        for n in names:
            if n in text and n not in found:
                found.append(n)
        for alias, canon in _BELL_CANON.items():
            if alias in text and canon in names and canon not in found:
                found.append(canon)
    return found


def map_calib(name: str):
    """底图缩放系数:图片像素 = 坐标 * s + o。

    默认 (1,1,0,0),即"底图像素 == 游戏坐标"。老图集若整体缩放过,
    在 data/maps/calib.json 里写 {"地图名": {"sx":..,"sy":..,"ox":..,"oy":..}}。
    """
    try:
        with open(MAP_CALIB_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {}
    v = data.get(name) or {}
    if not isinstance(v, dict):
        v = {}
    try:
        return (float(v.get("sx", 1.0)) or 1.0, float(v.get("sy", 1.0)) or 1.0,
                float(v.get("ox", 0.0)), float(v.get("oy", 0.0)))
    except Exception:
        return (1.0, 1.0, 0.0, 0.0)


def map_pixel(name: str, x: int, y: int):
    """游戏坐标 -> 底图上的像素位置(浮点)。"""
    sx, sy, ox, oy = map_calib(name)
    return (x * sx + ox, y * sy + oy)


def map_asset_save_path(name, ext=".png"):
    """游戏里采集来的底图存到 data/maps/<中文名>.png,并保证目录存在。"""
    os.makedirs(MAP_DIR, exist_ok=True)
    return os.path.join(MAP_DIR, name + ext)


def save_map_calib(name, sx, sy, ox=0.0, oy=0.0):
    """把某张地图的缩放系数写进 data/maps/calib.json(读-改-写,别覆盖别的图)。"""
    try:
        with open(MAP_CALIB_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            data = {}
    except Exception:
        data = {}
    data[name] = {"sx": float(sx), "sy": float(sy),
                  "ox": float(ox), "oy": float(oy)}
    os.makedirs(MAP_DIR, exist_ok=True)
    with open(MAP_CALIB_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def map_calib_from_bounds(w, h, bounds):
    """底图就是整张地图时,直接按坐标范围算出标定。

    bounds = [min_x, min_y, max_x, max_y]。游戏里地图原点 (0,0) 在**左下角**、
    y 轴朝上,所以 y 方向要翻过来(用负的 sy 加偏移表示),x 方向是普通的线性。
    返回 (sx, sy, ox, oy),范围不合法返回 None。
    """
    try:
        min_x, min_y, max_x, max_y = [float(v) for v in bounds]
    except Exception:
        return None
    if max_x <= min_x or max_y <= min_y or w <= 0 or h <= 0:
        return None
    sx = w / (max_x - min_x)
    sy = h / (max_y - min_y)
    return (sx, -sy, -min_x * sx, max_y * sy)


def load_map_bounds() -> dict:
    """地图坐标范围:data/maps/bounds.json 里 {"地图名": [minx, miny, maxx, maxy]}。"""
    try:
        with open(MAP_BOUNDS_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def auto_calibrate_from_bounds(overwrite=False):
    """有坐标范围的地图,自动算标定,省得挨个手点角色位置。

    返回 [(地图名, 说明)]。默认只补没有标定的那些,overwrite=True 才重算。
    """
    from PIL import Image
    out = []
    bounds_all = load_map_bounds()
    if not bounds_all:
        return out
    try:
        with open(MAP_CALIB_PATH, encoding="utf-8") as f:
            done = json.load(f)
        done = done if isinstance(done, dict) else {}
    except Exception:
        done = {}
    for name, bounds in bounds_all.items():
        if name.startswith("_"):          # 以 _ 开头的是注释行,不是地图
            continue
        path = map_asset(name)
        if not path:
            out.append((name, "没有底图"))
            continue
        if not overwrite and name in done:
            out.append((name, "已有标定,跳过"))
            continue
        try:
            with Image.open(path) as im:
                w, h = im.size
        except Exception as err:
            out.append((name, f"底图读不了({err})"))
            continue
        cal = map_calib_from_bounds(w, h, bounds)
        if not cal:
            out.append((name, "坐标范围不合法"))
            continue
        save_map_calib(name, *cal)
        out.append((name, f"sx={cal[0]:.2f} sy={cal[1]:.2f}"))
    return out
