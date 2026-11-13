"""Windows 桌面应用的进程环境(单文件可拷走复用)。

DPI 感知、任务栏独立应用 ID、单实例互斥体、系统深浅色判定、退出扫尾。
不认任何应用口径:互斥体名、AppID、日志名、要清理的目录全由调用方传,
文件里没有带本应用名字的默认值。
"""
import os


def dpi_aware():
    """让本进程按物理像素工作(Tk 的 winfo_* 才是真实像素)。"""
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def set_app_id(app_id):
    """让 Windows 把本进程当成**独立应用**。

    不设的话任务栏按 pythonw.exe 归组、显示 Python 的图标 —— 窗口自己的
    图标(`win_common.set_window_icon`)就看不见了。打包成 exe 之后这条其实
    可有可无,但源码运行必须它。app_id 由调用方给(各应用自己的 AUMID)。
    """
    import ctypes
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
    except Exception:
        pass


def single_instance(name):
    """工具只许开一个:已有实例在跑时返回 False(弹框退路在调用方)。

    name 是调用方的互斥体名(Global\\ 开头)。命名互斥体由系统在进程退出
    时自动释放,这里刻意不 CloseHandle —— 句柄得活满整个进程生命周期,
    提前关等于没锁。WinDLL(use_last_error=True)拿到的才是 CreateMutexW
    自己的错误码(183=ERROR_ALREADY_EXISTS)。
    """
    import ctypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateMutexW(None, False, name)
    return ctypes.get_last_error() != 183    # 183 = ERROR_ALREADY_EXISTS


def system_light_mode() -> bool:
    """系统是不是「明亮」主题(读 HKCU 的 AppsUseLightTheme;读不到按深色)。"""
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes"
                r"\Personalize") as key:
            return bool(winreg.QueryValueEx(key, "AppsUseLightTheme")[0])
    except Exception:
        return False


def cleanup_runtime(root, dirs=None, files=None):
    """退出时的扫尾:删掉运行期间攒出来的、下次会自己长回来的东西。

    默认清 `__pycache__/`(根/tools/ui 三处)和上一次轮转留下的旧日志;
    全部尽力而为:删不掉(被占用/没权限)就当没这回事,不影响退出。
    """
    import shutil
    if dirs is None:
        dirs = ("__pycache__", os.path.join("tools", "__pycache__"),
                os.path.join("ui", "__pycache__"))
    if files is None:
        files = ("bell.log.old",)
    for d in dirs:
        shutil.rmtree(os.path.join(root, d), ignore_errors=True)
    for f in files:
        try:
            os.remove(os.path.join(root, f))
        except OSError:
            pass
