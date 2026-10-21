# mhxy_降妖伏魔 —— 独立的降妖伏魔小助手

## 这是什么

Windows 桌面工具(Python 3.12 + Tk + RapidOCR/DirectML),从 `E:/Project/keju-answerer`
抽出来的独立应用,**纯读屏**:读任务提示里的"地图名+坐标" → 地图上画红点。
不碰游戏进程/内存,不自动操作游戏。

## 环境

```bash
# Python 用项目 venv(建法见 README)
.venv/Scripts/pythonw.exe main.py        # 启动
.venv/Scripts/python.exe tests.py --quiet # 回归:约 12 秒,全绿再收工(条数以跑出来的为准)
.venv/Scripts/python.exe check_shots.py   # 真机截图离线校验(docs/shots,10 张,约 7 秒)
```

- Bash 工具走 Git Bash,Windows 原生命令的参数要写双斜杠(`taskkill //F //PID`)
- 日志:`bell.log`,格式 `YYYY-MM-DD HH:MM:SS [模块]内容`
- 命令行:`python main.py --layout`(量对话框位置写分辨率表)

## 目录结构与职责(五层,别混)

```
入口  main.py      argparse + 依赖检查
界面  ui/*.py      bell(小窗,唯一窗口) / widgets(摆位/动效/小窗皮肤)
逻辑  tools/bell.py BellTool:自己的线程、状态、扫描循环
地基  core.py      配置(app/bell 两分区)/ OCR / 截图 / 窗口枚举 / Engine
数据  data/        maps(底图+标定)、bell_layouts.json(分辨率表)
```

## 界面约定(单窗应用,动界面前先读)

- **启动直达小窗,× 即退出**;没有主页/工具箱,`show_bell()` 就是整个入口
  (快部分建窗,慢活 `_enter_bell_slow` 排在动画起跑之后)
- **小窗上只有四类字**:地名、坐标、角色名 + 两颗无文字圆钮(**↻ 紧跟在角色名
  后面**,位置随名字长度走;**☀/☾ 在右下角**切深色/明亮;2026-10-21 用户选定的
  深色 HUD A + 明亮 B 两套皮肤,选择存 `bell.ui_mode`;不出现"监听/定位"这类
  交代程序在干什么的文案)。别再加状态行/文字按钮
- **没目标 = 空状态**:占位句「暂无目标」写在**地名位**(灰),画布**完全留空**
  (2026-10-21 用户定的:画布中间不再写字,否则像卡片上开了个洞)
- **最小化/关闭走系统标题栏**(2026-10-21 用户定的):底行**不再有 `−`**,
  标题栏那颗最大化虽被 `hide_maximize()` 清了 `WS_MAXIMIZEBOX` 而点不动,
  但 **Win11 24H2 仍会画一个灰框**(原生窗口实测:只置灰不消失),别以为是
  自己的 bug;真要它消失只能自绘标题栏,那会丢掉任务栏/最小化,不做
- **新目标红点弹一下**:换目标时红点从 16px 放大到 ~30px 再回弹(`PULSE_FRAMES`,
  全程 ~175ms,`after` 驱动),同目标重画(切主题)不弹 —— 判据是
  `app._bell_last_target`,别改成"每次 draw 都弹"。这是唯一的"新鲜度"反馈
  (用户 2026-10-21 明确不要时间戳)
- **圆钮靠 hover 自解释**:鼠标停上去时底行那句临时换成「换客户端」/「明亮模式」,
  **用金色**(角色名是灰的:同位置同颜色会看成"名字变了");没定位到底行写
  「暂未找到客户端」,不留空
- **失败提示就地写,不弹框**:点 ↻ 没找到客户端时 `ui_bell.flash_foot()` 在底行
  写 1.6 秒红字「没找到客户端」再还原(2026-10-21 用户定的:模态框会打断游戏)
- **首启跟随系统深浅色**:`core.default_ui_mode()` 在没选过 `bell.ui_mode` 时读
  注册表 `AppsUseLightTheme`(明亮→B,深色→A);选过就以配置为准,别再跟系统
- **窗口位置要记住**:退出时 `App.save_bell_pos()` 把位置写进 `bell.bell_pos`,
  下次 `set_place(pos=...)` 摆回原处;位置已经不在屏幕里(`ui/widgets:usable_xy`
  要求留一条标题栏在屏内)就退回居中
- **窗口一圈 1px 描边**(`win_edge`,2026-10-21):深色底压在深色场景上时只靠
  系统阴影分不清窗口边界;切主题时 `apply_theme` 要跟着换这条边的颜色
