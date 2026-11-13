"""屏幕截屏 + OCR 识别(RapidOCR 封装,GPU 可选)。

可独立复用的单文件模块:截一块屏幕区域出文字块。依赖:rapidocr_
onnxruntime / numpy / mss;GPU 开关走构造参数 use_gpu(True/False,
别的工程拷走传一下就行);不传才在 _get 里惰性 import core 问应用配置。
本文件从 keju 的 ocr.py 拿过来,额外保留降妖伏魔的快路径:det 的
limit_type(max)与真实识别耗时诊断(keju 侧只用 limit_side,不冲突)。
"""
import threading
import time

try:
    import numpy as np
except ImportError:  # main() 会给出友好提示
    np = None


WARMUP_TIMEOUT = 30.0      # OCR 预热超时(本机首次 GPU 预热约 1 秒,给足余量)
OCR_GPU_SLOW_MS = 800      # GPU 单次识别中位超过这个数 -> 日志提示可关 GPU(不自动降档)
OCR_SLOW_SAMPLES = 5       # 偏慢判断要攒够的连续真实识别次数


def _err_text(err) -> str:
    """把异常翻成可读文字。

    ORT 的状态串偶尔是 GBK(中文 Windows 的底层错误消息),Python 按 UTF-8
    解码会抛 UnicodeDecodeError、把真实原因糊掉 —— 2026-10-31 用户机器上
    DirectML 起不来,日志里只看得到一串字节码。UnicodeDecodeError 自己带着
    原始字节(`.object`),按 GBK 再解一次就能看到真话。
    """
    raw = getattr(err, "object", None)
    if isinstance(raw, (bytes, bytearray)):
        try:
            return raw.decode("gbk", errors="replace")
        except Exception:
            pass
    return str(err)


