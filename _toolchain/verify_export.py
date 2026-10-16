# -*- coding: utf-8 -*-
"""verify_export.py —— 部署产物一致性校验

回答一个问题：**导出的 ONNX 是不是真的来自我手上这个 best.pt？**

为什么需要这个脚本
------------------
YOLO 训练是一轮轮保存 best.pt 的，而 ONNX 导出是一个**独立的手工步骤**。
只要中间改过权重、或忘了重导，磁盘上就会出现
「export/weed_det.onnx 比 models/best.pt 旧」的情况 —— 而 ONNX 照样能正常
加载、正常推理、正常出检测框，**没有任何报错**，只是精度 quietly 停留在
旧模型上。这是最难发现的一类问题。

本脚本做两件事：
  1. 时间戳体检：比对权重与产物的修改时间，落后就报警
  2. 数值等价性：在同一批图上比对 PT 与 ONNX 的**原始输出张量**，
     而不是在 GPU 上跑完整 val（后者慢十几分钟，且只看 mAP 看不出
     "导出的到底是哪个权重"）

用法
----
  python _toolchain\verify_export.py
  python _toolchain\verify_export.py --weights models\\weed_det\\weights\\best.pt
  python _toolchain\verify_export.py --onnx export\\weed_det.onnx --num 10

判定标准
--------
  平均最大绝对差 < 0.02  →  导出无损，两个模型可以互换使用
  平均最大绝对差 >= 0.02 →  导出有偏差，或 ONNX 来自别的权重，需要重导
"""

import argparse
import glob
import os
import sys

import cv2
import numpy as np
import torch

PROJ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def hr(t):
    print("\n" + "=" * 68)
    print(f"  {t}")
    print("=" * 68)


def letterbox(im, size=640):
    """与 ultralytics 一致的 letterbox：等比缩放 + 居中填充 114"""
    h, w = im.shape[:2]
    r = max(h, w)
    py, px = (r - h) // 2, (r - w) // 2
    im = cv2.copyMakeBorder(im, py, r - h - py, px, r - w - px,
                            cv2.BORDER_CONSTANT, value=(114, 114, 114))
    return cv2.resize(im, (size, size))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default=os.path.join(PROJ, r"models\weed_det\weights\best.pt"))
    ap.add_argument("--onnx", default=os.path.join(PROJ, r"export\weed_det.onnx"))
    ap.add_argument("--imgs", default=os.path.join(PROJ, r"datasets\weed_yolo\val\images"))
    ap.add_argument("--num", type=int, default=6, help="比对图片数量")
    ap.add_argument("--tol", type=float, default=0.02, help="允许的最大绝对差")
    ap.add_argument("--imgsz", type=int, default=640)
    args = ap.parse_args()

    for p in (args.weights, args.onnx):
        if not os.path.exists(p):
            sys.exit(f"[verify] 文件不存在: {p}")

    # ---------- 1. 时间戳体检 ----------
    hr("1. 时间戳体检（产物是否比权重新？）")
    tw = os.path.getmtime(args.weights)
    to = os.path.getmtime(args.onnx)
    fmt = lambda t: __import__("time").strftime("%Y-%m-%d %H:%M:%S", __import__("time").localtime(t))
    print(f"  权重   {fmt(tw)}   {args.weights}")
    print(f"  ONNX   {fmt(to)}   {args.onnx}")
    delta_h = (tw - to) / 3600
    stale = delta_h > 0.01
    if stale:
        print(f"\n  ⚠️ 警告：ONNX 比权重旧了 {delta_h:.1f} 小时，产物可能来自旧权重！")
        print(f"     请重新导出：python _toolchain\\deploy_export.py --no-simplify")
    else:
        print(f"\n  ✅ ONNX 晚于权重 {abs(delta_h)*60:.0f} 分钟，顺序正确")

    # ---------- 2. 数值等价性 ----------
    hr("2. 数值等价性比对（PT 原始输出 vs ONNX 原始输出）")
    from ultralytics import YOLO
    files = sorted(glob.glob(os.path.join(args.imgs, "*.jpg")))[: args.num]
    if not files:
        sys.exit(f"[verify] 验证集图片不存在: {args.imgs}\n"
                 f"         先跑 python _toolchain\\parquet2yolo.py 生成数据集")

    m = YOLO(args.weights)
    net = cv2.dnn.readNetFromONNX(args.onnx)
    s = args.imgsz
    print(f"  权重加载于 CPU，比对 {len(files)} 张图 @ {s}x{s}")
    print()
    print(f"  {'图片':<26}{'输出形状':<20}{'最大绝对差':>12}")
    print("  " + "-" * 56)

    diffs = []
    for p in files:
        blob = letterbox(cv2.imread(p), s)
        with torch.no_grad():
            t = torch.from_numpy(blob[:, :, ::-1].copy()).permute(2, 0, 1).float().div(255).unsqueeze(0)
            out_pt = m.model(t)[0].numpy()
        net.setInput(cv2.dnn.blobFromImage(blob, 1 / 255.0, (s, s), swapRB=True, crop=False))
        out_ox = net.forward()
        if out_pt.shape != out_ox.shape:
            print(f"  {os.path.basename(p):<26}形状不一致 {out_pt.shape} vs {out_ox.shape}")
            sys.exit("[verify] 形状不一致，导出配置有误")
        d = float(np.abs(out_pt - out_ox).max())
        diffs.append(d)
        print(f"  {os.path.basename(p):<26}{str(out_pt.shape):<20}{d:>12.5f}")

    avg = float(np.mean(diffs))
    print()
    print(f"  平均最大绝对差 : {avg:.5f}   (阈值 {args.tol})")
    if avg < args.tol:
        print("  判定：✅ 导出无损，PT 与 ONNX 可互换使用")
    else:
        print("  判定：❌ 偏差过大，ONNX 很可能不是当前权重导出的，请重导")
        sys.exit(1)

    # ---------- 3. 部署延迟 ----------
    hr("3. OpenCV DNN 部署延迟（项目实际部署路径）")
    net.setInput(cv2.dnn.blobFromImage(letterbox(cv2.imread(files[0]), s),
                                       1 / 255.0, (s, s), swapRB=True, crop=False))
    for _ in range(3):
        net.forward()
    ts = []
    for _ in range(10):
        t0 = __import__("time").perf_counter()
        net.forward()
        ts.append((__import__("time").perf_counter() - t0) * 1000)
    med = float(np.median(ts))
    print(f"  CPU 中位延迟 : {med:.1f} ms   → 约 {1000/med:.1f} FPS")
    print(f"  最快/最慢   : {min(ts):.1f} / {max(ts):.1f} ms")

    hr("完成")
    print("  部署链一致性校验通过")


if __name__ == "__main__":
    main()