# -*- coding: utf-8 -*-
r"""
check_env.py —— 本机训练/部署环境自检
跑法:  python _toolchain\check_env.py
说明:  对"原生扩展能否加载"单独做容错探测（本机 TF/ORT 的 DLL 有已知问题，
       不影响主链路，因此记为 WARN 而非 FAIL）
"""
import os
import platform
import sys

OK, NO, WN = "[PASS]", "[FAIL]", "[WARN]"
results = []


def line(tag, text):
    print(f"{tag} {text}")
    results.append((tag, text))


print("=" * 70)
print("  杂草识别小车 · 本机环境自检")
print("=" * 70)

line(OK, f"Python {sys.version.split()[0]}  ({sys.executable})")
line(OK, f"OS {platform.system()} {platform.release()} build {platform.version()}")

# ---------- 依赖 ----------
print("-" * 70)


def check_pkg(name, imp=None):
    imp = imp or name
    try:
        m = __import__(imp)
        line(OK, f"{name:16s} {getattr(m, '__version__', '?')}")
        return m
    except Exception as e:
        line(NO, f"{name:16s} 未安装/不可用 ({type(e).__name__})")
        return None


torch = check_pkg("torch")
check_pkg("torchvision")
check_pkg("numpy")
cv2 = check_pkg("cv2", "cv2")
check_pkg("PIL", "PIL")
check_pkg("yaml", "yaml")
ultra = check_pkg("ultralytics")
check_pkg("onnx")
onnx_ok = sys.modules.get("onnx") is not None

# ---------- 原生扩展容错探测 ----------
print("-" * 70)
print("  原生扩展探测（失败不影响 YOLO 训练/ONNX 导出链路）")


def probe_native(label, fn, why):
    try:
        fn()
        line(OK, f"{label:16s} 可加载")
        return True
    except BaseException as e:
        msg = str(e).splitlines()[0][:70] if str(e) else type(e).__name__
        line(WN, f"{label:16s} 不可加载 -> {msg}")
        print(f"        ↳ {why}")
        return False


def _ort():
    import onnxruntime  # noqa
probe_native("onnxruntime", _ort, "用 cv2.dnn 代替（项目 onnx_inference.py 本来就是纯 OpenCV 路径）")


def _tf():
    import tensorflow  # noqa
probe_native("tensorflow", _tf, "本机 TF 原生库 DllMain 初始化失败；int8 量化重训需要它，"
                               "但 .cc/.h 生成不需要（纯字节导出）")


def _litert():
    from ai_edge_litert.interpreter import Interpreter  # noqa
probe_native("ai_edge_litert", _litert, "本机缺依赖 DLL；tflite 只能用结构校验代替运行时校验")

# ---------- OpenCV DNN 能力（ONNX 推理主路径）----------
if cv2 is not None:
    try:
        net = cv2.dnn.readNetFromONNX  # 只是取句柄，不加载模型
        has = hasattr(cv2.dnn, "readNetFromONNX")
        line(OK if has else NO, f"cv2.dnn.readNetFromONNX {'可用' if has else '缺失'}")
    except Exception as e:
        line(WN, f"cv2.dnn 探测异常 {e}")

# ---------- CUDA ----------
print("-" * 70)
if torch is not None:
    try:
        if torch.cuda.is_available():
            line(OK, "torch.cuda.is_available() = True")
            line(OK, f"CUDA runtime(wheel) = {torch.version.cuda}    cuDNN {torch.backends.cudnn.version()}")
            for i in range(torch.cuda.device_count()):
                p = torch.cuda.get_device_properties(i)
                line(OK, f"GPU[{i}] {p.name}  VRAM {p.total_memory/1024**3:.2f} GB  "
                         f"CC {p.major}.{p.minor}  SMs {p.multi_processor_count}")
            free, total = torch.cuda.mem_get_info()
            line(OK, f"显存空闲 {free/1024**3:.2f} GB / {total/1024**3:.2f} GB")
        else:
            line(NO, "torch.cuda.is_available() = False —— 会退回 CPU 训练")
    except Exception as e:
        line(NO, f"CUDA 检查异常: {e}")

    try:
        import time
        if torch.cuda.is_available():
            d = torch.device("cuda:0")
            a, b = torch.randn(4096, 4096, device=d), torch.randn(4096, 4096, device=d)
            for _ in range(3):
                c = a @ b
            torch.cuda.synchronize()
            t0 = time.time()
            for _ in range(20):
                c = a @ b
            torch.cuda.synchronize()
            dt = time.time() - t0
            line(OK, f"GPU 实测 fp32 算力 ≈ {20*2*4096**3/dt/1e12:.2f} TFLOPS "
                     f"(GTX1660S 理论峰值 5.0)")
            del a, b, c
            torch.cuda.empty_cache()
    except Exception as e:
        line(WN, f"GPU 基准失败: {e}")

# ---------- CPU / 磁盘 ----------
print("-" * 70)
try:
    import cpuinfo
    i = cpuinfo.get_cpu_info()
    fl = i.get("flags", [])
    need = [f for f in ("sse4_2", "avx", "avx2", "f16c", "fma") if f in fl]
    line(OK if "avx2" in fl else WN, f"CPU {i.get('brand_raw')}  [{','.join(need)}]")
except Exception:
    pass

PROJ = r"E:\PlantDiseaseProject"
for rel, tag in [("models\\best.pt", OK), ("yolov8n.pt", OK),
                 ("train_weed.py", OK), ("models\\weed_det\\weights\\best.pt", OK),
                 ("datasets\\weed_yolo\\data.yaml", OK),
                 ("datasets\\weed_yolo\\train\\images", OK),
                 ("datasets\\weed_yolo\\val\\images", OK),
                 ("_toolchain\\deploy_export.py", OK)]:
    p = os.path.join(PROJ, rel)
    if os.path.exists(p):
        if os.path.isfile(p):
            line(OK, f"{rel:38s} {os.path.getsize(p)/1048576:8.2f} MB")
        else:
            n = len(os.listdir(p))
            line(OK, f"{rel:38s} 目录({n} 项)")
    else:
        line(WN, f"{rel:38s} 缺失")

try:
    import shutil
    for drv in ("C:\\", "E:\\"):
        t, u, f = shutil.disk_usage(drv)
        line(OK, f"{drv} 空闲 {f/1024**3:.1f} GB / {t/1024**3:.1f} GB")
except Exception:
    pass

print("=" * 70)
nf = sum(1 for t, _ in results if t == NO)
nw = sum(1 for t, _ in results if t == WN)
print(f"  结果: {len(results)-nf-nw} PASS / {nw} WARN / {nf} FAIL")
print("=" * 70)
sys.exit(1 if nf else 0)
