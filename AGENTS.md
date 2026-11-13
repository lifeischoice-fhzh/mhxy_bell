# mhxy_降妖伏魔 —— 独立的降妖伏魔小助手

## 这是什么

Windows 桌面工具(Python 3.12 + Tk + RapidOCR/DirectML),从 `E:/Project/keju-answerer`
抽出来的独立应用,**纯读屏**:读任务提示里的"地图名+坐标" → 地图上画红点。
不碰游戏进程/内存,不自动操作游戏。

## 环境

```bash
# Python 用项目 venv(建法见 README;一条命令 `tools\setup_venv.bat` 会把
# onnxruntime 修成 DirectML 版并验证,requirements.txt 顶部的双发行版坑)
.venv/Scripts/pythonw.exe main.py        # 启动
.venv/Scripts/python.exe tests.py --quiet # 回归:约 12 秒,全绿再收工(条数以跑出来的为准)
.venv/Scripts/python.exe check_shots.py   # 真机截图离线校验(docs/shots,10 张,约 7 秒)
.venv/Scripts/python.exe package.py       # 绿版+安装包一条龙;版本 --version 指定,否则最右位自动+1
```

- 发给别人用 = `dist/mhxy_bell.exe`(Inno Setup 打的安装包,每用户安装到
  `%LocalAppData%\降妖伏魔`,不弹 UAC;装完桌面/开始菜单有图标,卸载删干净)。
  脚本 `tools/inno/installer.iss` 只打包 exe + `_internal`,本机运行数据
  (config/bell.log/data)不进去,首启自动生成。exe 未签名,对方首次运行会过
  SmartScreen 那道"更多信息 → 仍要运行"。版本号:`package.py` 不带参数每次
  打包自动把最右一位 +1(记录在 `tools/inno/version.txt`,随仓库提交);
  要定版本用 `--version 1.2.0`,只更新绿色版时 ISCC 缺席会自动跳过安装包。
  spec 对 onnxruntime **不要用 collect_all**(2026-11-05 瘦身):那会把
  quantization/transformers/tools 几百个离线工具 .py 拖进包;运行时只要
  capi 的 dll/pyd(spec 里 `collect_dynamic_libs('onnxruntime')`),改完
  spec 必须真机验证 —— 起打包版看日志里 `GPU(DirectML)` 是否就绪

