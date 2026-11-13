"""客户端生命周期:启动 / 登录 / 登出 / 关闭 / 最小化 / 恢复 / 挪窗 / 换档。

**纯逻辑,单文件复用**:不 import 本仓库任何模块,也不碰 core/界面/配置。
应用自己枚举窗口(见 client_common 的 find_client_windows / client_canvas)
并抠好角色名/分辨率,包成 `[Client(...)]` 喂给 `Tracker.poll()`,拿回这一拍
"和上一拍比发生了什么"的 `Event` 列表 —— 记日志、改观测列表、暂停/恢复
扫描都由应用自己决定。多客户端和单客户端共用这一份判定。

用法::

    tr = Tracker()
    for ev in tr.poll(snapshot(found, minimized, core.client_name)):
        if ev.kind == "logout":
            log(ev.note)

单客户端应用还可以用 `choose_one()` 挑"该跟哪台"(按角色名/标题,退第一个
已登录的),返回拿不到时的原因(登录窗/最小化/关掉了)。
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Client:
    """一台客户端窗口在**某一拍**的样子(不可变,方便直接比较)。"""
    title: str = ""
    box: tuple | None = None       # 客户区矩形 (x0,y0,x1,y1);最小化的没有
    name: str = ""                 # 角色名;"" = 登录窗(还没登录角色)
    res: tuple | None = None       # 游戏设置分辨率;None = 没画布(登录窗)
    supported: bool = True         # 这一档认不认(由应用按自己的口径算)
    minimized: bool = False

    @property
    def logged(self):
        """进角色了吗(标题抠得出角色名)。"""
        return bool(self.name)


@dataclass(frozen=True)
class Event:
    """一拍里的一个变化。kind 见 `diff()`;note 是现成的中文说明(日志直接用)。"""
    kind: str
    client: Client
    old: Client | None = None
    note: str = ""


def boxes_overlap(a, b):
    """两个矩形是否相交(重叠面积为正)。改分辨率/登录登出一般原位重摆,
    新老矩形必然还叠着 —— 用它认"这是同一台窗口"比标题稳(标题会变)。"""
    if not a or not b:
        return False
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def snapshot(found, minimized=(), name_of=None):
    """窗口枚举结果 -> `[Client]`。

    found = [(标题, 客户区矩形), ...](可见窗口);minimized = [标题, ...];
    name_of(title) 抠角色名(通常是 client_common.client_name)。分辨率/支持档
    这里不猜:默认 None/True,要判换档的应用自己填(见 Client 字段)。
    """
    out = []
    for title, box in found or ():
        out.append(Client(title=str(title),
                          box=tuple(int(v) for v in box),
                          name=(name_of(title) if name_of else "")))
    for title in minimized or ():
        out.append(Client(title=str(title), minimized=True,
                          name=(name_of(title) if name_of else "")))
    return out


def _who(c, old=None):
    return c.name or (old.name if old and old.name else "客户端")


def _same_identity(a, b):
    """最小化窗口没有矩形,只能按角色名(退标题)认是不是同一台。"""
    if a.name and b.name:
        return a.name == b.name
    return a.title == b.title


def _compare(p, c):
    """同一台窗口前后两拍:角色进出、挪窗、换档。"""
    out = []
    if p.name and not c.name:
        out.append(Event("logout", c, p, f"「{p.name}」已退出登录"))
    elif not p.name and c.name:
        out.append(Event("login", c, p, f"「{c.name}」登录角色"))
    elif p.name and c.name and p.name != c.name:
        # 同一台窗口里换了角色(退出一个、登录另一个):两条都给,应用各自取
        out.append(Event("logout", c, p, f"「{p.name}」已退出登录"))
        out.append(Event("login", c, p, f"「{c.name}」登录角色"))
    if p.box != c.box:
        out.append(Event("moved", c, p, f"「{_who(c, p)}」客户端位置变了"))
    if p.logged and c.logged and p.supported != c.supported:
        res = c.res or (0, 0)
        text = (f"「{c.name}」分辨率 {int(res[0])}×{int(res[1])} 当前不支持"
                if not c.supported else
                f"「{c.name}」恢复支持档 {int(res[0])}×{int(res[1])}")
        out.append(Event("tier", c, p, text))
    return out


def diff(prev, cur):
    """前后两拍快照 -> `[Event]`。

    kind:
      - `opened`    新出现的窗口(登录窗/最小化启动)
      - `login`     拿到角色名(新登录或窗口里换了角色)
      - `logout`    角色名没了(窗口还在 = 原地退出登录)
      - `closed`    窗口没了
      - `minimized` 变成最小化(截不到画面,窗口还在)
      - `restored`  从最小化恢复
      - `moved`     位置/大小变了
      - `tier`      支持档变了(要应用自己填 res/supported 才会出现)
    """
    prev = list(prev or [])
    cur = list(cur or [])
    p_vis = [p for p in prev if not p.minimized]
    p_min = [p for p in prev if p.minimized]
    c_vis = [c for c in cur if not c.minimized]
    c_min = [c for c in cur if c.minimized]
    used_p, used_c = set(), set()
    events = []

    # ① 可见窗口按矩形相交认身份(同一台:拖动/改档/登录登出/换角色)
    for ci, c in enumerate(c_vis):
        for pj, p in enumerate(p_vis):
            if pj in used_p:
                continue
            if boxes_overlap(c.box, p.box):
                used_p.add(pj)
                used_c.add(ci)
                events.extend(_compare(p, c))
                break

    # ② 剩下的可见窗口:上一拍是最小化的同一台 -> 还原
    for ci, c in enumerate(c_vis):
        if ci in used_c:
            continue
        for pj, p in enumerate(p_min):
            if pj in used_p:
                continue
            if _same_identity(p, c):
                used_p.add(pj)
                used_c.add(ci)
                events.append(Event("restored", c, p,
                                    f"「{_who(c, p)}」已还原 —— 继续监听"))
                break

    # ③ 上一拍可见、这一拍不见了:同名最小化 = 最小化,否则关闭
    for pj, p in enumerate(p_vis):
        if pj in used_p:
            continue
        hit = None
        for ck, c in enumerate(c_min):
            if ck in used_c:
                continue
            if _same_identity(p, c):
                hit = (ck, c)
                break
        if hit:
            used_c.add(hit[0])
            events.append(Event("minimized", hit[1], p,
                                f"「{_who(hit[1], p)}」已最小化 —— 截不到画面"))
        else:
            events.append(Event("closed", p, p, f"「{_who(p)}」已关闭"))

    # ④ 没认领的当前窗口:登录窗 = 客户端启动;有角色名 = 新登录
    for ci, c in enumerate(c_vis):
        if ci in used_c:
            continue
        events.append(Event(
            "login" if c.logged else "opened", c, None,
            (f"「{c.name}」登录角色" if c.logged
             else "检测到登录窗口 —— 登录角色后自动接入")))
    for ck, c in enumerate(c_min):
        if ck in used_c:
            continue
        events.append(Event("opened", c, None,
                            "检测到最小化的客户端 —— 还原窗口后自动接入"))
    return events


class Tracker:
    """记住上一拍,喂新快照,吐变化事件。线程内用,不需要锁。"""

    def __init__(self):
        self.prev = []

    def reset(self):
        """清掉记忆(进/出功能、换观测对象时):下一次 poll 会把当下的窗口
        当成"刚出现",不会补报旧的变化。"""
        self.prev = []

    def poll(self, cur):
        cur = list(cur or [])
        events = diff(self.prev, cur)
        self.prev = cur
        return events


def choose_one(clients, want="", previous_title="", previous_box=None):
    """单客户端应用:从快照里挑要跟的那台。返回 `(Client | None, 原因)`。

    优先级:`want`(用户选过的标题/角色名)> 跟上一拍同一窗口的那台
    (窗口矩形还叠着 —— 多标签版点了另一个角色标签时标题会变,窗口没变)
    > 第一个已登录可见的。
    原因(挑不到才有):
      - `"gone"`      选定的那台不在了(但同时还有别的客户端?照样返回,
                      由应用决定是暂停等用户重选还是换一台)
      - `"login"`     只剩登录窗(还没登录角色)
      - `"minimized"` 只有最小化的客户端(截不到画面)
      - `"none"`      一个窗口都没有
    同一窗口标题变了(换角色/切标签)时返回 `(该台, "renamed")`:应用别当成
    重新登录,也别暂停扫描。
    """
    logged = [c for c in clients if c.logged and not c.minimized
              and c.supported]
    if want and logged:
        for c in logged:
            if c.title == want or c.name == want:
                return c, ""
        if previous_box:
            # 标题/角色名对不上,但窗口还是那一块:多标签版切标签、或同一
            # 窗口里换了角色 —— 继续跟,别暂停等用户重选(2026-11-12 修)
            for c in logged:
                if boxes_overlap(previous_box, c.box):
                    return c, "renamed"
        if previous_title:
            # 有别的已登录客户端、但不是选定的那台:交给应用决定
            # (单客户端应用通常暂停,等用户重选)
            return None, "gone"
    if logged:
        return logged[0], ""
    if any(not c.minimized for c in clients):
        return None, "login"
    if clients:
        return None, "minimized"
    return None, "none"