- **画框固定 380x300**(2026-10-21 用户定;先试过 400x280):底图等比缩进画框后
  居中,换图时窗口高度不跳;**留边要等于窗口底色**(色板 `paper` = `bg`,别给它
  单独一个"画布色",用户 2026-10-21 报过);别再改回"画布高度跟着底图长宽比算"
- **网格烘在底图里**(2026-10-21 用户定的:不是运行时画线):`data/maps/傲来国.png`
  / `朱紫国.png` = 7 列 × 5 行,`长寿村.png` = 5 列 × 7 行,其余三张不画。要改
  格子就**重烘底图**,别在 `draw_bell` 里加线
- **文字必须完整显示**:Tk 字号是**磅值**(20pt 在 100% 下重排成 ~41px 高),
  所以地名行的行高**由内容撑、别写死**(写死 30px 会把字上下裁掉,用户
  2026-10-21 报过"地图名显示不全");地名太长由 `_fit_name` 缩字号(20→12pt),
  不许省略/截断
- 窗口摆位 `ui/widgets.set_place`(按请求尺寸居中;`pos=` 给了就摆回那儿、
  坏了才居中);`winfo_rootx/rooty` 差一个标题栏,别拿它摆窗
- 动效走 `pop_in/stop_anim`;顺序是死的:先 `-alpha 0` 再 `deiconify`
  再逐帧淡入。销毁窗口前先 `stop_anim`
- DPI:Tk 的 winfo_* 是逻辑像素,截图/窗口矩形是物理像素,换算用
  `gui.scale_rect(rect, gui.screen_scale(root))`
- 日志分家:小窗**没有日志区**(2026-10-21 撤),所有日志只进 `bell.log`
  (`ui=`/`ui_text=` 参数与 `_logs` 队列同日删光,`App.log` 只剩 `(msg, detail="")`)

## 五条红线(改完自己 grep 验)

1. 只能 `import core` + 调用时 `core.xxx`(tools/* 模块级连 import core 都不许)
2. `ui/` 只建控件不写行为(回调指向 `app.on_xxx`;例外:`ui/bell.py` 的 `draw_bell` 画布)
3. `tools/bell.py` 不许 import `ui`(工具层不反向依赖界面层)
4. `tools/bell.py` 自己的常量(MAP_DIR 等)测试用 `patch(mods=(tools_bell,), ...)` 换
5. 测试里 `PATCH_MODULES = (core,)` —— 改动前确认不让 `patch(...)` 打空炮

## 踩过的坑(继承自原项目,别再踩)

- 删代码时 `@staticmethod` / `@property` 跟着一起删/搬
- 一行改动用 Edit 工具,别写脚本猜缩进
- `self._stop = threading.Event()` 会覆盖线程私有方法,已改名 `_halt`
- 重构成败靠测试和探针,别只看代码"读起来对";写一次性探针,跑完删
- 打包版 `sys.executable` 是应用自己,要跑子任务就进程内做

## 铃铛识别口径

六种怪的对话框/任务栏原文表、`BELL_WORDS` 话术门槛、`known_map` 地名容错、
`_bell_scope` 圈范围、扫描门控、底图录入:全在 `docs/bell-internals.md`
(约 70KB,**别整份读**:Grep 标题 → Read 那一小段)。

- **真机截图夹具**在 `docs/shots/`(六种怪 10 张,坐标原文写在
  `expected.json`):改 det 参数 / 解析口径之后跑 `check_shots.py` 对数。
  它是独立进程(建真引擎);`tests.py` 只查表里文件在不在,不跑 OCR。

## 与原项目的关系

识别逻辑(`tools/bell.py`)原先与 `E:/Project/keju-answerer` 保持一致,那边的铃铛
bug 修复可以直接拷过来,反之亦然;**2026-10-21 起本应用只支持两档分辨率、任务栏框
一律来自表,删掉了整窗找框/学框/作废/退避冷却那条兜底链**(原项目还有),两边不再
逐字节一致 —— 拷修复前先 diff 这一块。`ui/bell.py` 2026-10-20 起按本应用的界面
走了(顶栏/抽屉/开关撤掉)。`data/` / `docs/bell-internals.md` 的识别口径部分原先
两边同源,同样自 2026-10-21 起分叉(本应用侧已按删整窗后的状态改写)。改完跑
`tests.py --quiet` 全绿再收工。

## 工作方式约定

- 不要自动提交/推送;改完留在工作区,等用户发话
- 改完必须跑测试,红了立刻回退,绝不留半成品
- 大改动分小步,每步跑一次测试
- 跑完删临时探针脚本/图片
