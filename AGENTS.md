# mhxy_降妖伏魔 —— 独立的降妖伏魔小助手

## 这是什么

Windows 桌面工具(Python 3.12 + Tk + RapidOCR/DirectML),从 `E:/Project/keju-answerer`
抽出来的独立应用,**纯读屏**:读任务提示里的"地图名+坐标" → 地图上画红点。
不碰游戏进程/内存,不自动操作游戏。

## 环境

```bash
# Python 用项目 venv(建法见 README)
.venv/Scripts/pythonw.exe main.py        # 启动
.venv/Scripts/python.exe tests.py --quiet # 回归:205 条,约 13 秒
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
- 窗口摆位 `ui/widgets.set_place`(按请求尺寸居中);`winfo_rootx/rooty`
  差一个标题栏,别拿它摆窗
- 动效走 `pop_in/stop_anim`;顺序是死的:先 `-alpha 0` 再 `deiconify`
  再逐帧淡入。销毁窗口前先 `stop_anim`
- DPI:Tk 的 winfo_* 是逻辑像素,截图/窗口矩形是物理像素,换算用
  `gui.scale_rect(rect, gui.screen_scale(root))`
- 日志分家:小窗**没有日志区**(2026-10-21 撤),所有日志只进 `bell.log`
  (`tools/bell.py` 的 `ui=`/`ui_text=` 参数保留,`gui.log` 照单全收不再另作他用)

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

识别逻辑(`tools/bell.py`,除 `on()` 一处:监听常开)与 `E:/Project/keju-answerer`
保持一致,那边的铃铛 bug 修复可以直接拷过来,反之亦然;`ui/bell.py` 2026-10-20
起按本应用的界面走了(顶栏/抽屉/开关撤掉),不再逐字节一致。`data/` /
`docs/bell-internals.md` 的识别口径部分两边同源。改完跑 `tests.py --quiet`
全绿再收工。

## 工作方式约定

- 不要自动提交/推送;改完留在工作区,等用户发话
- 改完必须跑测试,红了立刻回退,绝不留半成品
- 大改动分小步,每步跑一次测试
- 跑完删临时探针脚本/图片
