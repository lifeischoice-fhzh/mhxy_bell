# 降妖伏魔 —— 梦幻西游找点小助手

从 [keju-answerer](../keju-answerer) 项目里抽出来的**独立应用**,只做一件事:

读任务提示里的"地图名+坐标" → **地图上画红点**(不播语音,要的就是安静)。

纯读屏辅助:不碰游戏进程/内存,不自动操作游戏。客户端窗口全自动定位,
支持只认一台(多开时按角色名选)。

## 环境与启动

```bash
# 装依赖(Python 3.12;onnxruntime 两种发行版的注意事项见 requirements.txt 顶部)
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pip install --force-reinstall --no-deps onnxruntime-directml==1.24.4

# 启动
.venv/Scripts/pythonw.exe main.py

# 命令行
python main.py --layout      # 量当前客户端尺寸下对话框的位置,写进分辨率表
python tests.py --quiet      # 回归测试(187 条)
python check_shots.py        # 真机截图离线校验(docs/shots/ 里六种怪 10 张)
```

## 用法

- 启动**直接进小窗**(唯一窗口,置顶):自动定位客户端、按坐标范围标定,
  **监听常开**(没有开关)—— 认到妖魔只在小窗标一个红圆点 + 写日志
- 六张地图的底图**已内置**(长寿村/傲来国/朱紫国/建邺城/西梁女国/宝象国),
  界面没有采集入口;采集的代码完整保留(抽屉控件与回调都在,只是没有按钮),
  后续看情况开放
- 界面没有日志区(2026-10-21 撤);日志只进 `bell.log`
- **只支持 640x480 / 800x600** 两种客户端分辨率,别的尺寸会弹窗提醒
- 小窗 × = 退出应用(引擎/线程随之结束)

## 目录结构(五层)

```
入口  main.py           命令行入口(argparse + 依赖检查)
界面  ui/*.py           bell(小窗,唯一窗口) / widgets(摆位/动效/皮肤)
逻辑  tools/bell.py     BellTool:自己的线程/状态/扫描循环
地基  core.py           配置(app+bell 两分区)/OCR/截图/窗口枚举/Engine
数据  data/maps/*       底图(六张,随仓库分发)+ bounds/calib 标定
      data/bell_layouts.json   各分辨率下对话框/任务栏的位置表
```

## 与原项目(keju-answerer)的差异

- 只保留降妖伏魔;科举的题库(bank.py)/语音(Speaker/edge-tts/pywin32)/
  收益统计/CLI 自检全部不在
- **没有语音**:原项目 2026-10-16 起铃铛就只标点不播报,本应用顺水推舟
  把整条语音链(依赖与线程)拆掉了
- **单窗应用**:没有原项目的工具箱/主页——启动直达小窗,× 即退出;
  “读到妖魔自动弹出小窗”的 0操作模式随之删除(窗口常开,弹无从谈起)
- 配置只有 `app` / `bell` 两个分区;日志文件叫 `bell.log`
- `tools/bell.py`、`ui/bell.py`、`data/`、`docs/bell-internals.md` 原先与原项目
  逐字节一致(除个别注释),两边修 bug 可以互相搬运 —— 2026-10-20 起界面层
  按本应用的需求改了(顶栏/抽屉/开关撤掉),识别逻辑(`tools/bell.py`)仍保持同步
- 测试是从原 `tests.py` 移植的 `sec_bell` + `sec_bell_ui` 两组,
  跑法:`python tests.py --quiet`

## 打包(可选)

```bash
.venv/Scripts/python.exe -m pip install pyinstaller
package.bat          # 或 python package.py --dry-run 先看一眼
```

产出 `dist/降妖伏魔/降妖伏魔.exe`;配置、日志、自己录的底图会在重打包时保留。

## 文档

识别口径(六种怪的原文表、话术门槛、地名容错、扫描门控、底图录入)在
`docs/bell-internals.md` —— 动铃铛前先按标题查那一节,别整份读。
