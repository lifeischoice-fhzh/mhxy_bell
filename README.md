# 降妖伏魔 —— 梦幻西游找点小助手

从 [mhxy_keju](../mhxy_keju)(原 keju-answerer)项目里抽出来的**独立应用**,只做一件事:

读任务提示里的"地图名+坐标" → **地图上画红点**(不播语音,要的就是安静)。

纯读屏辅助:不碰游戏进程/内存,不自动操作游戏。客户端窗口全自动定位,
只认一台;登录窗不认,登录角色后自动接入监听(多开时可按角色名切换)。

## 环境与启动

```bash
# 一条命令建环境(Python 3.12):建 .venv、装钉死版本的依赖、把 onnxruntime
# 修成 DirectML 版并验证(两种发行版谁后装谁覆盖,详见 requirements.txt 顶部)
tools\setup_venv.bat

# 或手动(顺序别乱,最后一步不能省):
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
.venv/Scripts/python.exe -m pip install --force-reinstall --no-deps onnxruntime-directml==1.24.4

# 启动
.venv/Scripts/pythonw.exe main.py

# 命令行
python main.py --layout      # 量画布上对话框的位置,换算占画比打印
                             # (填 client_common.DLG_RATIOS;标注图存
                             #  docs/layout/<版式>_<分辨率>_缩放<N>.png)
python tests.py --quiet      # 回归测试(约 12 秒,全绿再收工)
python check_shots.py        # 真机截图离线校验(docs/shots/ 里六种怪 10 张)
```

## 用法

- 启动**直接进小窗**(唯一窗口,**不置顶**,盖到游戏就拖到旁边):自动定位客户端、
  按坐标范围标定,**监听常开**(没有开关)—— 认到妖魔只在小窗标一个红圆点 + 写日志。
  启动时还在登录页也没关系:**登录角色后自动接入监听**,不用再点药丸
- 六张地图的底图**已内置**(长寿村/傲来国/朱紫国/建邺城/西梁女国/宝象国),
  界面没有采集入口;采集的代码完整保留(抽屉控件与回调都在,只是没有按钮),
  后续看情况开放
- 界面没有日志区(2026-10-21 撤);日志只进 `bell.log`
- **支持 640×480 / 800×600 / 1024×768 三档游戏分辨率**(2026-11-12 起 1024
  重新加入),按游戏设置分辨率精确判(WSGAME 画布 ÷ 显示器缩放),别的档
  弹窗提醒;两种窗口版式都认(多标签"多开合一"与独立窗口),登录窗不认。
  对话框/任务栏的比例框**只按分辨率分档,两种版式共用一套**(2026-11-12
  用户定的「多标签和独立的共用一套,不用分开」):对话框三档 8/48/93.6/84.6、
  16/48/85/78、17/48/84/76,任务栏占画比 0.6/0.1/1/0.66、0.7/0.08/1/0.53、
  0.76/0.06/1/0.42
- 小窗 × = 退出应用(引擎/线程随之结束)

## 目录结构(五层)

```
入口  main.py           命令行入口(argparse + 依赖检查)
界面  ui/bell.py        小窗(唯一窗口)
      ui/widgets.py     再导出(摆位/动效/皮肤)
      ui/skin.py        小窗色板 + 圆角图/ttk 样式
逻辑  tools/bell.py     BellTool:自己的线程/状态/扫描循环
      tools/bell_parse.py 提示文法/文字块解析(纯函数)
      tools/panel.py      对话框面板检测/内容签名
      tools/maps.py       底图/坐标范围/标定
      tools/mapfind.py    截图里找地图窗口
      tools/layout.py     --layout 量框命令行
地基  core.py           配置(app+bell 两分区)/Engine/各层再导出
      appenv.py         Windows 进程环境(DPI/AppID/单实例/扫尾)
      screen.py         截屏(Screen + freeze_screen)
      ocr.py            OCR(Ocr,与 keju 同源),core 再导出
      win_common.py     窗口摆位/动效/标题栏/图标(可拷给新 Tk 应用)
客户端 client_common.py  窗口/WSGAME 画布枚举、游戏分辨率折算、档位表、
                        对话框框比例 DLG_RATIOS、任务栏框比例 TRK_BOXES、
                        角色名(与 keju 两边同源)
      clients.py        本应用口径(core 再导出供上层使用)
      client_watch.py   客户端生命周期判定(启动/登录/登出/关闭/最小化/
                        还原/挪窗/换档;纯逻辑、单文件可复用,与 keju 同口径)
数据  data/maps/*       底图(六张,随仓库分发)+ bounds/calib 标定
      data/bell.ico     窗口/任务栏/exe 图标
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
package.bat          # 绿版 + 安装包 dist/mhxy_bell.exe 一条龙
```

产出两样:`dist/降妖伏魔/`(绿色版,重打包时保留配置/日志/底图)和
`dist/mhxy_bell.exe`(安装包)。安装包版本号在 `tools/inno/version.txt`,
每次打包自动把最右一位 +1;要定版本用 `package.py --version 1.2.0`。

## 文档

识别口径(六种怪的原文表、话术门槛、地名容错、扫描门控、底图录入)在
`docs/bell-internals.md` —— 动铃铛前先按标题查那一节,别整份读。
