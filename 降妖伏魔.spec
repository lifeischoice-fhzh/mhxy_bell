# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

datas = [('data/bell_layouts.json', 'data'),
         ('data/bell.ico', 'data'),
         ('data/maps', 'data/maps')]
binaries = []
hiddenimports = ['PIL', 'mss']
tmp_ret = collect_all('rapidocr_onnxruntime')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
# onnxruntime **不要** collect_all(2026-11-05 瘦身):那会把 quantization/
# transformers/tools/datasets 里几百个离线工具 .py 全拖进包(安装包 94MB 的
# 大头之一)。识别运行时只碰 capi 的 dll/pyd + 顶层几个 .py —— 二进制这里
# 显式收一份(官方 contrib 钩子本来也会收,写明意图),纯 .py 由 import
# 分析自动跟进;rapidocr 的模型/配置走上面那条 collect_all。
binaries += collect_dynamic_libs('onnxruntime')


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['torch', 'matplotlib', 'scipy', 'pandas'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='降妖伏魔',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon='data/bell.ico',
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='降妖伏魔',
)
