# -*- coding: utf-8 -*-
"""一键打包:重建 dist/降妖伏魔 + 生成安装包 dist/mhxy_bell.exe。

用法:
    package.bat                          # 双击或命令行(推荐):绿版+安装包一条龙
    .venv/Scripts/python.exe package.py --dry-run
    .venv/Scripts/python.exe package.py --version 1.2.0   # 指定安装包版本号

PyInstaller 会整个重建 dist/降妖伏魔;配置、日志和自己录的地图底图都在
那个目录里。脚本打包前把它们抄到临时目录,打完再放回去。绿版成功后接着
调 Inno Setup 打安装包(没装 Inno Setup 就只更新绿色版)。

安装包版本号:--version 指定则原样用;不给就自动把最右一位 +1
(记录在 tools/inno/version.txt,打进安装包向导;只在安装包真编出来后才写)。
"""
import argparse
import locale
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
APP_NAME = "降妖伏魔"
SPEC = ROOT / f"{APP_NAME}.spec"
DIST = ROOT / "dist" / APP_NAME
EXE = DIST / f"{APP_NAME}.exe"
ISS = ROOT / "tools" / "inno" / "installer.iss"
SETUP = ROOT / "dist" / "mhxy_bell.exe"            # 安装包产物
VERSION_FILE = ROOT / "tools" / "inno" / "version.txt"   # 安装包版本记录

# 运行时产物(每台机器/每次使用都不一样,打包不能丢)
KEEP_FILES = ("config.json",)
KEEP_GLOBS = ("bell.log*",)
# 运行时目录里的地图底图(内置的六张 + 以后可能重新采的)和配套标定:
# 打包会整个重建 dist,先抄出来、打完再放回去(calib 是自动算的,丢了会重算)。
MAP_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
KEEP_MAPS = ("calib.json",)

# 打包结果里必须有的资源(少一个就是 spec 漏了)。查的是**捆绑位置**:
# PyInstaller 6 的 datas 落在 _internal/ 下,首次运行时 ensure_data_files 才把
# 它们镜像到 exe 旁边的 data/ —— 那份是运行时数据,首次打包时还不存在。
REQUIRED = (
    "_internal/data/bell_layouts.json",
    "_internal/data/bell.ico",             # 窗口/任务栏/exe 图标(标题栏那把)
    "_internal/data/maps/bounds.json",
    "_internal/data/maps/calib.json",
    "_internal/data/maps/宝象国.png",      # 六张底图随仓库分发:少一张就是 datas 漏了
)


def say(msg):
    print(f"[打包] {msg}", flush=True)


def runtime_files():
    """dist 里需要保留的运行时文件(打包前还不存在就返回空)。"""
    out = []
    for rel in KEEP_FILES:
        p = DIST / rel
        if p.is_file():
            out.append(p)
    for pat in KEEP_GLOBS:
        out.extend(p for p in DIST.glob(pat) if p.is_file())
    maps = DIST / "data" / "maps"
    if maps.is_dir():
        for p in maps.iterdir():
            if p.is_file() and (p.suffix.lower() in MAP_EXTS
                                or p.name in KEEP_MAPS):
                out.append(p)
    seen, uniq = set(), []
    for p in out:
        key = p.resolve()
        if key not in seen:
            seen.add(key)
            uniq.append(p)
    return uniq


def backup(files, target):
    for p in files:
        dst = target / p.relative_to(DIST)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst)


def restore(target):
    n = 0
    for p in target.rglob("*"):
        if not p.is_file():
            continue
        dst = DIST / p.relative_to(target)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dst)
        n += 1
    return n


def stop_running():
    """打包前关掉正在运行的打包版,不然 PyInstaller 删不掉旧目录。"""
    if os.name != "nt":
        return False
    try:
        r = subprocess.run(
            ["taskkill", "/F", "/IM", EXE.name],
            capture_output=True, text=True,
            encoding=locale.getpreferredencoding(False), errors="replace")
    except OSError:
        return False
    if r.returncode == 0:
        say(f"已关闭正在运行的 {EXE.name}")
        return True
    return False


def pyinstaller_ready():
    try:
        import PyInstaller  # noqa: F401
        return True
    except ImportError:
        say("缺少 PyInstaller。先装一下:")
        say(f'  "{VENV_PY}" -m pip install pyinstaller')
        return False


def read_version():
    """version.txt 里的安装包版本;文件没有/坏了按 1.0.0 起步。"""
    try:
        v = VERSION_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return "1.0.0"
    return v if re.fullmatch(r"\d+(\.\d+)*", v) else "1.0.0"


def write_version(v):
    VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    VERSION_FILE.write_text(v + "\n", encoding="utf-8")


def bump_version(v):
    """「1.0.0」->「1.0.1」:最右一位 +1(用户定的:没指定版本每次打包 +1)。"""
    parts = [int(p) for p in v.split(".")]
    parts[-1] += 1
    return ".".join(str(p) for p in parts)