- Bash 工具走 Git Bash,Windows 原生命令的参数要写双斜杠(`taskkill //F //PID`)
- 日志:`bell.log`,格式 `YYYY-MM-DD HH:MM:SS [模块]内容`
- 命令行:`python main.py --layout`(量画布上对话框的位置,换算占画比打印
  —— 直接可填 client_common.DLG_RATIOS 对应的那一档;**每档存标注图**到
  `docs/layout/<版式>_<WxH>_缩放<N>.png`(红=任务栏框、蓝=对话框框;
  一档一张,重跑同名覆盖,别加后缀)

## 目录结构与职责(五层,别混)

```
入口  main.py          argparse + 依赖检查
界面  ui/bell.py       小窗(唯一窗口)
      ui/widgets.py    再导出(摆位/动效/皮肤),ui_widgets.XXX 引用不变
      ui/skin.py       小窗色板 + PIL 圆角图/ttk 样式
逻辑  tools/bell.py    BellTool:自己的线程、状态、扫描循环(兼做再导出)
      tools/bell_parse.py 提示文法/文字块解析(纯函数,好离线测)
      tools/panel.py      对话框面板检测/内容签名(可拷给别的读屏应用)
      tools/maps.py       底图查找/坐标范围/标定/地图名(可拷走)
      tools/mapfind.py    截图里找地图窗口(彩色块 + 深色外框,可拷走)
      tools/layout.py     --layout 量框命令行
地基  core.py          配置(app/bell 两分区)/ Engine / 各层再导出
      appenv.py        Windows 进程环境(DPI/AppID/单实例/深浅色/扫尾)
      screen.py        截屏(Screen + freeze_screen)
      ocr.py           OCR(Ocr;与 keju 同源,本应用多 limit_type 快路径
                       与耗时诊断),core 再导出
      win_common.py    窗口摆位/动效/标题栏/图标(可拷给新 Tk 应用)
客户端 client_common.py(与 keju 同源,窗口/画布枚举、游戏分辨率折算、
       档位表、对话框比例 DLG_RATIOS、任务栏比例 TRK_BOXES、角色名,以及
       通用的 box_of / ratio_of / draw_box —— 比例↔像素、画框复核,别的应用
       直接拿)
       + clients.py(本应用口径,如支持档文案);core.py `from clients
       import ...` 再导出,外界仍只认 core.XXX
       + client_watch.py(客户端生命周期判定:启动/登录/登出/关闭/最小化/
       还原/挪窗/换档;纯逻辑不碰 core/界面,单文件可复用 —— 应用把窗口
       枚举包成 Client 快照喂 Tracker.poll,拿 Event 自己记日志;单客户端
       应用另用 choose_one() 选台。与 keju 的 _follow_clients 同口径)
数据  data/        maps(底图+标定)、bell.ico(窗口图标)
```

- 2026-11-13 按"能单独成文件复用"拆过一轮并核过依赖:`screen.py` /
  `appenv.py` / `win_common.py` 是**与业务无关、可整文件拷给新应用**的
  (appenv 不带任何应用默认值:互斥体名/AppID 必传、cleanup_runtime 只默认
  清根目录 __pycache__,本应用的 tools/ui 缓存与 bell.log.old 由 core 显式传);
  `tools/*.py` 里 `maps/mapfind/panel/bell_parse` 只依赖 numpy/PIL(或纯
  文本),**不 import core**(工具层红线),需要截图/窗口时由调用方传进来;
  `tools/layout.py` 不在复用件之列 —— 它是 `--layout` 量框命令行,函数内
  用 core 的 Screen/画布探测/比例表(为量本应用的表服务,天生带应用语境)。
  `tools/bell.py` 仍保留一长串 import 只是**再导出** —— `gui.py`、
  `ui/bell.py`、`check_shots.py`、`tests.py` 里 `tools_bell.XXX` 的引用
  不变,别顺手删那些"看起来没人用"的名字。
- 拆模块后的测试补丁口径:地图路径(`MAP_DIR` / `MAP_CALIB_PATH` /
  `MAP_BOUNDS_PATH`)打在 **`tools.maps`** 上(`tests.py` 里
  `patch(mods=(tools_maps,), ...)`);`canvas_res_of` / `cursor_pos` /
  `BellTool` 仍在 `tools_bell`。`core.system_light_mode` 这类补丁不变
  (`appenv` 的名字由 core 再导出,`default_ui_mode` 在 core 里查全局名)。
- `ocr.py` 是 2026-11-12 从隔壁 keju 拿过来的单文件(keju 那边本就为
  可复用拆出来):`Ocr` 是本应用的**超集** —— 多出 det 的
  `limit_type="max"` 快路径(对话框条带按原像素跑)与真实识别耗时诊断,
  同步时别把这两段冲掉;顶层不 import core,`_get` 里惰性 `import core`
  读 use_gpu(构造参数 `use_gpu=True/False` 显式给了就不碰 core —— 别的
  工程拷走传一下即可;红线:模块级只用自己的常量)。截屏的 `Screen` 2026-11-12 起在
  `screen.py`(`Ocr` 仍从 ocr.py 出;`core.Screen` 再导出,旧引用不变)。
- 客户端探测那两层是 2026-11-12 从隔壁 keju 搬来的:`client_common.py`
  **除文件头一段外逐字同源,同步 = 整文件覆盖**(两边一起改口径);
  `clients.py` 只放本应用特有的口径。别把应用口径写进 client_common,
  也别绕过 core 直接 import clients/client_common(tools 层红线同样适用)。
  画布探测结果带**版式**第 5 元(`"tab"` 多标签版 = 顶层 MHXYMainFrame 挂
  角色标签子层;`"win"` 独立窗口版 = 顶层自身就是 WSGAME)—— 只用于日志和
  存档文件名;**比例表/框表不按版式分,两版式共用一套**(2026-11-12 用户
  定的:「多标签和独立的共用一套,不用分开」)

## 界面约定(单窗应用,动界面前先读)

- **启动直达小窗,× 即退出**;没有主页/工具箱,`show_bell()` 就是整个入口;
  小窗**不置顶**(2026-11-05 用户定的:置顶会一直盖住游戏画面,别加回去)
  (快部分建窗,慢活 `_enter_bell_slow` 排在动画起跑之后)
- **小窗上只有四类字**:地名、坐标、角色名(**包在左下角一个圆角药丸里,无三角**),
  右下角一颗无文字的 **☀/☾** 切深色/明亮(2026-10-21 用户选定的深色 HUD A +
  明亮 B 两套皮肤,选择存 `bell.ui_mode`;不出现"监听/定位"这类交代程序在干什么
  的文案)。别再加状态行/文字按钮
- **左下角那个药丸就是"重新定位"**(2026-10-22 用户定的,方案 E):点一下 = 重新
  找一次客户端,**列表从药丸头上浮出来**,盖在地图上 —— **窗口尺寸一步不动**
  (用户明确不要"改变应用高度"的方式);再点一下药丸收起。面板**只有客户端行**,
  几个列几个,行距统一 `ROW_H`(24),当前那台**最右边金点**、字提亮,悬停整行
  亮一档。**药丸宽 = 7 个字的宽**(`chip_width`),长名字末尾省略,别加三角
  (用户 2026-10-22 明确删掉)。按下时字变金色(点击感),平时灰色。单独的 ↻ 圆钮已删
- **列表只写角色名**:不显示客户端尺寸(用户 2026-10-22),非当前行是
  11pt `sub` 灰、当前行提亮 `txt`;超过 6 台只列前 6 台
- **没有 hover 文字提示**(2026-10-22 用户取消):鼠标停按钮上不再改底行文案 ——
  之前"提示比名字短把 ↻ 挤走、Enter/Leave 打架整行狂闪"的坑也一并没了;别再
  往底行加"临时换字"的逻辑。**唯一例外**:角色名药丸上悬停浮出当前游戏分辨率
  (2026-11-12 用户点名要的,照 keju 的做法;`gui.App.on_client_hover_start` +
  `win_common.hover_tip`,无边框透明抠圆小条,按**角色名实时匹配**画布 ——
  拖动窗口/换分辨率都跟得上,别扩散到别的控件;分辨率**不在支持档时直接
  红字「分辨率不支持」**,只报数字还要用户自己去比档位表,2026-11-12 定的)
- **主题钮(☀/☾)= 圆形按钮**(2026-10-22 用户定的):`ui/skin.py:_icon_pil`
  画一个圆底(btn 色 + btn_line 描边)+ 字形;常态灰字、悬停**不变**、
  **按下金字**(点击感),悬停不换背景。列表/抽屉里的普通按钮仍是圆角矩形
- **失败提示就地写,不弹框**:框里没找到客户端时 `ui_bell.flash_foot()` 写 1.6 秒
  红字「没找到客户端」再还原(2026-10-21 用户定的:模态框会打断游戏)
- **登录窗不进客户端列表**(2026-11-12,与 keju 同判):`tools_bell.client_choices()`
  按 `core.client_name(title)` 空串过滤登录窗;全被过滤掉时手动点药丸在底行红字
  「请先登录角色」,启动自动定位只落日志(别一开应用就弹),别把登录窗列出来
  再提示分辨率/没有画面
- **客户端退出/回登录页,药丸要跟着收掉旧角色名**(2026-11-12 用户报「客户端
  退出了,为什么角色名还在」):判定在 `client_watch.py`(登录/登出/关闭/
  最小化的前后两拍差分),`BellTool.regions()` 照着置 `_client_lost`
  (`ui_state()["client_lost"]`)—— 枚举不到任何窗口、只剩登录窗、选中的那台
  不在列表里;`gui._drain_logs` 看到它就 `_refresh_bell_locate(None)`
  写「暂未找到客户端」并记一条日志。**最小化不算退出**(截不到画面但客户端还在,
  底行名字留着)。配置里的 `bell_client` **不清**:同一角色重登会自动接回去,
  换角色登录自动接第一台。原地登出会写一条带角色名的日志
  「「祭花′」已退出登录 —— 登录角色后自动接入监听」;同一窗口里角色换了
  (真换角色或多标签版点标签)写中性的「当前角色换成「B」(原「A」)」——
  切标签并没有登出,别写成"已退出登录"(2026-11-12)
- **客户端枚举每拍都做,不缓存**(2026-11-12 用户定的):实测一次整表枚举
  ≈0.24ms,比截图/OCR 便宜得多;缓存会让窗口挪动/换分辨率晚一拍甚至更久。
  `regions()` → `_poll_clients()` 每拍 `find_client_windows`,画布每拍
  `canvas_res_of`;画布配不到(登录窗/最小化/刚换档)就**整拍跳过**,不按旧
  坐标读。登录/登出/换角色/关闭/最小化的前后两拍判定在 `client_watch.py`
  (纯逻辑、可复用),别再给窗口枚举加节流。**同一窗口标题变了照样跟**
  (`choose_one(..., previous_box=...)`:窗口矩形还叠着就返回 `"renamed"`,
  继续扫、不暂停、不写"自动接入")—— 多标签版一个窗口挂多个角色,标题跟着
  **当前标签**变(2026-11-12 真机:8 秒里标题在「杰尼龟徒弟10」/「荆门好礼
  掌柜」之间跳),只按标题认台会把点标签当成客户端退出、扫描反复暂停
- **工具只许开一个**(2026-11-05 用户定的,实现抄 keju):`main.py` 用命名互斥体
  (`core.single_instance`,`Global\MHXY_BELL_TOOL_MUTEX`)拦第二实例,弹框退场;
  `--layout` 命令行模式不拦,方便并用。分辨率不支持的**提示 = 角色名变红**
  (2026-11-12 用户定的):扫描发现当前客户端掉到不支持的档,就把药丸上的
  角色名染红(`ui_bell.set_name_bad`,文案不变),改回支持档自动复原;
  **不弹模态框、也不加一句"分辨率不支持"**;客户端照样留在列表里
  (与 keju 一致,不藏人)。档位判定/文案统一走 `core.supported_res` /
  `core.supported_res_text`(实现在 `clients.py`,档位表本体在 client_common
  与 keju 同源),别再手写死档位数字;**不支持时的行为对齐 keju**:
  `fixed_dialog` 记一条「游戏分辨率 W×H 不支持,已跳过 —— 只支持 …(请在
  游戏设置里改一下)」(同一尺寸只写一次),改回支持档后 `check_size` 记一条
  「已恢复到支持档 W×H,继续识别」并自动恢复扫描
  (keju 叫"自动纳入观测");**本应用不把客户端移出观测**(单客户端、药丸
  还挂着角色名),界面上**不再做"建议调最小分辨率"的提示**
  (2026-11-12 用户去掉,别加回来)
  (**三档**:640×480 / 800×600 / 1024×768,2026-11-12 起 1024 与 keju
  对齐重新加入,按**游戏设置分辨率**精确判;对话框比例表 `DLG_RATIOS` 与
  任务栏框表 `TRK_BOXES` 都**只按分辨率分档,多标签版与独立窗口版共用一套**
  (2026-11-12 用户定的:「多标签和独立的共用一套,不用分开」;画布元组的
  版式第 5 元只进日志/存档文件名):对话框 640 = 8/48/93.6/84.6、800 =
  16/48/85/78、1024 = 17/48/84/76;任务栏占画比 640 = 0.6/0.1/1/0.66、
  800 = 0.7/0.08/1/0.53、1024 = 0.76/0.06/1/0.42(都是 2026-11-12
  用户逐档定的);没量的档 `fixed_dialog` / 任务栏那支整支不读,加新档
  先量再填;**游戏里换了分辨率**(窗口矩形常常一像素不动)也按新档重取任务栏框
  (`SlotState.res` 变了就重种,签名/时刻归零;表框是画布锚定的绝对坐标,
  存进 `st.trk` 前先减窗口原点 —— `trk_seed_rel`,扫描时 `abs_rect` 再加回去);
  老的窗口尺寸表 bell_layouts.json 已整体退役)
- **对话框门控两条路**(2026-11-12,游戏能换对话框皮肤):暗比
  (`tools/panel.py:panel_box`)照旧是快路;**暗比不够时**改走**结构锚点**
  (`flat_panel_box`)—— 4× 块平均(抹掉面板自带的 3px 扫描线纹理)后找
  "一整块低频平坦的横条(空白区)+ 上面 2~3 排文字行",与配色无关。门槛:
  空白带 ≥24px(2026-11-13 从 40 降下来:给"字更多的对话框"留余量,真机最密
  的对话空白带 144px、合成压测 12px 行距都能过)、宽 ≥0.55W、上方文字行
  ≥2 排(**从框顶看起,不设窗口** —— 文字顶格排版,第一行固定贴着框顶,
  2026-11-13 用户指正;返回的框从框顶开始,OCR 的"框顶 62%"裁剪不受影响)、
  **空白带还要一直落到画面下缘**(≥0.72 框高:定稿框下边离面板底只
  有 ~17px;世界里的半截路面/地板只到 ~57%,靠这条挡)。真机实测:**浅/暗
  两套皮肤 × 640/800/1024 三档全部认出**(浅色只靠结构、暗色两条路都认),
  三档各 3 块世界对照 0 误报;10 张老夹具全认出、6 段世界对照 0 误报。
  日志里走结构那条会写 `(暗比 0.00,结构)`。浅色面板实测宽 0.66~0.68W,
  别拿暗色那条 0.72W 卡它
- **多开选客户端 = 药丸头上浮出来的面板(方案 E)**,不弹独立窗口、**不改变窗口
  尺寸**(2026-10-22 用户定的):`ui/bell.py:show_client_menu` / `close_client_menu`,
  面板和药丸**同宽**、悬在药丸上方盖住地图下缘;点行 = `app.on_pick_client(i)`;
  **再点一下药丸收起**(`_chip_release` 负责开/关),切主题直接收掉。面板里
  **只有客户端行**,几个列几个(没有"当前名字"那格),当前那台**最右边一个金点**、
  字提亮,悬停整行亮一档。独立的 `pick_client` / `on_pick_client_close` 都已删
- **药丸宽度 = 7 个字的宽**(`ui_bell.chip_width`,按真实字体量,**没有三角**):
  长名字末尾省略;别改回"跟着名字伸缩",也别把三角加回来(用户 2026-10-22 定的)
- **没目标 = 空状态**:占位句「暂无目标」写在**地名位**(灰),画布**完全留空**
  (2026-10-21 用户定的:画布中间不再写字,否则像卡片上开了个洞)
- **最小化/关闭走系统标题栏**(2026-10-21 用户定的):底行**没有 `−`**,
  标题栏那颗最大化虽被 `hide_maximize()` 清了 `WS_MAXIMIZEBOX` 而点不动,
  但 **Win11 24H2 仍会画一个灰框**(原生窗口实测:只置灰不消失),别以为是
  自己的 bug;真要它消失只能自绘标题栏,那会丢掉任务栏/最小化,不做
- **新目标红点弹一下**:换目标时红点从 16px 放大到 ~30px 再回弹(`PULSE_FRAMES`,
  全程 ~175ms,`after` 驱动),同目标重画(切主题)不弹 —— 判据是
  `app._bell_last_target`,别改成"每次 draw 都弹"。这是唯一的"新鲜度"反馈
  (用户 2026-10-21 明确不要时间戳)
- **首启跟随系统深浅色**:`core.default_ui_mode()` 在没选过 `bell.ui_mode` 时读
  注册表 `AppsUseLightTheme`(明亮→B,深色→A);选过就以配置为准,别再跟系统
- **窗口位置要记住**:退出时 `App.save_bell_pos()` 把位置写进 `bell.bell_pos`,
  下次 `set_place(pos=...)` 摆回原处;位置已经不在屏幕里(`win_common:usable_xy`
  要求留一条标题栏在屏内)就退回居中
- **窗口一圈 1px 描边**(`win_edge`,2026-10-21):深色底压在深色场景上时只靠
  系统阴影分不清窗口边界;切主题时 `apply_theme` 要跟着换这条边的颜色
- **窗口图标 = `data/bell.ico`**:标题栏、任务栏(最小化)、exe 文件共用这一把
  (金铃铛 + 红点,配色就是界面那套:`#0f1116` 底 / `#2a3242` 边 /
  `#f0c05a` 铃铛 / `#ff3b30` 点)。挂载**只走 `ui_widgets.set_window_icon`**
  (自己 `LoadImage` 精确尺寸 + `WM_SETICON`),**别再调 `wm iconbitmap`**:
  Tk 取 32px 那一档、还会在映射后盖一次,任务栏缩到 30px 就糊(2026-10-22
  用户拿旁边 Chrome/微信对比过)。本进程是 DPI 不感知的,真实缩放比从
  `shcore.GetScaleFactorForMonitor` 拿(`GetDpiForWindow` 只会给 96)。
  打包走 spec 的 `datas` + `EXE(icon=)`,`ensure_data_files` 会把它镜像到
  程序目录。要换图标直接重画这个 ico(**按 16–256 逐档画**,小尺寸别用白圈/
  外描边),别在代码里现画
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
4. 各模块自己的常量:扫描循环的 `cursor_pos` / `canvas_res_of` 用
   `patch(mods=(tools_bell,), ...)`;`tools/maps.py` 的 `MAP_DIR` /
   `MAP_CALIB_PATH` / `MAP_BOUNDS_PATH` 用 `patch(mods=(tools_maps,), ...)`
5. 测试里 `PATCH_MODULES = (core,)` —— 改动前确认不让 `patch(...)` 打空炮

## 踩过的坑(继承自原项目,别再踩)

- 删代码时 `@staticmethod` / `@property` 跟着一起删/搬
- 一行改动用 Edit 工具,别写脚本猜缩进
- `self._stop = threading.Event()` 会覆盖线程私有方法,已改名 `_halt`
- 重构成败靠测试和探针,别只看代码"读起来对";写一次性探针,跑完删
- 打包版 `sys.executable` 是应用自己,要跑子任务就进程内做
- **扫描/OCR 要给游戏让路**(2026-10-31 用户反馈"游戏被拖卡"):进程按
  「低于标准」优先级跑(`main.py:_low_priority`,别改回普通);GPU 识别偏慢
  只记日志提示手动关 `use_gpu`,**不自动降档 CPU**(同机满载实测 CPU 识别
  3~6s / GPU 0.7s,降档=把识别弄残);减负靠砍白读(非铃铛面板重读间隔
  `DIALOG_OTHER_GAP` 已从 0.6 放宽到 1.2)

## 铃铛识别口径

六种怪的对话框/任务栏原文表、`BELL_WORDS` 话术门槛、`known_map` 地名容错、
`_bell_scope` 圈范围、扫描门控、底图录入:全在 `docs/bell-internals.md`
(约 70KB,**别整份读**:Grep 标题 → Read 那一小段)。

- **真机截图夹具**在 `docs/shots/`(六种怪 10 张,坐标原文写在
  `expected.json`):改 det 参数 / 解析口径之后跑 `check_shots.py` 对数。
  它是独立进程(建真引擎);`tests.py` 只查表里文件在不在,不跑 OCR。

## 与原项目的关系

识别逻辑(`tools/bell.py`)原先与 `E:/Project/keju-answerer` 保持一致,那边的铃铛
bug 修复可以直接拷过来,反之亦然;**2026-10-21 起本应用只支持表里量过的档、任务栏框
一律来自表,删掉了整窗找框/学框/作废/退避冷却那条兜底链**,两边不再
逐字节一致 —— 拷修复前先 diff 这一块。`ui/bell.py` 2026-10-20 起按本应用的界面
走了(顶栏/抽屉/开关撤掉)。`data/` / `docs/bell-internals.md` 的识别口径部分原先
两边同源,同样自 2026-10-21 起分叉(本应用侧已按删整窗后的状态改写)。

**隔壁现在是 `E:/Project/mhxy_keju`**(keju-answerer 已改名),客户端探测 2026-11-12
起两边同源:`client_common.py` 整文件覆盖同步(除文件头一段),本应用缺口
(独立窗口版式、登录窗过滤、客户区矩形、三档 1024×768)都抄自它 2026-11-09
的实测定案;`clients.py` 各写各的应用口径。截屏/OCR 的 `ocr.py` 同日从它
拿来(Screen 逐字一致,Ocr 带本应用的 limit_type 快路径与耗时诊断,见上);
2026-11-12 起 `Screen` 单独落在 `screen.py`(两边仍同源,`freeze_screen`
也在这儿),`ocr.py` 只留 `Ocr`。
改完跑 `tests.py --quiet` 全绿再收工。

## 工作方式约定

- 不要自动提交/推送;改完留在工作区,等用户发话
- 改完必须跑测试,红了立刻回退,绝不留半成品
- 大改动分小步,每步跑一次测试
- 跑完删临时探针脚本/图片