class Ocr:
    """RapidOCR 封装(线程安全,懒加载)。"""

    def __init__(self, log=None, use_gpu=None):
        self._engine = None
        self._lock = threading.Lock()
        self._log = log or (lambda m: None)
        self._use_gpu = use_gpu   # None=问 core 的配置;True/False=显式定,不碰 core
        self.device = "CPU"
        self.ok = True                 # warmup 那次真实推理成功过吗(False=假就绪)
        self.err = ""                  # 不健康的原因(引擎/看门狗据此重建与报错)
        self._lats = []                # 最近几次真实识别的耗时(ms),慢速诊断用
        self._slow_noted = False       # "GPU 偏慢"提示只说一次

    def warmup(self, timeout: float = WARMUP_TIMEOUT):
        """预热:建好引擎 + 真跑一次推理,结果记在 ok 上。

        GPU(DirectML) 首次推理要初始化显存/算子(约 1 秒),提前吃掉,
        否则第一拍会明显变慢。这次推理失败**不再静默**:GPU 上先按既有
        机制回退 CPU 再试,仍然不行就把 ok 标成 False(附 err)——引擎据此
        报"识别不可用"而不是"已就绪",看门狗也能发现假就绪。

        预热整段放进临时线程跑,主线程只等 timeout:万一卡在驱动/引擎里不
        返回,这里照样标 ok=False。否则引擎线程恒活 + ok 默认 True,看门狗
        永远不动作,日志还会说"引擎已就绪"。
        """
        box: dict = {}
        done = threading.Event()

        def _work():
            try:
                box["ok"], box["err"] = self._warmup_once()
            except BaseException as e:      # 临时线程里出事也得落到 ok 上
                box["ok"], box["err"] = False, f"{type(e).__name__}: {e}"
            finally:
                done.set()

        th = threading.Thread(target=_work, name="OCR预热", daemon=True)
        th.start()
        if not done.wait(timeout):
            # 超时:那次预热的结论不再采信(卡住的线程还在就让它去),按不可用报
            self.ok = False
            self.err = f"预热超时({timeout:.0f} 秒没返回,可能卡在显卡驱动)"
            self._log(f"[OCR]{self.err},识别不可用,看门狗将重建引擎")
            return
        self.ok = bool(box.get("ok", False))
        self.err = str(box.get("err") or "")

    def _warmup_once(self):
        """真跑一次预热推理,返回 (ok, err);不直接改 self.ok(超时那次不采信)。"""
        with self._lock:
            self._get()
        dummy = np.full((32, 160, 3), 255, dtype=np.uint8)
        try:
            self._infer(dummy)
        except Exception as err:
            self._log(f"[OCR]推理初始化失败({_err_text(err)}),设备可能不可用")
            if str(self.device).startswith("GPU"):
                self._fallback_to_cpu(err)     # 既有机制:GPU 出问题就重建为 CPU
            try:
                self._infer(dummy)             # 回退后再试一次
            except Exception as err2:
                self._log(f"[OCR]推理仍不可用({err2}):"
                          "识别会一直报错,看门狗将重建引擎")
                return False, str(err2)
        return True, ""

    def _get(self):
        if self._engine is None:
            from rapidocr_onnxruntime import RapidOCR
            self.device = "CPU"
            try:
                use_gpu = self._use_gpu
                if use_gpu is None:      # 没显式给才问应用配置(懒 import core)
                    import core
                    cfg = core.load_config()
                    use_gpu = core.app_cfg(cfg).get("use_gpu", True)
                if use_gpu:
                    import onnxruntime as ort
                    if "DmlExecutionProvider" in ort.get_available_providers():
                        self._engine = RapidOCR(det_use_dml=True,
                                                rec_use_dml=True,
                                                cls_use_dml=True)
                        self.device = "GPU(DirectML)"
            except Exception:
                self._engine = None
            if self._engine is None:
                self._engine = RapidOCR()
        return self._engine

    def _infer(self, img_bgr, limit_side=None, limit_type=None):
        """跑一次推理。limit_side / limit_type 临时改 det 的缩放(改完还原)。

        limit_type 是 det 拿哪个边长去对 limit_side:**min**(默认)=短边不够就放大,
        **max** =长边超了才缩小。字本来就大的那块传 max + 一个够大的边长,就是
        "按原像素跑、别白放大"。

        det 的这两个属性挂在引擎实例上,整段在锁里做 —— 两个线程同时识别也
        不会互相看到对方的临时值。取不到那个属性(库换实现)就按默认跑。
        """
        with self._lock:
            eng = self._get()
            det = getattr(eng, "text_det", None)
            old = getattr(det, "limit_side_len", None)
            old_type = getattr(det, "limit_type", None)
            if limit_side and old is not None:
                try:
                    det.limit_side_len = int(limit_side)
                except Exception:
                    old = None
            if limit_type and old_type is not None:
                try:
                    det.limit_type = str(limit_type)
                except Exception:
                    old_type = None
            try:
                result, _ = eng(img_bgr, use_cls=False)
            finally:
                if old is not None:
                    det.limit_side_len = old
                if old_type is not None:
                    det.limit_type = old_type
        return result or []

    def _fallback_to_cpu(self, err):
        """GPU 运行中出错时,重建为 CPU 引擎,保证识别不中断。

        重建也进锁:引擎的创建一律发生在 self._lock 里(_get 同理)。锁里先
        复查一次设备 —— 两条线程同时识别失败时,后进锁的那条发现已经回退过
        就直接回去,不会把先建好的那份 CPU 引擎再建一遍(白占一份模型内存)。

        注意这条只接**报错**(引擎崩/驱动问题),不接"慢":2026-10-31 实测
        游戏同机满载时 CPU 识别要 3~6 秒(GPU 0.7 秒),因慢降档等于把识别
        弄残。慢的对策是减读次,不是换设备。
        """
        try:
            from rapidocr_onnxruntime import RapidOCR
            with self._lock:
                if not str(self.device).startswith("GPU"):
                    return
                self._log(f"[OCR]GPU 识别异常({_err_text(err)}),自动回退 CPU")
                self._engine = RapidOCR()
                self.device = "CPU(已回退)"
        except Exception as e:
            self._log(f"[OCR]CPU 引擎重建失败: {e}")

    def _note_latency(self, ms):
        """记一次真实识别的耗时;GPU 持续偏慢时**说一次**去哪关 GPU 加速。

        只统计真实调用(预热不计),只记日志不自动降档 —— 2026-10-31 实测
        弱机/满载下 CPU 识别 3~6 秒,自动降档会把读坐标拖到不可用;真正要
        让路得靠用户自己权衡(改 config.json 的 use_gpu)。
        """
        self._lats.append(float(ms))
        if len(self._lats) > OCR_SLOW_SAMPLES * 2:
            del self._lats[:-OCR_SLOW_SAMPLES * 2]
        if (not str(self.device).startswith("GPU")
                or len(self._lats) < OCR_SLOW_SAMPLES
                or self._slow_noted):
            return
        recent = sorted(self._lats[-OCR_SLOW_SAMPLES:])
        mid = recent[len(recent) // 2]
        if mid >= OCR_GPU_SLOW_MS:
            self._slow_noted = True
            self._log(f"[OCR]GPU 识别偏慢(近 {OCR_SLOW_SAMPLES} 次中位 "
                      f"{mid:.0f}ms ≥ {OCR_GPU_SLOW_MS}ms,疑似显卡吃紧)—— "
                      "游戏若觉得卡,可在 config.json 里把 use_gpu 改成 false")

    def recognize(self, img_bgr) -> str:
        return "".join(b["text"] for b in self.recognize_blocks(img_bgr))

    def recognize_blocks(self, img_bgr, limit_side=None, limit_type=None):
        """返回带坐标的文本块列表,按 (y, x) 排序。

        limit_side: 这一次识别的 det 输入下限(默认跟着引擎配置 736)。
        小图会被 det 放大到这个下限再检测 —— 识别准一点,但**很贵**(一块
        860x240 的小区域放大到 2840x736 再跑 det)。只扫游戏界面里的一小块时
        调小它,又快又不掉准头(实测调小后连"朱紫国"都读得更对)。

        limit_type: "min"(默认,短边不足就放大)/ "max"(长边超了才缩小)。
        字本来就大的那块(对话框条带)传 max + 足够大的 limit_side,就是按
        原像素跑 det —— 实测比放大到 480 快四成,读出来的东西一样。
        """
        t0 = time.perf_counter()
        try:
            result = self._infer(img_bgr, limit_side, limit_type)
        except Exception as e:
            if str(self.device).startswith("GPU"):
                self._fallback_to_cpu(e)
                result = self._infer(img_bgr, limit_side, limit_type)   # CPU 重试一次
            else:
                raise
        self._note_latency((time.perf_counter() - t0) * 1000)
        if not result:
            return []

        def sort_key(item):
            box = item[0]
            ys = [p[1] for p in box]
            xs = [p[0] for p in box]
            return (sum(ys) / len(ys), sum(xs) / len(xs))

        blocks = []
        for box, text, conf in sorted(result, key=sort_key):
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            blocks.append({
                "text": str(text),
                "x1": int(min(xs)), "y1": int(min(ys)),
                "x2": int(max(xs)), "y2": int(max(ys)),
                "conf": float(conf),
            })
        return blocks

# 截屏封装单独成文件(单文件可拷走复用);这里保留 Screen 名字,core.Screen
# 与 tests 的既有引用不变。
from screen import Screen  # noqa: E402,F401