def find_iscc():
    """找 Inno Setup 编译器:常见安装位置 + PATH;找不到返回 None。"""
    env = os.environ
    candidates = (
        Path(env.get("LOCALAPPDATA", "")) / "Programs" / "Inno Setup 6" / "ISCC.exe",
        Path(env.get("ProgramFiles(x86)", "")) / "Inno Setup 6" / "ISCC.exe",
        Path(env.get("ProgramFiles", "")) / "Inno Setup 6" / "ISCC.exe",
    )
    for p in candidates:
        if p.is_file():
            return str(p)
    return shutil.which("ISCC")


def main(argv=None):
    ap = argparse.ArgumentParser(description="一键打包降妖伏魔(绿版+安装包)")
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印要保留的文件和打包命令,不真的打包")
    ap.add_argument("--version", metavar="X.Y.Z",
                    help="安装包版本号;不给就自动把最右一位 +1"
                         "(记录在 tools/inno/version.txt)")
    ap.add_argument("--no-clean", action="store_true",
                    help="保留 PyInstaller 缓存(更快,但依赖变动后可能打进旧东西)")
    ap.add_argument("--no-backup", action="store_true",
                    help="不保留 dist 里的运行时数据(配置/日志/地图底图等)")
    args = ap.parse_args(argv)

    if args.version and not re.fullmatch(r"\d+(\.\d+)*", args.version):
        say(f"版本号格式不对: {args.version} —— 应为 1.2.3 这种纯数字段")
        return 2

    if not SPEC.is_file():
        say(f"找不到打包配置: {SPEC}")
        return 2
    if VENV_PY.is_file() and Path(sys.executable).resolve() != VENV_PY.resolve():
        say(f"请用项目 venv 运行: {VENV_PY}")
        say(f"  (或者直接双击 {ROOT / 'package.bat'})")
        return 2
    if not pyinstaller_ready():
        return 2

    files = [] if args.no_backup else runtime_files()
    cmd = [sys.executable, "-m", "PyInstaller", "--noconfirm"]
    if not args.no_clean:
        cmd.append("--clean")
    cmd.append(str(SPEC))

    say(f"程序目录: {DIST}")
    if files:
        say(f"将保留 {len(files)} 个运行时文件:")
        for p in files:
            say(f"  + {p.relative_to(DIST)}")
    else:
        say("没有可保留的运行时文件(首次打包或已指定 --no-backup)")

    if args.dry_run:
        say("dry-run:不执行打包")
        say("将执行: " + " ".join(cmd))
        iscc = find_iscc()
        if iscc is None:
            say("没找到 ISCC,只会更新绿色版")
        else:
            ver = args.version or bump_version(read_version())
            say(f"将执行: \"{iscc}\" /DAPP_VERSION={ver} \"{ISS}\"")
        return 0

    stop_running()
    tmp = Path(tempfile.mkdtemp(prefix="bell_pkg_")) if files else None
    ok = False
    try:
        if tmp is not None:
            backup(files, tmp)
        t0 = time.time()
        say("开始打包…")
        say("  " + " ".join(cmd))
        rc = subprocess.call(cmd, cwd=str(ROOT))
        if rc != 0:
            say(f"PyInstaller 失败(exit {rc})")
            return rc
        if not EXE.is_file():
            say(f"打包结束但没找到 {EXE}")
            return 3
        if tmp is not None:
            n = restore(tmp)
            say(f"已恢复 {n} 个运行时文件")
        missing = [rel for rel in REQUIRED if not (DIST / rel).exists()]
        if missing:
            say("警告:打包结果缺少这些资源:" + ", ".join(missing))
            say("     请检查 降妖伏魔.spec 的 datas")
        size = EXE.stat().st_size / 1024 / 1024
        say(f"完成: {EXE}")
        say(f"  {size:.1f} MB,耗时 {time.time() - t0:.0f}s")
        # ---- 安装包:绿版成功才打;版本 --version 给定原样用,否则最右位 +1 ----
        # (version.txt 只在安装包真编出来后才写,失败/跳过不占号)
        iscc = find_iscc()
        if iscc is None:
            say("没找到 Inno Setup(ISCC.exe)—— 跳过安装包,只更新了绿色版")
        else:
            ver = args.version or bump_version(read_version())
            say(f"安装包版本: {ver}")
            rc2 = subprocess.call([iscc, f"/DAPP_VERSION={ver}", str(ISS)])
            if rc2 != 0 or not SETUP.is_file():
                say(f"安装包编译失败(ISCC exit {rc2})")
                return rc2 or 4
            write_version(ver)
            mb = SETUP.stat().st_size / 1024 / 1024
            say(f"安装包: {SETUP}({mb:.1f} MB)")
        ok = True
        return 0
    finally:
        if tmp is not None:
            if ok:
                shutil.rmtree(tmp, ignore_errors=True)
            else:
                say(f"未完成,运行时备份留在: {tmp}")


if __name__ == "__main__":
    sys.exit(main())
