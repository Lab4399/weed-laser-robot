# -*- coding: utf-8 -*-
r"""
deploy_export.py —— 部署导出链：best.pt -> ONNX -> 校验 -> 实测推理

推理后端用 OpenCV DNN（与项目自带 onnx_inference.py 同一条路，不依赖 onnxruntime）。

跑法:
  python _toolchain\deploy_export.py
  python _toolchain\deploy_export.py --weights models\weed_det\weights\best.pt

产出:
  E:\PlantDiseaseProject\export\weed_det.onnx
"""
import argparse
import glob
import os
import shutil
import sys
import time

PROJ = r"E:\PlantDiseaseProject"


def hr(t):
    print("\n" + "=" * 70)
    print("  " + t)
    print("=" * 70)


def letterbox(img, imgsz, stride=32):
    import cv2
    import numpy as np
    h, w = img.shape[:2]
    r = min(imgsz / h, imgsz / w)
    nh, nw = int(round(h * r)), int(round(w * r))
    if (w, h) != (nw, nh):
        img = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR)
    canvas = np.full((imgsz, imgsz, 3), 114, np.uint8)
    top, left = (imgsz - nh) // 2, (imgsz - nw) // 2
    canvas[top:top + nh, left:left + nw] = img
    return canvas, r, left, top


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default=os.path.join(PROJ, r"models\weed_det\weights\best.pt"))
    ap.add_argument("--out", default=os.path.join(PROJ, r"export\weed_det.onnx"))
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--opset", type=int, default=12)
    ap.add_argument("--no-simplify", action="store_true")
    ap.add_argument("--skip-export", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(args.weights):
        sys.exit(f"[deploy] 权重不存在: {args.weights}")

    # ---------- 0. 模型体检 ----------
    hr("0. 加载 .pt 模型")
    from ultralytics import YOLO
    import torch
    m = YOLO(args.weights)
    nparam = sum(p.numel() for p in m.model.parameters())
    print(f"  权重       : {args.weights}  ({os.path.getsize(args.weights)/1048576:.2f} MB)")
    print(f"  task       : {m.task}")
    print(f"  类别数 nc  : {len(m.names)}   类别名: {m.names}")
    print(f"  参数量     : {nparam/1e6:.2f} M")
    print(f"  设备       : {'cuda:0' if torch.cuda.is_available() else 'cpu'}")

    # ---------- 1. 导出 ONNX ----------
    if not args.skip_export:
        hr("1. 导出 ONNX")
        t0 = time.time()
        onnx_path = m.export(format="onnx", imgsz=args.imgsz,
                             simplify=not args.no_simplify, dynamic=False,
                             opset=args.opset, device="cpu")
        print(f"  ultralytics 输出: {onnx_path}   ({time.time()-t0:.1f}s)")
        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        if os.path.abspath(str(onnx_path)) != os.path.abspath(args.out):
            shutil.copy(onnx_path, args.out)

    print(f"  ONNX 路径  : {args.out}  ({os.path.getsize(args.out)/1048576:.2f} MB)  "
          f"压缩率 {(1-os.path.getsize(args.out)/os.path.getsize(args.weights))*100:.0f}%")

    # ---------- 2. ONNX 结构校验 ----------
    hr("2. ONNX 结构校验")
    import onnx
    mod = onnx.load(args.out)
    onnx.checker.check_model(mod)
    print("  onnx.checker : 通过")
    print(f"  IR version   : {mod.ir_version}    opset {[o.version for o in mod.opset_import]}")
    for i in mod.graph.input:
        print(f"  input        : {i.name}  {[d.dim_value for d in i.type.tensor_type.shape.dim]}")
    for o in mod.graph.output:
        print(f"  output       : {o.name}  {[d.dim_value for d in o.type.tensor_type.shape.dim]}")
    print(f"  算子种类     : {len(set(n.op_type for n in mod.graph.node))} 种")

    # ---------- 3. OpenCV DNN 实测 ----------
    hr("3. OpenCV DNN 实测推理（项目部署路径）")
    import cv2
    import numpy as np
    print(f"  OpenCV : {cv2.__version__}")
    net = cv2.dnn.readNetFromONNX(args.out)
    print(f"  加载后端: OpenCV DNN (readNetFromONNX)  OpenCV {cv2.__version__}")
    blob = np.random.rand(1, 3, args.imgsz, args.imgsz).astype(np.float32)
    net.setInput(blob)
    out = net.forward()
    print(f"  输出 shape: {out.shape}   (期望 (1, 4+nc, 8400) = (1,{4+len(m.names)},8400))")
    times = []
    for _ in range(20):
        t0 = time.time()
        net.setInput(blob)
        net.forward()
        times.append(time.time() - t0)
    times.sort()
    print(f"  CPU 推理延迟: 中位 {times[len(times)//2]*1000:.1f} ms  "
          f"最快 {times[0]*1000:.1f} ms  → 约 {1/times[len(times)//2]:.1f} FPS")

    # ---------- 4. 真实图片端到端 ----------
    hr("4. 真实图片端到端检测")
    cands = sorted(glob.glob(os.path.join(PROJ, r"datasets\weed_yolo\val\images\*.jpg")))[:6]
    if not cands:
        print("  （没找到样图）")
    else:
        outdir = os.path.join(PROJ, "export", "pred")
        os.makedirs(outdir, exist_ok=True)
        nc = len(m.names)
        names = m.names
        nbox = 0
        for ip in cands:
            img = cv2.imread(ip)
            H, W = img.shape[:2]
            canvas, r, left, top = letterbox(img, args.imgsz)
            blob = canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
            blob = np.ascontiguousarray(blob)
            net.setInput(blob)
            t0 = time.time()
            pred = net.forward()
            dt = (time.time() - t0) * 1000
            pred = pred[0].T                      # (8400, 4+nc)
            scores = pred[:, 4:]
            cls_ids = scores.argmax(1)
            confs = scores.max(1)
            keep = confs > 0.25
            dets = []
            for (cx, cy, w, h), cid, cf in zip(pred[keep, :4], cls_ids[keep], confs[keep]):
                x1 = (cx - w / 2 - left) / r
                y1 = (cy - h / 2 - top) / r
                x2 = (cx + w / 2 - left) / r
                y2 = (cy + h / 2 - top) / r
                dets.append((int(x1), int(y1), int(x2), int(y2), float(cf), int(cid)))
            # NMS
            idxs = cv2.dnn.NMSBoxes([d[:4] for d in dets], [d[4] for d in dets], 0.25, 0.45)
            idxs = [int(i) for i in (idxs.flatten() if len(idxs) else [])]
            vis = img.copy()
            cnt = {"crop": 0, "weed": 0}
            for i in idxs:
                x1, y1, x2, y2, cf, cid = dets[i]
                nm = str(names[cid])
                col = (0, 200, 0) if nm == "crop" else (0, 0, 255)   # crop绿 / weed红
                cv2.rectangle(vis, (x1, y1), (x2, y2), col, 2)
                cv2.putText(vis, f"{nm} {cf:.2f}", (x1, max(y1 - 5, 12)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1)
                cnt[nm] = cnt.get(nm, 0) + 1
            cv2.imwrite(os.path.join(outdir, os.path.basename(ip)), vis)
            nbox += len(idxs)
            print(f"  {os.path.basename(ip):20s} {W}x{H}  {dt:6.1f} ms  "
                  f"crop {cnt.get('crop',0)} / weed {cnt.get('weed',0)}")
        print(f"  标注结果图 -> {outdir}")

    hr("完成")
    print(f"  部署中间产物: {args.out}")
    print(r"  下一步: python _toolchain\tflite_to_cc.py  （int8 模型 -> C 数组）")


if __name__ == "__main__":
    main()
